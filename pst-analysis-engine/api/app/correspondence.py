# pyright: reportCallInDefaultInitializer=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""
Correspondence API Endpoints
Email correspondence management for PST analysis
"""

import asyncio
import logging
import os
import re as _re_module
import uuid
from datetime import datetime
from typing import Annotated, Any

from boto3.s3.transfer import TransferConfig
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from pydantic.fields import Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Case,
    Company,
    DocStatus,
    Document,
    EmailAttachment,
    EmailMessage,
    Keyword,
    Project,
    PSTFile,
    Stakeholder,
    User,
)
from .security import current_user, get_db
from .storage import (
    multipart_complete,
    multipart_start,
    presign_get,
    presign_part,
    presign_put,
    s3,
)
from .tasks import celery_app

logger = logging.getLogger(__name__)

# Pre-compiled regex patterns for inline image detection (compiled once at module load)
_IMAGE_NUMBER_PATTERN = _re_module.compile(
    r"^image\d{3}\.(png|jpg|jpeg|gif|bmp)$"
)  # image001.png
_IMG_NUMBER_PATTERN = _re_module.compile(
    r"^img_?\d+\.(png|jpg|jpeg|gif|bmp)$"
)  # img_001.png

# Pre-compiled set for O(1) lookup instead of list iteration
_TRACKING_FILES = frozenset(
    ["blank.gif", "spacer.gif", "pixel.gif", "1x1.gif", "oledata.mso"]
)
_EXCLUDED_KEYWORDS = frozenset(
    ["signature", "logo", "banner", "header", "footer", "badge", "icon"]
)


def _is_embedded_image(att_data: dict[str, Any]) -> bool:
    """Check if attachment is an embedded/inline image that should be excluded from attachment lists

    Uses pre-compiled patterns and sets for optimal performance.
    """
    # Trust the is_inline flag set by the PST processor
    if att_data.get("is_inline") is True:
        return True

    filename = (att_data.get("filename") or att_data.get("name") or "").lower()
    content_type = (att_data.get("content_type") or "").lower()
    file_size = att_data.get("file_size") or att_data.get("size") or 0

    # O(1) lookup for tracking files
    if filename in _TRACKING_FILES:
        return True

    # Quick prefix checks before regex
    if filename.startswith(("cid:", "cid_")):
        return True

    # Pre-compiled regex matching
    if _IMAGE_NUMBER_PATTERN.match(filename) or _IMG_NUMBER_PATTERN.match(filename):
        return True

    # Only check keywords if content type is image (avoid unnecessary work)
    if "image" in content_type:
        # Very small images are likely embedded icons/logos
        if file_size and file_size < 20000:
            return True
        # Check for signature/logo keywords using set intersection
        if any(kw in filename for kw in _EXCLUDED_KEYWORDS):
            return True

    return False


# Main router for correspondence features
router = APIRouter(prefix="/api/correspondence", tags=["correspondence"])

# Secondary router for wizard endpoints (no prefix for compatibility)
wizard_router = APIRouter(prefix="/api", tags=["wizard"])

# Unified router for both projects and cases
unified_router = APIRouter(prefix="/api/unified", tags=["unified"])


# ========================================
# PYDANTIC MODELS
# ========================================


class PSTUploadInitRequest(BaseModel):
    """Request to initiate PST upload"""

    case_id: str | None = None  # Made optional
    filename: str
    file_size: int
    project_id: str | None = None


class PSTUploadInitResponse(BaseModel):
    """Response with presigned upload URL"""

    pst_file_id: str
    upload_url: str
    s3_bucket: str
    s3_key: str


class PSTMultipartInitRequest(BaseModel):
    """Request to initiate multipart PST upload for large files (>100MB)"""

    case_id: str | None = None
    filename: str
    file_size: int
    project_id: str | None = None
    content_type: str = "application/vnd.ms-outlook"


class PSTMultipartInitResponse(BaseModel):
    """Response with multipart upload info"""

    pst_file_id: str
    upload_id: str
    s3_bucket: str
    s3_key: str
    chunk_size: int  # Recommended chunk size in bytes


class PSTMultipartPartResponse(BaseModel):
    """Response with presigned URL for a single part"""

    url: str
    part_number: int


class PSTMultipartCompleteRequest(BaseModel):
    """Request to complete multipart upload"""

    pst_file_id: str
    upload_id: str
    parts: list[dict[str, Any]]  # List of {ETag, PartNumber}


class PSTProcessingStatus(BaseModel):
    """PST processing status"""

    pst_file_id: str
    status: str  # queued, processing, completed, failed
    total_emails: int
    processed_emails: int
    progress_percent: float
    error_message: str | None = None


class PSTFileInfo(BaseModel):
    """PST file info for list view"""

    id: str
    filename: str
    file_size_bytes: int | None
    total_emails: int
    processed_emails: int
    processing_status: str
    uploaded_at: datetime | None
    processing_started_at: datetime | None
    processing_completed_at: datetime | None
    error_message: str | None = None
    case_id: str | None = None
    project_id: str | None = None


class PSTFileListResponse(BaseModel):
    """Response for listing PST files"""

    items: list[PSTFileInfo]
    total: int
    page: int
    page_size: int


class EmailMessageSummary(BaseModel):
    """Email message summary for list view"""

    id: str
    subject: str | None
    sender_email: str | None
    sender_name: str | None
    body_text_clean: str | None = None
    body_html: str | None = None  # Original HTML body for rendering
    body_text: str | None = None  # Plain text body
    content_hash: str | None = None
    date_sent: datetime | None
    has_attachments: bool
    matched_stakeholders: list[str] | None
    matched_keywords: list[str] | None
    importance: str | None
    meta: dict[str, Any] | None = None  # Include attachments and other metadata

    # AG Grid compatibility fields
    email_subject: str | None = None
    email_from: str | None = None
    email_to: str | None = None
    email_cc: str | None = None
    email_date: datetime | None = None
    email_body: str | None = None
    attachments: list[dict[str, Any]] | None = None

    # Additional AG Grid fields (editable/custom fields)
    programme_activity: str | None = None
    baseline_activity: str | None = None
    as_built_activity: str | None = None
    delay_days: int | None = None
    programme_variance: str | None = None
    is_critical_path: bool | None = None
    programme_status: str | None = None
    planned_progress: float | None = None
    actual_progress: float | None = None
    category: str | None = None
    suggested_category: str | None = None  # AI-suggested category based on content
    keywords: str | None = None
    stakeholder: str | None = None
    stakeholder_role: str | None = None  # Party role from matched stakeholders
    priority: str | None = None
    status: str | None = None
    notes: str | None = None
    thread_id: str | None = None


class EmailMessageDetail(BaseModel):
    """Full email message details"""

    id: str
    subject: str | None
    sender_email: str | None
    sender_name: str | None
    recipients_to: list[str] | None  # Changed to list of strings (text[] in DB)
    recipients_cc: list[str] | None  # Changed to list of strings (text[] in DB)
    date_sent: datetime | None
    date_received: datetime | None
    body_text: str | None
    body_html: str | None
    body_text_clean: str | None = None
    content_hash: str | None = None
    has_attachments: bool
    attachments: list[dict[str, Any]]
    matched_stakeholders: list[str] | None
    matched_keywords: list[str] | None
    importance: str | None
    pst_message_path: str | None


class EmailListResponse(BaseModel):
    """Paginated email list"""

    total: int
    emails: list[EmailMessageSummary]
    page: int
    page_size: int


class EmailUpdate(BaseModel):
    """Schema for updating email fields"""

    baseline_activity: str | None = None
    as_built_activity: str | None = None
    delay_days: int | None = None
    is_critical_path: bool | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    notes: str | None = None


# ========================================
# PST UPLOAD ENDPOINTS
# ========================================


@router.post("/pst/upload")
async def upload_pst_file(
    file: Annotated[UploadFile, File(...)],
    case_id: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Direct server-side upload for PST files.
    Uploads to S3 and creates PSTFile record.
    """
    # Get default admin user
    default_user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not default_user:
        from .security import hash_password
        from .models import UserRole

        default_user = User(
            email="admin@vericase.com",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)

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
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not determine PST file size for %s: %s", file.filename, exc)
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
    if s3_client is not None:  # pyright: ignore[reportUnnecessaryComparison]
        transfer_config = TransferConfig(
            multipart_threshold=8 * 1024 * 1024,
            multipart_chunksize=8 * 1024 * 1024,
            max_concurrency=2,
            use_threads=True,
        )

        async def _stream_upload() -> int:
            """
            Stream upload to S3 to avoid buffering large PSTs in memory.
            Falls back to manual multipart if the legacy endpoint receives a big file.
            """
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
                    except Exception as abort_exc:  # pragma: no cover - best effort cleanup
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
        processing_status="pending",
        uploaded_by=default_user.id,
    )

    db.add(pst_file)
    db.commit()

    logger.info(f"Uploaded PST file via server: {pst_file_id}")

    # Trigger processing immediately
    # Enqueue Celery task for PST processing
    task_id = None
    try:
        task = celery_app.send_task(
            "worker_app.worker.process_pst_file",
            args=[pst_file_id],
            queue=settings.CELERY_PST_QUEUE,
        )
        task_id = task.id
    except Exception as e:
        logger.warning(f"Failed to enqueue Celery task (Redis unavailable?): {e}")
        # Upload still succeeded, just no async processing

    return {
        "pst_file_id": pst_file_id,
        "message": "PST uploaded successfully" + (" and processing started" if task_id else " (processing pending)"),
        "task_id": task_id
    }


