"""
Evidence Repository API Utils
"""

from datetime import date, datetime
from typing import Any, cast
import hashlib
import uuid

from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_

from ..models import EvidenceItem, User, EvidenceActivityLog
from ..security import hash_password
from ..models import UserRole


def _safe_dict_list(value: list[Any] | None) -> list[dict[str, Any]]:
    """Return only dict entries to satisfy type expectations."""
    if value is None:
        return []
    result: list[dict[str, Any]] = []
    for idx in range(len(value)):
        entry_typed: object = value[idx]
        if isinstance(entry_typed, dict):
            # Use cast to explicitly type the dict for the type checker
            typed_dict = cast(dict[str, Any], entry_typed)
            typed_entry: dict[str, Any] = {}
            for k in typed_dict:
                typed_entry[str(k)] = typed_dict[k]
            result.append(typed_entry)
    return result


def get_file_type(filename: str) -> str | None:
    """Extract file extension as type.

    Returns the file extension, truncated to 255 chars max for database compatibility.
    Returns None only if no extension found.
    """
    if "." in filename:
        ext = filename.rsplit(".", 1)[1].lower().strip()
        if ext:
            # Truncate to database column max (255) - be flexible, don't reject
            return ext[:255]
    return None


def compute_file_hash(file_content: bytes) -> str:
    """Compute SHA-256 hash of file content"""
    return hashlib.sha256(file_content).hexdigest()


