# pyright: reportCallInDefaultInitializer=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""
Correspondence API Routes
"""

from typing import Annotated
import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    Body,
)
from sqlalchemy.orm import Session

from ..security import current_user, get_db
from ..models import User
from .services import (
    upload_pst_file_service,
    init_pst_upload_service,
    init_pst_multipart_upload_service,
    get_pst_multipart_part_url_service,
    complete_pst_multipart_upload_service,
    start_pst_processing_service,
    get_pst_status_service,
    list_pst_files_service,
    list_emails_service,
    admin_cleanup_pst_service,
)
from .utils import (
    PSTUploadInitRequest,
    PSTUploadInitResponse,
    PSTMultipartInitRequest,
    PSTMultipartInitResponse,
    PSTMultipartPartResponse,
    PSTMultipartCompleteRequest,
    PSTProcessingStatus,
    PSTFileListResponse,
    EmailListResponse,
)
from ..search import search_emails
import logging

logger = logging.getLogger("vericase")

router = APIRouter(prefix="/api/correspondence", tags=["correspondence"])


@router.post("/pst/upload")
async def upload_pst_file(
    file: Annotated[UploadFile, File(...)],
    case_id: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return await upload_pst_file_service(file, case_id, project_id, db, user)


@router.post("/pst/upload/init", response_model=PSTUploadInitResponse)
async def init_pst_upload(
    request: PSTUploadInitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return await init_pst_upload_service(request, db, user)


@router.post("/pst/upload/multipart/init", response_model=PSTMultipartInitResponse)
async def init_pst_multipart_upload(
    request: PSTMultipartInitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return await init_pst_multipart_upload_service(request, db, user)


@router.get("/pst/upload/multipart/part", response_model=PSTMultipartPartResponse)
async def get_pst_multipart_part_url(
    pst_file_id: str = Query(..., description="PST file ID"),
    upload_id: str = Query(..., description="Multipart upload ID"),
    part_number: int = Query(..., ge=1, le=10000, description="Part number (1-10000)"),
    db: Session = Depends(get_db),
):
    return await get_pst_multipart_part_url_service(
        pst_file_id, upload_id, part_number, db
    )


@router.post("/pst/upload/multipart/complete")
async def complete_pst_multipart_upload(
    request: PSTMultipartCompleteRequest,
    db: Session = Depends(get_db),
):
    return await complete_pst_multipart_upload_service(request, db)


@router.post("/pst/{pst_file_id}/process")
async def start_pst_processing(
    pst_file_id: str,
    db: Session = Depends(get_db),
):
    return await start_pst_processing_service(pst_file_id, db)


@router.get("/pst/{pst_file_id}/status", response_model=PSTProcessingStatus)
async def get_pst_status(
    pst_file_id: str,
    db: Session = Depends(get_db),
):
    return await get_pst_status_service(pst_file_id, db)


@router.get("/pst/files", response_model=PSTFileListResponse)
async def list_pst_files(
    project_id: Annotated[
        uuid.UUID | None, Query(description="Filter by project ID")
    ] = None,
    case_id: Annotated[uuid.UUID | None, Query(description="Filter by case ID")] = None,
    status: Annotated[
        str | None, Query(description="Filter by processing status")
    ] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return await list_pst_files_service(
        project_id, case_id, status, page, page_size, db
    )


@router.get("/emails", response_model=EmailListResponse)
async def list_emails(
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(5000, ge=1, le=50000),
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
    status_filter: Annotated[
        str | None, Query(description="Filter by status tag")
    ] = None,
    include_hidden: Annotated[bool, Query(description="Include ALL emails")] = False,
    db: Session = Depends(get_db),
):
    return await list_emails_service(
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
    )


@router.get("/emails/search")
async def search_emails_endpoint(
    query: str,
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    sender: Annotated[str | None, Query(description="Filter by sender")] = None,
    recipient: Annotated[str | None, Query(description="Filter by recipient")] = None,
    date_from: Annotated[
        str | None, Query(description="Date from (ISO format)")
    ] = None,
    date_to: Annotated[str | None, Query(description="Date to (ISO format)")] = None,
    has_attachments: Annotated[
        bool | None, Query(description="Filter by attachments")
    ] = None,
    size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Full-text search for emails using OpenSearch.
    """
    try:
        results = search_emails(
            query=query,
            size=size,
            case_id=case_id,
            project_id=project_id,
            sender=sender,
            recipient=recipient,
            date_from=date_from,
            date_to=date_to,
            has_attachments=has_attachments,
        )

        hits = results.get("hits", {}).get("hits", [])
        return {
            "total": results.get("hits", {}).get("total", {}).get("value", 0),
            "items": [
                {
                    "id": hit["_id"],
                    "score": hit["_score"],
                    "subject": hit["_source"].get("subject"),
                    "sender": hit["_source"].get("sender_email"),
                    "date": hit["_source"].get("date_sent"),
                    "preview": (hit.get("highlight", {}).get("body") or [""])[0],
                    "has_attachments": hit["_source"].get("has_attachments"),
                }
                for hit in hits
            ],
        }
    except Exception as e:
        logger.error(f"Search endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Search failed")


# NOTE: the advanced correspondence endpoints (server-side grid, thread, attachments,
# spam filter, etc.) are currently not wired up in this slimmed-down router.
# We keep the core PST upload/status/list + admin cleanup endpoints.


@router.post("/pst/admin/cleanup")
async def admin_cleanup_pst(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Admin: cleanup duplicate/failed/stuck PSTs for a project/case.

    Body keys (all optional except project_id/case_id):
      project_id, case_id, stuck_hours, include_failed, include_stuck,
      include_duplicates, filename_contains, apply

    Default behavior is DRY-RUN unless apply=true.
    """
    return await admin_cleanup_pst_service(body, db, user)


@router.get("/notifications")
async def get_notifications(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """
    Get recent notifications for the current user.
    This is a simple polling endpoint. In a real production app, use WebSockets.
    """
    # For MVP, we'll just return recent activity logs as notifications
    from ..models import EvidenceActivityLog

    logs = (
        db.query(EvidenceActivityLog)
        .filter(EvidenceActivityLog.user_id == user.id)
        .order_by(EvidenceActivityLog.created_at.desc())
        .limit(10)
        .all()
    )

    return [
        {
            "id": str(log.id),
            "message": f"Action '{log.action}' completed",
            "timestamp": log.created_at.isoformat(),
            "details": log.action_details,
            "read": False,
        }
        for log in logs
    ]