@router.post("/pst/upload/init", response_model=PSTUploadInitResponse)
async def init_pst_upload(
    request: PSTUploadInitRequest,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Initialize PST file upload
    Returns presigned S3 URL for direct browser upload
    """

    # Get default admin user
    default_user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not default_user:
        from .security import hash_password
        from .models import UserRole

        default_user = User(
            email="admin@vericase.com",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)

    # Verify case or project exists
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

    # Generate PST file record
    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    s3_key = f"{entity_prefix}/pst/{pst_file_id}/{request.filename}"

    # Create PST file record
    pst_file = PSTFile(
        id=pst_file_id,
        filename=request.filename,
        case_id=request.case_id,
        project_id=request.project_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size_bytes=request.file_size,
        processing_status="pending",
        uploaded_by=default_user.id,
    )

    db.add(pst_file)
    db.commit()

    # Generate presigned upload URL (valid for 4 hours for large files)
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


# ========================================
# MULTIPART UPLOAD ENDPOINTS (for large PST files 100MB+)
# ========================================

# Recommended chunk size: 100MB for optimal performance
MULTIPART_CHUNK_SIZE = 100 * 1024 * 1024  # 100MB
# Server-side streaming chunk size for legacy uploads to avoid buffering entire files
SERVER_STREAMING_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/pst/upload/multipart/init", response_model=PSTMultipartInitResponse)
async def init_pst_multipart_upload(
    request: PSTMultipartInitRequest,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Initialize multipart PST file upload for large files (>100MB).
    Returns upload_id and s3_key for subsequent part uploads.
    """
    # Get default admin user
    default_user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not default_user:
        from .security import hash_password
        from .models import UserRole

        default_user = User(
            email="admin@vericase.com",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)

    # Verify case or project exists
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

    # Generate PST file record
    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    s3_key = f"{entity_prefix}/pst/{pst_file_id}/{request.filename}"

    # Start S3 multipart upload
    upload_id = multipart_start(s3_key, request.content_type, bucket=s3_bucket)

    # Create PST file record with upload_id for tracking
    pst_file = PSTFile(
        id=pst_file_id,
        filename=request.filename,
        case_id=request.case_id,
        project_id=request.project_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size_bytes=request.file_size,
        processing_status="uploading",
        uploaded_by=default_user.id,
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


@router.get("/pst/upload/multipart/part", response_model=PSTMultipartPartResponse)
async def get_pst_multipart_part_url(
    pst_file_id: str = Query(..., description="PST file ID"),
    upload_id: str = Query(..., description="Multipart upload ID"),
    part_number: int = Query(..., ge=1, le=10000, description="Part number (1-10000)"),
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Get presigned URL for uploading a specific part of the multipart upload.
    Parts must be numbered 1-10000 and uploaded in order or parallel.
    """
    # Verify PST file exists
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    # Generate presigned URL for this part (valid for 4 hours)
    url = presign_part(
        pst_file.s3_key,
        upload_id,
        part_number,
        expires=14400,
        bucket=pst_file.s3_bucket,
    )

    return PSTMultipartPartResponse(url=url, part_number=part_number)


@router.post("/pst/upload/multipart/complete")
async def complete_pst_multipart_upload(
    request: PSTMultipartCompleteRequest,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Complete multipart upload after all parts are uploaded.
    Requires list of {ETag, PartNumber} for each uploaded part.
    """
    # Verify PST file exists
    pst_file = db.query(PSTFile).filter_by(id=request.pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    try:
        # Complete the multipart upload in S3
        multipart_complete(
            pst_file.s3_key, request.upload_id, request.parts, bucket=pst_file.s3_bucket
        )

        # Update PST file status
        pst_file.processing_status = "pending"
        db.commit()

        logger.info(f"Completed multipart upload for PST: {request.pst_file_id}")

        return {
            "success": True,
            "pst_file_id": request.pst_file_id,
            "message": "Upload complete. Call /pst/{pst_file_id}/process to start processing.",
        }

    except Exception as e:
        logger.error(f"Failed to complete multipart upload: {e}")
        raise HTTPException(500, f"Failed to complete upload: {str(e)}")


@router.post("/pst/{pst_file_id}/process")
async def start_pst_processing(
    pst_file_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Start PST processing after upload completes
    Enqueues Celery task for background processing
    """

    # Get PST file record
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    # Verify access - PST can be linked to either a project or a case
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

    # Enqueue Celery task for PST processing
    task = celery_app.send_task(
        "worker_app.worker.process_pst_file",
        args=[pst_file_id],  # Pass PST file ID - worker fetches details from DB
        queue=settings.CELERY_PST_QUEUE,
    )

    logger.info(f"Enqueued PST processing task {task.id} for file {pst_file_id}")

    return {
        "success": True,
        "task_id": task.id,
        "pst_file_id": pst_file_id,
        "message": "PST processing started",
    }


@router.get("/pst/{pst_file_id}/status", response_model=PSTProcessingStatus)
async def get_pst_status(
    pst_file_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get PST processing status with Redis-based progress tracking"""
    from redis import Redis

    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")

    # Try to get detailed progress from Redis
    try:
        redis_client: Redis = Redis.from_url(settings.REDIS_URL)  # type: ignore[reportGeneralTypeIssues]
        redis_key = f"pst:{pst_file_id}"
        redis_data: dict[bytes, bytes] = redis_client.hgetall(redis_key)  # type: ignore[reportGeneralTypeIssues]

        if redis_data:
            # Decode Redis data (bytes to string)
            decoded_redis_data = {k.decode(): v.decode() for k, v in redis_data.items()}

            # Get chunk progress
            total_chunks = int(decoded_redis_data.get("total_chunks", "0"))
            completed_chunks = int(decoded_redis_data.get("completed_chunks", "0"))
            failed_chunks = int(decoded_redis_data.get("failed_chunks", "0"))

            # Calculate progress based on chunks
            if total_chunks > 0:
                progress = (
                    float(completed_chunks + failed_chunks) / float(total_chunks)
                ) * 100.0
            else:
                progress = 0.0

            # Get processed emails from Redis
            processed_emails_val = (
                pst_file.processed_emails
                if pst_file.processed_emails is not None
                else 0
            )
            processed_emails = int(
                decoded_redis_data.get("processed_emails", str(processed_emails_val))
            )

            # Update database with latest count
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
            return PSTProcessingStatus(
                pst_file_id=str(pst_file.id),
                status=decoded_redis_data.get(
                    "status", pst_file.processing_status or "pending"
                ),
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

    # Fall back to database progress
    progress = 0.0
    total_emails = pst_file.total_emails if pst_file.total_emails is not None else 0
    processed_emails = (
        pst_file.processed_emails if pst_file.processed_emails is not None else 0
    )
    if total_emails > 0:
        progress = (float(processed_emails) / float(total_emails)) * 100.0

    return PSTProcessingStatus(
        pst_file_id=str(pst_file.id),
        status=pst_file.processing_status or "pending",  # type: ignore[reportArgumentType]
        total_emails=total_emails,  # type: ignore[reportArgumentType]
        processed_emails=processed_emails,
        progress_percent=round(float(progress), 1),
        error_message=(
            str(pst_file.error_message) if pst_file.error_message is not None else None
        ),
    )


@router.get("/pst/files", response_model=PSTFileListResponse)
async def list_pst_files(
    project_id: Annotated[str | None, Query(description="Filter by project ID")] = None,
    case_id: Annotated[str | None, Query(description="Filter by case ID")] = None,
    status: Annotated[
        str | None, Query(description="Filter by processing status")
    ] = None,
    page: int = Query(1, ge=1),  # type: ignore[reportCallInDefaultInitializer]
    page_size: int = Query(50, ge=1, le=200),  # type: ignore[reportCallInDefaultInitializer]
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """List uploaded PST files with filtering and pagination"""
    query = db.query(PSTFile)

    # Apply filters
    if project_id:
        query = query.filter(PSTFile.project_id == project_id)
    if case_id:
        query = query.filter(PSTFile.case_id == case_id)
    if status:
        query = query.filter(PSTFile.processing_status == status)

    # Get total count
    total = query.count()

    # Order by most recent first and paginate
    query = query.order_by(PSTFile.uploaded_at.desc())
    offset = (page - 1) * page_size
    pst_files = query.offset(offset).limit(page_size).all()

    # Convert to response format
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


# ========================================
# EMAIL CORRESPONDENCE ENDPOINTS
# ========================================


@router.get("/emails/count")
async def get_email_count(
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Get email count for a case or project - lightweight endpoint for dashboards.
    Much faster than the full emails endpoint when only count is needed.
    """
    from sqlalchemy import func

    if case_id:
        count = (
            db.query(func.count(EmailMessage.id))
            .filter(EmailMessage.case_id == case_id)
            .scalar()
            or 0
        )
    elif project_id:
        count = (
            db.query(func.count(EmailMessage.id))
            .filter(EmailMessage.project_id == project_id)
            .scalar()
            or 0
        )
    else:
        count = db.query(func.count(EmailMessage.id)).scalar() or 0

    return {"count": count}


@router.get("/emails", response_model=EmailListResponse)
async def list_emails(
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    page: int = Query(1, ge=1),  # type: ignore[reportCallInDefaultInitializer]
    page_size: int = Query(5000, ge=1, le=50000),  # type: ignore[reportCallInDefaultInitializer]
    search: Annotated[
        str | None, Query(description="Search in subject and body")
    ] = None,
    stakeholder_id: Annotated[
        str | None, Query(description="Filter by stakeholder")
    ] = None,
    keyword_id: Annotated[str | None, Query(description="Filter by keyword")] = None,
    has_attachments: Annotated[
        bool | None, Query(description="Filter by attachments")
    ] = None,
    date_from: Annotated[datetime | None, Query(description="Date range start")] = None,
    date_to: Annotated[datetime | None, Query(description="Date range end")] = None,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    List emails for a case or project with filtering and pagination
    """

    # Build query - no authentication checks, full open access
    if not case_id and not project_id:
        # View all emails across all projects/cases
        query = db.query(EmailMessage)
    elif case_id:
        case = db.query(Case).filter_by(id=case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
        # Build query
        query = db.query(EmailMessage).filter_by(case_id=case_id)
    else:
        project = db.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
        # Build query
        query = db.query(EmailMessage).filter_by(project_id=project_id)

    # Apply filters
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

    # Get total count
    total = query.count()

    # Apply pagination and ordering
    offset = (page - 1) * page_size
    emails = (
        query.order_by(EmailMessage.date_sent.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Convert to summaries with attachment info
    email_summaries: list[EmailMessageSummary] = []

    for e in emails:
        # Get attachments from eager-loaded relationship (no N+1 queries)
        attachments = (
            e.attachments if hasattr(e, "attachments") and e.attachments else []
        )

        # Build attachment list from email_attachments table, excluding embedded images
        attachment_list = []
        for att in attachments:
            att_data = {
                "id": str(att.id),
                "filename": att.filename,
                "name": att.filename,
                "content_type": att.content_type,
                "file_size": att.file_size_bytes,
                "size": att.file_size_bytes,
                "s3_key": att.s3_key,
                "s3_bucket": att.s3_bucket,
                "is_inline": getattr(att, "is_inline", False),
                "content_id": getattr(att, "content_id", None),
                "attachment_hash": getattr(att, "attachment_hash", None),
                "is_duplicate": getattr(att, "is_duplicate", False),
            }
            # Only include non-embedded attachments
            if not _is_embedded_image(att_data):
                attachment_list.append(att_data)

        # Check metadata field for attachments (primary source for PST-processed emails)
        email_meta: dict[str, Any] = (
            dict(e.meta) if e.meta is not None and isinstance(e.meta, dict) else {}
        )

        if not attachment_list:
            # Try to get attachments from metadata, filtering out embedded images
            metadata_attachments = email_meta.get("attachments", [])
            if metadata_attachments and isinstance(metadata_attachments, list):
                attachment_list = [
                    att for att in metadata_attachments if not _is_embedded_image(att)
                ]
        else:
            # Update meta with new attachment list from email_attachments table
            email_meta["attachments"] = attachment_list

        # Ensure has_attachments flag is set correctly (only count real attachments)
        email_meta["has_attachments"] = len(attachment_list) > 0

        has_attachments_val = len(attachment_list) > 0

        # Helper function to format recipients - handles None/null values and various formats
        def format_recipients(recipients: list[Any] | str | None) -> str:
            if not recipients or recipients is None:
                return ""
            if not isinstance(recipients, list):
                # Handle single string value
                if isinstance(recipients, str):
                    return recipients.strip()
                return ""
            formatted: list[str] = []
            try:
                for recipient in recipients:
                    if isinstance(recipient, str):
                        # Plain string format (e.g., "John Smith" or "john@example.com")
                        if recipient.strip():
                            formatted.append(recipient.strip())
                    elif isinstance(recipient, dict):
                        # Dict format with email/name keys
                        email_addr = (
                            recipient.get("email") or recipient.get("address") or ""
                        )
                        name = (
                            recipient.get("name") or recipient.get("display_name") or ""
                        )
                        if email_addr and name:
                            formatted.append(f"{name} <{email_addr}>")
                        elif email_addr:
                            formatted.append(str(email_addr))
                        elif name:
                            formatted.append(str(name))
            except Exception as ex:
                logger.warning(f"Error formatting recipients: {ex}")
                return ""
            return ", ".join([item for item in formatted if item])

        # Format keywords and stakeholders for display
        keywords_str = ", ".join(e.matched_keywords) if e.matched_keywords else None
        stakeholder_str = (
            ", ".join(e.matched_stakeholders) if e.matched_stakeholders else None
        )

        # Look up stakeholder role from matched stakeholders
        stakeholder_role = None
        if e.matched_stakeholders and len(e.matched_stakeholders) > 0:
            # Look up first matched stakeholder's role
            first_stakeholder = (
                db.query(Stakeholder)
                .filter(
                    Stakeholder.project_id == project_id,
                    Stakeholder.name == e.matched_stakeholders[0],
                )
                .first()
            )
            if first_stakeholder:
                stakeholder_role = first_stakeholder.role

        # AI-assisted category suggestion based on subject and body content
        def suggest_category(subject: str | None, body: str | None) -> str | None:
            """Suggest a category based on email content patterns"""
            text = f"{subject or ''} {body or ''}".lower()

            # Category patterns with keywords (ordered by specificity)
            category_patterns = [
                (
                    "Compensation Event",
                    ["compensation event", "ce notice", "ce-", "compensation notice"],
                ),
                (
                    "Early Warning",
                    ["early warning", "ew notice", "ew-", "potential risk"],
                ),
                (
                    "Delay Notice",
                    [
                        "delay notice",
                        "extension of time",
                        "eot",
                        "time extension",
                        "programme delay",
                        "critical delay",
                    ],
                ),
                (
                    "Site Instruction",
                    ["site instruction", "si-", "si ", "instruction to", "directed to"],
                ),
                (
                    "Variation",
                    [
                        "variation order",
                        "vo-",
                        "vo ",
                        "change order",
                        "additional works",
                        "omission",
                    ],
                ),
                (
                    "Payment",
                    [
                        "payment certificate",
                        "interim payment",
                        "valuation",
                        "invoice",
                        "final account",
                        "payment application",
                    ],
                ),
                (
                    "Meeting Minutes",
                    [
                        "meeting minutes",
                        "minutes of meeting",
                        "attendees:",
                        "action items",
                        "agenda",
                    ],
                ),
                (
                    "Technical Query",
                    [
                        "technical query",
                        "tq-",
                        "rfi",
                        "request for information",
                        "clarification required",
                    ],
                ),
                (
                    "Progress Update",
                    [
                        "progress report",
                        "weekly report",
                        "monthly report",
                        "status update",
                        "progress update",
                    ],
                ),
                (
                    "Quality Issue",
                    [
                        "quality issue",
                        "defect",
                        "snag",
                        "ncr",
                        "non-conformance",
                        "remedial",
                    ],
                ),
                (
                    "Safety/H&S",
                    [
                        "safety",
                        "health and safety",
                        "h&s",
                        "accident",
                        "incident",
                        "near miss",
                        "hazard",
                    ],
                ),
                (
                    "Contract Document",
                    ["contract", "specification", "drawing", "schedule", "appendix"],
                ),
            ]

            for category, keywords in category_patterns:
                if any(kw in text for kw in keywords):
                    return category

            return None

        suggested_category = suggest_category(
            e.subject, e.body_text_clean or e.body_text
        )

        # Clean the email body - strip HTML tags and decode escape sequences
        def clean_body_text(
            body_text_clean: str | None, body_html: str | None, body_text: str | None
        ) -> str:
            """Return clean text for display in grid"""
            import re
            from html import unescape

            # Prefer body_text_clean if available
            if body_text_clean:
                return body_text_clean

            # Fall back to body_html or body_text
            text = body_html or body_text or ""
            if not text:
                return "[No content]"

            # Convert bytes to string if needed
            if isinstance(text, bytes):
                try:
                    text = text.decode("utf-8", errors="ignore")
                except Exception:
                    return "[Unable to decode]"

            # If it starts with "b'" it's a string representation of bytes
            if text.startswith("b'") or text.startswith('b"'):
                text = text[2:-1]  # Remove b' and trailing '

            # Replace escaped sequences first
            text = text.replace("\\r\\n", "\n")
            text = text.replace("\\n", "\n")
            text = text.replace("\\r", "\n")
            text = text.replace("\\t", " ")
            text = text.replace("\\'", "'")
            text = text.replace('\\"', '"')

            # Fix common escaped Unicode characters
            text = text.replace("\\xe2\\x80\\x93", "-")  # en-dash
            text = text.replace("\\xe2\\x80\\x94", "--")  # em-dash
            text = text.replace("\\xe2\\x80\\x99", "'")  # right single quote
            text = text.replace("\\xe2\\x80\\x98", "'")  # left single quote
            text = text.replace("\\xe2\\x80\\x9c", '"')  # left double quote
            text = text.replace("\\xe2\\x80\\x9d", '"')  # right double quote
            text = text.replace("\\xe2\\x80\\x8b", "")  # zero-width space
            text = text.replace("\\xa0", " ")  # non-breaking space

            # Replace actual Unicode characters
            text = text.replace("\u00a0", " ")  # non-breaking space
            text = text.replace("\u200b", "")  # zero-width space
            text = text.replace("\u2013", "-")  # en-dash
            text = text.replace("\u2014", "--")  # em-dash
            text = text.replace("\u2019", "'")  # right single quote
            text = text.replace("\u201c", '"')  # left double quote
            text = text.replace("\u201d", '"')  # right double quote

            # Replace the � character and other common issues
            text = text.replace("�", " ")
            text = text.replace("&nbsp;", " ")

            # Remove style tags and their content
            text = re.sub(
                r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
            )
            text = re.sub(
                r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
            )

            # Remove CSS/VML definitions
            text = re.sub(r"v\\\\:\*\s*{[^}]*}", "", text)
            text = re.sub(r"o\\\\:\*\s*{[^}]*}", "", text)
            text = re.sub(r"w\\\\:\*\s*{[^}]*}", "", text)
            text = re.sub(r"\.shape\s*{[^}]*}", "", text)
            text = re.sub(r"{behavior:url\([^)]+\);}", "", text)

            # Remove all HTML tags
            text = re.sub(r"<[^>]+>", " ", text)

            # Decode HTML entities
            text = unescape(text)

            # Normalize all Unicode whitespace to regular spaces
            text = re.sub(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]", " ", text)

            # Remove excessive whitespace and newlines
            text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)  # Max 2 newlines
            text = re.sub(r" +", " ", text)  # Multiple spaces to single
            text = re.sub(
                r"\s*\n\s*", " ", text
            )  # Newlines to spaces for compact display

            # Strip disclaimers and common footer text
            text = re.sub(
                r"The information contained in this message.*?$",
                "",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            text = re.sub(
                r"EXTERNAL EMAIL:.*?safe\.", "", text, flags=re.DOTALL | re.IGNORECASE
            )

            # Clean up and trim
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = " ".join(lines)

            # Limit length for preview
            if len(text) > 300:
                text = text[:300] + "..."

            return text.strip() or "[No readable content]"

        email_summaries.append(
            EmailMessageSummary(
                id=str(e.id),
                subject=e.subject,  # type: ignore[reportArgumentType]
                sender_email=e.sender_email,  # type: ignore[reportArgumentType]
                sender_name=e.sender_name,  # type: ignore[reportArgumentType]
                body_text_clean=e.body_text_clean,  # type: ignore[reportArgumentType]
                body_html=e.body_html,  # type: ignore[reportArgumentType]
                body_text=e.body_text,  # type: ignore[reportArgumentType]
                content_hash=e.content_hash,  # type: ignore[reportArgumentType]
                date_sent=e.date_sent,  # type: ignore[reportArgumentType]
                has_attachments=has_attachments_val,
                matched_stakeholders=e.matched_stakeholders,  # type: ignore[reportArgumentType]
                matched_keywords=e.matched_keywords,  # type: ignore[reportArgumentType]
                importance=e.importance,  # type: ignore[reportArgumentType]
                meta=email_meta,
                # AG Grid compatibility fields
                email_subject=e.subject,  # type: ignore[reportArgumentType]
                email_from=e.sender_email if e.sender_email is not None else e.sender_name,  # type: ignore[reportArgumentType]
                email_to=format_recipients(e.recipients_to),
                email_cc=format_recipients(e.recipients_cc),
                email_date=e.date_sent,  # type: ignore[reportArgumentType]
                email_body=clean_body_text(e.body_text_clean, e.body_html, e.body_text),
                attachments=attachment_list,
                # Additional AG Grid fields (with defaults)
                programme_activity=getattr(
                    e, "as_planned_activity", None
                ),  # Default to as-planned
                baseline_activity=getattr(e, "as_planned_activity", None),
                as_built_activity=getattr(e, "as_built_activity", None),
                delay_days=getattr(e, "delay_days", None),
                programme_variance=None,
                is_critical_path=None,
                programme_status=None,
                planned_progress=None,
                actual_progress=None,
                category=None,
                suggested_category=suggested_category,  # AI-suggested category
                keywords=keywords_str,
                stakeholder=stakeholder_str,
                stakeholder_role=stakeholder_role,  # Party role from matched stakeholders
                priority="Normal",  # Default priority
                status="Open",  # Default status
                notes=None,
                thread_id=getattr(e, "thread_id", None),
            )
        )

    return EmailListResponse(
        total=total, emails=email_summaries, page=page, page_size=page_size
    )


# ========================================
# SERVER-SIDE ROW MODEL ENDPOINT (High Performance)
# ========================================


class ServerSideRequest(BaseModel):
    """AG Grid Server-Side Row Model request"""

    startRow: int = 0
    endRow: int = 100
    sortModel: list[dict] = Field(default_factory=list)
    filterModel: dict = Field(default_factory=dict)
    groupKeys: list[str] = Field(default_factory=list)
    rowGroupCols: list[dict] = Field(default_factory=list)


class ServerSideResponse(BaseModel):
    """AG Grid Server-Side Row Model response"""

    rows: list[dict]
    lastRow: int  # -1 if more rows exist, otherwise total count
    # Statistics for the stats bar
    stats: dict = Field(default_factory=dict)


@router.post("/emails/server-side")
async def get_emails_server_side(
    request: ServerSideRequest,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    db: Session = Depends(get_db),
) -> ServerSideResponse:
    """
    High-performance server-side endpoint for AG Grid.
    Only loads the rows needed for display, enabling handling of 100k+ emails.
    """
    start_row = request.startRow
    end_row = request.endRow
    page_size = end_row - start_row

    # Build base query
    if case_id:
        query = db.query(EmailMessage).filter(
            EmailMessage.case_id == uuid.UUID(case_id)
        )
    elif project_id:
        query = db.query(EmailMessage).filter(
            EmailMessage.project_id == uuid.UUID(project_id)
        )
    else:
        query = db.query(EmailMessage)

    # Apply AG Grid filters
    for col_id, filter_data in request.filterModel.items():
        filter_type = filter_data.get("filterType", "text")
        filter_op = filter_data.get("type", "contains")
        filter_value = filter_data.get("filter", "")

        # Map column IDs to model attributes
        column_map = {
            "subject": EmailMessage.subject,
            "sender_name": EmailMessage.sender_name,
            "sender_email": EmailMessage.sender_email,
            "date_sent": EmailMessage.date_sent,
            "has_attachments": EmailMessage.has_attachments,
            "body_text": EmailMessage.body_text,
            "baseline_activity": EmailMessage.as_planned_activity,
            "as_built_activity": EmailMessage.as_built_activity,
            "delay_days": EmailMessage.delay_days,
        }

        col = column_map.get(col_id)
        if col is None:
            continue

        if filter_type == "text":
            if filter_op == "contains":
                query = query.filter(col.ilike(f"%{filter_value}%"))
            elif filter_op == "notContains":
                query = query.filter(~col.ilike(f"%{filter_value}%"))
            elif filter_op == "equals":
                query = query.filter(col == filter_value)
            elif filter_op == "notEqual":
                query = query.filter(col != filter_value)
            elif filter_op == "startsWith":
                query = query.filter(col.ilike(f"{filter_value}%"))
            elif filter_op == "endsWith":
                query = query.filter(col.ilike(f"%{filter_value}"))
        elif filter_type == "date":
            date_from = filter_data.get("dateFrom")
            date_to = filter_data.get("dateTo")
            if date_from:
                query = query.filter(
                    col >= datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                )
            if date_to:
                query = query.filter(
                    col <= datetime.fromisoformat(date_to.replace("Z", "+00:00"))
                )
        elif filter_type == "set":
            values = filter_data.get("values", [])
            if values:
                query = query.filter(col.in_(values))

    # Get total count (cached if possible)
    total = query.count()

    # Apply sorting
    if request.sortModel:
        for sort in request.sortModel:
            col_id = sort.get("colId", "date_sent")
            sort_dir = sort.get("sort", "desc")

            column_map = {
                "subject": EmailMessage.subject,
                "sender_name": EmailMessage.sender_name,
                "sender_email": EmailMessage.sender_email,
                "date_sent": EmailMessage.date_sent,
                "has_attachments": EmailMessage.has_attachments,
                "baseline_activity": EmailMessage.as_planned_activity,
                "as_built_activity": EmailMessage.as_built_activity,
                "delay_days": EmailMessage.delay_days,
            }

            col = column_map.get(col_id, EmailMessage.date_sent)
            if sort_dir == "desc":
                query = query.order_by(col.desc())
            else:
                query = query.order_by(col.asc())
    else:
        # Default sort by date descending
        query = query.order_by(EmailMessage.date_sent.desc())

    # Apply pagination
    emails = query.offset(start_row).limit(page_size).all()

    # Convert to dicts with attachment info for grid display
    rows = []
    for e in emails:
        # Combine recipients from to/cc/bcc fields
        recipients_list = []
        if e.recipients_to:
            recipients_list.extend(e.recipients_to)
        if e.recipients_cc:
            recipients_list.extend(e.recipients_cc)

        # Load attachments from relationship (uses selectin loading - efficient)
        attachment_list = []

        # Ensure we are loading attachments - try relationships first
        try:
            db_attachments = e.attachments if hasattr(e, "attachments") else []
        except Exception:
            # Fallback if lazy loading fails
            db_attachments = []

        for att in db_attachments:
            att_data = {
                "id": str(att.id),
                "filename": att.filename,
                "name": att.filename,
                "content_type": att.content_type,
                "file_size": att.file_size_bytes,
                "size": att.file_size_bytes,
                "s3_key": att.s3_key,
                "s3_bucket": att.s3_bucket,
                "is_inline": getattr(att, "is_inline", False),
                "content_id": getattr(att, "content_id", None),
                "attachment_hash": getattr(att, "attachment_hash", None),
                "is_duplicate": getattr(att, "is_duplicate", False),
            }
            # Include ALL attachments here - filtering happens on frontend or via flag
            # But we mark embedded ones clearly so frontend can filter if needed
            att_data["is_embedded"] = _is_embedded_image(att_data)
            attachment_list.append(att_data)

        # Fallback: Check meta field for attachments if none found in relationship
        if not attachment_list:
            email_meta = dict(e.meta) if e.meta and isinstance(e.meta, dict) else {}
            meta_attachments = email_meta.get("attachments", [])
            if meta_attachments and isinstance(meta_attachments, list):
                attachment_list = []
                for att in meta_attachments:
                    # Normalize meta attachment structure
                    att_data = dict(att)
                    if "is_embedded" not in att_data:
                        att_data["is_embedded"] = _is_embedded_image(att_data)
                    attachment_list.append(att_data)

        # Explicitly log if we found attachments but they were filtered out
        # if e.has_attachments and not attachment_list:
        #    logger.debug(f"Email {e.id} has_attachments=True but attachment_list is empty")

        rows.append(
            {
                "id": str(e.id),
                # Map to expected frontend field names
                "email_subject": e.subject or "(No Subject)",
                "subject": e.subject or "(No Subject)",
                "baseline_activity": getattr(e, "as_planned_activity", None),
                "as_built_activity": getattr(e, "as_built_activity", None),
                "delay_days": getattr(e, "delay_days", None),
                "email_from": e.sender_email or "",
                "sender_name": e.sender_name or "",
                "sender_email": e.sender_email or "",
                "email_date": e.date_sent.isoformat() if e.date_sent else None,
                "date_sent": e.date_sent.isoformat() if e.date_sent else None,
                "email_to": e.recipients_to or [],
                "email_cc": e.recipients_cc or [],
                "recipients": recipients_list,
                "recipients_to": e.recipients_to or [],
                "recipients_cc": e.recipients_cc or [],
                "has_attachments": len(attachment_list) > 0
                or (e.has_attachments or False),
                "attachment_count": len(attachment_list)
                or getattr(e, "attachment_count", 0)
                or 0,
                "attachments": attachment_list,  # Include ALL attachments details for grid cell renderer
                "meta": (
                    {"attachments": attachment_list} if attachment_list else None
                ),  # Also in meta for compatibility
                "is_flagged": getattr(e, "is_flagged", False),
                "importance": getattr(e, "importance", "normal"),
                "read_status": getattr(e, "read_status", "unread"),
                "thread_id": (
                    str(e.thread_id) if getattr(e, "thread_id", None) else None
                ),
                "conversation_index": getattr(e, "conversation_index", None),
                "categories": getattr(e, "categories", []) or [],
                "linked_activity_id": (
                    str(e.linked_activity_id)
                    if getattr(e, "linked_activity_id", None)
                    else None
                ),
                "notes": getattr(e, "notes", None),
                # Body content for Message column - prefer clean text over raw
                "email_body": e.body_text_clean or e.body_text or "",
                "body_text": e.body_text or "",
                "body_text_clean": e.body_text_clean or "",
                "body_html": getattr(e, "body_html", None),
                "content": e.body_text_clean or e.body_text or "",
            }
        )

    # Determine lastRow: -1 if more data exists, otherwise total
    last_row = total if end_row >= total else -1

    # Calculate statistics (only on first request to avoid repeated queries)
    stats = {}
    if start_row == 0:
        # Build base query for stats (without pagination)
        stats_query = db.query(EmailMessage)
        if case_id:
            stats_query = stats_query.filter(EmailMessage.case_id == uuid.UUID(case_id))
        elif project_id:
            stats_query = stats_query.filter(
                EmailMessage.project_id == uuid.UUID(project_id)
            )

        # Total count
        stats["total"] = total

        # Unique threads
        thread_count = (
            stats_query.filter(EmailMessage.thread_id.isnot(None))
            .distinct(EmailMessage.thread_id)
            .count()
        )
        stats["uniqueThreads"] = thread_count

        # With attachments
        with_attachments = stats_query.filter(
            EmailMessage.has_attachments.is_(True)
        ).count()
        stats["withAttachments"] = with_attachments

        # Date range
        date_result = db.query(
            func.min(EmailMessage.date_sent), func.max(EmailMessage.date_sent)
        )
        if case_id:
            date_result = date_result.filter(EmailMessage.case_id == uuid.UUID(case_id))
        elif project_id:
            date_result = date_result.filter(
                EmailMessage.project_id == uuid.UUID(project_id)
            )

        min_date, max_date = date_result.first()
        if min_date and max_date:
            stats["dateRange"] = (
                f"{min_date.strftime('%d/%m/%Y')} - {max_date.strftime('%d/%m/%Y')}"
            )
        else:
            stats["dateRange"] = "-"

    return ServerSideResponse(rows=rows, lastRow=last_row, stats=stats)


@router.get("/emails/{email_id}", response_model=EmailMessageDetail)
async def get_email_detail(
    email_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Get full email details including attachments"""

    email = db.query(EmailMessage).filter_by(id=email_id).first()
    if not email:
        raise HTTPException(404, "Email not found")

    # Get attachments
    attachments = db.query(EmailAttachment).filter_by(email_message_id=email_id).all()

    # Generate presigned URLs for attachments, filtering out embedded images
    attachment_list: list[dict[str, Any]] = []
    for att in attachments:
        try:
            if att.s3_key is None or att.s3_bucket is None:
                continue

            # Build attachment data to check if it's embedded
            att_data = {
                "filename": att.filename,
                "content_type": att.content_type,
                "file_size": att.file_size_bytes,
                "is_inline": att.is_inline,
                "content_id": att.content_id,
            }

            # Skip embedded images
            if _is_embedded_image(att_data):
                continue

            download_url = presign_get(
                att.s3_key,
                expires=3600,
                bucket=att.s3_bucket,
                response_disposition=(
                    f'attachment; filename="{att.filename}"'
                    if att.filename
                    else "attachment"
                ),
            )
            attachment_list.append(
                {
                    "id": str(att.id),
                    "filename": att.filename,
                    "name": att.filename,  # Also include 'name' for frontend compatibility
                    "content_type": att.content_type,
                    "file_size": att.file_size_bytes,
                    "size": att.file_size_bytes,  # Also include 'size' for frontend compatibility
                    "download_url": download_url,
                    "has_been_ocred": att.has_been_ocred,
                    "is_inline": att.is_inline,
                    "content_id": att.content_id,
                    "attachment_hash": att.attachment_hash,
                    "is_duplicate": att.is_duplicate,
                }
            )
        except Exception as e:
            logger.error(f"Error generating presigned URL for attachment {att.id}: {e}")

    return EmailMessageDetail(
        id=str(email.id),
        subject=email.subject,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        recipients_to=email.recipients_to,
        recipients_cc=email.recipients_cc,
        date_sent=email.date_sent,
        date_received=email.date_received,
        body_text=email.body_text,
        body_html=email.body_html,
        body_text_clean=email.body_text_clean,
        content_hash=email.content_hash,
        has_attachments=email.has_attachments,
        attachments=attachment_list,
        matched_stakeholders=email.matched_stakeholders,
        matched_keywords=email.matched_keywords,
        importance=email.importance,
        pst_message_path=email.pst_message_path,
    )


@router.patch("/emails/{email_id}")
async def update_email(
    email_id: str,
    update_data: EmailUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    """Update email metadata (e.g. programme linking)"""
    try:
        email_uuid = uuid.UUID(email_id)
    except ValueError:
        raise HTTPException(400, "Invalid email ID")

    email = db.query(EmailMessage).filter_by(id=email_uuid).first()
    if not email:
        raise HTTPException(404, "Email not found")

    # Update programme linking fields
    if update_data.baseline_activity is not None:
        email.as_planned_activity = update_data.baseline_activity
    if update_data.as_built_activity is not None:
        email.as_built_activity = update_data.as_built_activity
    if update_data.delay_days is not None:
        email.delay_days = update_data.delay_days
    if update_data.is_critical_path is not None:
        email.is_critical_path = update_data.is_critical_path

    # Update other metadata in meta field
    if email.meta is None:
        email.meta = {}

    # Reassign to ensure change detection
    meta_update = dict(email.meta)

    if update_data.category is not None:
        meta_update["category"] = update_data.category
    if update_data.priority is not None:
        meta_update["priority"] = update_data.priority
    if update_data.status is not None:
        meta_update["status"] = update_data.status
    if update_data.notes is not None:
        meta_update["notes"] = update_data.notes

    email.meta = meta_update

    db.commit()
    return {"status": "success", "id": str(email.id)}


@router.get("/attachments/{attachment_id}/signed-url")
async def get_attachment_signed_url(
    attachment_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Get presigned URL for an email attachment"""
    try:
        att_uuid = uuid.UUID(attachment_id)
    except ValueError:
        raise HTTPException(400, "Invalid attachment ID")

    attachment = db.query(EmailAttachment).filter_by(id=att_uuid).first()
    if not attachment:
        raise HTTPException(404, "Attachment not found")

    if not attachment.s3_key:
        raise HTTPException(404, "Attachment has no S3 key")

    # Generate presigned URL for download
    url = presign_get(
        attachment.s3_key,
        expires=3600,
        bucket=attachment.s3_bucket,
    )

    return {
        "url": url,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
    }


@router.get("/emails/{email_id}/thread")
async def get_email_thread(
    email_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Get full email thread containing this email"""

    email = db.query(EmailMessage).filter_by(id=email_id).first()
    if not email:
        raise HTTPException(404, "Email not found")

    # Build thread by finding all related emails
    thread_emails: list[EmailMessage] = []

    if email.case_id is not None:
        entity_filter = EmailMessage.case_id == email.case_id
    elif email.project_id is not None:
        entity_filter = EmailMessage.project_id == email.project_id
    else:
        raise HTTPException(400, "Email has no case_id or project_id")

    if email.thread_id:
        thread_emails = list(
            db.query(EmailMessage)
            .filter(
                and_(
                    entity_filter,
                    EmailMessage.thread_id == email.thread_id,
                )
            )
            .order_by(EmailMessage.date_sent)
            .all()
        )

    if not thread_emails and email.message_id:
        thread_emails = list(
            db.query(EmailMessage)
            .filter(
                and_(
                    entity_filter,
                    or_(
                        EmailMessage.message_id == email.message_id,
                        EmailMessage.in_reply_to == email.message_id,
                        EmailMessage.email_references.contains(email.message_id),
                    ),
                )
            )
            .order_by(EmailMessage.date_sent)
            .all()
        )

    if not thread_emails and email.conversation_index:
        thread_emails = list(
            db.query(EmailMessage)
            .filter(
                and_(
                    entity_filter,
                    EmailMessage.conversation_index == email.conversation_index,
                )
            )
            .order_by(EmailMessage.date_sent)
            .all()
        )

    thread_summaries: list[dict[str, Any]] = []
    for e in thread_emails:
        thread_email_id = str(e.id)
        thread_summaries.append(
            {
                "id": thread_email_id,
                "subject": e.subject,
                "sender_email": e.sender_email,
                "sender_name": e.sender_name,
                "date_sent": e.date_sent.isoformat() if e.date_sent else None,
                "has_attachments": e.has_attachments,
                "is_current": thread_email_id == email_id,
                "thread_id": e.thread_id,
            }
        )

    return {
        "thread_size": len(thread_summaries),
        "thread_id": email.thread_id,
        "emails": thread_summaries,
    }


@router.get("/attachments/{attachment_id}/ocr-text")
async def get_attachment_ocr_text(
    attachment_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get OCR extracted text for an attachment

    Returns:
    - extracted_text: The OCR'd text content
    - has_been_ocred: Whether OCR has completed
    - ocr_status: Processing status
    """
    email_attachment = db.query(EmailAttachment).filter_by(id=attachment_id).first()

    if email_attachment:
        return {
            "attachment_id": str(email_attachment.id),
            "filename": email_attachment.filename,
            "has_been_ocred": email_attachment.has_been_ocred,
            "extracted_text": email_attachment.extracted_text,
            "ocr_status": (
                "completed" if email_attachment.has_been_ocred else "processing"
            ),
            "file_size": email_attachment.file_size_bytes,
            "content_type": email_attachment.content_type,
        }

    # Fallback: try as Document (for backward compatibility)
    document = db.query(Document).filter_by(id=attachment_id).first()
    if not document:
        raise HTTPException(404, "Attachment not found")

    is_attachment = document.meta.get("is_email_attachment") if document.meta else None

    return {
        "attachment_id": str(document.id),
        "filename": document.filename,
        "has_been_ocred": document.status == DocStatus.READY,
        "extracted_text": document.text_excerpt,
        "ocr_status": (
            "completed" if document.status == DocStatus.READY else "processing"
        ),
        "file_size": document.size,
        "content_type": document.content_type,
        "is_email_attachment": is_attachment,
    }


# ========================================
# PROJECTS & CASES (for wizard)
# ========================================


class ProjectCreateRequest(BaseModel):
    """Create project from wizard"""

    project_name: str | None = None
    project_code: str | None = None
    start_date: datetime | None = None
    completion_date: datetime | None = None
    contract_type: str | None = None
    stakeholders: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[dict[str, Any]] = Field(default_factory=list)
    # Retrospective analysis fields
    analysis_type: str | None = None  # 'retrospective' or 'project'
    project_aliases: str | None = None
    site_address: str | None = None
    include_domains: str | None = None
    exclude_people: str | None = None
    project_terms: str | None = None
    exclude_keywords: str | None = None


class ProjectUpdateRequest(BaseModel):
    """Update project details"""
    project_name: str | None = None
    project_code: str | None = None
    # Add other fields as needed for flexibility


class CaseCreateRequest(BaseModel):
    """Create case from wizard"""

    case_name: str | None = None
    case_id_custom: str | None = None
    resolution_route: str | None = None
    claimant: str | None = None
    defendant: str | None = None
    client: str | None = None
    case_status: str | None = "active"
    stakeholders: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[dict[str, Any]] = Field(default_factory=list)
    legal_team: list[dict[str, Any]] = Field(default_factory=list)
    heads_of_claim: list[dict[str, Any]] = Field(default_factory=list)
    deadlines: list[dict[str, Any]] = Field(default_factory=list)


# ========================================
# STAKEHOLDER AND KEYWORD ENDPOINTS
# ========================================


@wizard_router.get("/projects")
async def list_projects(
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """List all projects - no auth required"""
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return [
        {
            "id": str(p.id),
            "project_name": p.project_name,
            "project_code": p.project_code,
            "contract_type": p.contract_type,
        }
        for p in projects
    ]


@wizard_router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get a single project with lightweight related info (for dashboard)"""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    proj = db.query(Project).filter(Project.id == project_uuid).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    stakeholders = db.query(Stakeholder).filter_by(project_id=project_uuid).all()
    keywords = db.query(Keyword).filter_by(project_id=project_uuid).all()

    return {
        "id": str(proj.id),
        "projectName": proj.project_name,
        "projectCode": proj.project_code,
        "contractType": proj.contract_type,
        "project-stakeholders": {
            "stakeholders": [
                {
                    "stakeholder-role": s.role,
                    "stakeholder-name": s.name,
                    "stakeholder-email": s.email,
                    "organization": s.organization,
                }
                for s in stakeholders
            ],
            "keywords": [{"name": k.keyword_name} for k in keywords],
        },
    }


@wizard_router.get("/cases/{case_id}/stakeholders")
async def get_case_stakeholders(
    case_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get stakeholders for a case"""
    stakeholders = db.query(Stakeholder).filter_by(case_id=case_id).all()

    return [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization,
        }
        for s in stakeholders
    ]


@wizard_router.get("/cases/{case_id}/keywords")
async def get_case_keywords(
    case_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get keywords for a case"""
    keywords = db.query(Keyword).filter_by(case_id=case_id).all()

    return [
        {"id": str(k.id), "name": k.keyword_name, "variations": k.variations}
        for k in keywords
    ]


@wizard_router.get("/projects/{project_id}/stakeholders")
async def get_project_stakeholders(
    project_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get stakeholders for a project"""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    stakeholders = (
        db.query(Stakeholder).filter(Stakeholder.project_id == project_uuid).all()
    )

    return [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization,
        }
        for s in stakeholders
    ]


@wizard_router.get("/projects/{project_id}/keywords")
async def get_project_keywords(
    project_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get keywords for a project"""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    keywords = db.query(Keyword).filter(Keyword.project_id == project_uuid).all()

    return [
        {"id": str(k.id), "name": k.keyword_name, "variations": k.variations}
        for k in keywords
    ]


@wizard_router.get("/projects/{project_id}/domains")
async def get_project_email_domains(
    project_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Get unique email domains from all correspondence in a project.
    Extracts domains from sender_email, recipients_to, and recipients_cc fields.
    Returns domains with email counts and any existing stakeholder role assignment.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # Get all PST files for this project
    pst_files = db.query(PSTFile).filter(PSTFile.project_id == project_uuid).all()
    pst_ids = [p.id for p in pst_files]

    if not pst_ids:
        return {"domains": [], "total": 0}

    # Get all emails for this project's PSTs
    emails = db.query(EmailMessage).filter(EmailMessage.pst_file_id.in_(pst_ids)).all()

    # Extract domains from all email addresses
    domain_counts: dict[str, dict[str, Any]] = {}

    def extract_domain(email_addr: str | None) -> str | None:
        if not email_addr:
            return None
        # Handle "Name <email@domain.com>" format
        if "<" in email_addr and ">" in email_addr:
            email_addr = email_addr.split("<")[1].split(">")[0]
        if "@" in email_addr:
            return email_addr.split("@")[1].lower().strip()
        return None

    def add_domain(domain: str | None, email_type: str):
        if not domain:
            return
        if domain not in domain_counts:
            domain_counts[domain] = {
                "domain": domain,
                "total_emails": 0,
                "as_sender": 0,
                "as_recipient": 0,
                "role": None,
                "stakeholder_id": None,
            }
        domain_counts[domain]["total_emails"] += 1
        if email_type == "sender":
            domain_counts[domain]["as_sender"] += 1
        else:
            domain_counts[domain]["as_recipient"] += 1

    for email in emails:
        # Extract sender domain
        sender_domain = extract_domain(email.sender_email)
        add_domain(sender_domain, "sender")

        # Extract recipient domains from recipients_to
        if email.recipients_to:
            for recipient in email.recipients_to:
                recipient_domain = extract_domain(recipient)
                add_domain(recipient_domain, "recipient")

        # Extract recipient domains from recipients_cc
        if email.recipients_cc:
            for recipient in email.recipients_cc:
                recipient_domain = extract_domain(recipient)
                add_domain(recipient_domain, "recipient")

    # Look up existing stakeholder assignments for these domains
    existing_stakeholders = (
        db.query(Stakeholder)
        .filter(
            Stakeholder.project_id == project_uuid,
            Stakeholder.email_domain.in_(domain_counts.keys()),
        )
        .all()
    )

    # Map existing stakeholders to domains
    for s in existing_stakeholders:
        if s.email_domain and s.email_domain in domain_counts:
            domain_counts[s.email_domain]["role"] = s.role
            domain_counts[s.email_domain]["stakeholder_id"] = str(s.id)
            domain_counts[s.email_domain]["organization"] = s.organization

    # Sort by total emails descending
    sorted_domains = sorted(
        domain_counts.values(), key=lambda x: x["total_emails"], reverse=True
    )

    return {"domains": sorted_domains, "total": len(sorted_domains)}


class DomainRoleMapping(BaseModel):
    """Mapping of a domain to a stakeholder role"""

    domain: str
    role: str
    organization: str | None = None


class BulkStakeholderUpdate(BaseModel):
    """Bulk update of domain-to-role mappings"""

    mappings: list[DomainRoleMapping]


@wizard_router.post("/projects/{project_id}/stakeholders/bulk")
async def update_project_stakeholders_bulk(
    project_id: str,
    update_data: BulkStakeholderUpdate,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Bulk update/create stakeholders for domain-to-role mappings.
    Creates new stakeholders or updates existing ones based on email_domain.
    """
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    # Verify project exists
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    created = 0
    updated = 0

    for mapping in update_data.mappings:
        # Check if stakeholder already exists for this domain
        existing = (
            db.query(Stakeholder)
            .filter(
                Stakeholder.project_id == project_uuid,
                Stakeholder.email_domain == mapping.domain.lower(),
            )
            .first()
        )

        if existing:
            existing.role = mapping.role
            if mapping.organization:
                existing.organization = mapping.organization
            updated += 1
        else:
            new_stakeholder = Stakeholder(
                id=uuid.uuid4(),
                project_id=project_uuid,
                role=mapping.role,
                name=mapping.organization or mapping.domain,
                email_domain=mapping.domain.lower(),
                organization=mapping.organization,
            )
            db.add(new_stakeholder)
            created += 1

    db.commit()

    return {
        "message": "Stakeholders updated successfully",
        "created": created,
        "updated": updated,
    }


@wizard_router.post("/projects/default")
async def get_or_create_default_project(
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Get or create the default project.
    This endpoint ALWAYS returns a valid project - creates one if needed.
    Used by the frontend to ensure there's always a valid context for uploads.
    """
    # Get default admin user
    default_user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not default_user:
        from .security import hash_password
        from .models import UserRole

        default_user = User(
            email="admin@vericase.com",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)

    # Look for existing default project
    default_project = (
        db.query(Project).filter(Project.project_code == "DEFAULT").first()
    )

    if not default_project:
        # Create the default project
        today = datetime.now()
        default_project = Project(
            id=uuid.uuid4(),
            project_name="Evidence Uploads",
            project_code="DEFAULT",
            start_date=datetime(2010, 1, 1),
            completion_date=today,
            analysis_type="retrospective",
            owner_user_id=default_user.id,
            meta={"is_default": True},
        )
        db.add(default_project)
        db.commit()
        db.refresh(default_project)
        logger.info(f"Created default project: {default_project.id}")

    return {
        "id": str(default_project.id),
        "project_name": default_project.project_name,
        "project_code": default_project.project_code,
        "start_date": (
            default_project.start_date.isoformat()
            if default_project.start_date
            else None
        ),
        "completion_date": (
            default_project.completion_date.isoformat()
            if default_project.completion_date
            else None
        ),
        "meta": default_project.meta or {},
        "is_default": True,
    }


@wizard_router.post("/projects", status_code=201)
async def create_project(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Create new project"""

    # Get default admin user for project ownership
    default_user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not default_user:
        # Create admin user if doesn't exist
        from .security import hash_password
        from .models import UserRole

        default_user = User(
            email="admin@vericase.com",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)

    project_id = uuid.uuid4()  # Fixed: Use UUID object, not string

    # Generate default values if not provided
    project_name = (
        request.project_name or f"Project {datetime.now().strftime('%Y%m%d-%H%M')}"
    )
    project_code = request.project_code or f"PROJ-{uuid.uuid4().hex[:8].upper()}"

    project = Project(
        id=project_id,
        project_name=project_name,
        project_code=project_code,
        start_date=request.start_date,
        completion_date=request.completion_date,
        contract_type=request.contract_type,
        analysis_type=request.analysis_type,
        project_aliases=request.project_aliases,
        site_address=request.site_address,
        include_domains=request.include_domains,
        exclude_people=request.exclude_people,
        project_terms=request.project_terms,
        exclude_keywords=request.exclude_keywords,
        owner_user_id=default_user.id,
    )

    db.add(project)

    # Add stakeholders
    if request.stakeholders:
        for s in request.stakeholders:
            email_val = str(s.get("email", ""))
            email_domain = (
                email_val.split("@")[1] if email_val and "@" in str(email_val) else None
            )
            stakeholder = Stakeholder(
                project_id=project_id,
                case_id=None,  # Project-level stakeholder
                role=s.get("role", ""),
                name=s.get("name", ""),
                email=email_val,
                organization=s.get("organization"),
                email_domain=email_domain,
            )
            db.add(stakeholder)

    # Add keywords
    if request.keywords:
        for k in request.keywords:
            keyword = Keyword(
                project_id=project_id,
                case_id=None,
                keyword_name=k.get("name", ""),
                variations=k.get("variations"),
                is_regex=k.get("is_regex", False),
            )
            db.add(keyword)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        if "projects_project_code_key" in message:
            raise HTTPException(status_code=409, detail="Project code already exists")
        logger.error("Integrity error creating project %s: %s", project_id, message)
        raise HTTPException(status_code=400, detail="Invalid project data")
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail="Failed to create project")

    logger.info(f"Created project: {project_id}")

    # Inform if defaults were used
    auto_generated = []
    if not request.project_name:
        auto_generated.append("project name")
    if not request.project_code:
        auto_generated.append("project code")

    message = "Project created successfully"
    if auto_generated:
        message += f'. Auto-generated: {", ".join(auto_generated)}'

    return {
        "id": str(project_id),  # Convert UUID to string for JSON response
        "project_name": project_name,
        "project_code": project_code,
        "success": True,
        "message": message,
    }


@wizard_router.put("/projects/{project_id}")
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update project details (e.g. rename)"""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if request.project_name:
        project.project_name = request.project_name
    if request.project_code:
        project.project_code = request.project_code

    db.commit()
    db.refresh(project)

    return {
        "id": str(project.id),
        "name": project.project_name,
        "code": project.project_code,
        "status": "updated",
    }


@wizard_router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    """Delete a project and all associated data"""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    project = db.query(Project).filter(Project.id == p_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_name = project.project_name

    # Delete associated PST files records
    db.query(PSTFile).filter(PSTFile.project_id == p_uuid).delete()

    # Delete associated email messages
    db.query(EmailMessage).filter(EmailMessage.project_id == p_uuid).delete()

    # Delete the project itself
    db.delete(project)
    db.commit()

    return {
        "id": project_id,
        "name": project_name,
        "status": "deleted",
        "message": f"Project '{project_name}' and all associated data have been deleted",
    }


@wizard_router.post("/cases", status_code=201)
async def create_case(
    request: CaseCreateRequest,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Create new case"""

    # Get default admin user for case ownership
    default_user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not default_user:
        # Create admin user if doesn't exist
        from .security import hash_password
        from .models import UserRole

        default_user = User(
            email="admin@vericase.com",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )
        db.add(default_user)
        db.commit()
        db.refresh(default_user)

    # Create default company for open access
    company = db.query(Company).filter(Company.name == "Default Company").first()
    if not company:
        company = Company(name="Default Company")
        db.add(company)
        db.flush()

    case_uuid = uuid.uuid4()
    case_number = request.case_id_custom or f"CASE-{uuid.uuid4().hex[:10].upper()}"
    status_value = request.case_status or "active"

    case = Case(
        id=case_uuid,
        case_number=case_number,
        case_id_custom=request.case_id_custom,
        name=request.case_name or f"Case {datetime.now().strftime('%Y%m%d-%H%M')}",
        description=None,
        project_name=request.case_name,
        resolution_route=request.resolution_route,
        contract_type=request.resolution_route,
        claimant=request.claimant,
        defendant=request.defendant,
        client=request.client,
        status=status_value,
        case_status=status_value,
        legal_team=request.legal_team or [],
        heads_of_claim=request.heads_of_claim or [],
        deadlines=request.deadlines or [],
        owner_id=default_user.id,
        company_id=company.id,
    )
    db.add(case)
    db.flush()

    # Add stakeholders
    if request.stakeholders:
        for s in request.stakeholders:
            email_val = str(s.get("email", ""))
            email_domain = (
                email_val.split("@")[1] if email_val and "@" in str(email_val) else None
            )
            stakeholder = Stakeholder(
                case_id=case.id,
                project_id=None,
                role=s.get("role", ""),
                name=s.get("name", ""),
                email=email_val,
                organization=s.get("organization"),
                email_domain=email_domain,
            )
            db.add(stakeholder)

    # Add keywords
    if request.keywords:
        for k in request.keywords:
            keyword = Keyword(
                case_id=case.id,
                project_id=None,
                keyword_name=k.get("name", ""),
                variations=k.get("variations"),
                is_regex=k.get("is_regex", False),
            )
            db.add(keyword)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        logger.error("Integrity error creating case %s: %s", case_uuid, message)
        raise HTTPException(
            status_code=400, detail="Case could not be created (duplicate number?)"
        )
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create case %s: %s", case_uuid, exc)
        raise HTTPException(status_code=500, detail="Failed to create case")

    logger.info("Created case %s", case_uuid)

    # Inform if defaults were used
    auto_generated = []
    if not request.case_name:
        auto_generated.append("case name")

    message = "Case created successfully"
    if auto_generated:
        message += f'. Auto-generated: {", ".join(auto_generated)}'

    return {
        "id": str(case.id),
        "case_number": case.case_number,
        "case_name": case.name,
        "success": True,
        "message": message,
    }


def _get_entity_ids(
    profile_uuid: uuid.UUID, profile_type: str, db: Session
) -> tuple[str | None, str | None, str | None]:
    """Get case_id, project_id, and company_id for the given entity"""
    if profile_type == "case":
        case = db.query(Case).filter(Case.id == profile_uuid).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        return (
            str(case.id),
            None,
            str(case.company_id) if case.company_id is not None else None,
        )
    else:
        project = db.query(Project).filter(Project.id == profile_uuid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return (
            None,
            str(project.id),
            (
                str(project.owner_user_id)
                if getattr(project, "owner_user_id", None)
                else None
            ),
        )


async def _upload_file_to_storage(
    file: UploadFile, s3_key: str, content_type: str
) -> int:
    """Upload file to S3/MinIO and return file size"""
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    # Use S3_BUCKET for AWS compatibility
    bucket = settings.S3_BUCKET or settings.MINIO_BUCKET

    import logging

    logger = logging.getLogger(__name__)
    logger.info(f"[UPLOAD DEBUG] Starting upload to bucket={bucket}, key={s3_key}")
    logger.info(f"[UPLOAD DEBUG] MINIO_ACCESS_KEY={settings.MINIO_ACCESS_KEY}")
    logger.info(f"[UPLOAD DEBUG] MINIO_ENDPOINT={settings.MINIO_ENDPOINT}")
    logger.info(f"[UPLOAD DEBUG] USE_AWS_SERVICES={settings.USE_AWS_SERVICES}")

    s3_client = s3()
    if not s3_client:
        raise HTTPException(status_code=500, detail="S3 client not available")

    # Test connection first
    try:
        buckets = s3_client.list_buckets()
        logger.info(
            f"[UPLOAD DEBUG] list_buckets succeeded: {[b['Name'] for b in buckets.get('Buckets', [])]}"
        )
    except Exception as e:
        logger.error(f"[UPLOAD DEBUG] list_buckets failed: {type(e).__name__}: {e}")

    try:
        await asyncio.to_thread(
            s3_client.upload_fileobj,
            file.file,
            bucket,
            s3_key,
            ExtraArgs={"ContentType": content_type},
        )
    except Exception as e:
        logger.error(f"[UPLOAD ERROR] Failed to upload to {bucket}/{s3_key}: {e}")
        raise HTTPException(status_code=500, detail=f"S3 Upload failed: {str(e)}")

    return size


def _queue_processing_task(
    filename: str, document_id: str, case_id: str | None, company_id: str | None
) -> str:
    """Queue appropriate processing task and return status"""
    if filename.lower().endswith(".pst"):
        task_case_id = case_id if case_id else "00000000-0000-0000-0000-000000000000"
        _ = celery_app.send_task(
            "worker_app.worker.process_pst_file",
            args=[document_id, task_case_id, company_id or ""],
        )
        return "PROCESSING_PST"
    else:
        _ = celery_app.send_task("worker_app.worker.ocr_and_index", args=[document_id])
        return "QUEUED"


def _get_or_create_default_project(db: Session, user: User) -> Project:
    """Get or create a default project for uploads when no project is specified."""
    # Look for existing default project
    default_project = (
        db.query(Project).filter(Project.project_code == "DEFAULT").first()
    )

    if not default_project:
        # Create default project
        from datetime import date

        default_project = Project(
            project_name="Evidence Uploads",
            project_code="DEFAULT",
            start_date=date(2010, 1, 1),
            completion_date=date.today(),
            owner_user_id=None,
        )
        db.add(default_project)
        db.commit()
        db.refresh(default_project)
        logger.info(f"Created default project: {default_project.id}")

    return default_project


@wizard_router.post("/evidence/upload")
async def upload_evidence(
    profileId: str | None = Form(None),  # type: ignore[reportCallInDefaultInitializer]
    profileType: str = Form("project"),  # type: ignore[reportCallInDefaultInitializer]
    file: UploadFile = File(...),  # type: ignore[reportCallInDefaultInitializer]
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
    user: User = Depends(current_user),  # Use Admin Bypass from security.py
):
    """
    Simplified upload endpoint for wizard dashboard.
    Streams file directly to S3/MinIO and queues processing tasks.
    If no profileId is provided, uses/creates a default project automatically.
    """
    try:
        # --- SIMPLIFICATION: Robust Fallback for Single User ---
        # If IDs are missing or invalid, fallback to defaults instead of failing.
        
        # 1. Handle User
        if not user:
            # Fallback to default admin user
            logger.warning("No user provided, falling back to default admin")
            stmt = select(User).where(User.email == "admin@vericase.com")
            result = db.execute(stmt)
            default_user = result.scalar_one_or_none()
            if not default_user:
                 # Should be seeded by startup, but just in case
                 logger.error("Default admin user not found!")
                 raise HTTPException(status_code=500, detail="System configuration error: Default user missing")
        else:
            default_user = user

        # 2. Handle Profile ID (Project/Case)
        target_profile_id = profileId
        
        # If missing or invalid UUID, fallback to default project
        use_default = False
        if not target_profile_id or target_profile_id == "null" or target_profile_id == "undefined":
            use_default = True
        else:
            try:
                uuid.UUID(target_profile_id)
                # Verify it exists
                if profileType == "project":
                    stmt = select(Project).where(Project.id == target_profile_id)
                    if not db.execute(stmt).scalar_one_or_none():
                        logger.warning(f"Project {target_profile_id} not found, falling back")
                        use_default = True
                elif profileType == "case":
                    stmt = select(Case).where(Case.id == target_profile_id)
                    if not db.execute(stmt).scalar_one_or_none():
                        logger.warning(f"Case {target_profile_id} not found, falling back")
                        use_default = True
            except ValueError:
                logger.warning(f"Invalid UUID {target_profile_id}, falling back")
                use_default = True
        
        if use_default:
            logger.info("Using default project fallback")
            # Use known default project UUID
            default_project_id = "dbae0b15-8b63-46f7-bb2e-1b5a4de13ed8"
            # Ensure it exists (it should from startup)
            stmt = select(Project).where(Project.id == default_project_id)
            if not db.execute(stmt).scalar_one_or_none():
                 # Create it if missing (safety net)
                 logger.warning("Default project missing in DB, creating on fly")
                 default_project = _get_or_create_default_project(db, default_user)
                 target_profile_id = str(default_project.id)
            else:
                 target_profile_id = default_project_id
            profileType = "project"

        # Use the resolved ID
        profileId = target_profile_id
        profile_uuid = uuid.UUID(profileId)
        
        logger.info(f"Upload context resolved: User={default_user.id}, Profile={profileId} ({profileType})")
        # -------------------------------------------------------


        if not file or not file.filename:
            raise HTTPException(status_code=400, detail="Missing file")

        # Get entity IDs
        case_id, project_id, company_id = _get_entity_ids(profile_uuid, profileType, db)

        # Prepare S3 key
        safe_name = file.filename.replace(" ", "_")
        s3_key = f"uploads/{profileType}/{profileId}/{uuid.uuid4()}_{safe_name}"
        content_type = file.content_type or "application/octet-stream"

        # Upload file
        size = await _upload_file_to_storage(file, s3_key, content_type)

        # Record document metadata
        # Use S3_BUCKET for AWS compatibility
        bucket = settings.S3_BUCKET or settings.MINIO_BUCKET

        document = Document(
            filename=file.filename,
            path=f"{profileType}/{profileId}",
            content_type=content_type,
            size=size,
            bucket=bucket,
            s3_key=s3_key,
            status=DocStatus.NEW,
            owner_user_id=default_user.id,
            meta={
                "profile_type": profileType,
                "profile_id": profileId,
                "uploaded_by": str(default_user.id),
            },
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        # For PST files, also create a PSTFile record (worker expects this)
        pst_file_id = None
        if file.filename and file.filename.lower().endswith(".pst"):
            pst_file = PSTFile(
                filename=file.filename,
                case_id=case_id,
                project_id=project_id,
                s3_bucket=bucket,
                s3_key=s3_key,
                file_size_bytes=size,
                processing_status="pending",
                uploaded_by=default_user.id,
            )
            db.add(pst_file)
            db.commit()
            db.refresh(pst_file)
            pst_file_id = str(pst_file.id)
            logger.info(f"Created PSTFile record {pst_file_id} for {file.filename}")

        # Queue processing - use pst_file_id for PST files, document_id for others
        processing_id = pst_file_id if pst_file_id else str(document.id)
        processing_state = _queue_processing_task(
            file.filename, processing_id, case_id, company_id
        )

        return {
            "id": str(document.id),
            "status": processing_state,
            "case_id": case_id,
            "project_id": project_id,
            "s3_key": s3_key,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Detailed error in upload_evidence")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@wizard_router.post("/evidence/upload-bulk")
async def upload_evidence_bulk(
    profileId: str | None = Form(None),  # type: ignore[reportCallInDefaultInitializer]
    profileType: str = Form("project"),  # type: ignore[reportCallInDefaultInitializer]
    files: list[UploadFile] = File(...),  # type: ignore[reportCallInDefaultInitializer]
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
    user: User = Depends(current_user),  # Use Admin Bypass from security.py
):
    """
    Bulk upload endpoint for multiple email files (.eml, .msg).
    Parses emails directly and creates EmailMessage records in bulk.
    Much more efficient than uploading one file at a time.
    """
    try:
        # Get default admin user (from dependency)
        default_user = user

        # If no profileId provided, use default project
        if not profileId or profileId == "null" or profileId == "undefined":
            default_project = _get_or_create_default_project(db, default_user)
            profileId = str(default_project.id)
            profileType = "project"

        try:
            profile_uuid = uuid.UUID(profileId)
        except ValueError:
            default_project = _get_or_create_default_project(db, default_user)
            profileId = str(default_project.id)
            profile_uuid = default_project.id
            profileType = "project"

        # Get entity IDs
        case_id, project_id, _company_id = _get_entity_ids(
            profile_uuid, profileType, db
        )

        # Create a dummy PSTFile record for bulk uploads (required for EmailMessage foreign key)
        bucket = settings.S3_BUCKET or settings.MINIO_BUCKET
        pst_file = PSTFile(
            filename=f"bulk_upload_{uuid.uuid4().hex[:8]}.eml",
            case_id=case_id,
            project_id=project_id,
            s3_bucket=bucket,
            s3_key=f"bulk_uploads/{profileId}/{uuid.uuid4()}/emails",
            file_size_bytes=0,
            processing_status="completed",
            uploaded_by=default_user.id,
            total_emails=len(files),
            processed_emails=0,
        )
        db.add(pst_file)
        db.commit()
        db.refresh(pst_file)

        # Track results with explicit types
        success_count = 0
        failed_count = 0
        processed_emails: list[dict[str, Any]] = []
        error_list: list[dict[str, str]] = []

        for file in files:
            try:
                if not file.filename:
                    failed_count += 1
                    error_list.append({"file": "unknown", "error": "No filename"})
                    continue

                filename_lower = file.filename.lower()
                content = await file.read()

                # Parse email based on file type
                if filename_lower.endswith(".eml"):
                    email_data = _parse_eml_file(content)
                elif filename_lower.endswith(".msg"):
                    email_data = _parse_msg_file(content, file.filename)
                else:
                    # Store as regular file
                    s3_key = f"uploads/{profileType}/{profileId}/{uuid.uuid4()}_{file.filename}"
                    await _upload_bytes_to_storage(
                        content, s3_key, file.content_type or "application/octet-stream"
                    )
                    success_count += 1
                    continue

                if not email_data:
                    failed_count += 1
                    error_list.append(
                        {"file": file.filename, "error": "Failed to parse email"}
                    )
                    continue

                # Create EmailMessage record
                email_msg = EmailMessage(
                    pst_file_id=pst_file.id,
                    case_id=case_id,
                    project_id=project_id,
                    message_id=email_data.get("message_id"),
                    in_reply_to=email_data.get("in_reply_to"),
                    subject=email_data.get("subject"),
                    sender_email=email_data.get("sender_email"),
                    sender_name=email_data.get("sender_name"),
                    recipients_to=email_data.get("recipients_to", []),
                    recipients_cc=email_data.get("recipients_cc", []),
                    date_sent=email_data.get("date_sent"),
                    body_text=email_data.get("body_text"),
                    body_html=email_data.get("body_html"),
                    body_preview=email_data.get("body_preview"),
                    has_attachments=email_data.get("has_attachments", False),
                    importance=email_data.get("importance"),
                    pst_message_path=f"bulk_upload/{file.filename}",
                    meta={
                        "source": "bulk_upload",
                        "original_filename": file.filename,
                        "attachments": email_data.get("attachments", []),
                    },
                )
                db.add(email_msg)

                success_count += 1
                date_sent = email_data.get("date_sent")
                processed_emails.append(
                    {
                        "filename": file.filename,
                        "subject": email_data.get("subject"),
                        "sender": email_data.get("sender_email"),
                        "date": date_sent.isoformat() if date_sent else None,
                    }
                )

            except Exception as e:
                logger.error(f"Error processing {file.filename}: {e}")
                failed_count += 1
                error_list.append({"file": file.filename or "unknown", "error": str(e)})

        # Update PST file record with final count
        pst_file.processed_emails = success_count
        pst_file.total_emails = success_count
        db.commit()

        return {
            "total": len(files),
            "success": success_count,
            "failed": failed_count,
            "emails": processed_emails,
            "errors": error_list,
            "project_id": project_id,
            "pst_file_id": str(pst_file.id),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Detailed error in upload_evidence_bulk")
        raise HTTPException(status_code=500, detail=f"Bulk Upload failed: {str(e)}")


def _parse_eml_file(content: bytes) -> dict[str, Any] | None:
    """Parse .eml file content into email data"""
    import email
    from email.utils import parsedate_to_datetime, parseaddr
    from datetime import timezone

    try:
        msg = email.message_from_bytes(content)

        # Parse sender
        from_header = msg.get("From", "")
        sender_name, sender_email = parseaddr(from_header)

        # Parse recipients
        to_header = msg.get("To", "")
        recipients_to = [addr.strip() for addr in to_header.split(",") if addr.strip()]

        cc_header = msg.get("Cc", "")
        recipients_cc = [addr.strip() for addr in cc_header.split(",") if addr.strip()]

        # Parse date
        date_sent = None
        date_str = msg.get("Date")
        if date_str:
            try:
                date_sent = parsedate_to_datetime(date_str)
                if date_sent.tzinfo is None:
                    date_sent = date_sent.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Extract body
        body_text = None
        body_html = None

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain" and not body_text:
                    try:
                        body_text = part.get_payload(decode=True).decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        pass
                elif content_type == "text/html" and not body_html:
                    try:
                        body_html = part.get_payload(decode=True).decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        pass
        else:
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    text = payload.decode("utf-8", errors="replace")
                    if content_type == "text/html":
                        body_html = text
                    else:
                        body_text = text
            except Exception:
                pass

        # Check for attachments
        attachments = []
        has_attachments = False
        if msg.is_multipart():
            for part in msg.walk():
                disp = part.get_content_disposition()
                if disp == "attachment":
                    has_attachments = True
                    attachments.append(
                        {
                            "filename": part.get_filename() or "attachment",
                            "content_type": part.get_content_type(),
                            "size": len(part.get_payload(decode=True) or b""),
                        }
                    )

        return {
            "message_id": msg.get("Message-ID"),
            "in_reply_to": msg.get("In-Reply-To"),
            "subject": msg.get("Subject"),
            "sender_email": sender_email or from_header,
            "sender_name": sender_name,
            "recipients_to": recipients_to,
            "recipients_cc": recipients_cc,
            "date_sent": date_sent,
            "body_text": body_text,
            "body_html": body_html,
            "body_preview": (body_text or "")[:500] if body_text else None,
            "has_attachments": has_attachments,
            "attachments": attachments,
            "importance": msg.get("Importance") or msg.get("X-Priority"),
        }

    except Exception as e:
        logger.error(f"Error parsing EML: {e}")
        return None


def _parse_msg_file(content: bytes, filename: str) -> dict[str, Any] | None:
    """Parse .msg file content into email data"""
    try:
        # Try using extract_msg if available
        import extract_msg  # type: ignore[import-not-found]
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix=".msg") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            msg = extract_msg.Message(tmp_path)

            date_sent = None
            if msg.date:
                from datetime import timezone

                date_sent = msg.date
                if date_sent.tzinfo is None:
                    date_sent = date_sent.replace(tzinfo=timezone.utc)

            # Extract recipients - handle different formats
            to_list: list[str] = []
            if msg.to:
                if isinstance(msg.to, str):
                    to_list = [msg.to]
                elif hasattr(msg.to, "__iter__"):
                    to_list = [
                        r.email if hasattr(r, "email") else str(r) for r in msg.to
                    ]

            cc_list: list[str] = []
            if msg.cc:
                if isinstance(msg.cc, str):
                    cc_list = [msg.cc]
                elif hasattr(msg.cc, "__iter__"):
                    cc_list = [
                        r.email if hasattr(r, "email") else str(r) for r in msg.cc
                    ]

            # Extract attachments
            attachments: list[dict[str, Any]] = []
            has_attachments = False
            if msg.attachments:
                has_attachments = len(msg.attachments) > 0
                for a in msg.attachments:
                    att_name = getattr(a, "longFilename", None) or getattr(
                        a, "shortFilename", "attachment"
                    )
                    att_data = getattr(a, "data", None)
                    attachments.append(
                        {"filename": att_name, "size": len(att_data) if att_data else 0}
                    )

            return {
                "message_id": getattr(msg, "messageId", None),
                "in_reply_to": getattr(msg, "inReplyTo", None),
                "subject": msg.subject,
                "sender_email": msg.sender,
                "sender_name": getattr(msg, "senderName", None),
                "recipients_to": to_list,
                "recipients_cc": cc_list,
                "date_sent": date_sent,
                "body_text": msg.body,
                "body_html": getattr(msg, "htmlBody", None),
                "body_preview": (msg.body or "")[:500],
                "has_attachments": has_attachments,
                "attachments": attachments,
                "importance": getattr(msg, "importance", None),
            }
        finally:
            os.unlink(tmp_path)

    except ImportError:
        # Fallback: just extract basic info from filename
        logger.warning("extract_msg not available, using fallback")
        return {
            "message_id": None,
            "subject": filename.replace(".msg", ""),
            "sender_email": "unknown",
            "recipients_to": [],
            "recipients_cc": [],
            "date_sent": None,
            "body_text": f"MSG file: {filename} (parsing requires extract_msg library)",
            "body_html": None,
            "body_preview": f"MSG file: {filename}",
            "has_attachments": False,
            "attachments": [],
        }
    except Exception as e:
        logger.error(f"Error parsing MSG file {filename}: {e}")
        return None


async def _upload_bytes_to_storage(
    content: bytes, s3_key: str, content_type: str
) -> int:
    """Upload bytes directly to S3/MinIO storage"""
    # Use S3_BUCKET for AWS, MINIO_BUCKET for local
    bucket = settings.S3_BUCKET or settings.MINIO_BUCKET

    try:
        s3.put_object(  # type: ignore[union-attr]
            Bucket=bucket, Key=s3_key, Body=content, ContentType=content_type
        )
        return len(content)
    except Exception as e:
        logger.error(f"Error uploading to storage: {e}")
        raise


# ========================================
# UNIFIED ENDPOINTS (Work with both Projects and Cases)
# ========================================


@unified_router.get("/{entity_id}/evidence")
async def get_unified_evidence(
    entity_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get evidence/emails for either a project or case"""
    # Try to find as case first
    case = db.query(Case).filter(Case.id == entity_id).first()  # type: ignore[reportGeneralTypeIssues]
    if case:
        # Ownership check - disabled for admin auto-login
        # if case.owner_id != user.id:
        #     # Also check if user is part of the case's company if applicable
        #     if case.company_id is not None:
        #         user_company = db.query(UserCompany).filter(
        #             UserCompany.user_id == user.id,  # type: ignore[reportGeneralTypeIssues]
        #             UserCompany.company_id == case.company_id # type: ignore[reportGeneralTypeIssues]
        #         ).first()
        #         if not user_company and user.role != UserRole.ADMIN:
        #             raise HTTPException(status_code=403, detail="Not authorized to access this case")
        #     elif user.role != UserRole.ADMIN:
        #         raise HTTPException(status_code=403, detail="Not authorized to access this case")
        pass  # Allow all access

        # Use existing case evidence logic
        emails = (
            db.query(EmailMessage)
            .filter(
                EmailMessage.case_id == entity_id  # type: ignore[reportGeneralTypeIssues]
            )
            .order_by(EmailMessage.date_sent.desc())
            .all()
        )
    else:
        # Try as project
        project = db.query(Project).filter(Project.id == entity_id).first()  # type: ignore[reportGeneralTypeIssues]
        if not project:
            raise HTTPException(status_code=404, detail="Entity not found")

        # Ownership check - allow admin or owner
        # Since we auto-create admin user, this should always pass
        # if project.owner_user_id != user.id and user.role != UserRole.ADMIN:
        #     raise HTTPException(status_code=403, detail="Not authorized to access this project")

        # Get emails associated with project
        emails = (
            db.query(EmailMessage)
            .filter(
                EmailMessage.project_id == entity_id  # type: ignore[reportGeneralTypeIssues]
            )
            .order_by(EmailMessage.date_sent.desc())
            .all()
        )

    def _format_recipients(recipients: list[Any] | None) -> str:
        if not recipients:
            return ""
        if not isinstance(recipients, list):
            # Handle single string value
            if isinstance(recipients, str):
                return recipients.strip()
            return ""
        formatted: list[str] = []
        for recipient in recipients:
            if isinstance(recipient, str):
                # Plain string format (e.g., "John Smith" or "john@example.com")
                if recipient.strip():
                    formatted.append(recipient.strip())
            elif isinstance(recipient, dict):
                # Dict format with email/name keys
                email_addr = recipient.get("email") or recipient.get("address") or ""
                name = recipient.get("name") or recipient.get("display_name") or ""
                if email_addr and name:
                    formatted.append(f"{name} <{email_addr}>")
                elif email_addr:
                    formatted.append(email_addr)
                elif name:
                    formatted.append(name)
        return ", ".join([item for item in formatted if item])

    # Get attachments for all emails
    email_ids = [email.id for email in emails]
    attachments_by_email: dict[Any, list[dict[str, Any]]] = {}

    if email_ids:
        # Query all attachments for these emails
        attachments = (
            db.query(EmailAttachment)
            .filter(EmailAttachment.email_message_id.in_(email_ids))
            .all()
        )

        # Group by email_message_id
        for att in attachments:
            email_msg_id = att.email_message_id
            if email_msg_id not in attachments_by_email:
                attachments_by_email[email_msg_id] = []
            attachments_by_email[email_msg_id].append(
                {
                    "id": str(att.id),
                    "filename": att.filename,
                    "size": att.file_size_bytes,
                    "content_type": att.content_type,
                    "s3_bucket": att.s3_bucket,
                    "s3_key": att.s3_key,
                }
            )

    return [
        {
            "id": str(email.id),
            # Map to expected field names for correspondence view
            "email_subject": email.subject or "",
            "email_from": (
                email.sender_email
                if email.sender_email is not None
                else email.sender_name or "Unknown"
            ),
            "email_to": _format_recipients(email.recipients_to),
            "email_cc": _format_recipients(email.recipients_cc),
            "email_date": (
                email.date_sent.isoformat() if email.date_sent is not None else None
            ),
            # Include full content
            "content": (
                email.body_html
                if email.body_html is not None
                else email.body_text or ""
            ),
            "body": email.body_text or "",
            "meta": {
                "content": (
                    email.body_html
                    if email.body_html is not None
                    else email.body_text or ""
                ),
                "content_type": "html" if email.body_html is not None else "text",
                "importance": email.importance,
                "has_attachments": bool(attachments_by_email.get(email.id, [])),
                "attachments": attachments_by_email.get(email.id, []),
            },
            # Additional fields for compatibility
            "sender_name": email.sender_name,
            "recipients_to": email.recipients_to,
            "recipients_cc": email.recipients_cc,
            "date_sent": (
                email.date_sent.isoformat() if email.date_sent is not None else None
            ),
            "body_text": email.body_text,
            "body_html": email.body_html,
            "importance": email.importance,
            "has_attachments": bool(attachments_by_email.get(email.id, [])),
            "attachments": attachments_by_email.get(email.id, []),
            "pst_file_id": (
                str(email.pst_file_id) if email.pst_file_id is not None else None
            ),
            "matched_stakeholders": email.matched_stakeholders,  # type: ignore[reportArgumentType]
            "matched_keywords": email.matched_keywords,  # type: ignore[reportArgumentType]
            "thread_id": getattr(email, "thread_id", None),
        }
        for email in emails
    ]


@unified_router.get("/{entity_id}")
async def get_unified_entity(
    entity_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get details for either a project or case"""
    # Try to find as case first
    case = db.query(Case).filter(Case.id == entity_id).first()  # type: ignore[reportGeneralTypeIssues]
    if case:
        # Ownership check disabled - auto-admin has full access
        # if case.owner_id != user.id:
        #     if case.company_id is not None:
        #         user_company = db.query(UserCompany).filter(
        #             UserCompany.user_id == user.id,
        #             UserCompany.company_id == case.company_id
        #         ).first()
        #         if not user_company and user.role != UserRole.ADMIN:
        #             raise HTTPException(status_code=403, detail="Not authorized to access this case")
        #     elif user.role != UserRole.ADMIN:
        #         raise HTTPException(status_code=403, detail="Not authorized to access this case")

        return {
            "id": str(case.id),
            "type": "case",
            "name": case.name or case.case_number,
            "case_number": case.case_number,
            "status": case.status,
            "created_at": case.created_at.isoformat() if case.created_at else None,
        }

    # Try as project
    project = db.query(Project).filter(Project.id == entity_id).first()  # type: ignore[reportGeneralTypeIssues]
    if project:
        # Ownership check disabled - auto-admin has full access
        # if project.owner_user_id != user.id and user.role != UserRole.ADMIN:
        #     raise HTTPException(status_code=403, detail="Not authorized to access this project")
        pass  # Allow all access

        return {
            "id": str(project.id),
            "type": "project",
            "name": project.project_name,
            "project_code": project.project_code,
            "status": "active",  # Projects don't have status field
            "created_at": (
                project.created_at.isoformat()
                if hasattr(project, "created_at") and project.created_at
                else None
            ),
        }

    raise HTTPException(status_code=404, detail="Entity not found")


@unified_router.get("/{entity_id}/stakeholders")
async def get_unified_stakeholders(
    entity_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get stakeholders for either a project or case"""
    # Check if it's a case
    stakeholders = db.query(Stakeholder).filter(Stakeholder.case_id == entity_id).all()  # type: ignore[reportGeneralTypeIssues]

    # If no case stakeholders, try project
    if not stakeholders:
        stakeholders = db.query(Stakeholder).filter(Stakeholder.project_id == entity_id).all()  # type: ignore[reportGeneralTypeIssues]

    return [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization,
        }
        for s in stakeholders
    ]


@unified_router.get("/{entity_id}/keywords")
async def get_unified_keywords(
    entity_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """Get keywords for either a project or case"""
    # Check if it's a case
    keywords = db.query(Keyword).filter(Keyword.case_id == entity_id).all()  # type: ignore[reportGeneralTypeIssues]

    # If no case keywords, try project
    if not keywords:
        keywords = db.query(Keyword).filter(Keyword.project_id == entity_id).all()  # type: ignore[reportGeneralTypeIssues]

    return [
        {"id": str(k.id), "name": k.keyword_name, "variations": k.variations}
        for k in keywords
    ]


# ============================================================================
# Data Management & Background Tasks
# ============================================================================

@router.delete("/projects/{project_id}/clear-emails")
async def clear_project_emails(
    project_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Clear all emails and PST files for a project.
    This allows you to re-upload fresh PST data.
    """
    try:
        proj_uuid = uuid.UUID(project_id)

        # Delete all email messages for this project
        deleted_emails = db.query(EmailMessage).filter(EmailMessage.project_id == proj_uuid).delete()

        # Delete all email attachments for this project
        deleted_attachments = db.query(EmailAttachment).filter(
            EmailAttachment.project_id == proj_uuid
        ).delete()

        # Delete all PST files for this project
        deleted_psts = db.query(PSTFile).filter(PSTFile.project_id == proj_uuid).delete()

        db.commit()

        logger.info(
            f"Cleared project {project_id}: {deleted_emails} emails, "
            f"{deleted_attachments} attachments, {deleted_psts} PST files"
        )

        return {
            "status": "success",
            "message": "All email data cleared for project",
            "deleted": {
                "emails": deleted_emails,
                "attachments": deleted_attachments,
                "pst_files": deleted_psts,
            }
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to clear project emails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/index-semantic")
async def trigger_semantic_indexing_project(
    project_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Manually trigger semantic indexing for all emails in a project.
    Returns task ID for tracking progress.
    """
    try:
        # Verify project exists
        project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Queue the indexing task
        from .tasks import index_project_emails_semantic
        task = index_project_emails_semantic.delay(project_id)

        return {
            "status": "queued",
            "task_id": task.id,
            "message": "Semantic indexing task queued",
            "check_status_url": f"/api/correspondence/tasks/{task.id}/status"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to queue semantic indexing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cases/{case_id}/index-semantic")
async def trigger_semantic_indexing_case(
    case_id: str,
    db: Session = Depends(get_db),  # type: ignore[reportCallInDefaultInitializer]
):
    """
    Manually trigger semantic indexing for all emails in a case.
    Returns task ID for tracking progress.
    """
    try:
        # Verify case exists
        case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Queue the indexing task
        from .tasks import index_case_emails_semantic
        task = index_case_emails_semantic.delay(case_id)

        return {
            "status": "queued",
            "task_id": task.id,
            "message": "Semantic indexing task queued",
            "check_status_url": f"/api/correspondence/tasks/{task.id}/status"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to queue semantic indexing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    """
    Check the status of a background task (e.g., semantic indexing).
    
    Returns:
        - status: PENDING, PROGRESS, SUCCESS, FAILURE
        - result: Task result if completed
        - info: Progress information if in progress
    """
    try:
        from celery.result import AsyncResult
        
        task = AsyncResult(task_id, app=celery_app)
        
        if task.state == 'PENDING':
            response = {
                'status': task.state,
                'message': 'Task is waiting to start'
            }
        elif task.state == 'PROGRESS':
            response = {
                'status': task.state,
                'current': task.info.get('current', 0),
                'total': task.info.get('total', 0),
                'percent': task.info.get('percent', 0),
                'indexed': task.info.get('indexed', 0),
            }
        elif task.state == 'SUCCESS':
            response = {
                'status': task.state,
                'result': task.result,
                'message': 'Task completed successfully'
            }
        elif task.state == 'FAILURE':
            response = {
                'status': task.state,
                'error': str(task.info),
                'message': 'Task failed'
            }
        else:
            response = {
                'status': task.state,
                'info': str(task.info)
            }
        
        return response
        
    except Exception as e:
        logger.exception(f"Failed to get task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
