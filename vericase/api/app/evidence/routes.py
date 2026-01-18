"""
Evidence Repository API Routes
"""

from typing import Annotated, Any
from datetime import date

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..security import get_db, current_user
from ..models import User
from .services import (
    init_evidence_upload_service,
    complete_evidence_upload_service,
    direct_upload_evidence_service,
    list_evidence_service,
    get_evidence_server_side_service,
    get_evidence_download_url_service,
    get_evidence_full_service,
    get_evidence_detail_service,
    update_evidence_service,
    delete_evidence_service,
    assign_evidence_service,
    toggle_star_service,
    get_evidence_correspondence_service,
    link_evidence_to_email_service,
    delete_correspondence_link_service,
    list_collections_service,
    create_collection_service,
    update_collection_service,
    delete_collection_service,
    add_to_collection_service,
    remove_from_collection_service,
    get_evidence_stats_service,
    get_evidence_types_service,
    get_evidence_metadata_service,
    get_evidence_preview_service,
    get_evidence_office_render_service,
    trigger_metadata_extraction_service,
    get_evidence_thumbnail_service,
    get_evidence_text_content_service,
    sync_email_attachments_to_evidence_service,
    get_sync_status_service,
    extract_all_metadata_service,
    auto_categorize_evidence_service,
)
from .utils import (
    EvidenceUploadInitRequest,
    EvidenceUploadInitResponse,
    EvidenceItemCreate,
    EvidenceItemUpdate,
    EvidenceListResponse,
    ServerSideEvidenceRequest,
    ServerSideEvidenceResponse,
    CollectionCreate,
    CollectionUpdate,
    CollectionSummary,
    CorrespondenceLinkCreate,
    AssignRequest,
    AutoCategorizeRequest,
    AutoCategorizeResponse,
)

router = APIRouter(prefix="/api/evidence", tags=["evidence-repository"])

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]


@router.post("/upload/init", response_model=EvidenceUploadInitResponse)
async def init_evidence_upload(
    request: EvidenceUploadInitRequest,
    db: DbSession,
):
    return await init_evidence_upload_service(request, db)


@router.post("/upload/complete")
async def complete_evidence_upload(
    request: EvidenceItemCreate,
    db: DbSession,
):
    return await complete_evidence_upload_service(request, db)


@router.post("/upload/direct")
async def direct_upload_evidence(
    file: Annotated[UploadFile, File(...)],
    db: DbSession,
    case_id: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    collection_id: Annotated[str | None, Form()] = None,
    evidence_type: Annotated[str | None, Form()] = None,
    tags: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    return await direct_upload_evidence_service(
        file, db, case_id, project_id, collection_id, evidence_type, tags
    )


@router.get("/items", response_model=EvidenceListResponse)
async def list_evidence(
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=10000)] = 50,
    search: Annotated[
        str | None, Query(description="Search in filename, title, text")
    ] = None,
    evidence_type: Annotated[str | None, Query()] = None,
    document_category: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    tags: Annotated[str | None, Query(description="Comma-separated tags")] = None,
    has_correspondence: Annotated[bool | None, Query()] = None,
    is_starred: Annotated[bool | None, Query()] = None,
    is_reviewed: Annotated[bool | None, Query()] = None,
    include_email_info: Annotated[
        bool, Query(description="Include emails from correspondence")
    ] = False,
    unassigned: Annotated[
        bool | None, Query(description="Only show items not in any case/project")
    ] = None,
    case_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    collection_id: Annotated[str | None, Query()] = None,
    processing_status: Annotated[str | None, Query()] = None,
    sort_by: Annotated[str, Query(description="Sort field")] = "created_at",
    sort_order: Annotated[str, Query(description="asc or desc")] = "desc",
    include_hidden: Annotated[
        bool, Query(description="Include spam-filtered/hidden items")
    ] = False,
) -> EvidenceListResponse:
    return await list_evidence_service(
        db,
        page,
        page_size,
        search,
        evidence_type,
        document_category,
        date_from,
        date_to,
        tags,
        has_correspondence,
        is_starred,
        is_reviewed,
        include_email_info,
        unassigned,
        case_id,
        project_id,
        collection_id,
        processing_status,
        sort_by,
        sort_order,
        include_hidden,
    )


