# pyright: reportCallInDefaultInitializer=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""
Correspondence API Services
"""

import logging
import os
import uuid
import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session, selectinload, load_only
from sqlalchemy import func, or_, String
from boto3.s3.transfer import TransferConfig

from ..config import settings
from ..models import (
    Case,
    Project,
    PSTFile,
    EmailMessage,
    EvidenceItem,
    EvidenceCorrespondenceLink,
    User,
)
from ..storage import (
    multipart_abort,
    multipart_list_parts,
    multipart_complete,
    multipart_start,
    presign_part,
    presign_put,
    presign_get,
    s3,
)
from ..tasks import celery_app

# NOTE: PST cleanup helpers are intentionally local to this module so we can run
# cleanup using the *production* DB connection from within the API (no need for
# direct RDS access from a developer machine).
from .utils import (
    _parse_pst_status_filter,
    build_correspondence_hard_exclusion_filter,
    build_correspondence_visibility_filter,
    compute_correspondence_exclusion,
    _is_embedded_image,
    PSTUploadInitResponse,
    PSTMultipartInitResponse,
    PSTMultipartPartResponse,
    PSTProcessingStatus,
    PSTStatus,
    PSTFileListResponse,
    PSTFileInfo,
    EmailListResponse,
    EmailMessageSummary,
    EmailMessageDetail,
    ServerSideRequest,
    ServerSideResponse,
)

logger = logging.getLogger(__name__)

# Recommended chunk size: 100MB for optimal performance
MULTIPART_CHUNK_SIZE = 100 * 1024 * 1024  # 100MB
# Server-side streaming chunk size for legacy uploads to avoid buffering entire files
SERVER_STREAMING_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB


def _join_recipients(values: list[str] | None) -> str | None:
    if not values:
        return None
    # Keep it readable for UI display.
    return ", ".join([v for v in values if v]) or None


def _recipient_display_from_meta(meta: dict[str, Any], key: str) -> str | None:
    """Best-effort display fallback for To/Cc/Bcc when we don't have parseable SMTP addresses."""
    try:
        recips = meta.get("recipients_display")
        if isinstance(recips, dict):
            value = recips.get(key)
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    return cleaned[:2000]
    except Exception:
        return None
    return None


def _build_email_row(
    e: EmailMessage,
    attachment_items: list[dict[str, Any]] | None = None,
    linked_to_count: int | None = None,
    pst_filename: str | None = None,
) -> EmailMessageSummary:
    meta: dict[str, Any] = e.meta if isinstance(e.meta, dict) else {}
    exclusion = compute_correspondence_exclusion(meta, e.subject)
    email_to_display = _join_recipients(
        e.recipients_to
    ) or _recipient_display_from_meta(meta, "to")
    email_cc_display = _join_recipients(
        e.recipients_cc
    ) or _recipient_display_from_meta(meta, "cc")

    sender_display = None
    if e.sender_name and e.sender_email:
        sender_display = f"{e.sender_name} <{e.sender_email}>"
    else:
        sender_display = e.sender_name or e.sender_email

    attachments_payload = attachment_items or []

    # The UI uses these AG Grid compatibility fields.
    # Prefer a cleaned "display" body, but keep the raw body in dedicated fields.
    from ..email_normalizer import clean_email_body_for_display

    email_body = (
        clean_email_body_for_display(
            body_text_clean=e.body_text_clean,
            body_text=e.body_text,
            body_html=e.body_html,
        )
        or ""
    )

    effective_date = e.date_sent or e.date_received
    return EmailMessageSummary(
        id=str(e.id),
        subject=e.subject,
        sender_email=e.sender_email,
        sender_name=e.sender_name,
        body_text_clean=e.body_text_clean,
        body_html=e.body_html,
        body_text=e.body_text,
        content_hash=e.content_hash,
        date_sent=e.date_sent,
        has_attachments=bool(e.has_attachments),
        matched_stakeholders=e.matched_stakeholders,
        matched_keywords=e.matched_keywords,
        importance=e.importance,
        meta={**meta, "exclusion": exclusion},
        email_subject=e.subject,
        email_from=sender_display,
        email_to=email_to_display,
        email_cc=email_cc_display,
        email_date=effective_date,
        email_body=email_body,
        attachments=attachments_payload,
        attachment_count=len(attachments_payload),
        linked_to_count=linked_to_count,
        status=(meta.get("status") if isinstance(meta, dict) else None),
        # Programme/critical path fields (mapped from EmailMessage columns)
        programme_activity=e.as_planned_activity,
        as_built_activity=e.as_built_activity,
        as_planned_finish_date=e.as_planned_finish_date,
        as_built_finish_date=e.as_built_finish_date,
        delay_days=e.delay_days,
        is_critical_path=e.is_critical_path,
        # Notes: quick-win storage in metadata; can be migrated to a first-class column later.
        notes=(
            meta.get("notes")
            if isinstance(meta, dict) and isinstance(meta.get("notes"), str)
            else None
        ),
        thread_id=e.thread_group_id or e.thread_id,
        pst_file_id=str(e.pst_file_id) if e.pst_file_id else None,
        pst_filename=pst_filename,
    )


def _truncate_text(value: str | None, max_chars: int) -> str | None:
    if not value:
        return value
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _build_email_row_server_side(
    e: EmailMessage,
    *,
    attachment_items: list[dict[str, Any]] | None = None,
    linked_to_count: int | None = None,
    pst_filename: str | None = None,
    body_max_chars: int = 4000,
) -> dict[str, Any]:
    """
    Lightweight row payload for the AG Grid server-side row model.

    Critical: do NOT include full `body_text` / `body_html` in this response. Those fields
    can be very large and will slow down the correspondence grid dramatically. The full
    body is available via the email detail endpoint and is fetched on demand.
    """

    meta: dict[str, Any] = e.meta if isinstance(e.meta, dict) else {}
    exclusion = compute_correspondence_exclusion(meta, e.subject)
    email_to_display = _join_recipients(
        e.recipients_to
    ) or _recipient_display_from_meta(meta, "to")
    email_cc_display = _join_recipients(
        e.recipients_cc
    ) or _recipient_display_from_meta(meta, "cc")

    sender_display: str | None
    if e.sender_name and e.sender_email:
        sender_display = f"{e.sender_name} <{e.sender_email}>"
    else:
        sender_display = e.sender_name or e.sender_email

    attachments_payload = attachment_items or []

    # Prefer a cleaned "display" body preview, but keep it bounded.
    from ..email_normalizer import clean_email_body_for_display

    # Use the actual body_html field if available - this contains the full email content.
    # body_preview often contains only CAUTION banners for external emails.
    body_display = clean_email_body_for_display(
        body_text_clean=e.body_text_clean,
        body_text=e.body_text,
        body_html=e.body_html,
    )
    # If the cleaned display is empty, retry using the raw preview text (often fuller
    # than body_text_clean for externally bannered messages).
    if not body_display and e.body_preview:
        body_display = clean_email_body_for_display(
            body_text_clean=None,
            body_text=e.body_preview,
            body_html=None,
        )

    # Never return an empty body preview if we have *any* stored body signal.
    # Prefer preview text over banner-only clean bodies.
    if not body_display:
        body_display = e.body_preview or e.body_text_clean or ""

    email_body = _truncate_text((body_display or "").strip(), body_max_chars) or None

    return {
        "id": str(e.id),
        "subject": e.subject,
        "sender_email": e.sender_email,
        "sender_name": e.sender_name,
        "content_hash": e.content_hash,
        "date_sent": e.date_sent,
        "has_attachments": bool(e.has_attachments),
        "matched_stakeholders": e.matched_stakeholders,
        "matched_keywords": e.matched_keywords,
        "importance": e.importance,
        # Minimal meta: only what's required for the grid (exclusion badge/filters).
        "meta": {"exclusion": exclusion},
        # AG Grid compatibility fields
        "email_subject": e.subject,
        "email_from": sender_display,
        "email_to": email_to_display,
        "email_cc": email_cc_display,
        "email_date": e.date_sent or e.date_received,
        "email_body": email_body,
        "attachments": attachments_payload,
        "attachment_count": len(attachments_payload),
        "linked_to_count": linked_to_count,
        # Programme/critical path fields (mapped from EmailMessage columns)
        "programme_activity": e.as_planned_activity,
        "as_built_activity": e.as_built_activity,
        "as_planned_finish_date": e.as_planned_finish_date,
        "as_built_finish_date": e.as_built_finish_date,
        "delay_days": e.delay_days,
        "is_critical_path": e.is_critical_path,
        # Notes: quick-win storage in metadata; can be migrated to a first-class column later.
        "notes": (
            meta.get("notes")
            if isinstance(meta, dict) and isinstance(meta.get("notes"), str)
            else None
        ),
        "thread_id": e.thread_group_id or e.thread_id,
        "pst_file_id": str(e.pst_file_id) if e.pst_file_id else None,
        "pst_filename": pst_filename,
    }


