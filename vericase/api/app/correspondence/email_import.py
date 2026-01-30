"""Email (.eml/.msg) import into Correspondence.

Goal: Treat uploaded standalone email files as if they were ingested from a PST.

Implementation notes:
- EmailMessage.pst_file_id is non-nullable -> we create a synthetic PSTFile for each import batch.
- Attachments must be represented as EvidenceItem(source_email_id=...) for best UI behavior.
- Threading + dedupe are run at finalize to match PST processing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..email_content import decode_maybe_bytes, html_to_text, select_best_body
from ..email_normalizer import (
    NORMALIZER_RULESET_HASH,
    NORMALIZER_VERSION,
    build_content_hash,
    clean_body_text,
)
from ..forensic_integrity import compute_normalized_text_hash, sha256_hex_bytes
from ..models import (
    Case,
    EmailAttachment,
    EmailMessage,
    EvidenceItem,
    PSTFile,
    Project,
    User,
)
from ..hybrid_spam_filter import classify_email_fast as classify_email_ai_sync
from ..spam_filter import extract_other_project
from ..storage import put_object
from .email_import_types import ParsedAttachment, ParsedEmail
from .pdf_email_parser import parse_pdf_email_bytes
from .whatsapp_parser import parse_whatsapp_bytes, parse_whatsapp_zip_bytes

logger = logging.getLogger("vericase")


_HTML_DOC_START_RE = re.compile(
    r"(?is)^\s*(?:<!doctype\s+html\b|<\s*(?:html|head|body)\b)"
)
_HTML_COMMON_TAG_RE = re.compile(
    r"(?is)<\s*\/?\s*(?:div|span|p|br|table|tr|td|th|style|meta|link|font|center|a)\b"
)

# Best-effort parsing of embedded forwarded messages (Outlook-style blocks inside body).
_EMBEDDED_HEADER_RE = re.compile(
    r"(?i)^\s*>*\s*(from|sent|date|to|cc|bcc|subject)\s*:\s*(.*)$"
)
_EMBEDDED_SEPARATOR_RE = re.compile(
    r"(?i)^\s*(?:-+\s*original message\s*-+|-+\s*forwarded message\s*-+|begin forwarded message)\s*$"
)


def _looks_like_html_markup(text: str | None) -> bool:
    if not text or not isinstance(text, str):
        return False
    s = text.lstrip()
    if not s:
        return False
    # Strong signals: an HTML document-ish start.
    if _HTML_DOC_START_RE.search(s):
        return True
    # Common email HTML fragments: table layouts, basic formatting tags, etc.
    if _HTML_COMMON_TAG_RE.search(s):
        return True
    # Count generic tags as a fallback heuristic.
    tag_count = len(re.findall(r"<\s*\/?\s*[A-Za-z][A-Za-z0-9:_-]*\b", s))
    return tag_count >= 8


def _safe_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}") from exc


def _parse_addresses(headers: list[str] | None) -> list[str] | None:
    if not headers:
        return None
    pairs = getaddresses(headers)
    emails = [_clean_email_address(addr) for _, addr in pairs]
    emails = [addr for addr in emails if addr]
    return emails or None


def _parse_date(date_header: str | None) -> datetime | None:
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Best-effort: treat naive dates as UTC.
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _parse_forwarded_datetime(value: str | None) -> datetime | None:
    """Parse forwarded/replied message date blocks (Outlook/Gmail-ish)."""

    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    # RFC-ish first.
    dt = _parse_date(text)
    if dt:
        return dt

    # dateutil if present (best overall).
    try:
        from dateutil import parser as date_parser  # type: ignore

        dt = date_parser.parse(text, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass

    # Common Outlook formats (no timezone).
    fmts = [
        "%A, %d %B %Y %H:%M",
        "%A, %d %B %Y %H:%M:%S",
        "%d %B %Y %H:%M",
        "%d %B %Y %H:%M:%S",
        "%a, %d %b %Y %H:%M",
        "%a, %d %b %Y %H:%M:%S",
        "%d %b %Y %H:%M",
        "%d %b %Y %H:%M:%S",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return None


def _parse_sender_from_header(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    raw = str(value).strip()
    if not raw:
        return None, None
    name, addr = parseaddr(raw)
    name = (name or "").strip() or None
    addr = _clean_email_address(addr)

    # If parseaddr returns a "non-email" addr, treat it as name.
    if addr and "@" not in addr:
        if not name:
            name = addr
        addr = None

    if not addr and not name:
        return None, raw

    return addr, name


def _parse_recipients_from_header(value: str | None) -> list[str] | None:
    if not value:
        return None
    pairs = getaddresses([str(value)])
    emails = [_clean_email_address(addr) for _, addr in pairs]
    emails = [addr for addr in emails if addr]
    return emails or None


def _strip_mailto(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"mailto:", "", str(text), flags=re.IGNORECASE)
    cleaned = re.sub(r"([\\w.+-]+@[\\w.-]+)\\?[^\\s>;,]*", r"\\1", cleaned)
    return cleaned


def _clean_email_address(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _strip_mailto(value) or ""
    cleaned = cleaned.strip().strip("<>").strip()
    if "@" not in cleaned:
        return None
    return cleaned


def _normalize_recipient_display(value: Any | None) -> str | None:
    if value is None:
        return None
    text = _strip_mailto(str(value)) or ""
    text = text.strip()
    if not text or text.lower() == "none":
        return None
    return text[:2000]


def _join_header_values(values: list[str] | None) -> str | None:
    if not values:
        return None
    parts = [str(v).strip() for v in values if v and str(v).strip()]
    if not parts:
        return None
    return ", ".join(parts)


def _unquote_lines(text: str) -> str:
    if not text:
        return text
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        while stripped.startswith(">"):
            stripped = stripped[1:].lstrip()
        out.append(stripped)
    return "\n".join(out)


def _extract_embedded_forwarded_emails(
    body_text: str, *, max_emails: int = 25
) -> list[ParsedEmail]:
    """Best-effort extraction of embedded messages from forwarded/replied bodies."""

    if not body_text:
        return []

    text = body_text
    if len(text) > 300_000:
        text = text[:300_000]

    lines = text.splitlines()
    i = 0
    results: list[ParsedEmail] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()

    def _header_kv(line: str) -> tuple[str, str] | None:
        m = _EMBEDDED_HEADER_RE.match(line)
        if not m:
            return None
        return m.group(1).lower(), (m.group(2) or "").strip()

    while i < len(lines) and len(results) < max_emails:
        line = lines[i].strip()
        if _EMBEDDED_SEPARATOR_RE.match(line):
            i += 1
            continue

        first = _header_kv(line)
        if not first:
            i += 1
            continue

        start_i = i
        headers: dict[str, str] = {}
        last_key: str | None = None

        # Read a header block (skip blank lines; stop on first non-header line).
        while i < len(lines):
            raw_line = lines[i]
            stripped = raw_line.strip()
            if not stripped:
                i += 1
                continue
            kv = _header_kv(stripped)
            if kv:
                key, val = kv
                headers[key] = (
                    headers.get(key, "") + ("\n" if key in headers else "") + val
                ).strip()
                last_key = key
                i += 1
                continue
            if last_key and (raw_line.startswith(" ") or raw_line.startswith("\t")):
                headers[last_key] = (headers.get(last_key, "") + " " + stripped).strip()
                i += 1
                continue
            break

        from_val = headers.get("from")
        subject_val = headers.get("subject")
        date_val = headers.get("sent") or headers.get("date")
        if not (from_val and subject_val and date_val):
            i = start_i + 1
            continue

        sender_email, sender_name = _parse_sender_from_header(from_val)
        dt = _parse_forwarded_datetime(date_val)
        subject = subject_val.strip() or None

        # Read body until the next embedded header block.
        body_lines: list[str] = []
        while i < len(lines):
            peek = lines[i].strip()
            if _EMBEDDED_SEPARATOR_RE.match(peek):
                break
            if _header_kv(peek):
                break
            body_lines.append(lines[i])
            i += 1

        body_plain = _unquote_lines("\n".join(body_lines)).strip() or None

        fp = (
            (sender_email or sender_name or None),
            subject,
            (dt.isoformat() if dt else None),
        )
        if fp in seen:
            continue
        seen.add(fp)

        recipients_display: dict[str, str] = {}
        for key in ("to", "cc", "bcc"):
            display_val = _normalize_recipient_display(headers.get(key))
            if display_val:
                recipients_display[key] = display_val

        results.append(
            ParsedEmail(
                subject=subject,
                sender_email=sender_email,
                sender_name=sender_name,
                recipients_to=_parse_recipients_from_header(headers.get("to")),
                recipients_cc=_parse_recipients_from_header(headers.get("cc")),
                recipients_bcc=_parse_recipients_from_header(headers.get("bcc")),
                recipients_display=recipients_display or None,
                date_sent=dt,
                date_received=None,
                message_id=None,
                in_reply_to=None,
                references=None,
                body_plain=body_plain,
                body_html=None,
                body_rtf=None,
                attachments=[],
                raw_headers={k: v for k, v in headers.items()},
            )
        )

    return results


def _text_part_to_str(part: Any) -> str | None:
    # Under policy.default, get_content() returns str for text/* parts.
    try:
        val = part.get_content()
        if isinstance(val, str):
            return val
    except Exception:
        pass

    try:
        payload = part.get_payload(decode=True)
        if not payload:
            return None
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return None


def parse_eml_bytes(raw: bytes) -> ParsedEmail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    subject = (msg.get("Subject") or "").strip() or None
    sender_email, sender_name = _parse_sender_from_header(msg.get("From") or "")

    # Common headers can appear multiple times; get_all covers that.
    to_list = _parse_addresses(msg.get_all("To"))
    cc_list = _parse_addresses(msg.get_all("Cc"))
    bcc_list = _parse_addresses(msg.get_all("Bcc"))
    to_display = _normalize_recipient_display(_join_header_values(msg.get_all("To")))
    cc_display = _normalize_recipient_display(_join_header_values(msg.get_all("Cc")))
    bcc_display = _normalize_recipient_display(_join_header_values(msg.get_all("Bcc")))

    date_sent = _parse_date(msg.get("Date"))

    message_id = (msg.get("Message-ID") or "").strip() or None
    in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
    references = (msg.get("References") or "").strip() or None

    body_plain: str | None = None
    body_html: str | None = None
    body_rtf: str | None = None
    attachments: list[ParsedAttachment] = []

    # Capture raw headers (best-effort) for forensics/meta.
    raw_headers: dict[str, str] = {}
    try:
        for k, v in msg.items():
            raw_headers[str(k)] = str(v)
    except Exception:
        raw_headers = {}

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue

            ctype = (part.get_content_type() or "application/octet-stream").lower()
            disposition = (part.get_content_disposition() or "").lower() or None
            filename = part.get_filename()
            content_id = part.get("Content-ID")
            if content_id:
                content_id = content_id.strip().strip("<>")

            # Prefer first encountered bodies of each type.
            if disposition is None and ctype == "text/plain" and body_plain is None:
                body_plain = _text_part_to_str(part)
                continue
            if disposition is None and ctype == "text/html" and body_html is None:
                body_html = _text_part_to_str(part)
                continue
            if disposition is None and ctype == "text/rtf" and body_rtf is None:
                body_rtf = _text_part_to_str(part)
                continue

            payload = None
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = None

            if not payload:
                continue

            payload_bytes: bytes
            if isinstance(payload, (bytes, bytearray)):
                payload_bytes = bytes(payload)
            else:
                # Extremely defensive: some parsers can surface non-bytes payloads.
                payload_bytes = str(payload).encode("utf-8", errors="replace")

            is_attachment = bool(filename) or disposition in {"attachment", "inline"}
            if not is_attachment:
                continue

            safe_name = filename or "attachment"
            attachments.append(
                ParsedAttachment(
                    filename=safe_name,
                    content_type=ctype or "application/octet-stream",
                    data=payload_bytes,
                    is_inline=(disposition == "inline"),
                    content_id=content_id,
                )
            )
    else:
        # Non-multipart: treat payload as body
        ctype = (msg.get_content_type() or "text/plain").lower()
        if ctype == "text/html":
            body_html = _text_part_to_str(msg)
        elif ctype == "text/rtf":
            body_rtf = _text_part_to_str(msg)
        else:
            body_plain = _text_part_to_str(msg)

    # Guard: some emails put HTML markup into the text/plain part.
    if body_plain and not body_html and _looks_like_html_markup(body_plain):
        body_html = body_plain
        body_plain = None
    # Ensure we have a reasonable plain-text fallback when only HTML exists.
    if not body_plain and body_html:
        try:
            derived = html_to_text(body_html)
            if derived and derived.strip():
                body_plain = derived
        except Exception:
            pass

    recipients_display: dict[str, str] = {}
    if to_display:
        recipients_display["to"] = to_display
    if cc_display:
        recipients_display["cc"] = cc_display
    if bcc_display:
        recipients_display["bcc"] = bcc_display

    return ParsedEmail(
        subject=subject,
        sender_email=sender_email,
        sender_name=sender_name,
        recipients_to=to_list,
        recipients_cc=cc_list,
        recipients_bcc=bcc_list,
        recipients_display=recipients_display or None,
        date_sent=date_sent,
        date_received=None,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        body_plain=body_plain,
        body_html=body_html,
        body_rtf=body_rtf,
        attachments=attachments,
        raw_headers=raw_headers,
    )


def parse_msg_bytes(raw: bytes) -> ParsedEmail:
    """Parse Outlook .msg bytes.

    Uses the optional `extract_msg` dependency. If it isn't installed, raise a
    helpful error so deployments can decide whether to enable MSG support.
    """

    try:
        import extract_msg  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=400,
            detail="MSG import support is not installed on the server (missing extract-msg)",
        ) from exc

    with tempfile.NamedTemporaryFile(suffix=".msg", delete=True) as tmp:
        tmp.write(raw)
        tmp.flush()

        m: Any | None = None
        try:
            m = extract_msg.Message(tmp.name)
            # extract-msg API compatibility:
            # - Older versions exposed Message.process()
            # - Newer versions (e.g. 0.55.0) parse lazily and do NOT have process()
            maybe_process = getattr(m, "process", None)
            if callable(maybe_process):
                maybe_process()
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to parse MSG: {exc}"
            ) from exc

        subject = (getattr(m, "subject", None) or "").strip() or None
        sender_raw = (
            getattr(m, "sender", None) or getattr(m, "sender_email", None) or ""
        )
        sender_name, sender_email = parseaddr(str(sender_raw))
        sender_name = sender_name.strip() or None
        sender_email = _clean_email_address(sender_email)

        to_list = _parse_addresses([str(getattr(m, "to", "") or "")])
        cc_list = _parse_addresses([str(getattr(m, "cc", "") or "")])
        bcc_list = _parse_addresses([str(getattr(m, "bcc", "") or "")])
        to_display = _normalize_recipient_display(getattr(m, "to", None))
        cc_display = _normalize_recipient_display(getattr(m, "cc", None))
        bcc_display = _normalize_recipient_display(getattr(m, "bcc", None))

        date_sent = _parse_date(str(getattr(m, "date", "") or ""))

        body_plain = getattr(m, "body", None)
        body_html = getattr(m, "htmlBody", None)
        body_rtf = getattr(m, "rtfBody", None)

        attachments: list[ParsedAttachment] = []
        try:
            for i, att in enumerate(getattr(m, "attachments", []) or []):
                try:
                    fname = (
                        getattr(att, "longFilename", None)
                        or getattr(att, "shortFilename", None)
                        or getattr(att, "filename", None)
                        or f"attachment_{i}"
                    )
                    fname = str(fname)

                    data: bytes | None = None
                    if hasattr(att, "data"):
                        data = getattr(att, "data")
                    elif hasattr(att, "getData"):
                        data = att.getData()  # type: ignore[attr-defined]

                    if data is None and hasattr(att, "save"):
                        with tempfile.TemporaryDirectory() as td:
                            try:
                                path = att.save(customPath=td)  # type: ignore[attr-defined]
                            except TypeError:
                                path = att.save(td)  # type: ignore[attr-defined]
                            if path and os.path.exists(path):
                                with open(path, "rb") as fh:
                                    data = fh.read()

                    if not data:
                        continue

                    ct, _ = mimetypes.guess_type(fname)
                    attachments.append(
                        ParsedAttachment(
                            filename=fname,
                            content_type=ct or "application/octet-stream",
                            data=data,
                            is_inline=False,
                            content_id=None,
                        )
                    )
                except Exception:
                    continue
        finally:
            # Ensure file handles are released (extract-msg keeps the OLE file open).
            try:
                if m is not None and callable(getattr(m, "close", None)):
                    m.close()
            except Exception:
                pass

        # extract_msg does not expose full RFC headers reliably; keep a small hint.
        raw_headers = {"X-Parsed-By": "extract_msg"}

        # Robust decode: extract-msg occasionally surfaces bytes for bodies.
        # Never use str(bytes) because it yields "b'...'" which then leaks into the UI.
        body_plain_str = decode_maybe_bytes(body_plain)
        body_html_str = decode_maybe_bytes(body_html)
        body_rtf_str = decode_maybe_bytes(body_rtf)

        # Guard: some MSG files expose HTML markup only via .body (htmlBody empty).
        if (
            not body_html_str
            and body_plain_str
            and _looks_like_html_markup(body_plain_str)
        ):
            body_html_str = body_plain_str
            body_plain_str = None

        # Ensure a plain-text fallback exists for display/search when only HTML exists.
        if not body_plain_str and body_html_str:
            try:
                derived = html_to_text(body_html_str)
                if derived and derived.strip():
                    body_plain_str = derived
            except Exception:
                pass

        recipients_display: dict[str, str] = {}
        if to_display:
            recipients_display["to"] = to_display
        if cc_display:
            recipients_display["cc"] = cc_display
        if bcc_display:
            recipients_display["bcc"] = bcc_display

        return ParsedEmail(
            subject=subject,
            sender_email=sender_email,
            sender_name=sender_name,
            recipients_to=to_list,
            recipients_cc=cc_list,
            recipients_bcc=bcc_list,
            recipients_display=recipients_display or None,
            date_sent=date_sent,
            date_received=None,
            message_id=None,
            in_reply_to=None,
            references=None,
            body_plain=body_plain_str,
            body_html=body_html_str,
            body_rtf=body_rtf_str,
            attachments=attachments,
            raw_headers=raw_headers,
        )


def _sanitize_attachment_filename(filename: str | None, fallback: str) -> str:
    if not filename:
        return fallback
    name = os.path.basename(str(filename).strip())
    name = name.replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = name.strip("._")
    return name or fallback


def _is_signature_image(
    filename: str, size: int, content_id: str | None, content_type: str | None
) -> bool:
    filename_lower = filename.lower() if filename else ""

    signature_patterns = [
        r"^logo\d*\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^signature\d*\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^image\d{3,}\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^~wrd\d+\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^banner\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^icon\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^header\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^footer\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^disclaimer\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^external.*\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^caution.*\.(?:png|jpg|jpeg|gif|bmp)$",
        r"^warning.*\.(?:png|jpg|jpeg|gif|bmp)$",
    ]

    for pattern in signature_patterns:
        if re.match(pattern, filename_lower):
            return True

    if size and size < 50000 and content_type and content_type.startswith("image/"):
        if content_id:
            return True
        if size < 10000:
            return True

    if (
        content_id
        and size
        and size < 500000
        and content_type
        and content_type.startswith("image/")
    ):
        return True

    return False


def _evidence_type_for_attachment(content_type: str | None, filename: str) -> str:
    file_ext = (os.path.splitext(filename)[1] or "").lstrip(".").lower()
    ct = (content_type or "").lower()

    if ct.startswith("image/") or file_ext in {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "bmp",
        "tiff",
        "webp",
    }:
        return "image"
    if ct.startswith("video/") or file_ext in {
        "mp4",
        "mov",
        "m4v",
        "avi",
        "mkv",
        "webm",
        "wmv",
    }:
        return "video"
    if ct.startswith("audio/") or file_ext in {
        "mp3",
        "wav",
        "m4a",
        "aac",
        "flac",
        "ogg",
        "opus",
    }:
        return "audio"
    if ct == "application/pdf" or file_ext == "pdf":
        return "pdf"
    if "word" in ct or ct.endswith(".document") or file_ext in {"doc", "docx"}:
        return "word_document"
    if "excel" in ct or "spreadsheet" in ct or file_ext in {"xls", "xlsx", "csv"}:
        return "spreadsheet"
    if "powerpoint" in ct or "presentation" in ct or file_ext in {"ppt", "pptx"}:
        return "presentation"

    return "document"


def _sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    mv = memoryview(data)
    # Chunk to avoid peak allocs for very large attachments.
    for i in range(0, len(mv), 1024 * 1024):
        h.update(mv[i : i + 1024 * 1024])
    return h.hexdigest()


def _detect_email_import_kind(filename: str, raw: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    magic = raw[:5]

    if ext in {"eml", "msg"}:
        return ext

    if magic.startswith(b"%PDF"):
        return "pdf"
    if magic[:2] == b"PK":
        return "zip"

    if ext == "pdf":
        return "pdf"
    if ext == "zip":
        return "zip"
    if ext == "txt":
        return "txt"

    return ext or "unknown"


def _store_source_artifact(
    *,
    raw: bytes,
    pst: PSTFile,
    filename: str,
    file_hash: str | None = None,
) -> tuple[str, str, str]:
    file_hash = file_hash or sha256_hex_bytes(raw)
    safe_name = _sanitize_attachment_filename(filename, "source")
    bucket = (
        pst.s3_bucket
        or settings.S3_PST_BUCKET
        or settings.S3_BUCKET
        or settings.MINIO_BUCKET
    )
    s3_key = f"email_import_sources/{pst.id}/{file_hash}_{safe_name}"
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        put_object(s3_key, raw, content_type, bucket=bucket)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to store source file: {exc}"
        ) from exc
    return file_hash, bucket, s3_key


def _merge_meta_payload(
    meta_payload: dict[str, Any],
    *,
    source_details: dict[str, Any] | None,
    extra_meta: dict[str, Any] | None,
) -> None:
    if source_details:
        meta_payload["source_details"] = source_details
        if source_details.get("file_sha256"):
            meta_payload["source_file_sha256"] = source_details.get("file_sha256")
        if source_details.get("file_name"):
            meta_payload["source_file_name"] = source_details.get("file_name")
        if source_details.get("stored_key"):
            meta_payload["source_file_key"] = source_details.get("stored_key")
        if source_details.get("stored_bucket"):
            meta_payload["source_file_bucket"] = source_details.get("stored_bucket")
    if extra_meta:
        meta_payload.update(extra_meta)


@dataclass
class AttachmentEntry:
    safe_filename: str
    content_type: str
    data: bytes
    size: int
    file_hash: str
    is_inline: bool
    content_id: str | None


def _normalize_message_id(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"<([^>]+)>", text)
    if match:
        text = match.group(1)
    text = text.strip().strip("<>").strip()
    return text.lower() or None


def _message_id_variants(value: str | None) -> list[str]:
    if not value:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    variants: set[str] = {raw}
    raw_trim = raw.strip().strip("<>").strip()
    if raw_trim:
        variants.add(raw_trim)
        variants.add(f"<{raw_trim}>")
    norm = _normalize_message_id(raw)
    if norm:
        variants.add(norm)
        variants.add(f"<{norm}>")
    return sorted({v for v in variants if v})


def _prepare_attachment_entries(
    attachments: list[ParsedAttachment],
) -> list[AttachmentEntry]:
    entries: list[AttachmentEntry] = []
    for i, att in enumerate(attachments or []):
        data = att.data or b""
        if not data:
            continue
        size = len(data)
        safe_filename = _sanitize_attachment_filename(att.filename, f"attachment_{i}")
        content_type = (att.content_type or "application/octet-stream").lower()

        if content_type.startswith("image/") and _is_signature_image(
            safe_filename, size, att.content_id, content_type
        ):
            continue
        if att.is_inline and content_type.startswith("image/"):
            continue

        file_hash = _sha256_hex(data)
        entries.append(
            AttachmentEntry(
                safe_filename=safe_filename,
                content_type=content_type,
                data=data,
                size=size,
                file_hash=file_hash,
                is_inline=bool(att.is_inline),
                content_id=att.content_id,
            )
        )
    return entries


def _load_attachment_hashes(
    db: Session, email_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    if not email_ids:
        return {}
    rows = (
        db.query(EmailAttachment.email_message_id, EmailAttachment.attachment_hash)
        .filter(EmailAttachment.email_message_id.in_(email_ids))
        .all()
    )
    attachments: dict[uuid.UUID, list[str]] = {}
    for email_id, attachment_hash in rows:
        if not email_id or not attachment_hash:
            continue
        attachments.setdefault(email_id, []).append(str(attachment_hash))
    for key in attachments:
        attachments[key] = sorted(set(attachments[key]))
    return attachments


def _persist_attachment_entries(
    *,
    entries: list[AttachmentEntry],
    email_id: uuid.UUID,
    pst: PSTFile,
    company_id: str | None,
    original_filename: str,
    db: Session,
    user: User,
) -> list[dict[str, Any]]:
    attachments_info: list[dict[str, Any]] = []
    if not entries:
        return attachments_info

    attach_bucket = settings.S3_ATTACHMENTS_BUCKET or settings.S3_BUCKET
    entity_folder = (
        f"case_{pst.case_id}" if pst.case_id else f"project_{pst.project_id}"
    )
    company_prefix = company_id if company_id else "no_company"

    for entry in entries:
        hash_prefix = entry.file_hash[:8]
        s3_key = (
            f"attachments/{company_prefix}/{entity_folder}/"
            f"{hash_prefix}_{entry.safe_filename}"
        )

        try:
            put_object(s3_key, entry.data, entry.content_type, bucket=attach_bucket)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to store attachment {entry.safe_filename}: {exc}",
            ) from exc

        email_attachment = EmailAttachment(
            email_message_id=email_id,
            filename=entry.safe_filename,
            content_type=entry.content_type,
            file_size_bytes=entry.size,
            s3_bucket=attach_bucket,
            s3_key=s3_key,
            attachment_hash=entry.file_hash,
            is_inline=bool(entry.is_inline),
            content_id=entry.content_id,
            is_duplicate=False,
        )
        db.add(email_attachment)

        evidence_item_id = uuid.uuid4()
        evidence_type_category = _evidence_type_for_attachment(
            entry.content_type, entry.safe_filename
        )
        evidence_item = EvidenceItem(
            id=evidence_item_id,
            filename=entry.safe_filename,
            original_path=f"EMAIL_IMPORT:{original_filename}/{entry.safe_filename}",
            file_type=(
                os.path.splitext(entry.safe_filename)[1] or ""
            ).lstrip(".").lower()
            or None,
            mime_type=entry.content_type,
            file_size=entry.size,
            file_hash=entry.file_hash,
            s3_bucket=attach_bucket,
            s3_key=s3_key,
            evidence_type=evidence_type_category,
            source_type="email_import",
            source_email_id=email_id,
            case_id=pst.case_id,
            project_id=pst.project_id,
            is_duplicate=False,
            duplicate_of_id=None,
            processing_status="pending",
            auto_tags=["email-attachment", "from-email-import"],
            uploaded_by=getattr(user, "id", None),
            meta={
                "email_import": {
                    "pst_file_id": str(pst.id),
                    "email_id": str(email_id),
                    "content_id": entry.content_id,
                    "is_inline": bool(entry.is_inline),
                }
            },
        )
        db.add(evidence_item)

        attachments_info.append(
            {
                "attachment_id": str(email_attachment.id),
                "evidence_item_id": str(evidence_item_id),
                "filename": entry.safe_filename,
                "size": entry.size,
                "content_type": entry.content_type,
                "is_inline": bool(entry.is_inline),
                "content_id": entry.content_id,
                "s3_key": s3_key,
                "hash": entry.file_hash,
                "attachment_hash": entry.file_hash,
                "is_duplicate": False,
            }
        )

    return attachments_info


def _ingest_parsed_email(
    *,
    parsed: ParsedEmail,
    pst: PSTFile,
    db: Session,
    user: User,
    company_id: str | None,
    source_type: str,
    original_filename: str,
    source_details: dict[str, Any] | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # ============================================================
    # PST-parity body extraction (per-message)
    # ============================================================
    body_selection = select_best_body(
        plain_text=parsed.body_plain,
        html_body=parsed.body_html,
        rtf_body=parsed.body_rtf,
    )

    body_html_content = parsed.body_html or None
    full_body_text = body_selection.full_text or ""
    full_body_text_original = full_body_text

    canonical_body = body_selection.top_text or ""
    # Mirror PST ingestion guardrails (avoid empty/too-short top_text).
    if canonical_body and len(canonical_body) < 20 and len(full_body_text) <= 200:
        canonical_body = full_body_text
    elif not canonical_body and full_body_text and len(full_body_text) > 200:
        canonical_body = full_body_text

    body_text_clean = clean_body_text(canonical_body)
    if body_text_clean is not None:
        canonical_body = body_text_clean

    # Normalize canonical body for hashing/spam (PST parity).
    if canonical_body:
        canonical_body = re.sub(r"\s+", " ", canonical_body).strip()

    scope_preview = (body_text_clean or canonical_body or full_body_text).strip()
    scope_preview = scope_preview[:4000] if scope_preview else None

    # ============================================================
    # Early duplicate detection (before spam + heavy extraction)
    # ============================================================
    dedupe_content_hash = build_content_hash(
        canonical_body or None,
        parsed.sender_email,
        parsed.sender_name,
        parsed.recipients_to,
        parsed.subject,
        parsed.date_sent,
    )
    message_id_norm = _normalize_message_id(parsed.message_id)
    message_id_variants = _message_id_variants(parsed.message_id)

    attachment_entries = _prepare_attachment_entries(parsed.attachments)
    incoming_attachment_hashes = [entry.file_hash for entry in attachment_entries]

    if dedupe_content_hash or message_id_variants:
        filters = []
        if dedupe_content_hash:
            filters.append(EmailMessage.content_hash == dedupe_content_hash)
        if message_id_variants:
            filters.append(EmailMessage.message_id.in_(message_id_variants))

        candidates = (
            db.query(EmailMessage)
            .filter(or_(*filters))
            .filter(EmailMessage.project_id == pst.project_id)
            .filter(EmailMessage.case_id == pst.case_id)
            .all()
        )
    else:
        candidates = []

    if candidates:
        candidate_ids = [row.id for row in candidates if row.id]
        attachments_by_email = _load_attachment_hashes(db, candidate_ids)

        best_candidate = None
        best_rank = None
        for row in candidates:
            row_msg_norm = _normalize_message_id(row.message_id)
            match_message_id = bool(
                message_id_norm and row_msg_norm == message_id_norm
            )
            match_content = bool(
                dedupe_content_hash and row.content_hash == dedupe_content_hash
            )
            if not (match_message_id or match_content):
                continue
            existing_hashes = set(attachments_by_email.get(row.id, []))
            rank = (
                2 if match_message_id else 0,
                1 if match_content else 0,
                len(existing_hashes),
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_candidate = {
                    "id": row.id,
                    "existing_hashes": existing_hashes,
                }

        if best_candidate:
            existing_hashes = best_candidate["existing_hashes"]
            missing_hashes = set(incoming_attachment_hashes) - existing_hashes
            existing_email_id = best_candidate["id"]

            if not missing_hashes:
                return {
                    "email_id": str(existing_email_id),
                    "duplicate": True,
                    "duplicate_of_email_id": str(existing_email_id),
                    "attachments_merged": False,
                    "attachments_added": 0,
                    "pst_file_id": str(pst.id),
                    "embedded_email_ids": [],
                    "has_attachments": bool(existing_hashes),
                    "message": "Duplicate skipped",
                }

            # Same message but new attachments: merge into the existing email.
            existing_email = (
                db.query(EmailMessage)
                .filter(EmailMessage.id == existing_email_id)
                .first()
            )
            if existing_email:
                missing_entries = [
                    entry
                    for entry in attachment_entries
                    if entry.file_hash in missing_hashes
                ]
                attachments_info = _persist_attachment_entries(
                    entries=missing_entries,
                    email_id=existing_email_id,
                    pst=pst,
                    company_id=company_id,
                    original_filename=original_filename,
                    db=db,
                    user=user,
                )

                has_attachments = bool(existing_hashes or attachments_info)
                existing_email.has_attachments = has_attachments

                meta = existing_email.meta if isinstance(existing_email.meta, dict) else {}
                existing_meta_attachments = meta.get("attachments", [])
                if isinstance(existing_meta_attachments, list):
                    meta["attachments"] = (
                        existing_meta_attachments + attachments_info
                    )
                else:
                    meta["attachments"] = attachments_info
                meta["has_attachments"] = has_attachments
                existing_email.meta = meta

                db.commit()

                return {
                    "email_id": str(existing_email_id),
                    "duplicate": True,
                    "duplicate_of_email_id": str(existing_email_id),
                    "attachments_merged": True,
                    "attachments_added": len(attachments_info),
                    "pst_file_id": str(pst.id),
                    "embedded_email_ids": [],
                    "has_attachments": has_attachments,
                    "message": "Duplicate merged attachments",
                }

    # ============================================================
    # PST-parity spam classification (subject/sender/body)
    # ============================================================
    spam_res = classify_email_ai_sync(
        parsed.subject or "",
        (parsed.sender_email or parsed.sender_name or ""),
        scope_preview or "",
        db,
    )
    spam_category = spam_res.get("category")
    spam_score = int(spam_res.get("score") or 0)
    is_spam = bool(spam_res.get("is_spam"))
    spam_is_hidden = bool(spam_res.get("is_hidden", False))

    # Best-effort: keep the legacy "other project" detector as a fallback.
    other_project_value = spam_res.get("extracted_entity") or extract_other_project(
        parsed.subject
    )

    excluded = bool((is_spam and spam_is_hidden) or other_project_value)

    derived_status = "other_project" if other_project_value else "spam"
    body_label = spam_category or derived_status or "spam"

    # ============================================================
    # PST-parity preview + optional offload of FULL body to S3
    # ============================================================
    preview_source = full_body_text or body_html_content or ""
    body_preview = preview_source[:10000] if preview_source else None

    body_offload_threshold = (
        getattr(settings, "PST_BODY_OFFLOAD_THRESHOLD", 50000) or 50000
    )
    body_offload_bucket = (
        getattr(settings, "S3_EMAIL_BODY_BUCKET", None)
        or settings.S3_BUCKET
        or settings.MINIO_BUCKET
    )

    offloaded_body_key: str | None = None
    if (
        not excluded
        and full_body_text
        and len(full_body_text) > int(body_offload_threshold)
        and body_offload_bucket
    ):
        try:
            entity_folder = (
                f"case_{pst.case_id}" if pst.case_id else f"project_{pst.project_id}"
            )
            dt_part = parsed.date_sent.isoformat() if parsed.date_sent else "no_date"
            offloaded_body_key = (
                f"email-bodies/{entity_folder}/{dt_part}_{uuid.uuid4().hex}.txt"
            )
            put_object(
                offloaded_body_key,
                full_body_text.encode("utf-8"),
                "text/plain; charset=utf-8",
                bucket=body_offload_bucket,
            )
            # Keep only preview in DB; canonical body remains for dedupe/search.
            full_body_text = ""
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Failed to offload email body: {exc}"
            ) from exc

    # ============================================================
    # PST-parity content hash (dedupe)
    # ============================================================
    if excluded:
        content_hash = build_content_hash(
            None,
            parsed.sender_email,
            parsed.sender_name,
            parsed.recipients_to,
            parsed.subject,
            parsed.date_sent,
        )
    else:
        content_hash = dedupe_content_hash

    normalized_hash = (
        compute_normalized_text_hash((body_text_clean or canonical_body or ""))
        if (not excluded and (body_text_clean or canonical_body))
        else None
    )

    email_id = uuid.uuid4()

    spam_payload: dict[str, Any] = {
        "is_spam": is_spam,
        "score": spam_score,
        "category": spam_category,
        "is_hidden": spam_is_hidden,
        "status_set_by": "spam_filter_ingest",
    }

    recipients_display = parsed.recipients_display or None

    meta_payload: dict[str, Any] = {
        "source": source_type,
        "original_filename": original_filename,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
        "spam_score": spam_score,
        "is_spam": is_spam,
        "is_hidden": bool(spam_is_hidden or other_project_value),
        "spam_reasons": [spam_category] if spam_category else [],
        "other_project": other_project_value,
        "spam": spam_payload,
        "raw_headers": parsed.raw_headers,
        "recipients_display": recipients_display,
        "attachments": [],
    }

    _merge_meta_payload(
        meta_payload, source_details=source_details, extra_meta=extra_meta
    )

    if excluded:
        meta_payload["status"] = derived_status
        meta_payload["excluded"] = True
        spam_payload["applied_status"] = derived_status
        meta_payload["attachments_skipped"] = bool(parsed.attachments)
        meta_payload["attachments_skipped_reason"] = derived_status
    else:
        meta_payload.update(
            {
                "canonical_hash": content_hash,
                "body_offloaded": bool(offloaded_body_key),
                "body_offload_bucket": (
                    body_offload_bucket if offloaded_body_key else None
                ),
                "body_offload_key": offloaded_body_key,
                # Backward-compatible hint for consumers expecting the explicit field.
                "body_full_s3_key": offloaded_body_key,
                "body_source": body_selection.selected_source,
                "body_selection": body_selection.diagnostics,
                "body_quoted_len": len(body_selection.quoted_text or ""),
                "body_signature_len": len(body_selection.signature_text or ""),
            }
        )

    email_message = EmailMessage(
        id=email_id,
        pst_file_id=pst.id,
        case_id=pst.case_id,
        project_id=pst.project_id,
        message_id=parsed.message_id,
        in_reply_to=parsed.in_reply_to,
        email_references=parsed.references,
        conversation_index=None,
        subject=parsed.subject,
        sender_email=parsed.sender_email,
        sender_name=parsed.sender_name,
        recipients_to=parsed.recipients_to,
        recipients_cc=parsed.recipients_cc,
        recipients_bcc=parsed.recipients_bcc,
        date_sent=parsed.date_sent,
        date_received=parsed.date_received,
        body_text=None if excluded else (full_body_text or None),
        body_html=None if excluded else body_html_content,
        body_text_clean=None if excluded else (body_text_clean or None),
        body_text_clean_hash=normalized_hash,
        body_preview=(f"[EXCLUDED: {body_label}]" if excluded else body_preview),
        body_full_s3_key=offloaded_body_key,
        content_hash=content_hash,
        has_attachments=bool(parsed.attachments) if excluded else False,
        meta=meta_payload,
        thread_group_id=parsed.thread_group_id,
        thread_position=parsed.thread_position,
        thread_path=parsed.thread_path,
    )

    db.add(email_message)

    # Attachments: only ingest for non-excluded emails (parity with PST processor).
    attachments_info: list[dict[str, Any]] = []
    has_attachments = bool(parsed.attachments) if excluded else False

    if not excluded:
        attachments_info = _persist_attachment_entries(
            entries=attachment_entries,
            email_id=email_id,
            pst=pst,
            company_id=company_id,
            original_filename=original_filename,
            db=db,
            user=user,
        )
        has_attachments = bool(attachments_info)

    email_message.has_attachments = has_attachments
    if isinstance(email_message.meta, dict):
        email_message.meta["attachments"] = attachments_info
        email_message.meta["has_attachments"] = has_attachments

    # Best-effort: extract embedded forwarded messages (common in saved .msg forwards).
    embedded_created = 0
    embedded_email_ids: list[str] = []
    extract_embedded = bool(
        getattr(settings, "EMAIL_IMPORT_EXTRACT_EMBEDDED", False)
    )
    if not excluded and extract_embedded:
        try:
            embedded = _extract_embedded_forwarded_emails(full_body_text_original)
        except Exception:
            embedded = []

        if embedded:
            for idx, emb in enumerate(embedded[:25]):
                # Avoid inserting empty shells
                if not (
                    emb.subject or emb.sender_email or emb.sender_name or emb.body_plain
                ):
                    continue

                sel = select_best_body(
                    plain_text=emb.body_plain,
                    html_body=emb.body_html,
                    rtf_body=emb.body_rtf,
                )
                emb_full = (sel.full_text or "").strip()
                emb_canon = (sel.top_text or "").strip()
                if emb_canon and len(emb_canon) < 20 and len(emb_full) <= 200:
                    emb_canon = emb_full
                elif not emb_canon and emb_full and len(emb_full) > 200:
                    emb_canon = emb_full

                cleaned = clean_body_text(emb_canon)
                if cleaned is not None:
                    emb_canon = cleaned
                if emb_canon:
                    emb_canon = re.sub(r"\s+", " ", emb_canon).strip()

                # Skip obvious duplicates of the parent.
                if (
                    (emb.sender_email and emb.sender_email == parsed.sender_email)
                    and (emb.subject and emb.subject == parsed.subject)
                    and (emb.date_sent and emb.date_sent == parsed.date_sent)
                ):
                    continue

                emb_hash = build_content_hash(
                    emb_canon or None,
                    emb.sender_email,
                    emb.sender_name,
                    emb.recipients_to,
                    emb.subject,
                    emb.date_sent,
                )
                if emb_hash and emb_hash == content_hash:
                    continue

                emb_norm_hash = (
                    compute_normalized_text_hash(emb_canon) if emb_canon else None
                )
                emb_id = uuid.uuid4()
                emb_meta: dict[str, Any] = {
                    "source": f"{source_type}_embedded",
                    "original_filename": original_filename,
                    "derived_from_email_id": str(email_id),
                    "embedded_index": idx,
                    "normalizer_version": NORMALIZER_VERSION,
                    "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
                    "raw_headers": emb.raw_headers,
                }

                db.add(
                    EmailMessage(
                        id=emb_id,
                        pst_file_id=pst.id,
                        case_id=pst.case_id,
                        project_id=pst.project_id,
                        message_id=None,
                        in_reply_to=None,
                        email_references=None,
                        conversation_index=None,
                        subject=emb.subject,
                        sender_email=emb.sender_email,
                        sender_name=emb.sender_name,
                        recipients_to=emb.recipients_to,
                        recipients_cc=emb.recipients_cc,
                        recipients_bcc=emb.recipients_bcc,
                        date_sent=emb.date_sent,
                        date_received=None,
                        body_text=emb_full or None,
                        body_html=None,
                        body_text_clean=emb_canon or None,
                        body_text_clean_hash=emb_norm_hash,
                        body_preview=(emb_full[:10000] if emb_full else None),
                        body_full_s3_key=None,
                        content_hash=emb_hash,
                        has_attachments=False,
                        meta=emb_meta,
                    )
                )
                embedded_created += 1
                embedded_email_ids.append(str(emb_id))

            if isinstance(email_message.meta, dict) and embedded_created:
                email_message.meta["embedded_extracted"] = embedded_created
                email_message.meta["embedded_email_ids"] = embedded_email_ids

    # Best-effort progress update.
    try:
        pst.processed_emails = int(pst.processed_emails or 0) + 1 + embedded_created
    except Exception:
        pass

    db.commit()

    return {
        "email_id": str(email_id),
        "embedded_email_ids": embedded_email_ids,
        "pst_file_id": str(pst.id),
        "excluded": excluded,
        "has_attachments": has_attachments,
        "message": "Email imported",
    }

async def init_email_import_service(
    *,
    case_id: str | None,
    project_id: str | None,
    batch_name: str | None,
    db: Session,
    user: User,
) -> dict[str, Any]:
    if not case_id and not project_id:
        raise HTTPException(
            status_code=400, detail="Either case_id or project_id must be provided"
        )

    company_id: str | None = None
    entity_prefix: str

    if case_id:
        case = db.query(Case).filter_by(id=case_id).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        company_id = str(getattr(case, "company_id", None) or "") or None
        entity_prefix = f"case_{case_id}"
    else:
        project = db.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        company_id = str(getattr(project, "company_id", None) or "") or None
        entity_prefix = f"project_{project_id}"

    _ = company_id  # reserved for future use

    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    safe_name = (batch_name or "Email import").strip() or "Email import"
    # Represent the import batch as a synthetic PST container.
    pst_filename = f"{safe_name}.email_import.json"
    s3_key = f"{entity_prefix}/email_import/{pst_file_id}/{pst_filename}"

    manifest = {
        "type": "email_import",
        "pst_file_id": pst_file_id,
        "case_id": case_id,
        "project_id": project_id,
        "batch_name": safe_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": str(getattr(user, "id", "") or ""),
        "notes": "Synthetic container for standalone email imports",
    }

    try:
        put_object(
            s3_key,
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            "application/json",
            bucket=s3_bucket,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to store import manifest: {exc}"
        ) from exc

    pst_file = PSTFile(
        id=pst_file_id,
        filename=pst_filename,
        case_id=case_id,
        project_id=project_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size_bytes=len(json.dumps(manifest)),
        total_emails=0,
        processed_emails=0,
        processing_status="processing",
        processing_started_at=datetime.utcnow(),
        uploaded_by=getattr(user, "id", None),
    )
    db.add(pst_file)
    db.commit()

    return {
        "pst_file_id": pst_file_id,
        "message": "Email import initialized",
    }


async def upload_email_file_service(
    *,
    pst_file_id: str,
    file: UploadFile,
    db: Session,
    user: User,
) -> dict[str, Any]:
    _ = user  # auth enforced by routes; stored by synthetic PSTFile

    pst_uuid = _safe_uuid(pst_file_id, "pst_file_id")
    pst = db.query(PSTFile).filter(PSTFile.id == pst_uuid).first()
    if not pst:
        raise HTTPException(status_code=404, detail="Import batch not found")

    if pst.processing_status not in {"processing", "pending", "uploaded"}:
        raise HTTPException(
            status_code=409,
            detail=f"Batch is not accepting uploads (status={pst.processing_status})",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    kind = _detect_email_import_kind(file.filename, raw)
    file_hash = sha256_hex_bytes(raw)

    # Resolve company ID for attachment storage prefix.
    company_id: str | None = None
    if pst.case_id:
        case = db.query(Case).filter(Case.id == pst.case_id).first()
        company_id = str(getattr(case, "company_id", None) or "") or None
    elif pst.project_id:
        project = db.query(Project).filter(Project.id == pst.project_id).first()
        company_id = str(getattr(project, "company_id", None) or "") or None

    source_details: dict[str, Any] | None = None
    parsed_messages: list[ParsedEmail] = []
    source_type = "eml_import"

    if kind == "eml":
        parsed_messages = [parse_eml_bytes(raw)]
        source_type = "eml_import"
    elif kind == "msg":
        parsed_messages = [parse_msg_bytes(raw)]
        source_type = "msg_import"
    elif kind in {"txt", "zip"}:
        file_hash, bucket, key = _store_source_artifact(
            raw=raw, pst=pst, filename=file.filename, file_hash=file_hash
        )
        default_order = str(getattr(settings, "WHATSAPP_DATE_ORDER", "DMY") or "DMY")
        max_messages = getattr(settings, "WHATSAPP_MAX_MESSAGES", None)

        if kind == "txt":
            result = parse_whatsapp_bytes(
                raw,
                filename=file.filename,
                source_file_sha256=file_hash,
                default_date_order=default_order,
                max_messages=max_messages,
            )
        else:
            max_files = int(getattr(settings, "EMAIL_IMPORT_ZIP_MAX_FILES", 2000))
            max_bytes = int(
                getattr(
                    settings,
                    "EMAIL_IMPORT_ZIP_MAX_UNCOMPRESSED_BYTES",
                    1024 * 1024 * 500,
                )
            )
            max_ratio = float(getattr(settings, "EMAIL_IMPORT_ZIP_MAX_RATIO", 200.0))
            result = parse_whatsapp_zip_bytes(
                raw,
                filename=file.filename,
                source_file_sha256=file_hash,
                default_date_order=default_order,
                max_messages=max_messages,
                max_files=max_files,
                max_uncompressed_bytes=max_bytes,
                max_ratio=max_ratio,
            )

        parsed_messages = result.messages
        source_type = "whatsapp_import"
        unmatched = result.unmatched_media or []
        if len(unmatched) > 50:
            unmatched = unmatched[:50]
        source_details = {
            "type": "whatsapp",
            "file_name": file.filename,
            "file_sha256": file_hash,
            "file_size": len(raw),
            "stored_bucket": bucket,
            "stored_key": key,
            "chat_name": result.chat_name,
            "export_format": result.export_format,
            "parser_version": "whatsapp_v1",
            "timezone_assumed": "UTC",
            "date_order": default_order,
            "stats": result.stats,
            "unmatched_media": unmatched,
            "unmatched_media_truncated": len(result.unmatched_media or []) > 50,
        }
    elif kind == "pdf":
        file_hash, bucket, key = _store_source_artifact(
            raw=raw, pst=pst, filename=file.filename, file_hash=file_hash
        )
        use_textract = bool(
            getattr(settings, "EMAIL_IMPORT_PDF_USE_TEXTRACT", False)
        )
        pdf_result = await parse_pdf_email_bytes(
            raw,
            filename=file.filename,
            source_file_sha256=file_hash,
            use_tika=True,
            use_textract=use_textract,
        )
        parsed_messages = pdf_result.messages
        source_type = "pdf_import"
        source_details = {
            "type": "pdf_email",
            "file_name": file.filename,
            "file_sha256": file_hash,
            "file_size": len(raw),
            "stored_bucket": bucket,
            "stored_key": key,
            "extraction_method": pdf_result.extraction_method,
            "warnings": pdf_result.warnings,
            "stats": pdf_result.stats,
            "parser_version": "pdf_email_v1",
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type for email import",
        )

    if not parsed_messages:
        raise HTTPException(
            status_code=400, detail="No messages could be parsed from the file"
        )

    email_ids: list[str] = []
    duplicates_found = 0
    merged_count = 0
    merged_attachments = 0
    embedded_ids: list[str] = []
    imported_count = 0

    for parsed in parsed_messages:
        res = _ingest_parsed_email(
            parsed=parsed,
            pst=pst,
            db=db,
            user=user,
            company_id=company_id,
            source_type=source_type,
            original_filename=file.filename,
            source_details=source_details,
        )
        if res.get("email_id"):
            email_ids.append(res["email_id"])
        if res.get("embedded_email_ids"):
            embedded_ids.extend(res.get("embedded_email_ids") or [])
        if res.get("duplicate"):
            duplicates_found += 1
            if res.get("attachments_merged"):
                merged_count += 1
                merged_attachments += int(res.get("attachments_added") or 0)
        else:
            imported_count += 1

    return {
        "pst_file_id": pst_file_id,
        "source_type": source_type,
        "messages_total": len(parsed_messages),
        "messages_imported": imported_count,
        "duplicates_found": duplicates_found,
        "duplicate": duplicates_found > 0,
        "attachments_merged": merged_count > 0,
        "attachments_added": merged_attachments,
        "email_ids": email_ids,
        "embedded_email_ids": embedded_ids,
        "message": "Email import processed",
    }


async def finalize_email_import_service(
    *,
    pst_file_id: str,
    db: Session,
    user: User,
) -> dict[str, Any]:
    _ = user  # auth enforced by routes

    pst_uuid = _safe_uuid(pst_file_id, "pst_file_id")
    pst = db.query(PSTFile).filter(PSTFile.id == pst_uuid).first()
    if not pst:
        raise HTTPException(status_code=404, detail="Import batch not found")

    emails_in_db = (
        db.query(func.count(EmailMessage.id))
        .filter(EmailMessage.pst_file_id == pst_uuid)
        .scalar()
    )
    emails_in_db = int(emails_in_db or 0)

    # If nothing was imported, treat the batch as failed. This avoids the confusing
    # "Complete (0 of 0)" state which commonly happens when *all* uploads failed.
    if emails_in_db <= 0:
        pst.processing_status = "failed"
        pst.total_emails = 0
        pst.processed_emails = 0
        pst.processing_completed_at = datetime.utcnow()
        pst.error_message = (
            "Email import finished with 0 emails. "
            "This usually means all file uploads failed or were rejected by the server."
        )
        db.commit()
        raise HTTPException(status_code=409, detail=pst.error_message)

    from ..email_threading import build_email_threads
    from ..email_dedupe import dedupe_emails

    thread_scope = (
        str(getattr(settings, "PST_THREADING_SCOPE", "pst") or "pst")
        .strip()
        .lower()
    )
    thread_pst_id = pst_uuid if thread_scope == "pst" else None
    thread_stats = build_email_threads(
        db,
        case_id=pst.case_id,
        project_id=pst.project_id,
        pst_file_id=thread_pst_id,
        run_id="email_import_finalize",
    )

    dedupe_scope = (
        str(getattr(settings, "PST_DEDUPE_SCOPE", "pst") or "pst")
        .strip()
        .lower()
    )
    dedupe_pst_id = pst_uuid if dedupe_scope == "pst" else None
    dedupe_stats = dedupe_emails(
        db,
        case_id=pst.case_id,
        project_id=pst.project_id,
        pst_file_id=dedupe_pst_id,
        run_id="email_import_finalize",
    )

    pst.processing_status = "completed"
    pst.total_emails = emails_in_db
    pst.processed_emails = emails_in_db
    pst.processing_completed_at = datetime.utcnow()
    pst.error_message = None
    db.commit()

    return {
        "pst_file_id": pst_file_id,
        "emails_in_db": emails_in_db,
        "threading": {
            "threads_identified": int(
                getattr(thread_stats, "threads_identified", 0) or 0
            ),
            "links_created": int(getattr(thread_stats, "links_created", 0) or 0),
        },
        "dedupe": {
            "emails_total": int(getattr(dedupe_stats, "emails_total", 0) or 0),
            "duplicates_found": int(getattr(dedupe_stats, "duplicates_found", 0) or 0),
            "groups_matched": int(getattr(dedupe_stats, "groups_matched", 0) or 0),
        },
        "message": "Email import finalized",
    }
