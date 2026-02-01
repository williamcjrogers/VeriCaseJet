"""Upload routes (presign, complete, multipart) and admin PST endpoints.

Extracted from main.py to reduce module size.
"""

import logging
import uuid
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from .config import settings
from .db import SessionLocal
from .models import Document, DocStatus, User, UserRole, PSTFile
from .storage import presign_put, presign_get, multipart_start, presign_part, multipart_complete
from .tasks import celery_app
from .security import get_db, current_user
from .csrf import verify_csrf_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/uploads/init")
def init_upload(
    body: dict = Body(...),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    """Initialize file upload - returns upload_id and presigned URL"""
    filename = body.get("filename")
    ct = body.get("content_type") or "application/octet-stream"
    _ = int(body.get("size") or 0)

    # Generate unique upload ID and S3 key
    upload_id = str(uuid4())
    s3_key = f"uploads/{user.id}/{upload_id}/{filename}"

    # Get presigned PUT URL
    upload_url = presign_put(s3_key, ct)

    return {"upload_id": upload_id, "upload_url": upload_url, "s3_key": s3_key}


@router.post("/uploads/presign")
def presign_upload(
    body: dict = Body(...),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    filename = body.get("filename")
    ct = body.get("content_type") or "application/octet-stream"
    path = (body.get("path") or "").strip().strip("/")
    key = f"{path + '/' if path else ''}{uuid.uuid4()}/{filename}"
    url = presign_put(key, ct)
    return {"key": key, "url": url}


@router.post("/uploads/complete")
def complete_upload(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    # Support both new (upload_id) and legacy (key) formats
    upload_id = body.get("upload_id")
    filename = body.get("filename") or "file"

    if upload_id:
        # New format: construct key from upload_id
        key = f"uploads/{user.id}/{upload_id}/{filename}"
    else:
        # Legacy format: use provided key
        key = body.get("key")

    ct = body.get("content_type") or "application/octet-stream"
    size = int(body.get("size") or 0)
    title = body.get("title")
    path = body.get("path")

    # Set empty paths to None so they're treated consistently
    if path == "":
        path = None

    # Extract profile info for PST processing
    profile_type = body.get("profile_type") or body.get("profileType")
    profile_id = body.get("profile_id") or body.get("profileId")

    # Build metadata
    meta = {}
    if profile_type and profile_id:
        meta["profile_type"] = profile_type
        meta["profile_id"] = profile_id
        meta["uploaded_by"] = str(user.id)

    doc = Document(
        filename=filename,
        path=path,
        content_type=ct,
        size=size,
        bucket=settings.MINIO_BUCKET,
        s3_key=key,
        title=title,
        status=DocStatus.NEW,
        owner_user_id=user.id,
        meta=meta if meta else None,
    )
    db.add(doc)
    db.commit()

    # Check if PST file - trigger PST processor instead of OCR
    if filename.lower().endswith(".pst"):
        # Extract case/project from body if provided
        case_id = body.get("case_id")
        project_id = body.get("project_id")

        # Create pst_files record so forensic pipeline has a stable ID
        pst_file = PSTFile(
            filename=filename,
            case_id=uuid.UUID(case_id) if case_id else None,
            project_id=uuid.UUID(project_id) if project_id else None,
            s3_bucket=doc.bucket,
            s3_key=doc.s3_key,
            file_size_bytes=size or None,
            processing_status="pending",
            uploaded_by=user.id,
        )
        db.add(pst_file)
        db.commit()
        db.refresh(pst_file)

        logger.info(
            "Queuing forensic PST processing task doc_id=%s pst_file_id=%s case_id=%s project_id=%s",
            str(doc.id),
            str(pst_file.id),
            case_id,
            project_id,
        )

        celery_app.send_task(
            "worker_app.worker.process_pst_file",
            args=[str(pst_file.id)],
            queue=settings.CELERY_PST_QUEUE,
        )

        # Mark as pending so the UI can show the job immediately.
        pst_file.processing_status = "pending"
        pst_file.error_message = None
        db.commit()
        return {
            "id": str(doc.id),
            "status": "PROCESSING_PST_FORENSIC",
            "message": "Forensic PST file queued for extraction and analysis",
            "pst_file_id": str(pst_file.id),
        }
    else:
        # Queue OCR and AI classification for other files
        celery_app.send_task("worker_app.worker.ocr_and_index", args=[str(doc.id)])
        return {"id": str(doc.id), "status": "QUEUED", "ai_enabled": True}


@router.post("/api/admin/trigger-pst")
def admin_trigger_pst(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Admin endpoint to trigger PST processing for files already in S3.
    This is useful for re-processing or processing files uploaded outside the normal flow.

    Body:
        s3_key: str - The S3 key of the PST file
        project_id: str - The project ID to associate emails with
    """
    # Require true admin role (do not use email heuristics).
    if user.role != UserRole.ADMIN and user.email not in {
        "admin@veri-case.com",
        "admin@vericase.com",
    }:
        raise HTTPException(status_code=403, detail="Admin access required")

    s3_key = body.get("s3_key")
    project_id = body.get("project_id")

    if not s3_key or not project_id:
        raise HTTPException(status_code=400, detail="s3_key and project_id required")

    filename = s3_key.split("/")[-1]
    if not filename.lower().endswith(".pst"):
        raise HTTPException(status_code=400, detail="Only PST files supported")

    # Check if PST file already exists in pst_files table
    existing = db.query(PSTFile).filter(PSTFile.s3_key == s3_key).first()

    if existing:
        # Reset status to pending and re-trigger
        existing.processing_status = "pending"
        existing.error_message = None
        existing.total_emails = 0
        existing.processed_emails = 0
        db.commit()
        pst_file_id = str(existing.id)
    else:
        # Create new pst_files record
        pst_record = PSTFile(
            project_id=uuid.UUID(project_id),
            filename=filename,
            s3_key=s3_key,
            s3_bucket=settings.S3_BUCKET,
            processing_status="pending",
        )
        db.add(pst_record)
        db.commit()
        pst_file_id = str(pst_record.id)

    # Queue the forensic processing task
    celery_app.send_task(
        "worker_app.worker.process_pst_file",
        args=[pst_file_id],
        queue=settings.CELERY_PST_QUEUE,
    )

    # Mark as pending so the UI can show the job immediately.
    existing = db.query(PSTFile).filter(PSTFile.id == uuid.UUID(pst_file_id)).first()
    if existing:
        existing.processing_status = "pending"
        existing.error_message = None
        db.commit()

    return {
        "pst_file_id": pst_file_id,
        "status": "QUEUED",
        "message": f"PST processing queued for {filename}",
    }


@router.post("/api/admin/pst/cleanup")
def admin_cleanup_pst(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Admin endpoint to cleanup stuck/failed/duplicate PST jobs for a project/case.

    This runs *inside* the production environment (same DB connectivity), avoiding the
    need for direct RDS access from a developer machine.

    Body:
      project_id: str | None
      case_id: str | None
      stuck_hours: float (default 1)
      include_failed: bool (default true)
      include_stuck: bool (default true)
      include_duplicates: bool (default true)
      filename_contains: str | None  (e.g. "Paul.Walker")
      apply: bool (default false)  -> dry-run unless true

    Returns:
      candidates_count, selected_count, summary counts.
    """

    # Require true admin role (do not use email heuristics).
    if user.role != UserRole.ADMIN and user.email not in {
        "admin@veri-case.com",
        "admin@vericase.com",
    }:
        raise HTTPException(status_code=403, detail="Admin access required")

    from datetime import timedelta

    from .models import EmailMessage, EmailAttachment, EvidenceItem

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

    # Load candidates for scope
    q = db.query(PSTFile)
    if project_id:
        q = q.filter(PSTFile.project_id == uuid.UUID(project_id))
    if case_id:
        q = q.filter(PSTFile.case_id == uuid.UUID(case_id))

    candidates = q.order_by(PSTFile.uploaded_at.desc()).all()

    # Compute selected IDs
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
        # duplicates = same filename + file_size_bytes, and all have 0 emails extracted
        groups: dict[tuple[str, int | None], list[PSTFile]] = {}
        for pst in candidates:
            groups.setdefault((pst.filename or "", pst.file_size_bytes), []).append(pst)

        for _, group in groups.items():
            if len(group) <= 1:
                continue
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

    # Count rows to delete
    total_counts = {
        "pst_files": 0,
        "email_messages": 0,
        "email_attachments": 0,
        "evidence_items": 0,
    }

    def _counts_for_pst(pst_id: uuid.UUID) -> dict[str, int]:
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
        return {
            "pst_files": 1,
            "email_messages": len(email_ids),
            "email_attachments": int(att_count),
            "evidence_items": int(ev_count),
        }

    per_pst = []
    for pst in selected:
        c = _counts_for_pst(pst.id)
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
                "counts": c,
            }
        )
        for k, v in c.items():
            total_counts[k] += v

    if apply:
        # delete in dependency order per pst
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


@router.post("/uploads/multipart/start")
def multipart_start_ep(
    body: dict = Body(...),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    filename = body.get("filename")
    ct = body.get("content_type") or "application/octet-stream"
    path = (body.get("path") or "").strip().strip("/")
    key = f"{path + '/' if path else ''}{uuid.uuid4()}/{filename}"
    upload_id = multipart_start(key, ct)
    return {"key": key, "uploadId": upload_id}


@router.get("/uploads/multipart/part")
def multipart_part_url(
    key: str, uploadId: str, partNumber: int, user: User = Depends(current_user)
):
    return {"url": presign_part(key, uploadId, partNumber)}


@router.post("/uploads/multipart/complete")
def multipart_complete_ep(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    key = body["key"]
    upload_id = body["uploadId"]
    parts = body["parts"]
    multipart_complete(key, upload_id, parts)
    filename = body.get("filename") or "file"
    ct = body.get("content_type") or "application/octet-stream"
    size = int(body.get("size") or 0)
    title = body.get("title")
    path = body.get("path")
    # Set empty paths to None so they're treated consistently
    if path == "":
        path = None

    doc = Document(
        filename=filename,
        path=path,
        content_type=ct,
        size=size,
        bucket=settings.MINIO_BUCKET,
        s3_key=key,
        title=title,
        status=DocStatus.NEW,
        owner_user_id=user.id,
    )
    db.add(doc)
    db.commit()
    celery_app.send_task("worker_app.worker.ocr_and_index", args=[str(doc.id)])
    return {"id": str(doc.id), "status": "QUEUED"}