def _apply_ag_grid_text_filter(query, column, spec: dict[str, Any]):
    """Apply an AG Grid text filter spec to a query.

    We intentionally implement only the common cases used in the UI.
    """

    value = spec.get("filter")
    if value is None or value == "":
        return query
    op = (spec.get("type") or "contains").lower()
    text = str(value)

    if op == "equals":
        return query.filter(column == text)
    if op == "notEqual".lower():
        return query.filter(or_(column.is_(None), column != text))
    if op == "startsWith".lower():
        return query.filter(column.ilike(f"{text}%"))
    if op == "endsWith".lower():
        return query.filter(column.ilike(f"%{text}"))
    if op == "notcontains":
        return query.filter(or_(column.is_(None), ~column.ilike(f"%{text}%")))
    # default contains
    return query.filter(column.ilike(f"%{text}%"))


def _apply_ag_grid_boolean_filter(query, column, spec: dict[str, Any]):
    value = spec.get("filter")
    if value is None:
        return query
    if isinstance(value, str):
        value_bool = value.strip().lower() in {"true", "1", "yes", "y"}
    else:
        value_bool = bool(value)
    return query.filter(column.is_(value_bool))


def _apply_ag_grid_number_filter(query, column, spec: dict[str, Any]):
    """Apply an AG Grid number filter spec to a query."""

    value = spec.get("filter")
    if value is None or value == "":
        return query

    try:
        num = float(value)
    except (TypeError, ValueError):
        return query

    op = (spec.get("type") or "equals").lower()
    if op == "equals":
        return query.filter(column == num)
    if op == "notequal":
        return query.filter(column != num)
    if op == "greaterthan":
        return query.filter(column > num)
    if op == "greaterthanorequal":
        return query.filter(column >= num)
    if op == "lessthan":
        return query.filter(column < num)
    if op == "lessthanorequal":
        return query.filter(column <= num)
    if op == "inrange":
        to_value = spec.get("filterTo")
        try:
            num_to = float(to_value)
        except (TypeError, ValueError):
            return query
        return query.filter(column >= num, column <= num_to)

    return query


def _apply_ag_grid_date_filter(query, column, spec: dict[str, Any]):
    """Apply an AG Grid date filter spec (best-effort).

    AG Grid typically sends ISO dates (YYYY-MM-DD) in dateFrom/dateTo.
    We treat them as inclusive bounds.
    """

    date_from = spec.get("dateFrom") or spec.get("filter")
    if not date_from:
        return query

    op = (spec.get("type") or "equals").lower()

    def _parse(d: str | None) -> datetime | None:
        if not d:
            return None
        try:
            # Accept either YYYY-MM-DD or full ISO timestamp.
            return datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.strptime(str(d), "%Y-%m-%d")
            except Exception:
                return None

    dt_from = _parse(str(date_from))
    if not dt_from:
        return query

    if op == "equals":
        # Same-day match: [from, from+1d)
        dt_to = dt_from.replace(hour=0, minute=0, second=0, microsecond=0)
        dt_end = dt_to + timedelta(days=1)
        return query.filter(column >= dt_to, column < dt_end)

    if op == "greaterthan":
        return query.filter(column > dt_from)

    if op == "lessthan":
        return query.filter(column < dt_from)

    if op == "inrange":
        dt_to = _parse(spec.get("dateTo") or spec.get("filterTo"))
        if not dt_to:
            return query
        return query.filter(column >= dt_from, column <= dt_to)

    return query


def _date_range_to_text(dmin, dmax) -> str:
    if not dmin and not dmax:
        return "-"
    if dmin and not dmax:
        return str(dmin.date())
    if dmax and not dmin:
        return str(dmax.date())
    return f"{dmin.date()} → {dmax.date()}"


def _safe_uuid(value: str | None, field_name: str) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}") from exc