@router.post("/items/server-side", response_model=ServerSideEvidenceResponse)
async def get_evidence_server_side(
    request: ServerSideEvidenceRequest,
    db: DbSession,
    project_id: str | None = Query(None),
    case_id: str | None = Query(None),
    collection_id: str | None = Query(None),
    include_email_info: bool = Query(False),
    include_hidden: bool = Query(
        False, description="Include spam-filtered/hidden items"
    ),
) -> ServerSideEvidenceResponse:
    return await get_evidence_server_side_service(
        request,
        db,
        project_id,
        case_id,
        collection_id,
        include_email_info,
        include_hidden,
    )


@router.get("/items/{evidence_id}/download-url")
async def get_evidence_download_url(evidence_id: str, db: DbSession) -> dict[str, Any]:
    return await get_evidence_download_url_service(evidence_id, db)


@router.get("/items/{evidence_id}/full")
async def get_evidence_full(
    evidence_id: str,
    db: DbSession,
) -> dict[str, Any]:
    return await get_evidence_full_service(evidence_id, db)


@router.get("/items/{evidence_id}")
async def get_evidence_detail_endpoint(
    evidence_id: str,
    db: DbSession,
):
    return await get_evidence_detail_service(evidence_id, db)


@router.patch("/items/{evidence_id}")
async def update_evidence_endpoint(
    evidence_id: str, updates: EvidenceItemUpdate, db: DbSession
):
    return await update_evidence_service(evidence_id, updates, db)


@router.post("/items/auto-categorize", response_model=AutoCategorizeResponse)
async def auto_categorize_evidence_endpoint(
    request: AutoCategorizeRequest,
    db: DbSession,
    project_id: str | None = Query(None),
    case_id: str | None = Query(None),
    include_hidden: bool = Query(
        False, description="Include spam-filtered/hidden items"
    ),
) -> AutoCategorizeResponse:
    return await auto_categorize_evidence_service(
        request,
        db,
        project_id=project_id,
        case_id=case_id,
        include_hidden=include_hidden,
    )


@router.delete("/items/{evidence_id}")
async def delete_evidence_endpoint(evidence_id: str, db: DbSession):
    return await delete_evidence_service(evidence_id, db)


@router.post("/items/{evidence_id}/assign")
async def assign_evidence_endpoint(
    evidence_id: str, assignment: AssignRequest, db: DbSession
):
    return await assign_evidence_service(evidence_id, assignment, db)


@router.post("/items/{evidence_id}/star")
async def toggle_star_endpoint(evidence_id: str, db: DbSession):
    return await toggle_star_service(evidence_id, db)


@router.get("/items/{evidence_id}/correspondence")
async def get_evidence_correspondence(
    evidence_id: str, db: DbSession
) -> dict[str, Any]:
    return await get_evidence_correspondence_service(evidence_id, db)


@router.post("/items/{evidence_id}/link-email")
async def link_evidence_to_email(
    evidence_id: str, link_request: CorrespondenceLinkCreate, db: DbSession
):
    return await link_evidence_to_email_service(evidence_id, link_request, db)


@router.delete("/correspondence-links/{link_id}")
async def delete_correspondence_link_endpoint(link_id: str, db: DbSession):
    return await delete_correspondence_link_service(link_id, db)


@router.get("/collections")
async def list_collections(
    db: DbSession,
    include_system: Annotated[bool, Query()] = True,
    case_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
) -> list[CollectionSummary]:
    return await list_collections_service(db, include_system, case_id, project_id)


@router.post("/collections")
async def create_collection(collection: CollectionCreate, db: DbSession):
    return await create_collection_service(collection, db)


