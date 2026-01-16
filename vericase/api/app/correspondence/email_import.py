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
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..email_content import decode_maybe_bytes, html_to_text, select_best_body
from ..email_normalizer import (
    NORMALIZER_RULESET_HASH,
    NORMALIZER_VERSION,
    build_content_hash,
    clean_body_text,
)
from ..forensic_integrity import compute_normalized_text_hash
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

logger = logging.getLogger("vericase")


_HTML_DOC_START_RE = re.compile(
    r"(?is)^\s*(?:<!doctype\s+html\b|<\s*(?:html|head|body)\b)"
)
_HTML_COMMON_TAG_RE = re.compile(
    r"(?is)<\s*\/?\s*(?:div|span|p|br|table|tr|td|th|style|meta|link|font|center|a)\b"
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


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    data: bytes
    is_inline: bool
    content_id: str | None


@dataclass
class ParsedEmail:
    subject: str | None
    sender_email: str | None
    sender_name: str | None
    recipients_to: list[str] | None
    recipients_cc: list[str] | None
    recipients_bcc: list[str] | None
    date_sent: datetime | None
    date_received: datetime | None
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    body_plain: str | None
    body_html: str | None
    body_rtf: str | None
    attachments: list[ParsedAttachment]
    raw_headers: dict[str, str]


def _safe_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}") from exc


