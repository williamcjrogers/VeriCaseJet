from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from ..config import settings
from ..forensic_integrity import sha256_hex_text, normalize_text_for_hash
from ..evidence.text_extract import tika_url_candidates
from .email_import_types import ParsedEmail, ParsedAttachment


_HEADER_ALIASES = {
    "from": "from",
    "to": "to",
    "cc": "cc",
    "bcc": "bcc",
    "subject": "subject",
    "date": "date",
    "sent": "date",
    # French
    "de": "from",
    "à": "to",
    "a": "to",
    "objet": "subject",
    "envoyé": "date",
    "envoye": "date",
    "cci": "bcc",
    # German
    "von": "from",
    "an": "to",
    "betreff": "subject",
    "gesendet": "date",
    "datum": "date",
    # Spanish
    "para": "to",
    "asunto": "subject",
    "enviado": "date",
    "fecha": "date",
    "cco": "bcc",
}

_HEADER_RE = re.compile(
    r"^(?:\s*>*)\s*([A-Za-zÀ-ÿ]+)\s*:\s*(.*)$"
)

_SECTION_BREAK_RE = re.compile(
    r"(?i)^\s*-{2,}\s*(original message|forwarded message)\s*-{2,}\s*$"
)


@dataclass
class PdfParseResult:
    messages: list[ParsedEmail]
    extraction_method: str
    warnings: list[str]
    stats: dict[str, Any]