async def upload_pst_file_service(
    file: UploadFile,
    case_id: str | None,
    project_id: str | None,
    db: Session,
    user: User,
):
    # Verify case or project exists
    if not case_id and not project_id:
        raise HTTPException(400, "Either case_id or project_id must be provided")

    if case_id:
        case = db.query(Case).filter_by(id=case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
        entity_prefix = f"case_{case_id}"
    else:
        project = db.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
        entity_prefix = f"project_{project_id}"

    if not file.filename:
        raise HTTPException(400, "Filename is required")

    # Best-effort size detection without reading the whole file into memory
    file_size = 0
    try:
        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
    except Exception as exc:
        logger.warning(
            "Could not determine PST file size for %s: %s", file.filename, exc
        )
    finally:
        try:
            file.file.seek(0)
        except Exception:
            pass

    # Generate PST file record
    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    s3_key = f"{entity_prefix}/pst/{pst_file_id}/{file.filename}"

    # Upload to S3
    s3_client = s3()
    if s3_client is not None:
        transfer_config = TransferConfig(
            multipart_threshold=100 * 1024 * 1024,  # 100MB to match multipart endpoint
            multipart_chunksize=100 * 1024 * 1024,  # Larger chunks = fewer API calls
            max_concurrency=20,  # High concurrency for 20GB+ files
            use_threads=True,
        )

        async def _stream_upload() -> int:
            nonlocal file_size

            # If the incoming PST is large, fall back to explicit multipart upload
            if file_size and file_size > MULTIPART_CHUNK_SIZE:
                upload_id = s3_client.create_multipart_upload(
                    Bucket=s3_bucket,
                    Key=s3_key,
                    ContentType="application/vnd.ms-outlook",
                )["UploadId"]
                parts: list[dict[str, Any]] = []
                part_number = 1
                uploaded_bytes = 0
                try:
                    while True:
                        chunk = file.file.read(SERVER_STREAMING_CHUNK_SIZE)
                        if not chunk:
                            break
                        uploaded_bytes += len(chunk)
                        resp = s3_client.upload_part(
                            Bucket=s3_bucket,
                            Key=s3_key,
                            UploadId=upload_id,
                            PartNumber=part_number,
                            Body=chunk,
                        )
                        parts.append({"ETag": resp["ETag"], "PartNumber": part_number})
                        part_number += 1

                    s3_client.complete_multipart_upload(
                        Bucket=s3_bucket,
                        Key=s3_key,
                        UploadId=upload_id,
                        MultipartUpload={"Parts": parts},
                    )
                    if uploaded_bytes and not file_size:
                        file_size = uploaded_bytes
                    return uploaded_bytes or file_size
                except Exception:
                    try:
                        s3_client.abort_multipart_upload(
                            Bucket=s3_bucket, Key=s3_key, UploadId=upload_id
                        )
                    except Exception as abort_exc:
                        logger.warning(
                            "Failed to abort multipart upload for %s: %s",
                            s3_key,
                            abort_exc,
                        )
                    raise

            # Default path: use TransferManager for efficient streaming
            file.file.seek(0)
            s3_client.upload_fileobj(
                Fileobj=file.file,
                Bucket=s3_bucket,
                Key=s3_key,
                ExtraArgs={"ContentType": "application/vnd.ms-outlook"},
                Config=transfer_config,
            )
            return file_size

        try:
            uploaded_size = await asyncio.to_thread(_stream_upload)
            if uploaded_size and not file_size:
                file_size = uploaded_size
        except Exception as exc:
            logger.error("Failed to upload PST %s to S3: %s", file.filename, exc)
            raise HTTPException(502, f"Failed to store PST: {exc}") from exc

    # Create PST file record
    pst_file = PSTFile(
        id=pst_file_id,
        filename=file.filename,
        case_id=case_id,
        project_id=project_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size_bytes=file_size or None,
        processing_status=PSTStatus.PENDING.value,
        uploaded_by=user.id,
    )

    db.add(pst_file)
    db.commit()

    logger.info(f"Uploaded PST file via server: {pst_file_id}")

    task_id = None
    message = "PST uploaded successfully"
    try:
        start_resp = await start_pst_processing_service(pst_file_id, db)
        task_id = start_resp.get("task_id")
        message = start_resp.get("message", message)
    except Exception as e:
        logger.warning(f"Failed to enqueue PST processing task: {e}")
        message = "PST uploaded successfully (processing pending)"

    return {"pst_file_id": pst_file_id, "message": message, "task_id": task_id}


async def init_pst_upload_service(request, db, user):
    if not request.case_id and not request.project_id:
        raise HTTPException(400, "Either case_id or project_id must be provided")

    if request.case_id:
        case = db.query(Case).filter_by(id=request.case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
        entity_prefix = f"case_{request.case_id}"
    else:
        project = db.query(Project).filter_by(id=request.project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
        entity_prefix = f"project_{request.project_id}"

    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    s3_key = f"{entity_prefix}/pst/{pst_file_id}/{request.filename}"

    pst_file = PSTFile(
        id=pst_file_id,
        filename=request.filename,
        case_id=request.case_id,
        project_id=request.project_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size_bytes=request.file_size,
        processing_status=PSTStatus.PENDING.value,
        uploaded_by=user.id,
    )

    db.add(pst_file)
    db.commit()

    upload_url = presign_put(
        s3_key, "application/vnd.ms-outlook", expires=14400, bucket=s3_bucket
    )

    logger.info(f"Initiated PST upload: {pst_file_id}")

    return PSTUploadInitResponse(
        pst_file_id=pst_file_id,
        upload_url=upload_url,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
    )


async def init_pst_multipart_upload_service(request, db, user):
    if not request.case_id and not request.project_id:
        raise HTTPException(400, "Either case_id or project_id must be provided")

    if request.case_id:
        case = db.query(Case).filter_by(id=request.case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
        entity_prefix = f"case_{request.case_id}"
    else:
        project = db.query(Project).filter_by(id=request.project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
        entity_prefix = f"project_{request.project_id}"

    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    s3_key = f"{entity_prefix}/pst/{pst_file_id}/{request.filename}"

    upload_id = multipart_start(s3_key, request.content_type, bucket=s3_bucket)

    pst_file = PSTFile(
        id=pst_file_id,
        filename=request.filename,
        case_id=request.case_id,
        project_id=request.project_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size_bytes=request.file_size,
        # Keep status aligned with the DB enum (pending|processing|completed|failed).
        processing_status=PSTStatus.PENDING.value,
        uploaded_by=user.id,
    )

    db.add(pst_file)
    db.commit()

    logger.info(
        f"Initiated multipart PST upload: {pst_file_id}, upload_id: {upload_id}"
    )

    return PSTMultipartInitResponse(
        pst_file_id=pst_file_id,
        upload_id=upload_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        chunk_size=MULTIPART_CHUNK_SIZE,
    )


async def get_pst_multipart_part_url_service(pst_file_id, upload_id, part_number, db):
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    url = presign_part(
        pst_file.s3_key,
        upload_id,
        part_number,
        expires=14400,
        bucket=pst_file.s3_bucket,
    )

    return PSTMultipartPartResponse(url=url, part_number=part_number)


async def get_pst_multipart_batch_urls_service(
    pst_file_id: str, upload_id: str, start_part: int, count: int, db: Session
):
    """
    Generate multiple presigned URLs in a single request to reduce round-trips.
    This significantly improves upload performance by allowing the client to
    fetch URLs for multiple parts at once instead of one per request.
    """
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    # Validate and cap count to prevent abuse
    count = min(max(1, count), 20)

    # Validate part number range
    if start_part < 1 or start_part > 10000:
        raise HTTPException(400, "Invalid start_part (must be 1-10000)")

    urls = []
    for i in range(count):
        part_number = start_part + i
        if part_number > 10000:  # S3 limit
            break
        url = presign_part(
            pst_file.s3_key,
            upload_id,
            part_number,
            expires=14400,
            bucket=pst_file.s3_bucket,
        )
        urls.append({"part_number": part_number, "url": url})

    return {
        "pst_file_id": pst_file_id,
        "upload_id": upload_id,
        "urls": urls,
    }


async def list_pst_multipart_parts_service(
    pst_file_id: str, upload_id: str, db: Session
):
    """List already-uploaded multipart parts (for client-side resume)."""
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    try:
        parts = multipart_list_parts(
            pst_file.s3_key, upload_id, bucket=pst_file.s3_bucket
        )
    except Exception as exc:
        logger.warning(
            "Failed to list multipart parts pst_file_id=%s upload_id=%s: %s",
            pst_file_id,
            upload_id,
            exc,
        )
        raise HTTPException(404, f"Multipart upload not found: {exc}") from exc

    return {
        "pst_file_id": pst_file_id,
        "upload_id": upload_id,
        "parts": parts,
    }


async def abort_pst_multipart_upload_service(
    pst_file_id: str, upload_id: str, db: Session
):
    """Abort a multipart upload (best-effort), and mark PST as failed/aborted."""
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    try:
        multipart_abort(pst_file.s3_key, upload_id, bucket=pst_file.s3_bucket)
    except Exception as exc:
        logger.warning(
            "Failed to abort multipart upload pst_file_id=%s upload_id=%s: %s",
            pst_file_id,
            upload_id,
            exc,
        )
        # Still mark as failed to avoid dangling "pending" rows for users.
        pst_file.processing_status = PSTStatus.FAILED.value
        pst_file.error_message = f"Multipart abort failed: {exc}"
        db.commit()
        raise HTTPException(502, f"Abort failed: {exc}") from exc

    pst_file.processing_status = PSTStatus.FAILED.value
    pst_file.error_message = "Upload aborted"
    db.commit()

    return {
        "success": True,
        "pst_file_id": pst_file_id,
        "upload_id": upload_id,
        "message": "Multipart upload aborted",
    }


async def complete_pst_multipart_upload_service(request, db):
    pst_file = db.query(PSTFile).filter_by(id=request.pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    try:
        # Defensive: only pass the fields boto3 accepts for completion.
        cleaned_parts: list[dict[str, Any]] = []
        for p in request.parts or []:
            if not isinstance(p, dict):
                continue
            etag = p.get("ETag") or p.get("etag")
            part_no = p.get("PartNumber") or p.get("part_number") or p.get("partNumber")
            if not etag or not part_no:
                continue
            try:
                cleaned_parts.append(
                    {"ETag": str(etag).replace('"', ""), "PartNumber": int(part_no)}
                )
            except Exception:
                continue
        cleaned_parts.sort(key=lambda x: int(x.get("PartNumber") or 0))

        if not cleaned_parts:
            raise HTTPException(400, "No valid parts provided for multipart completion")

        logger.info(
            f"Completing multipart upload for PST {request.pst_file_id}: "
            f"bucket={pst_file.s3_bucket}, key={pst_file.s3_key}, "
            f"upload_id={request.upload_id}, parts_count={len(cleaned_parts)}"
        )

        completion_result = multipart_complete(
            pst_file.s3_key,
            request.upload_id,
            cleaned_parts,
            bucket=pst_file.s3_bucket,
        )

        # Verify the object actually exists after completion
        from ..storage import s3 as get_s3_client
        from ..config import settings as api_settings

        # Log API's S3 configuration for debugging
        logger.info(
            "[API S3 DEBUG] Verifying upload: USE_AWS_SERVICES=%s, MINIO_ENDPOINT=%s, "
            "bucket=%s, key=%s",
            api_settings.USE_AWS_SERVICES,
            api_settings.MINIO_ENDPOINT,
            pst_file.s3_bucket,
            pst_file.s3_key,
        )

        try:
            head_result = get_s3_client().head_object(
                Bucket=pst_file.s3_bucket, Key=pst_file.s3_key
            )
            logger.info(
                f"PST upload verified: s3://{pst_file.s3_bucket}/{pst_file.s3_key} "
                f"({head_result.get('ContentLength', 0)} bytes)"
            )
        except Exception as verify_err:
            logger.error(
                f"PST multipart completed but object not found! "
                f"bucket={pst_file.s3_bucket}, key={pst_file.s3_key}, "
                f"completion_result={completion_result}, error={verify_err}"
            )
            raise HTTPException(
                500,
                f"Multipart upload completed but object verification failed: {verify_err}",
            )

        pst_file.processing_status = "pending"
        db.commit()

        logger.info(f"Completed multipart upload for PST: {request.pst_file_id}")

        task_id = None
        message = "Upload complete. Processing pending."
        try:
            start_resp = await start_pst_processing_service(request.pst_file_id, db)
            task_id = start_resp.get("task_id")
            message = start_resp.get("message", message)
        except Exception as e:
            logger.warning(
                "Failed to enqueue PST processing after multipart upload %s: %s",
                request.pst_file_id,
                e,
            )

        return {
            "success": True,
            "pst_file_id": request.pst_file_id,
            "processing_started": task_id is not None,
            "task_id": task_id,
            "message": message,
        }

    except Exception as e:
        logger.error(f"Failed to complete multipart upload: {e}")
        raise HTTPException(500, f"Failed to complete upload: {str(e)}")


async def start_pst_processing_service(pst_file_id, db, force: bool = False):
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    # SECURITY: always use timezone-aware UTC for time calculations.
    now_utc = datetime.now(timezone.utc)
    # DB columns may be timezone-naive in some deployments; store UTC-naive when needed.
    now_db = now_utc.replace(tzinfo=None)

    def _as_utc(dt: datetime | None) -> datetime | None:
        """Interpret naive datetimes as UTC; normalize aware datetimes to UTC."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        try:
            return dt.astimezone(timezone.utc)
        except Exception:
            return dt

    raw_status = (pst_file.processing_status or "").strip().lower()
    # DB history: some deployments used "queued" (treat as "pending" for UI + controls).
    status = "pending" if raw_status == "queued" else raw_status

    # Idempotency / safety:
    # - Completed: do nothing unless forced.
    # - Processing: do nothing unless forced (admin can rescue instead).
    # - Pending: treat as "already enqueued" only for a short window; after that,
    #   allow re-enqueue to recover from missing workers / dead queues.
    if status == "completed" and not pst_file.error_message and not force:
        return {
            "success": True,
            "task_id": None,
            "pst_file_id": pst_file_id,
            "message": "PST processing already completed",
        }

    if status == "processing" and not force:
        # Helpful UX: if it looks stale, tell the caller what to do next.
        try:
            stale_h = float(
                getattr(settings, "PST_PROCESSING_STALE_AFTER_HOURS", 12.0) or 12.0
            )
        except Exception:
            stale_h = 12.0

        started_at_utc = _as_utc(pst_file.processing_started_at)
        age = (now_utc - started_at_utc) if started_at_utc else None

        if age is not None and age > timedelta(hours=stale_h):
            return {
                "success": True,
                "task_id": None,
                "pst_file_id": pst_file_id,
                "message": (
                    "PST is marked as processing but appears stale. "
                    "If emails were partially extracted, use Admin Rescue (Finalize). "
                    "If nothing was extracted, retry with ?force=true to re-enqueue."
                ),
            }
        return {
            "success": True,
            "task_id": None,
            "pst_file_id": pst_file_id,
            "message": "PST processing already started",
        }

    if (
        status in {"pending", "uploaded"}
        and pst_file.processing_started_at
        and not force
    ):
        # `processing_started_at` is used as "enqueued_at" while pending.
        # Only suppress re-enqueue for a limited time window.
        enqueued_at_utc = _as_utc(pst_file.processing_started_at)

        try:
            min_age_m = float(
                getattr(settings, "PST_PENDING_REENQUEUE_AFTER_MINUTES", 30.0) or 30.0
            )
        except Exception:
            min_age_m = 30.0

        age = (now_utc - enqueued_at_utc) if enqueued_at_utc else None

        if age is not None and age < timedelta(minutes=min_age_m):
            return {
                "success": True,
                "task_id": None,
                "pst_file_id": pst_file_id,
                "message": "PST processing already enqueued",
            }

    if pst_file.project_id:
        project = db.query(Project).filter_by(id=pst_file.project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
    elif pst_file.case_id:
        case = db.query(Case).filter_by(id=pst_file.case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
    else:
        raise HTTPException(400, "PST file not linked to any project or case")

    try:
        task = celery_app.send_task(
            "worker_app.worker.process_pst_file",
            args=[pst_file_id],
            queue=settings.CELERY_PST_QUEUE,
        )
    except Exception as exc:
        # Persist the enqueue failure so the UI/status endpoint can surface it.
        try:
            pst_file.processing_status = "failed"
            pst_file.error_message = f"Failed to enqueue PST processing: {exc}"
            pst_file.processing_started_at = now_db
            pst_file.processing_completed_at = now_db
            db.commit()
        except Exception:
            # Best-effort; don't mask the original error.
            pass
        raise HTTPException(
            status_code=502,
            detail="Failed to enqueue PST processing task (Celery/Redis unavailable)",
        ) from exc

    pst_file.processing_status = "pending"
    pst_file.error_message = None
    pst_file.processing_started_at = now_db
    pst_file.processing_completed_at = None
    # If we are retrying after a failure (or forcing a requeue), reset counters so
    # UI progress doesn't reflect stale values.
    if force or (status == "failed"):
        pst_file.total_emails = 0
        pst_file.processed_emails = 0
    db.commit()

    logger.info(
        "Enqueued PST processing task %s for file %s (force=%s, prev_status=%s)",
        task.id,
        pst_file_id,
        force,
        raw_status,
    )

    return {
        "success": True,
        "task_id": task.id,
        "pst_file_id": pst_file_id,
        "message": "PST processing enqueued",
    }


async def get_pst_status_service(pst_file_id, db):
    from redis import Redis

    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    def _derive_phase(status_value: str, total: int, processed: int) -> str:
        status_lc = (status_value or "").strip().lower()
        if status_lc in {"uploaded", "queued", "pending"}:
            return "uploaded"
        if status_lc == "processing":
            if total > 0 and processed >= total:
                return "parsing"
            return "extracting"
        if status_lc == "completed":
            return "indexing"
        return status_lc or "uploaded"

    try:
        # redis-py is strict about ssl_cert_reqs values; our env historically used
        # CERT_REQUIRED in the URL. Normalize to keep progress working.
        redis_url = settings.REDIS_URL or ""
        redis_url = redis_url.replace(
            "ssl_cert_reqs=CERT_REQUIRED", "ssl_cert_reqs=required"
        )
        redis_url = redis_url.replace("ssl_cert_reqs=CERT_NONE", "ssl_cert_reqs=none")
        redis_url = redis_url.replace(
            "ssl_cert_reqs=CERT_OPTIONAL", "ssl_cert_reqs=optional"
        )

        redis_client: Redis = Redis.from_url(redis_url)
        redis_key = f"pst:{pst_file_id}"
        redis_data: dict[bytes, bytes] = redis_client.hgetall(redis_key)

        if redis_data:
            decoded_redis_data = {k.decode(): v.decode() for k, v in redis_data.items()}

            total_chunks = int(decoded_redis_data.get("total_chunks", "0"))
            completed_chunks = int(decoded_redis_data.get("completed_chunks", "0"))
            failed_chunks = int(decoded_redis_data.get("failed_chunks", "0"))

            if total_chunks > 0:
                progress = (
                    float(completed_chunks + failed_chunks) / float(total_chunks)
                ) * 100.0
            else:
                progress = 0.0

            processed_emails_val = (
                pst_file.processed_emails
                if pst_file.processed_emails is not None
                else 0
            )
            processed_emails = int(
                decoded_redis_data.get("processed_emails", str(processed_emails_val))
            )

            db_processed_emails = (
                pst_file.processed_emails
                if pst_file.processed_emails is not None
                else 0
            )
            if processed_emails > db_processed_emails:
                pst_file.processed_emails = processed_emails
                db.commit()

            total_emails_val = (
                pst_file.total_emails if pst_file.total_emails is not None else 0
            )
            status_value = decoded_redis_data.get(
                "status", pst_file.processing_status or "pending"
            )
            current_phase = decoded_redis_data.get(
                "current_phase"
            ) or decoded_redis_data.get("phase")
            if not current_phase:
                current_phase = _derive_phase(
                    status_value, total_emails_val, processed_emails
                )
            return PSTProcessingStatus(
                pst_file_id=str(pst_file.id),
                status=status_value,
                current_phase=current_phase,
                total_emails=total_emails_val,
                processed_emails=processed_emails,
                progress_percent=round(float(progress), 1),
                error_message=(
                    str(pst_file.error_message)
                    if pst_file.error_message is not None
                    else None
                ),
            )
    except Exception as e:
        logger.warning(f"Could not get Redis progress for {pst_file_id}: {e}")

    progress = 0.0
    total_emails = pst_file.total_emails if pst_file.total_emails is not None else 0
    processed_emails = (
        pst_file.processed_emails if pst_file.processed_emails is not None else 0
    )
    if total_emails > 0:
        progress = (float(processed_emails) / float(total_emails)) * 100.0
    status_value = pst_file.processing_status or "pending"
    current_phase = _derive_phase(status_value, total_emails, processed_emails)

    return PSTProcessingStatus(
        pst_file_id=str(pst_file.id),
        status=status_value,
        current_phase=current_phase,
        total_emails=total_emails,
        processed_emails=processed_emails,
        progress_percent=round(float(progress), 1),
        error_message=(
            str(pst_file.error_message) if pst_file.error_message is not None else None
        ),
    )


async def admin_rescue_pst_service(
    pst_file_id: str, body: dict, db: Session, user: User
) -> dict[str, Any]:
    """Admin: finalize a stuck PST without re-upload/re-extract.

    This is designed for the common failure mode where:
      - extraction inserted most emails, then the worker died/hung
      - `pst_files.processing_status` stays "processing" forever

    Rescue strategy:
      1) Count emails already inserted for this pst_file_id
      2) Run threading + dedupe scoped to this PST
      3) Mark pst_files as completed using the DB count as the truth
    """

    if str(getattr(user, "role", "")).upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        pst_uuid = uuid.UUID(str(pst_file_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid pst_file_id") from exc

    pst = db.query(PSTFile).filter(PSTFile.id == pst_uuid).first()
    if not pst:
        raise HTTPException(status_code=404, detail="PST file not found")

    action = str(body.get("action") or "finalize").strip().lower()
    force = bool(body.get("force", False))

    before_status = str(pst.processing_status or "pending")
    if before_status == "completed" and not force:
        return {
            "pst_file_id": str(pst.id),
            "status": before_status,
            "message": "PST already completed (use force=true to re-run finalize)",
        }

    if action not in {"finalize", "fail"}:
        raise HTTPException(status_code=400, detail="Invalid action")

    # SECURITY: always use timezone-aware UTC for time calculations.
    now_utc = datetime.now(timezone.utc)
    # DB columns may be timezone-naive in some deployments; store UTC-naive when needed.
    now_db = now_utc.replace(tzinfo=None)
    emails_in_db = (
        db.query(func.count(EmailMessage.id))
        .filter(EmailMessage.pst_file_id == pst_uuid)
        .scalar()
    )
    emails_in_db = int(emails_in_db or 0)

    if action == "fail":
        pst.processing_status = "failed"
        pst.processing_completed_at = now_db
        pst.error_message = (
            str(body.get("reason"))
            or "Admin marked PST as failed (manual intervention)"
        )
        db.commit()
        return {
            "pst_file_id": str(pst.id),
            "from_status": before_status,
            "to_status": "failed",
            "emails_in_db": emails_in_db,
        }

    if emails_in_db <= 0:
        pst.processing_status = "failed"
        pst.processing_completed_at = now_db
        pst.error_message = (
            "Rescue failed: no extracted emails found in DB for this PST. "
            "Re-upload or reset and reprocess."
        )
        db.commit()
        raise HTTPException(status_code=409, detail=pst.error_message)

    from ..email_threading import build_email_threads
    from ..email_dedupe import dedupe_emails

    thread_stats = build_email_threads(
        db,
        case_id=pst.case_id,
        project_id=pst.project_id,
        pst_file_id=pst_uuid,
        run_id="admin_rescue",
    )
    dedupe_stats = dedupe_emails(
        db,
        case_id=pst.case_id,
        project_id=pst.project_id,
        pst_file_id=pst_uuid,
        run_id="admin_rescue",
    )

    pst.processing_status = "completed"
    pst.total_emails = emails_in_db
    pst.processed_emails = emails_in_db
    pst.processing_completed_at = now_db
    pst.error_message = None
    db.commit()

    return {
        "pst_file_id": str(pst.id),
        "from_status": before_status,
        "to_status": "completed",
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
    }


async def admin_cleanup_pst_service(body: dict, db: Session, user: User) -> dict:
    """Admin service to cleanup stuck/failed/duplicate PST jobs for a project/case.

    Designed to run inside the API so it has production DB connectivity.

    Body:
      project_id: str | None
      case_id: str | None
      stuck_hours: float (default 1)
      include_failed: bool (default true)
      include_stuck: bool (default true)
      include_duplicates: bool (default true)
      filename_contains: str | None
      apply: bool (default false)  -> dry-run unless true

    Deletes:
      pst_files rows + related email_messages + email_attachments + evidence_items (source_email_id)

    NOTE: This does NOT delete S3 objects.
    """

    # Admin check: trust role over email domain.
    if str(getattr(user, "role", "")).upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")

    project_id = body.get("project_id")
    case_id = body.get("case_id")
    if not project_id and not case_id:
        raise HTTPException(status_code=400, detail="project_id or case_id required")

    stuck_hours = float(body.get("stuck_hours") or 1)
    include_failed = bool(body.get("include_failed", True))
    include_stuck = bool(body.get("include_stuck", True))
    include_duplicates = bool(body.get("include_duplicates", True))
    filename_contains = body.get("filename_contains")
    apply = bool(body.get("apply", False))

    from datetime import datetime, timedelta, timezone

    from ..models import EmailAttachment, EvidenceItem

    q = db.query(PSTFile)
    if project_id:
        q = q.filter(PSTFile.project_id == uuid.UUID(str(project_id)))
    if case_id:
        q = q.filter(PSTFile.case_id == uuid.UUID(str(case_id)))

    candidates = q.order_by(PSTFile.uploaded_at.desc()).all()

    selected_ids: set[uuid.UUID] = set()

    now = datetime.now(timezone.utc)
    stuck_delta = timedelta(hours=stuck_hours)

    def _as_utc(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    if include_failed:
        for pst in candidates:
            if (pst.processing_status or "") == "failed":
                selected_ids.add(pst.id)

    if include_stuck:
        for pst in candidates:
            status = pst.processing_status or ""
            if status not in {"processing", "pending"}:
                continue
            ref = _as_utc(pst.processing_started_at) or _as_utc(pst.uploaded_at)
            if ref is None or (now - ref) > stuck_delta:
                selected_ids.add(pst.id)

    if include_duplicates:
        groups: dict[tuple[str, int | None], list[PSTFile]] = {}
        for pst in candidates:
            groups.setdefault((pst.filename or "", pst.file_size_bytes), []).append(pst)

        for _, group in groups.items():
            if len(group) <= 1:
                continue
            # Only treat as dupes if none extracted anything.
            if any(
                (pst.total_emails or 0) > 0 or (pst.processed_emails or 0) > 0
                for pst in group
            ):
                continue
            group_sorted = sorted(
                group,
                key=lambda x: (
                    _as_utc(x.uploaded_at) or datetime.min.replace(tzinfo=timezone.utc)
                ),
                reverse=True,
            )
            # keep newest, delete rest
            for pst in group_sorted[1:]:
                selected_ids.add(pst.id)

    if filename_contains:
        token = str(filename_contains).lower()
        for pst in candidates:
            if token in (pst.filename or "").lower():
                selected_ids.add(pst.id)

    selected = [pst for pst in candidates if pst.id in selected_ids]

    # Counts and preview
    total_counts = {
        "pst_files": 0,
        "email_messages": 0,
        "email_attachments": 0,
        "evidence_items": 0,
    }
    per_pst: list[dict] = []

    for pst in selected:
        pst_id = pst.id
        email_ids = [
            row[0]
            for row in db.query(EmailMessage.id)
            .filter(EmailMessage.pst_file_id == pst_id)
            .all()
        ]
        att_count = (
            db.query(EmailAttachment)
            .filter(EmailAttachment.email_message_id.in_(email_ids))
            .count()
            if email_ids
            else 0
        )
        ev_count = (
            db.query(EvidenceItem)
            .filter(EvidenceItem.source_email_id.in_(email_ids))
            .count()
            if email_ids
            else 0
        )
        counts = {
            "pst_files": 1,
            "email_messages": len(email_ids),
            "email_attachments": int(att_count),
            "evidence_items": int(ev_count),
        }
        for k, v in counts.items():
            total_counts[k] += v

        per_pst.append(
            {
                "id": str(pst.id),
                "filename": pst.filename,
                "status": pst.processing_status,
                "uploaded_at": pst.uploaded_at.isoformat() if pst.uploaded_at else None,
                "started_at": (
                    pst.processing_started_at.isoformat()
                    if pst.processing_started_at
                    else None
                ),
                "total_emails": pst.total_emails or 0,
                "processed_emails": pst.processed_emails or 0,
                "counts": counts,
            }
        )

    if apply:
        for pst in selected:
            pst_id = pst.id
            email_ids = [
                row[0]
                for row in db.query(EmailMessage.id)
                .filter(EmailMessage.pst_file_id == pst_id)
                .all()
            ]
            if email_ids:
                db.query(EmailAttachment).filter(
                    EmailAttachment.email_message_id.in_(email_ids)
                ).delete(synchronize_session=False)
                db.query(EvidenceItem).filter(
                    EvidenceItem.source_email_id.in_(email_ids)
                ).delete(synchronize_session=False)
                db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids)).delete(
                    synchronize_session=False
                )

            db.query(PSTFile).filter(PSTFile.id == pst_id).delete(
                synchronize_session=False
            )

        db.commit()

    return {
        "mode": "APPLY" if apply else "DRY_RUN",
        "candidates_count": len(candidates),
        "selected_count": len(selected),
        "summary": total_counts,
        "selected": per_pst,
    }


async def list_pst_files_service(project_id, case_id, status, page, page_size, db):
    query = db.query(PSTFile)

    if case_id:
        query = query.filter(PSTFile.case_id == case_id)

    if project_id:
        query = query.filter(PSTFile.project_id == project_id)
    if status:
        statuses = _parse_pst_status_filter(status)
        if statuses:
            if len(statuses) == 1:
                query = query.filter(PSTFile.processing_status == statuses[0])
            else:
                query = query.filter(PSTFile.processing_status.in_(statuses))

    total = query.count()

    query = query.order_by(PSTFile.uploaded_at.desc())
    offset = (page - 1) * page_size
    pst_files = query.offset(offset).limit(page_size).all()

    items = [
        PSTFileInfo(
            id=str(pst.id),
            filename=pst.filename,
            file_size_bytes=pst.file_size_bytes,
            total_emails=pst.total_emails or 0,
            processed_emails=pst.processed_emails or 0,
            processing_status=pst.processing_status or "pending",
            uploaded_at=pst.uploaded_at,
            processing_started_at=pst.processing_started_at,
            processing_completed_at=pst.processing_completed_at,
            error_message=pst.error_message,
            case_id=str(pst.case_id) if pst.case_id else None,
            project_id=str(pst.project_id) if pst.project_id else None,
        )
        for pst in pst_files
    ]

    return PSTFileListResponse(items=items, total=total, page=page, page_size=page_size)


async def list_emails_service(
    case_id,
    project_id,
    page,
    page_size,
    search,
    stakeholder_id,
    keyword_id,
    has_attachments,
    date_from,
    date_to,
    status_filter,
    include_hidden,
    db,
):
    # NOTE: This is the "simple" list endpoint. The Enterprise UI uses the
    # server-side endpoint, but we keep this functional for compatibility.
    if not case_id and not project_id:
        query = db.query(EmailMessage)
    elif case_id:
        case = db.query(Case).filter_by(id=case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
        query = db.query(EmailMessage).filter(EmailMessage.case_id == case.id)
    else:
        project = db.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
        query = db.query(EmailMessage).filter_by(project_id=project_id)

    query = query.filter(build_correspondence_hard_exclusion_filter())

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                EmailMessage.subject.ilike(search_term),
                EmailMessage.body_text.ilike(search_term),
                EmailMessage.sender_email.ilike(search_term),
                EmailMessage.sender_name.ilike(search_term),
            )
        )

    if stakeholder_id:
        query = query.filter(
            func.jsonb_exists(EmailMessage.matched_stakeholders, stakeholder_id)
        )

    if keyword_id:
        query = query.filter(
            func.jsonb_exists(EmailMessage.matched_keywords, keyword_id)
        )

    if has_attachments is not None:
        query = query.filter(EmailMessage.has_attachments.is_(has_attachments))

    if date_from:
        query = query.filter(EmailMessage.date_sent >= date_from)

    if date_to:
        query = query.filter(EmailMessage.date_sent <= date_to)

    status_field = EmailMessage.meta["status"].as_string()

    if status_filter:
        query = query.filter(status_field == status_filter)
    elif not include_hidden:
        query = query.filter(build_correspondence_visibility_filter())
        query = query.filter(
            or_(
                EmailMessage.subject.is_(None),
                ~EmailMessage.subject.like("IPM.%"),
            )
        )

    total = query.count()

    offset = (page - 1) * page_size
    emails = (
        query.options(selectinload(EmailMessage.attachments))
        .order_by(EmailMessage.date_sent.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    email_ids = [e.id for e in emails]
    link_counts_by_email: dict[uuid.UUID, int] = {}
    if email_ids:
        rows_linked = (
            db.query(
                EvidenceCorrespondenceLink.email_message_id,
                func.count(EvidenceCorrespondenceLink.id),
            )
            .filter(EvidenceCorrespondenceLink.email_message_id.in_(email_ids))
            .group_by(EvidenceCorrespondenceLink.email_message_id)
            .all()
        )
        link_counts_by_email = {
            email_id: int(cnt)
            for (email_id, cnt) in rows_linked
            if email_id is not None
        }

    email_summaries: list[EmailMessageSummary] = []
    pst_filename_by_id: dict[uuid.UUID, str] = {}
    pst_ids = {e.pst_file_id for e in emails if e.pst_file_id}
    if pst_ids:
        pst_rows = (
            db.query(PSTFile.id, PSTFile.filename).filter(PSTFile.id.in_(pst_ids)).all()
        )
        pst_filename_by_id = {
            pst_id: (filename or "")
            for pst_id, filename in pst_rows
            if pst_id is not None
        }

    for e in emails:
        atts: list[dict[str, Any]] = []
        for att in e.attachments or []:
            att_data = {
                "filename": att.filename,
                "content_type": att.content_type,
                "file_size": att.file_size_bytes,
                "is_inline": att.is_inline,
            }
            if _is_embedded_image(att_data):
                continue
            atts.append(
                {
                    "id": str(att.id),
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "file_size": att.file_size_bytes,
                    "s3_bucket": att.s3_bucket,
                    "s3_key": att.s3_key,
                    "is_inline": bool(att.is_inline),
                    "is_duplicate": bool(att.is_duplicate),
                }
            )

        email_summaries.append(
            _build_email_row(
                e,
                attachment_items=atts,
                linked_to_count=link_counts_by_email.get(e.id, 0),
                pst_filename=pst_filename_by_id.get(e.pst_file_id),
            )
        )

    return EmailListResponse(
        total=total, emails=email_summaries, page=page, page_size=page_size
    )


async def list_emails_server_side_service(
    request: ServerSideRequest,
    case_id: str | None,
    project_id: str | None,
    search: str | None,
    stakeholder_id: str | None,
    keyword_id: str | None,
    domain: str | None,
    include_hidden: bool,
    db: Session,
) -> ServerSideResponse:
    """Server-side row model endpoint for the Correspondence Enterprise grid."""

    t0 = time.perf_counter()
    case_uuid = _safe_uuid(case_id, "case_id")
    project_uuid = _safe_uuid(project_id, "project_id")

    # Base query used for grid data.
    q = db.query(EmailMessage).options(
        load_only(
            EmailMessage.id,
            EmailMessage.pst_file_id,
            EmailMessage.case_id,
            EmailMessage.project_id,
            EmailMessage.subject,
            EmailMessage.sender_email,
            EmailMessage.sender_name,
            EmailMessage.recipients_to,
            EmailMessage.recipients_cc,
            EmailMessage.date_sent,
            EmailMessage.date_received,
            EmailMessage.body_text_clean,
            EmailMessage.body_preview,
            EmailMessage.content_hash,
            EmailMessage.has_attachments,
            EmailMessage.matched_stakeholders,
            EmailMessage.matched_keywords,
            EmailMessage.importance,
            EmailMessage.as_planned_activity,
            EmailMessage.as_built_activity,
            EmailMessage.as_planned_finish_date,
            EmailMessage.as_built_finish_date,
            EmailMessage.delay_days,
            EmailMessage.is_critical_path,
            EmailMessage.thread_id,
            EmailMessage.thread_group_id,
            EmailMessage.meta,
        )
    )

    # Correlated subquery for evidence link count (used for sort/filter only).
    linked_count_expr = (
        db.query(func.count(EvidenceCorrespondenceLink.id))
        .filter(EvidenceCorrespondenceLink.email_message_id == EmailMessage.id)
        .correlate(EmailMessage)
        .scalar_subquery()
    )

    if case_uuid:
        q = q.filter(EmailMessage.case_id == case_uuid)
    if project_uuid:
        q = q.filter(EmailMessage.project_id == project_uuid)

    # Always exclude Outlook system items from the dataset.
    q = q.filter(
        or_(EmailMessage.subject.is_(None), ~EmailMessage.subject.like("IPM.%"))
    )

    # Exclude PST loader notification emails (system artifacts, not real correspondence)
    q = q.filter(
        or_(
            EmailMessage.sender_email.is_(None),
            EmailMessage.sender_email != "pst-loader@vericase",
        )
    )

    # Always exclude duplicates/spam/other-project emails from correspondence.
    q = q.filter(build_correspondence_hard_exclusion_filter())

    if search:
        search_term = f"%{search}%"
        q = q.filter(
            or_(
                EmailMessage.subject.ilike(search_term),
                EmailMessage.body_text.ilike(search_term),
                EmailMessage.sender_email.ilike(search_term),
                EmailMessage.sender_name.ilike(search_term),
            )
        )

    # Stakeholder / keyword filters (JSONB arrays of IDs).
    if stakeholder_id:
        q = q.filter(EmailMessage.matched_stakeholders.contains([stakeholder_id]))

    if keyword_id:
        q = q.filter(EmailMessage.matched_keywords.contains([keyword_id]))

    # Domain filter: match emails where domain appears in sender, to, or cc
    if domain:
        domain_pattern = f"%@{domain}%"
        domain_filter = or_(
            EmailMessage.sender_email.ilike(domain_pattern),
            func.cast(EmailMessage.recipients_to, String).ilike(domain_pattern),
            func.cast(EmailMessage.recipients_cc, String).ilike(domain_pattern),
        )
        q = q.filter(domain_filter)

    if not include_hidden:
        q = q.filter(build_correspondence_visibility_filter())

    # Effective date for sorting/filtering (fallback to received date).
    date_expr = func.coalesce(EmailMessage.date_sent, EmailMessage.date_received)

    # AG Grid filter model.
    filter_model: dict[str, Any] = request.filterModel or {}
    for field, spec_raw in filter_model.items():
        if not isinstance(spec_raw, dict):
            continue
        filter_type = (spec_raw.get("filterType") or "text").lower()

        # Map UI column IDs -> model columns.
        if field in {"email_subject", "subject"}:
            if filter_type == "text":
                q = _apply_ag_grid_text_filter(q, EmailMessage.subject, spec_raw)
        elif field in {"body_text_clean", "body_text", "email_body"}:
            if filter_type == "text":
                body_text = func.coalesce(
                    EmailMessage.body_text_clean,
                    EmailMessage.body_text,
                    "",
                )
                q = _apply_ag_grid_text_filter(q, body_text, spec_raw)
        elif field in {"email_from", "sender_email", "sender_name"}:
            if filter_type == "text":
                # Treat as match on either email or name.
                val = spec_raw.get("filter")
                if val is not None and val != "":
                    inner = f"%{val}%"
                    q = q.filter(
                        or_(
                            EmailMessage.sender_email.ilike(inner),
                            EmailMessage.sender_name.ilike(inner),
                        )
                    )
        elif field in {"has_attachments"}:
            if filter_type in {"boolean", "text"}:
                q = _apply_ag_grid_boolean_filter(
                    q, EmailMessage.has_attachments, spec_raw
                )

        elif field in {"email_to", "recipients_to"}:
            if filter_type == "text":
                recipients_text = func.coalesce(
                    func.array_to_string(EmailMessage.recipients_to, ", "), ""
                )
                q = _apply_ag_grid_text_filter(q, recipients_text, spec_raw)

        elif field in {"email_cc", "recipients_cc"}:
            if filter_type == "text":
                recipients_text = func.coalesce(
                    func.array_to_string(EmailMessage.recipients_cc, ", "), ""
                )
                q = _apply_ag_grid_text_filter(q, recipients_text, spec_raw)

        elif field in {"thread_id"}:
            if filter_type == "text":
                thread_key = func.coalesce(
                    EmailMessage.thread_group_id, EmailMessage.thread_id
                )
                q = _apply_ag_grid_text_filter(q, thread_key, spec_raw)

        elif field in {"notes"}:
            if filter_type == "text":
                notes_field = EmailMessage.meta["notes"].as_string()
                q = _apply_ag_grid_text_filter(q, notes_field, spec_raw)

        elif field in {"programme_activity", "as_planned_activity"}:
            if filter_type == "text":
                q = _apply_ag_grid_text_filter(
                    q, EmailMessage.as_planned_activity, spec_raw
                )

        elif field in {"as_built_activity"}:
            if filter_type == "text":
                q = _apply_ag_grid_text_filter(
                    q, EmailMessage.as_built_activity, spec_raw
                )

        elif field in {"delay_days"}:
            if filter_type in {"number", "text"}:
                q = _apply_ag_grid_number_filter(q, EmailMessage.delay_days, spec_raw)

        elif field in {"linked_to_count", "links", "link_count"}:
            if filter_type in {"number", "text"}:
                q = _apply_ag_grid_number_filter(q, linked_count_expr, spec_raw)

        elif field in {"email_date", "date_sent"}:
            if filter_type in {"date", "text"}:
                q = _apply_ag_grid_date_filter(q, date_expr, spec_raw)

    # IMPORTANT: Do NOT COUNT(*) the full filtered dataset for every block request.
    # That is extremely expensive at 100k+ rows and causes the correspondence page to stall.

    # Sorting.
    sort_model: list[dict[str, Any]] = request.sortModel or []
    for sort in sort_model:
        col_id = sort.get("colId")
        direction = (sort.get("sort") or "desc").lower()
        desc = direction != "asc"

        if col_id in {"email_date", "date_sent"}:
            q = q.order_by(date_expr.desc() if desc else date_expr.asc())
        elif col_id in {"email_subject", "subject"}:
            q = q.order_by(
                EmailMessage.subject.desc() if desc else EmailMessage.subject.asc()
            )
        elif col_id in {"email_from", "sender_email"}:
            q = q.order_by(
                EmailMessage.sender_email.desc()
                if desc
                else EmailMessage.sender_email.asc()
            )
        elif col_id in {"email_to", "recipients_to"}:
            recipients_text = func.coalesce(
                func.array_to_string(EmailMessage.recipients_to, ", "), ""
            )
            q = q.order_by(recipients_text.desc() if desc else recipients_text.asc())
        elif col_id in {"email_cc", "recipients_cc"}:
            recipients_text = func.coalesce(
                func.array_to_string(EmailMessage.recipients_cc, ", "), ""
            )
            q = q.order_by(recipients_text.desc() if desc else recipients_text.asc())
        elif col_id in {"thread_id"}:
            thread_key = func.coalesce(
                EmailMessage.thread_group_id, EmailMessage.thread_id
            )
            q = q.order_by(thread_key.desc() if desc else thread_key.asc())
        elif col_id in {"programme_activity", "as_planned_activity"}:
            q = q.order_by(
                EmailMessage.as_planned_activity.desc()
                if desc
                else EmailMessage.as_planned_activity.asc()
            )
        elif col_id in {"as_built_activity"}:
            q = q.order_by(
                EmailMessage.as_built_activity.desc()
                if desc
                else EmailMessage.as_built_activity.asc()
            )
        elif col_id in {"delay_days"}:
            q = q.order_by(
                EmailMessage.delay_days.desc()
                if desc
                else EmailMessage.delay_days.asc()
            )
        elif col_id in {"linked_to_count", "links", "link_count"}:
            q = q.order_by(
                linked_count_expr.desc() if desc else linked_count_expr.asc()
            )

    # Stable tie-break.
    q = q.order_by(EmailMessage.id.desc())

    start = max(0, int(request.startRow or 0))
    end = max(start, int(request.endRow or (start + 100)))
    page_size = max(1, end - start)

    emails = q.offset(start).limit(page_size).all()
    # lastRow semantics:
    # - return -1 when we don't know the total yet (more rows likely exist)
    # - return the exact row count only when we've reached the end of the dataset
    last_row = (start + len(emails)) if len(emails) < page_size else -1
    pst_filename_by_id: dict[uuid.UUID, str] = {}
    pst_ids = {e.pst_file_id for e in emails if e.pst_file_id}
    if pst_ids:
        pst_rows = (
            db.query(PSTFile.id, PSTFile.filename).filter(PSTFile.id.in_(pst_ids)).all()
        )
        pst_filename_by_id = {
            pst_id: (filename or "")
            for pst_id, filename in pst_rows
            if pst_id is not None
        }

    # Attachments: pull evidence items for these emails (used for preview/download in UI).
    email_ids = [e.id for e in emails]
    attachments_by_email: dict[uuid.UUID, list[dict[str, Any]]] = {
        eid: [] for eid in email_ids
    }
    if email_ids:
        evidence_atts = (
            db.query(EvidenceItem)
            .filter(EvidenceItem.source_email_id.in_(email_ids))
            .order_by(EvidenceItem.created_at.desc())
            .all()
        )
        for item in evidence_atts:
            if not item.source_email_id:
                continue
            att_data = {
                "filename": item.filename,
                "content_type": item.mime_type,
                "file_size": item.file_size,
            }
            if _is_embedded_image(att_data):
                continue
            attachments_by_email.setdefault(item.source_email_id, []).append(
                {
                    "evidenceId": str(item.id),
                    "attachmentId": str(item.id),
                    "fileName": item.filename,
                    "mime_type": item.mime_type,
                    "file_size": item.file_size,
                }
            )

    # Evidence link counts for "Link"/"Linked" columns.
    link_counts_by_email: dict[uuid.UUID, int] = {}
    if email_ids:
        rows_linked = (
            db.query(
                EvidenceCorrespondenceLink.email_message_id,
                func.count(EvidenceCorrespondenceLink.id),
            )
            .filter(EvidenceCorrespondenceLink.email_message_id.in_(email_ids))
            .group_by(EvidenceCorrespondenceLink.email_message_id)
            .all()
        )
        link_counts_by_email = {
            email_id: int(cnt)
            for (email_id, cnt) in rows_linked
            if email_id is not None
        }

    rows = [
        _build_email_row_server_side(
            e,
            attachment_items=attachments_by_email.get(e.id, []),
            linked_to_count=link_counts_by_email.get(e.id, 0),
            pst_filename=pst_filename_by_id.get(e.pst_file_id),
        )
        for e in emails
    ]

    stats: dict[str, Any] = {}

    elapsed = time.perf_counter() - t0
    if elapsed >= 2.0:
        logger.warning(
            "Slow correspondence server-side request: %.2fs start=%s size=%s fetched=%s lastRow=%s case=%s project=%s search=%s",
            elapsed,
            start,
            page_size,
            len(emails),
            last_row,
            case_id,
            project_id,
            bool(search),
        )
    else:
        logger.debug(
            "Correspondence server-side request: %.2fs start=%s size=%s fetched=%s lastRow=%s",
            elapsed,
            start,
            page_size,
            len(emails),
            last_row,
        )

    return ServerSideResponse(rows=rows, lastRow=last_row, stats=stats)


def _replace_cid_with_presigned_urls(
    html_body: str | None, attachments: list
) -> str | None:
    """
    Replace cid: references in HTML body with presigned S3 URLs.

    This enables inline images (like signature logos) to display properly
    when rendering the email in an iframe/Outlook view mode.

    Args:
        html_body: The HTML body content of the email
        attachments: List of EmailAttachment objects with content_id, s3_bucket, s3_key

    Returns:
        HTML body with cid: references replaced by presigned URLs
    """
    import re

    if not html_body or not attachments:
        return html_body

    # Build a mapping from content_id -> presigned URL
    cid_to_url: dict[str, str] = {}
    for att in attachments:
        content_id = getattr(att, "content_id", None)
        s3_bucket = getattr(att, "s3_bucket", None)
        s3_key = getattr(att, "s3_key", None)

        if content_id and s3_bucket and s3_key:
            # Clean the content_id (some have angle brackets)
            clean_cid = content_id.strip().strip("<>").strip()
            if clean_cid:
                try:
                    # Generate presigned URL with 1 hour expiry
                    url = presign_get(s3_key, expires=3600, bucket=s3_bucket)
                    cid_to_url[clean_cid] = url
                except Exception as e:
                    logger.debug(
                        f"Failed to generate presigned URL for CID {clean_cid}: {e}"
                    )

    if not cid_to_url:
        return html_body

    # Replace cid: references in src attributes
    # Pattern matches: src="cid:xxx" or src='cid:xxx'
    def replace_cid(match):
        quote = match.group(1)
        cid = match.group(2)
        if cid in cid_to_url:
            return f"src={quote}{cid_to_url[cid]}{quote}"
        return match.group(0)  # Return unchanged if no match

    # Match src="cid:content_id" patterns
    pattern = r'src=(["\'])cid:([^"\']+)\1'
    result = re.sub(pattern, replace_cid, html_body, flags=re.IGNORECASE)

    return result


def _strip_inline_images_from_html(html_body: str | None) -> str | None:
    """Remove/neutralize inline image references (cid:, data:) from HTML bodies.

    The user experience goal is to avoid pulling through signature logos / embedded images
    which are noisy and costly. We remove <img> tags pointing at cid: as well as other
    common inline patterns.
    """
    if not html_body:
        return html_body

    import re

    cleaned = html_body

    # Remove <img ... src="cid:..."> tags entirely (most common case).
    cleaned = re.sub(
        r"<img\b[^>]*\bsrc=(['\"])\s*cid:[^'\"]+\1[^>]*>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Neutralize any remaining src/background attributes referencing cid:.
    cleaned = re.sub(
        r"\b(src|background)=(['\"])\s*cid:[^'\"]+\2",
        r"\1=\2\2",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Neutralize CSS url(cid:...)
    cleaned = re.sub(
        r"url\(\s*cid:[^\)]+\)",
        "url()",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Remove data: images (often inline signatures too)
    cleaned = re.sub(
        r"<img\b[^>]*\bsrc=(['\"])\s*data:image/[^'\"]+\1[^>]*>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    return cleaned


async def get_email_detail_service(email_id: str, db: Session):
    from sqlalchemy.orm import selectinload
    from ..storage import get_object
    from ..models import EmailMessage, EvidenceItem

    email = (
        db.query(EmailMessage)
        .options(selectinload(EmailMessage.attachments))
        .filter(EmailMessage.id == email_id)
        .first()
    )
    if not email:
        raise HTTPException(404, "Email not found")

    # Reconstruct full body
    full_body_text = email.body_text
    full_body_html = email.body_html

    if email.body_full_s3_key:
        try:
            # Bodies may be offloaded to a dedicated bucket (S3_EMAIL_BODY_BUCKET).
            meta = email.meta if isinstance(email.meta, dict) else {}
            bucket = (
                meta.get("body_offload_bucket")
                or getattr(settings, "S3_EMAIL_BODY_BUCKET", None)
                or settings.S3_BUCKET
            )
            body_data = get_object(email.body_full_s3_key, bucket=bucket)
            full_body_text = body_data.decode("utf-8")
            # Optionally reconstruct HTML if needed, but use text for now
        except Exception as e:
            logger.warning(f"Failed to fetch full body from S3: {e}")

    # Build attachments list (prefer evidence items for preview/download support).
    atts = []
    evidence_atts = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.source_email_id == email.id)
        .order_by(EvidenceItem.created_at.desc())
        .all()
    )

    if evidence_atts:
        for item in evidence_atts:
            att_data = {
                "filename": item.filename,
                "content_type": item.mime_type,
                "file_size": item.file_size,
            }
            if _is_embedded_image(att_data):
                continue
            atts.append(
                {
                    "id": str(item.id),
                    "evidenceId": str(item.id),
                    "attachmentId": str(item.id),
                    "fileName": item.filename,
                    "mime_type": item.mime_type,
                    "file_size": item.file_size,
                }
            )
    else:
        for att in email.attachments or []:
            att_data = {
                "id": str(att.id),
                "filename": att.filename,
                "content_type": att.content_type,
                "file_size": att.file_size_bytes,
                "s3_bucket": att.s3_bucket,
                "s3_key": att.s3_key,
                "is_inline": bool(att.is_inline),
                "is_duplicate": bool(att.is_duplicate),
            }
            if _is_embedded_image(att_data):
                continue
            atts.append(att_data)

    # Compute a display-first body (cleaned banners/entities/signatures/quotes) while preserving raw.
    from ..email_normalizer import clean_email_body_for_display

    body_display = clean_email_body_for_display(
        body_text_clean=email.body_text_clean,
        body_text=full_body_text,
        body_html=full_body_html,
    )

    # Do NOT resolve inline CID images to presigned URLs.
    # Instead, strip them to avoid pulling through embedded logos/signatures.
    full_body_html_without_inline_images = _strip_inline_images_from_html(
        full_body_html
    )

    return EmailMessageDetail(
        id=str(email.id),
        subject=email.subject,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        recipients_to=email.recipients_to or [],
        recipients_cc=email.recipients_cc or [],
        date_sent=email.date_sent,
        date_received=email.date_received,
        body_text=body_display or full_body_text,
        body_html=full_body_html_without_inline_images,
        body_text_clean=body_display or email.body_text_clean,
        body_text_full=full_body_text,
        content_hash=email.content_hash,
        has_attachments=bool(email.has_attachments),
        attachments=atts,
        matched_stakeholders=email.matched_stakeholders or [],
        matched_keywords=email.matched_keywords or [],
        importance=email.importance,
        pst_message_path=email.pst_message_path,
    )