def _parse_addresses(headers: list[str] | None) -> list[str] | None:
    if not headers:
        return None
    pairs = getaddresses(headers)
    emails = [addr.strip() for _, addr in pairs if addr and addr.strip()]
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
    sender_name, sender_email = parseaddr(msg.get("From") or "")
    sender_name = sender_name.strip() or None
    sender_email = sender_email.strip() or None

    # Common headers can appear multiple times; get_all covers that.
    to_list = _parse_addresses(msg.get_all("To"))
    cc_list = _parse_addresses(msg.get_all("Cc"))
    bcc_list = _parse_addresses(msg.get_all("Bcc"))

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

    return ParsedEmail(
        subject=subject,
        sender_email=sender_email,
        sender_name=sender_name,
        recipients_to=to_list,
        recipients_cc=cc_list,
        recipients_bcc=bcc_list,
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
        sender_email = sender_email.strip() or None

        to_list = _parse_addresses([str(getattr(m, "to", "") or "")])
        cc_list = _parse_addresses([str(getattr(m, "cc", "") or "")])
        bcc_list = _parse_addresses([str(getattr(m, "bcc", "") or "")])

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

        return ParsedEmail(
            subject=subject,
            sender_email=sender_email,
            sender_name=sender_name,
            recipients_to=to_list,
            recipients_cc=cc_list,
            recipients_bcc=bcc_list,
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

    ext = os.path.splitext(file.filename)[1].lower().lstrip(".")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    if ext == "eml":
        parsed = parse_eml_bytes(raw)
        source_type = "eml_import"
    elif ext == "msg":
        parsed = parse_msg_bytes(raw)
        source_type = "msg_import"
    else:
        raise HTTPException(status_code=400, detail="Only .eml and .msg are supported")

    # Resolve company ID for attachment storage prefix.
    company_id: str | None = None
    if pst.case_id:
        case = db.query(Case).filter(Case.id == pst.case_id).first()
        company_id = str(getattr(case, "company_id", None) or "") or None
    elif pst.project_id:
        project = db.query(Project).filter(Project.id == pst.project_id).first()
        company_id = str(getattr(project, "company_id", None) or "") or None

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
        content_hash = build_content_hash(
            canonical_body or None,
            parsed.sender_email,
            parsed.sender_name,
            parsed.recipients_to,
            parsed.subject,
            parsed.date_sent,
        )

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

    meta_payload: dict[str, Any] = {
        "source": source_type,
        "original_filename": file.filename,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
        "spam_score": spam_score,
        "is_spam": is_spam,
        "is_hidden": bool(spam_is_hidden or other_project_value),
        "spam_reasons": [spam_category] if spam_category else [],
        "other_project": other_project_value,
        "spam": spam_payload,
        "raw_headers": parsed.raw_headers,
        "attachments": [],
    }

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
        pst_file_id=pst_uuid,
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
    )

    db.add(email_message)

    # Attachments: only ingest for non-excluded emails (parity with PST processor).
    attachments_info: list[dict[str, Any]] = []
    has_attachments = bool(parsed.attachments) if excluded else False

    if not excluded:
        attach_bucket = settings.S3_ATTACHMENTS_BUCKET or settings.S3_BUCKET
        entity_folder = (
            f"case_{pst.case_id}" if pst.case_id else f"project_{pst.project_id}"
        )
        company_prefix = company_id if company_id else "no_company"

        for i, att in enumerate(parsed.attachments):
            data = att.data or b""
            if not data:
                continue
            size = len(data)
            safe_filename = _sanitize_attachment_filename(
                att.filename, f"attachment_{i}"
            )
            content_type = (att.content_type or "application/octet-stream").lower()

            # Skip embedded/signature images (parity with PST processor).
            if content_type.startswith("image/") and _is_signature_image(
                safe_filename, size, att.content_id, content_type
            ):
                continue
            if att.is_inline and content_type.startswith("image/"):
                continue

            file_hash = _sha256_hex(data)
            hash_prefix = file_hash[:8]
            s3_key = f"attachments/{company_prefix}/{entity_folder}/{hash_prefix}_{safe_filename}"

            try:
                put_object(s3_key, data, content_type, bucket=attach_bucket)
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to store attachment {safe_filename}: {exc}",
                ) from exc

            email_attachment = EmailAttachment(
                email_message_id=email_id,
                filename=safe_filename,
                content_type=content_type,
                file_size_bytes=size,
                s3_bucket=attach_bucket,
                s3_key=s3_key,
                attachment_hash=file_hash,
                is_inline=bool(att.is_inline),
                content_id=att.content_id,
                is_duplicate=False,
            )
            db.add(email_attachment)

            evidence_item_id = uuid.uuid4()
            evidence_type_category = _evidence_type_for_attachment(
                content_type, safe_filename
            )

            evidence_item = EvidenceItem(
                id=evidence_item_id,
                filename=safe_filename,
                original_path=f"EMAIL_IMPORT:{file.filename}/{safe_filename}",
                file_type=(os.path.splitext(safe_filename)[1] or "").lstrip(".").lower()
                or None,
                mime_type=content_type,
                file_size=size,
                file_hash=file_hash,
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
                        "pst_file_id": pst_file_id,
                        "email_id": str(email_id),
                        "content_id": att.content_id,
                        "is_inline": bool(att.is_inline),
                    }
                },
            )
            db.add(evidence_item)

            attachments_info.append(
                {
                    "attachment_id": str(email_attachment.id),
                    "evidence_item_id": str(evidence_item_id),
                    "filename": safe_filename,
                    "size": size,
                    "content_type": content_type,
                    "is_inline": bool(att.is_inline),
                    "content_id": att.content_id,
                    "s3_key": s3_key,
                    "hash": file_hash,
                    "attachment_hash": file_hash,
                    "is_duplicate": False,
                }
            )
            has_attachments = True

    email_message.has_attachments = has_attachments
    if isinstance(email_message.meta, dict):
        email_message.meta["attachments"] = attachments_info
        email_message.meta["has_attachments"] = has_attachments

    # Best-effort progress update.
    try:
        pst.processed_emails = int(pst.processed_emails or 0) + 1
    except Exception:
        pass

    db.commit()

    return {
        "email_id": str(email_id),
        "pst_file_id": pst_file_id,
        "excluded": excluded,
        "has_attachments": has_attachments,
        "message": "Email imported",
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

    from ..email_threading import build_email_threads
    from ..email_dedupe import dedupe_emails

    thread_stats = build_email_threads(
        db,
        case_id=pst.case_id,
        project_id=pst.project_id,
        pst_file_id=pst_uuid,
        run_id="email_import_finalize",
    )
    dedupe_stats = dedupe_emails(
        db,
        case_id=pst.case_id,
        project_id=pst.project_id,
        pst_file_id=pst_uuid,
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