@router.patch("/collections/{collection_id}")
async def update_collection_endpoint(
    collection_id: str, updates: CollectionUpdate, db: DbSession
):
    return await update_collection_service(collection_id, updates, db)


@router.delete("/collections/{collection_id}")
async def delete_collection_endpoint(collection_id: str, db: DbSession):
    return await delete_collection_service(collection_id, db)


@router.post("/collections/{collection_id}/items/{evidence_id}")
async def add_to_collection_endpoint(
    collection_id: str, evidence_id: str, db: DbSession
):
    return await add_to_collection_service(collection_id, evidence_id, db)


@router.delete("/collections/{collection_id}/items/{evidence_id}")
async def remove_from_collection_endpoint(
    collection_id: str, evidence_id: str, db: DbSession
):
    return await remove_from_collection_service(collection_id, evidence_id, db)


@router.get("/stats")
async def get_evidence_stats_endpoint(
    db: DbSession,
    case_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    return await get_evidence_stats_service(db, case_id, project_id)


@router.get("/types")
async def get_evidence_types_endpoint():
    return await get_evidence_types_service()


@router.get("/items/{evidence_id}/metadata")
async def get_evidence_metadata_endpoint(
    evidence_id: str,
    db: DbSession,
    user: CurrentUser,
    extract_fresh: Annotated[bool, Query(description="Force re-extraction")] = False,
):
    return await get_evidence_metadata_service(evidence_id, db, user, extract_fresh)


@router.get("/items/{evidence_id}/preview")
async def get_evidence_preview_endpoint(
    evidence_id: str, db: DbSession, user: CurrentUser
):
    return await get_evidence_preview_service(evidence_id, db, user)


@router.get("/items/{evidence_id}/office-render")
async def get_evidence_office_render_endpoint(
    evidence_id: str,
    db: DbSession,
    user: CurrentUser,
    sheet: Annotated[str | None, Query(description="Excel sheet name")] = None,
    max_rows: Annotated[
        int, Query(description="Max rows to render", ge=1, le=1000)
    ] = 200,
    max_cols: Annotated[
        int, Query(description="Max columns to render", ge=1, le=200)
    ] = 40,
):
    return await get_evidence_office_render_service(
        evidence_id, db, user, sheet=sheet, max_rows=max_rows, max_cols=max_cols
    )


@router.post("/items/{evidence_id}/extract-metadata")
async def trigger_metadata_extraction_endpoint(
    evidence_id: str, db: DbSession, user: CurrentUser
):
    return await trigger_metadata_extraction_service(evidence_id, db, user)


@router.get("/items/{evidence_id}/thumbnail")
async def get_evidence_thumbnail_endpoint(
    evidence_id: str,
    db: DbSession,
    user: CurrentUser,
    size: Annotated[str, Query(description="Thumbnail size")] = "medium",
):
    return await get_evidence_thumbnail_service(evidence_id, db, user, size)


@router.get("/items/{evidence_id}/text-content")
async def get_evidence_text_content_endpoint(
    evidence_id: str,
    db: DbSession,
    user: CurrentUser,
    max_length: Annotated[int, Query(description="Max chars")] = 50000,
):
    return await get_evidence_text_content_service(evidence_id, db, user, max_length)


@router.post("/sync-attachments")
async def sync_email_attachments_to_evidence_endpoint(
    db: DbSession,
    user: CurrentUser,
    project_id: Annotated[str | None, Query()] = None,
    extract_metadata: Annotated[
        bool, Query(description="Extract metadata for synced attachments")
    ] = True,
) -> dict[str, Any]:
    return await sync_email_attachments_to_evidence_service(
        db, user, project_id, extract_metadata
    )


@router.get("/sync-status")
async def get_sync_status_endpoint(
    db: DbSession,
    project_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    return await get_sync_status_service(db, project_id)


@router.post("/extract-all-metadata")
async def extract_all_metadata_endpoint(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(description="Max items")] = 100,
    force: Annotated[bool, Query(description="Re-extract")] = False,
):
    return await extract_all_metadata_service(db, user, limit, force)