def log_activity(
    db: Session,
    action: str,
    user_id: uuid.UUID,
    evidence_item_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Log evidence activity"""
    activity = EvidenceActivityLog(
        evidence_item_id=evidence_item_id,
        collection_id=collection_id,
        action=action,
        action_details=details,
        user_id=user_id,
        ip_address=ip_address,
    )
    db.add(activity)


def _column_map() -> dict[str, Any]:
    """Map AG Grid column IDs to SQLAlchemy columns."""
    return {
        "filename": EvidenceItem.filename,
        "title": EvidenceItem.title,
        "document_date": EvidenceItem.document_date,
        "processing_status": EvidenceItem.processing_status,
        "evidence_type": EvidenceItem.evidence_type,
        "file_type": EvidenceItem.file_type,
        "mime_type": EvidenceItem.mime_type,
        "document_category": EvidenceItem.document_category,
        "file_size": EvidenceItem.file_size,
        "is_starred": EvidenceItem.is_starred,
        "created_at": EvidenceItem.created_at,
        "author": EvidenceItem.author,
        "page_count": EvidenceItem.page_count,
    }


def _apply_ag_filters(query: Any, filter_model: dict[str, Any]) -> Any:
    """Translate AG Grid filter model to SQLAlchemy filters."""
    if not filter_model:
        return query

    col_map = _column_map()

    for col_id, f in filter_model.items():
        column = col_map.get(col_id)

        # Special flags that are not direct columns
        if col_id == "unassigned" and f:
            query = query.filter(
                and_(EvidenceItem.case_id.is_(None), EvidenceItem.project_id.is_(None))
            )
            continue
        if col_id == "is_image":
            image_exts = [
                "jpg",
                "jpeg",
                "png",
                "gif",
                "bmp",
                "webp",
                "tif",
                "tiff",
                "heic",
                "heif",
                "svg",
            ]
            image_types = ["image", "photo", "photograph"]
            image_match = or_(
                EvidenceItem.mime_type.ilike("image/%"),
                EvidenceItem.file_type.in_(image_exts),
                EvidenceItem.evidence_type.in_(image_types),
            )
            if f is True:
                query = query.filter(image_match)
            elif f is False:
                query = query.filter(
                    and_(
                        or_(
                            EvidenceItem.mime_type.is_(None),
                            ~EvidenceItem.mime_type.ilike("image/%"),
                        ),
                        or_(
                            EvidenceItem.file_type.is_(None),
                            ~EvidenceItem.file_type.in_(image_exts),
                        ),
                        or_(
                            EvidenceItem.evidence_type.is_(None),
                            ~EvidenceItem.evidence_type.in_(image_types),
                        ),
                    )
                )
            continue
        if col_id == "is_media":
            image_exts = [
                "jpg",
                "jpeg",
                "png",
                "gif",
                "bmp",
                "webp",
                "tif",
                "tiff",
                "heic",
                "heif",
                "svg",
            ]
            video_exts = [
                "mp4",
                "mov",
                "m4v",
                "avi",
                "mkv",
                "webm",
                "wmv",
            ]
            audio_exts = [
                "mp3",
                "wav",
                "m4a",
                "aac",
                "flac",
                "ogg",
                "opus",
            ]
            media_exts = image_exts + video_exts + audio_exts
            media_types = ["image", "photo", "photograph", "video", "audio", "media"]
            media_match = or_(
                EvidenceItem.mime_type.ilike("image/%"),
                EvidenceItem.mime_type.ilike("video/%"),
                EvidenceItem.mime_type.ilike("audio/%"),
                EvidenceItem.file_type.in_(media_exts),
                EvidenceItem.evidence_type.in_(media_types),
            )
            if f is True:
                query = query.filter(media_match)
            elif f is False:
                query = query.filter(
                    and_(
                        or_(
                            EvidenceItem.mime_type.is_(None),
                            and_(
                                ~EvidenceItem.mime_type.ilike("image/%"),
                                ~EvidenceItem.mime_type.ilike("video/%"),
                                ~EvidenceItem.mime_type.ilike("audio/%"),
                            ),
                        ),
                        or_(
                            EvidenceItem.file_type.is_(None),
                            ~EvidenceItem.file_type.in_(media_exts),
                        ),
                        or_(
                            EvidenceItem.evidence_type.is_(None),
                            ~EvidenceItem.evidence_type.in_(media_types),
                        ),
                    )
                )
            continue
        if col_id == "is_correspondence":
            correspondence_exts = ["eml", "msg"]
            correspondence_types = ["correspondence", "email"]
            correspondence_match = or_(
                EvidenceItem.mime_type.ilike("message/%"),
                EvidenceItem.mime_type == "application/vnd.ms-outlook",
                EvidenceItem.file_type.in_(correspondence_exts),
                EvidenceItem.evidence_type.in_(correspondence_types),
                EvidenceItem.document_category == "email",
            )
            if f is True:
                query = query.filter(correspondence_match)
            elif f is False:
                query = query.filter(
                    and_(
                        or_(
                            EvidenceItem.mime_type.is_(None),
                            and_(
                                ~EvidenceItem.mime_type.ilike("message/%"),
                                EvidenceItem.mime_type != "application/vnd.ms-outlook",
                            ),
                        ),
                        or_(
                            EvidenceItem.file_type.is_(None),
                            ~EvidenceItem.file_type.in_(correspondence_exts),
                        ),
                        or_(
                            EvidenceItem.evidence_type.is_(None),
                            ~EvidenceItem.evidence_type.in_(correspondence_types),
                        ),
                        or_(
                            EvidenceItem.document_category.is_(None),
                            EvidenceItem.document_category != "email",
                        ),
                    )
                )
            continue
        if col_id == "is_starred" and f:
            query = query.filter(EvidenceItem.is_starred.is_(True))
            continue

        if column is None:
            continue

        filter_type = f.get("filterType")
        f_type = f.get("type")

        if filter_type == "text":
            value = f.get("filter")
            # Handle blank filter type (NULL or empty string)
            if f_type == "blank":
                query = query.filter(or_(column.is_(None), column == ""))
                continue
            if value is None:
                continue
            like_val = f"%{value}%"
            if f_type == "equals":
                query = query.filter(column == value)
            elif f_type == "startsWith":
                query = query.filter(column.ilike(f"{value}%"))
            elif f_type == "notBlank":
                query = query.filter(and_(column.isnot(None), column != ""))
            else:  # contains default
                query = query.filter(column.ilike(like_val))

        elif filter_type == "set":
            values = f.get("values") or []
            if values:
                query = query.filter(column.in_(values))

        elif filter_type == "number":
            val = f.get("filter")
            if val is None:
                continue
            if f_type == "lessThan":
                query = query.filter(column < val)
            elif f_type == "greaterThan":
                query = query.filter(column > val)
            elif f_type == "equals":
                query = query.filter(column == val)
            elif f_type == "inRange":
                to_val = f.get("filterTo")
                if to_val is not None:
                    query = query.filter(and_(column >= val, column <= to_val))

        elif filter_type == "date":
            date_from = f.get("dateFrom")
            date_to = f.get("dateTo")
            if f_type == "inRange" and date_from and date_to:
                query = query.filter(
                    and_(
                        column >= datetime.fromisoformat(date_from).date(),
                        column <= datetime.fromisoformat(date_to).date(),
                    )
                )
            elif date_from:
                query = query.filter(column >= datetime.fromisoformat(date_from).date())
            elif date_to:
                query = query.filter(column <= datetime.fromisoformat(date_to).date())

    return query


def _apply_ag_sorting(query: Any, sort_model: list[dict[str, Any]]) -> Any:
    """Apply AG Grid sorting model to query."""
    if not sort_model:
        return query.order_by(desc(EvidenceItem.created_at))

    col_map = _column_map()
    orders = []
    for sort in sort_model:
        col_id_raw = sort.get("colId")
        if not col_id_raw:
            continue
        col_id = str(col_id_raw)
        sort_dir = sort.get("sort", "asc")
        column = col_map.get(col_id)
        if not column:
            continue
        orders.append(desc(column) if sort_dir == "desc" else column)

    if not orders:
        return query.order_by(desc(EvidenceItem.created_at))

    return query.order_by(*orders)


def get_default_user(db: Session) -> User:
    """Get or create default admin user"""
    user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not user:
        user = User(
            email="admin@vericase.com",
            password_hash=hash_password("VeriCase1234?!"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ============================================================================
# PYDANTIC MODELS
# ============================================================================


class EvidenceUploadInitRequest(BaseModel):
    """Request to initiate evidence upload"""

    filename: str
    file_size: int
    content_type: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None
    tags: list[str] | None = None


class EvidenceUploadInitResponse(BaseModel):
    """Response with presigned upload URL"""

    evidence_id: str
    upload_url: str
    s3_bucket: str
    s3_key: str


class EvidenceItemCreate(BaseModel):
    """Create evidence item after upload"""

    filename: str
    s3_key: str
    file_size: int
    file_hash: str
    mime_type: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None
    evidence_type: str | None = None
    title: str | None = None
    description: str | None = None
    document_date: date | None = None
    tags: list[str] | None = None


class EvidenceItemUpdate(BaseModel):
    """Update evidence item"""

    title: str | None = None
    description: str | None = None
    evidence_type: str | None = None
    document_category: str | None = None
    document_date: date | None = None
    manual_tags: list[str] | None = None
    notes: str | None = None
    is_starred: bool | None = None
    is_privileged: bool | None = None
    is_confidential: bool | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None


class EvidenceItemSummary(BaseModel):
    """Evidence item summary for list view"""

    id: str
    filename: str
    author: str | None = None
    file_type: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    page_count: int | None = None
    evidence_type: str | None = None
    document_category: str | None = None
    document_date: date | None = None
    title: str | None = None
    processing_status: str
    is_starred: bool = False
    is_reviewed: bool = False
    has_correspondence: bool = False
    correspondence_count: int = 0
    correspondence_link_count: int = 0  # Alias for frontend compatibility
    auto_tags: list[str] = []
    manual_tags: list[str] = []
    extracted_parties: list[Any] = []
    extracted_amounts: list[Any] = []
    case_id: str | None = None
    project_id: str | None = None
    source_type: str | None = None
    source_email_id: str | None = None
    source_email_subject: str | None = None
    source_email_sender: str | None = None
    download_url: str | None = None
    created_at: datetime


class EvidenceItemDetail(BaseModel):
    """Full evidence item details"""

    id: str
    filename: str
    author: str | None = None
    original_path: str | None = None
    file_type: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    file_hash: str
    evidence_type: str | None = None
    document_category: str | None = None
    document_date: date | None = None
    title: str | None = None
    description: str | None = None
    page_count: int | None = None
    extracted_text: str | None = None
    extracted_parties: list[dict[str, Any]] = []
    extracted_dates: list[dict[str, Any]] = []
    extracted_amounts: list[dict[str, Any]] = []
    extracted_references: list[dict[str, Any]] = []
    auto_tags: list[str] = []
    manual_tags: list[str] = []
    processing_status: str
    source_type: str | None = None
    source_path: str | None = None
    is_duplicate: bool = False
    is_starred: bool = False
    is_privileged: bool = False
    is_confidential: bool = False
    is_reviewed: bool = False
    notes: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None
    correspondence_links: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    download_url: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class EvidenceListResponse(BaseModel):
    """Paginated evidence list"""

    total: int
    items: list[EvidenceItemSummary]
    page: int
    page_size: int


class ServerSideEvidenceRequest(BaseModel):
    """AG Grid server-side request contract"""

    startRow: int = 0
    endRow: int = 100
    sortModel: list[dict[str, Any]] = []
    filterModel: dict[str, Any] = {}


class ServerSideEvidenceResponse(BaseModel):
    """AG Grid server-side response"""

    rows: list[dict[str, Any]]
    lastRow: int
    stats: dict[str, Any] = {}


class CollectionCreate(BaseModel):
    """Create collection"""

    name: str
    description: str | None = None
    parent_id: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    color: str | None = None
    icon: str | None = None
    filter_rules: dict[str, Any] | None = None


class CollectionUpdate(BaseModel):
    """Update collection"""

    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    filter_rules: dict[str, Any] | None = None


class CollectionSummary(BaseModel):
    """Collection summary"""

    id: str
    name: str
    description: str | None = None
    collection_type: str
    parent_id: str | None = None
    item_count: int = 0
    is_system: bool = False
    color: str | None = None
    icon: str | None = None
    case_id: str | None = None
    project_id: str | None = None


class CorrespondenceLinkCreate(BaseModel):
    """Create correspondence link"""

    email_message_id: str | None = None
    link_type: str = "related"
    correspondence_type: str | None = None
    correspondence_reference: str | None = None
    correspondence_date: date | None = None
    correspondence_from: str | None = None
    correspondence_to: str | None = None
    correspondence_subject: str | None = None
    context_snippet: str | None = None


class AssignRequest(BaseModel):
    """Assign evidence to case/project"""

    case_id: str | None = None
    project_id: str | None = None
