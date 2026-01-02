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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import io
import csv
from sqlalchemy.orm import Session

from ..csrf import verify_csrf_token
from ..security import current_user, get_db
from ..models import User, EmailMessage, Stakeholder, Keyword
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
    admin_rescue_pst_service,
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
    ServerSideRequest,
    ServerSideResponse,
    EmailMessageDetail,
    build_correspondence_hard_exclusion_filter,
    build_correspondence_visibility_filter,
)
from ..search import search_emails, client as os_client
import logging

logger = logging.getLogger("vericase")

router = APIRouter(prefix="/api/correspondence", tags=["correspondence"])


def _safe_uuid(value: str | None, label: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {label} format")


class BulkEmailIdsRequest(BaseModel):
    email_ids: list[str] = Field(..., min_length=1)
    case_id: str | None = None
    project_id: str | None = None


class BulkExcludeRequest(BulkEmailIdsRequest):
    excluded: bool = True
    reason: str | None = None


class BulkSetCategoryRequest(BulkEmailIdsRequest):
    category: str = Field(..., min_length=1, max_length=100)


class BulkAddKeywordsRequest(BulkEmailIdsRequest):
    keyword_ids: list[str] = Field(..., min_length=1)


class ExportEmailsRequest(BulkEmailIdsRequest):
    include_body: bool = False


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


@router.post("/pst/{pst_file_id}/admin/rescue")
async def admin_rescue_pst(
    pst_file_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Admin: finalize/fail a PST without re-upload.

    Body:
      action: "finalize" | "fail" (default "finalize")
      force: bool (default false)
      reason: str (only used for action="fail")
    """
    return await admin_rescue_pst_service(pst_file_id, body, db, user)


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


@router.post("/emails/server-side", response_model=ServerSideResponse)
async def list_emails_server_side(
    request: ServerSideRequest,
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    search: Annotated[
        str | None, Query(description="Search in subject/body/sender")
    ] = None,
    stakeholder_id: Annotated[
        str | None, Query(description="Filter by stakeholder (server-side)")
    ] = None,
    keyword_id: Annotated[
        str | None, Query(description="Filter by keyword (server-side)")
    ] = None,
    include_hidden: Annotated[
        bool, Query(description="Include excluded/hidden emails")
    ] = False,
    db: Session = Depends(get_db),
):
    # NOTE: This endpoint is used by the Correspondence Enterprise AG Grid server-side row model.
    from .services import list_emails_server_side_service

    return await list_emails_server_side_service(
        request=request,
        case_id=case_id,
        project_id=project_id,
        search=search,
        stakeholder_id=stakeholder_id,
        keyword_id=keyword_id,
        include_hidden=include_hidden,
        db=db,
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


@router.get("/stakeholders")
async def list_stakeholders(
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List stakeholders (id + display fields) for filter UI."""

    q = db.query(Stakeholder)
    case_uuid = _safe_uuid(case_id, "case_id")
    project_uuid = _safe_uuid(project_id, "project_id")
    if case_uuid:
        q = q.filter(Stakeholder.case_id == case_uuid)
    if project_uuid:
        q = q.filter(Stakeholder.project_id == project_uuid)

    items = q.order_by(Stakeholder.name.asc()).limit(5000).all()
    return {
        "items": [
            {
                "id": str(s.id),
                "name": s.name,
                "role": s.role,
                "email": s.email,
                "organization": s.organization,
            }
            for s in items
        ]
    }


@router.get("/keywords")
async def list_keywords(
    case_id: Annotated[str | None, Query(description="Case ID")] = None,
    project_id: Annotated[str | None, Query(description="Project ID")] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List keywords (id + name) for filter UI."""

    q = db.query(Keyword)
    case_uuid = _safe_uuid(case_id, "case_id")
    project_uuid = _safe_uuid(project_id, "project_id")
    if case_uuid:
        q = q.filter(Keyword.case_id == case_uuid)
    if project_uuid:
        q = q.filter(Keyword.project_id == project_uuid)

    items = q.order_by(Keyword.keyword_name.asc()).limit(5000).all()
    return {
        "items": [
            {
                "id": str(k.id),
                "name": k.keyword_name,
                "definition": k.definition,
                "variations": k.variations,
                "is_regex": bool(k.is_regex),
            }
            for k in items
        ]
    }


@router.get("/emails/{email_id}/similar")
async def get_similar_emails(
    email_id: str,
    size: int = Query(25, ge=1, le=200),
    include_hidden: Annotated[
        bool, Query(description="Include excluded/hidden emails")
    ] = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Content-based similarity using OpenSearch `more_like_this`.

    We fetch candidate IDs from OpenSearch, then hydrate via DB and apply
    visibility rules server-side.
    """

    email_uuid = _safe_uuid(email_id, "email_id")
    if not email_uuid:
        raise HTTPException(400, "Invalid email_id format")

    # Use DB row to apply scoping filters and optionally boost duplicates.
    email = db.query(EmailMessage).filter(EmailMessage.id == email_uuid).first()
    if not email:
        raise HTTPException(404, "Email not found")

    filters: list[dict] = []
    if email.case_id:
        filters.append({"term": {"case_id": str(email.case_id)}})
    if email.project_id:
        filters.append({"term": {"project_id": str(email.project_id)}})

    should: list[dict] = [
        {
            "more_like_this": {
                "fields": ["body_clean", "subject"],
                "like": [{"_index": "emails", "_id": str(email.id)}],
                "min_term_freq": 1,
                "min_doc_freq": 1,
                "max_query_terms": 25,
            }
        }
    ]
    if email.content_hash:
        should.append({"term": {"content_hash": email.content_hash}})

    dsl = {
        "size": min(500, max(size * 5, size)),
        "query": {
            "bool": {
                "should": should,
                "minimum_should_match": 1,
                "filter": filters,
                "must_not": [{"term": {"id": str(email.id)}}],
            }
        },
        "_source": [
            "id",
            "subject",
            "sender_email",
            "sender_name",
            "date_sent",
            "has_attachments",
            "content_hash",
        ],
    }

    try:
        results = os_client().search(index="emails", body=dsl)
    except Exception as e:
        logger.warning("Similar emails search failed (OpenSearch unavailable?): %s", e)
        return {"items": [], "total": 0, "note": "Similarity search unavailable"}

    hits = results.get("hits", {}).get("hits", [])
    score_by_id: dict[str, float] = {}
    for h in hits:
        _id = str(h.get("_id"))
        if _id:
            score_by_id[_id] = float(h.get("_score") or 0.0)

    candidate_ids = list(score_by_id.keys())
    if not candidate_ids:
        return {"items": [], "total": 0}

    q = db.query(EmailMessage).filter(EmailMessage.id.in_(candidate_ids))
    q = q.filter(build_correspondence_hard_exclusion_filter())
    if not include_hidden:
        q = q.filter(build_correspondence_visibility_filter())

    # Preserve OpenSearch ordering.
    by_id = {str(e.id): e for e in q.all()}
    ordered = [by_id[i] for i in candidate_ids if i in by_id]
    ordered = ordered[:size]

    return {
        "items": [
            {
                "id": str(e.id),
                "score": score_by_id.get(str(e.id), 0.0),
                "subject": e.subject,
                "sender_email": e.sender_email,
                "sender_name": e.sender_name,
                "date_sent": e.date_sent.isoformat() if e.date_sent else None,
                "has_attachments": bool(e.has_attachments),
                "content_hash": e.content_hash,
            }
            for e in ordered
        ],
        "total": len(ordered),
    }


@router.post("/emails/bulk/exclude")
async def bulk_exclude_emails(
    payload: BulkExcludeRequest,
    _: None = Depends(verify_csrf_token),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Bulk exclude/include selected emails by updating `meta.status`."""

    email_ids = list({e for e in (payload.email_ids or []) if e})
    if not email_ids:
        raise HTTPException(400, "email_ids is required")

    q = db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids))
    case_uuid = _safe_uuid(payload.case_id, "case_id")
    project_uuid = _safe_uuid(payload.project_id, "project_id")
    if case_uuid:
        q = q.filter(EmailMessage.case_id == case_uuid)
    if project_uuid:
        q = q.filter(EmailMessage.project_id == project_uuid)

    rows = q.all()
    updated = 0
    for e in rows:
        meta = e.meta if isinstance(e.meta, dict) else {}
        status = "excluded" if payload.excluded else "active"
        updated_meta = {
            **meta,
            "status": status,
        }
        if payload.reason:
            updated_meta["user_exclude_reason"] = payload.reason
        updated_meta["user_exclude_by"] = str(user.id)
        updated_meta["user_exclude_at"] = datetime.utcnow().isoformat()
        e.meta = updated_meta
        updated += 1

    db.commit()
    return {"updated": updated}


@router.post("/emails/bulk/set-category")
async def bulk_set_category(
    payload: BulkSetCategoryRequest,
    _: None = Depends(verify_csrf_token),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Bulk set a user category for selected emails (stored in `meta.user_category`)."""

    email_ids = list({e for e in (payload.email_ids or []) if e})
    if not email_ids:
        raise HTTPException(400, "email_ids is required")

    q = db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids))
    case_uuid = _safe_uuid(payload.case_id, "case_id")
    project_uuid = _safe_uuid(payload.project_id, "project_id")
    if case_uuid:
        q = q.filter(EmailMessage.case_id == case_uuid)
    if project_uuid:
        q = q.filter(EmailMessage.project_id == project_uuid)

    rows = q.all()
    updated = 0
    for e in rows:
        meta = e.meta if isinstance(e.meta, dict) else {}
        e.meta = {
            **meta,
            "user_category": payload.category,
            "user_category_by": str(user.id),
            "user_category_at": datetime.utcnow().isoformat(),
        }
        updated += 1

    db.commit()
    return {"updated": updated}


@router.post("/emails/bulk/add-keywords")
async def bulk_add_keywords(
    payload: BulkAddKeywordsRequest,
    _: None = Depends(verify_csrf_token),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Bulk add keyword IDs to EmailMessage.matched_keywords (JSONB array)."""

    email_ids = list({e for e in (payload.email_ids or []) if e})
    keyword_ids = [k for k in (payload.keyword_ids or []) if k]
    if not email_ids:
        raise HTTPException(400, "email_ids is required")
    if not keyword_ids:
        raise HTTPException(400, "keyword_ids is required")

    q = db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids))
    case_uuid = _safe_uuid(payload.case_id, "case_id")
    project_uuid = _safe_uuid(payload.project_id, "project_id")
    if case_uuid:
        q = q.filter(EmailMessage.case_id == case_uuid)
    if project_uuid:
        q = q.filter(EmailMessage.project_id == project_uuid)

    rows = q.all()
    updated = 0
    for e in rows:
        existing = e.matched_keywords if isinstance(e.matched_keywords, list) else []
        merged = list({*existing, *keyword_ids})
        e.matched_keywords = merged
        updated += 1

        # Track who/when in meta (optional, but useful for audit).
        meta = e.meta if isinstance(e.meta, dict) else {}
        e.meta = {
            **meta,
            "user_keywords_by": str(user.id),
            "user_keywords_at": datetime.utcnow().isoformat(),
        }

    db.commit()
    return {"updated": updated}


@router.post("/emails/export")
async def export_emails_csv(
    payload: ExportEmailsRequest,
    _: None = Depends(verify_csrf_token),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Export selected emails to CSV (server-generated)."""

    email_ids = list({e for e in (payload.email_ids or []) if e})
    if not email_ids:
        raise HTTPException(400, "email_ids is required")

    q = db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids))
    case_uuid = _safe_uuid(payload.case_id, "case_id")
    project_uuid = _safe_uuid(payload.project_id, "project_id")
    if case_uuid:
        q = q.filter(EmailMessage.case_id == case_uuid)
    if project_uuid:
        q = q.filter(EmailMessage.project_id == project_uuid)

    rows = q.order_by(EmailMessage.date_sent.asc().nullslast()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        "id",
        "date_sent",
        "subject",
        "sender_email",
        "sender_name",
        "recipients_to",
        "recipients_cc",
        "has_attachments",
        "content_hash",
        "user_category",
        "status",
    ]
    if payload.include_body:
        headers.append("body_text_clean")
    writer.writerow(headers)

    for e in rows:
        meta = e.meta if isinstance(e.meta, dict) else {}
        status = meta.get("status")
        user_category = meta.get("user_category")
        row = [
            str(e.id),
            e.date_sent.isoformat() if e.date_sent else None,
            e.subject,
            e.sender_email,
            e.sender_name,
            ", ".join(e.recipients_to or []) if e.recipients_to else None,
            ", ".join(e.recipients_cc or []) if e.recipients_cc else None,
            bool(e.has_attachments),
            e.content_hash,
            user_category,
            status,
        ]
        if payload.include_body:
            row.append(e.body_text_clean or e.body_text or "")
        writer.writerow(row)

    output.seek(0)

    filename = "emails_export.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# NOTE: Some advanced correspondence endpoints are still unimplemented, but the
# server-side email grid endpoint is wired up because the UI depends on it.


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


@router.get("/emails/{email_id}", response_model=EmailMessageDetail)
async def get_email_detail(
    email_id: str,
    db: Session = Depends(get_db),
):
    from .services import get_email_detail_service

    return await get_email_detail_service(email_id, db)