def _parse_sender(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        from email.utils import parseaddr

        name, addr = parseaddr(value)
        name = (name or "").strip() or None
        addr = (addr or "").strip() or None
        if addr and "@" not in addr:
            if not name:
                name = addr
            addr = None
        return addr, name
    except Exception:
        return None, value.strip() or None


def _parse_recipients(value: str | None) -> list[str] | None:
    if not value:
        return None
    try:
        from email.utils import getaddresses

        pairs = getaddresses([value])
        emails = [addr for _, addr in pairs if addr and "@" in addr]
        return emails or None
    except Exception:
        return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        from dateutil import parser as date_parser  # type: ignore

        dt = date_parser.parse(text, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(text)
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None


def _compute_confidence(headers: dict[str, str]) -> int:
    score = 0
    if headers.get("from"):
        score += 40
    if headers.get("date"):
        score += 25
    if headers.get("subject"):
        score += 20
    if headers.get("to"):
        score += 10
    if headers.get("cc"):
        score += 5
    return min(score, 100)


def _extract_text_pypdf2(raw: bytes) -> tuple[str, int]:
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=400, detail=f"PyPDF2 is not available: {exc}"
        ) from exc

    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        raise HTTPException(
            status_code=400, detail="Encrypted PDF is not supported"
        )

    pages = len(reader.pages)
    text_parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text:
            text_parts.append(page_text)
    return "\n".join(text_parts), pages


async def _extract_text_tika(raw: bytes) -> str | None:
    tika_url = settings.TIKA_URL
    if not tika_url:
        return None

    for base in tika_url_candidates(tika_url):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.put(
                    f"{base}/tika",
                    content=raw,
                    headers={
                        "Accept": "text/plain",
                        "Content-Type": "application/pdf",
                    },
                )
            if resp.status_code == 200:
                text = resp.text or ""
                if text.strip():
                    return text
        except Exception:
            continue
    return None


def _split_sections(text: str) -> list[tuple[dict[str, str], str]]:
    lines = text.splitlines()
    sections: list[tuple[dict[str, str], list[str]]] = []

    current_headers: dict[str, str] = {}
    current_body: list[str] = []
    in_headers = False
    last_key: str | None = None

    def flush():
        nonlocal current_headers, current_body, in_headers, last_key
        if current_headers or current_body:
            sections.append((current_headers, current_body))
        current_headers = {}
        current_body = []
        in_headers = False
        last_key = None

    for raw in lines:
        line = raw.rstrip("\n")
        if _SECTION_BREAK_RE.match(line):
            flush()
            continue

        match = _HEADER_RE.match(line.strip())
        if match:
            key_raw = match.group(1).strip().lower()
            key = _HEADER_ALIASES.get(key_raw)
            if key:
                if not in_headers and current_headers:
                    # New header block after body - start a new section.
                    flush()
                in_headers = True
                val = (match.group(2) or "").strip()
                current_headers[key] = (
                    (current_headers.get(key) or "") + ("\n" if key in current_headers else "") + val
                ).strip()
                last_key = key
                continue

        if in_headers and (line.startswith(" ") or line.startswith("\t")) and last_key:
            current_headers[last_key] = (
                (current_headers.get(last_key) or "") + " " + line.strip()
            ).strip()
            continue

        if in_headers and not line.strip():
            in_headers = False
            continue

        current_body.append(line)

    flush()

    out: list[tuple[dict[str, str], str]] = []
    for headers, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not headers and not body:
            continue
        out.append((headers, body))

    return out


async def parse_pdf_email_bytes(
    raw: bytes,
    *,
    filename: str | None,
    source_file_sha256: str,
    use_tika: bool = True,
    use_textract: bool = False,
    min_text_len: int = 200,
) -> PdfParseResult:
    if not raw:
        raise HTTPException(status_code=400, detail="Empty PDF file")

    warnings: list[str] = []
    extraction_method = "pypdf2"
    text = ""

    if use_tika:
        tika_text = await _extract_text_tika(raw)
        if tika_text:
            text = tika_text
            extraction_method = "tika"

    if not text or len(text.strip()) < min_text_len:
        try:
            text, pages = _extract_text_pypdf2(raw)
            if pages and pages > getattr(settings, "TEXTRACT_MAX_PAGES", 500):
                warnings.append("pdf_pages_exceed_limit")
        except HTTPException:
            raise
        except Exception as exc:
            warnings.append(f"pypdf2_failed: {exc}")

    if use_textract and (not text or len(text.strip()) < min_text_len):
        warnings.append("textract_not_enabled_or_unavailable")

    sections = _split_sections(text)
    if not sections:
        raise HTTPException(status_code=400, detail="No email-like content found in PDF")

    valid_sections: list[tuple[dict[str, str], str]] = []
    for headers, body in sections:
        if headers.get("from") or headers.get("subject") or headers.get("date") or headers.get("to"):
            valid_sections.append((headers, body))

    if not valid_sections:
        raise HTTPException(
            status_code=400, detail="PDF does not appear to contain email headers"
        )

    messages: list[ParsedEmail] = []
    for idx, (headers, body) in enumerate(valid_sections):
        if not headers and not body:
            continue
        sender_email, sender_name = _parse_sender(headers.get("from"))
        subject = headers.get("subject") or None
        date_sent = _parse_date(headers.get("date"))

        body_clean = body.strip()
        header_text = "\n".join(
            f"{k}:{v}" for k, v in headers.items() if v
        )
        header_hash = sha256_hex_text(normalize_text_for_hash(header_text))
        body_hash = sha256_hex_text(normalize_text_for_hash(body_clean))
        message_id = (
            f"pdf-{sha256_hex_text(source_file_sha256 + '|' + str(idx) + '|' + header_hash + '|' + body_hash)[:16]}@pdf-import.local"
        )

        confidence = _compute_confidence(headers)

        messages.append(
            ParsedEmail(
                subject=subject,
                sender_email=sender_email,
                sender_name=sender_name,
                recipients_to=_parse_recipients(headers.get("to")),
                recipients_cc=_parse_recipients(headers.get("cc")),
                recipients_bcc=_parse_recipients(headers.get("bcc")),
                recipients_display=None,
                date_sent=date_sent,
                date_received=None,
                message_id=message_id,
                in_reply_to=None,
                references=None,
                body_plain=body_clean or None,
                body_html=None,
                body_rtf=None,
                attachments=[],
                raw_headers={
                    **{k: v for k, v in headers.items()},
                    "pdf_section_index": str(idx),
                    "pdf_confidence": str(confidence),
                },
                thread_group_id=None,
                thread_position=None,
            )
        )

    stats = {
        "sections": len(sections),
        "messages": len(messages),
    }

    return PdfParseResult(
        messages=messages,
        extraction_method=extraction_method,
        warnings=warnings,
        stats=stats,
    )
