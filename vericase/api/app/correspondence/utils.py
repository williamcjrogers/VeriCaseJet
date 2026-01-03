# pyright: reportCallInDefaultInitializer=false, reportUnknownMemberType=false, reportUnknownVariableType=false
"""
Correspondence API Utils
"""

import re as _re_module
from typing import Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class PSTStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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


def _parse_pst_status_filter(status: str | None) -> list[str] | None:
    """Parse the `status` query param for PST list endpoints.

    Supports comma-separated lists (e.g. "pending,processing").
    Returns None when no filtering should be applied.
    """

    if not status:
        return None
    statuses = [s.strip().lower() for s in status.split(",") if s.strip()]
    return statuses or None


def build_correspondence_visibility_filter():
    """Return a SQLAlchemy filter for *visible* correspondence emails.

    Kept for backward compatibility; the canonical implementation lives in
    `api.app.visibility.build_email_visibility_filter`.
    """

    from ..visibility import build_email_visibility_filter
    from ..models import EmailMessage

    return build_email_visibility_filter(EmailMessage)


def build_correspondence_hard_exclusion_filter():
    """Return a SQLAlchemy filter that always excludes duplicates, spam, and other-project emails."""

    from sqlalchemy import and_, or_
    from ..models import EmailMessage

    status_field = EmailMessage.meta["status"].as_string()
    spam_override_field = EmailMessage.meta.op("->")("spam").op("->>")("user_override")
    spam_hidden_field = EmailMessage.meta.op("->")("spam").op("->>")("is_hidden")
    is_spam_field = EmailMessage.meta["is_spam"].as_string()
    ai_reason_field = EmailMessage.meta["ai_exclude_reason"].as_string()

    return and_(
        or_(EmailMessage.is_duplicate.is_(False), EmailMessage.is_duplicate.is_(None)),
        or_(
            status_field.is_(None),
            ~status_field.in_(["spam", "other_project", "duplicate"]),
        ),
        or_(spam_override_field.is_(None), spam_override_field != "hidden"),
        or_(spam_hidden_field.is_(None), spam_hidden_field != "true"),
        or_(is_spam_field.is_(None), is_spam_field != "true"),
        or_(
            ai_reason_field.is_(None),
            and_(
                ~ai_reason_field.ilike("spam%"),
                ~ai_reason_field.ilike("other_project%"),
                ai_reason_field != "duplicate",
            ),
        ),
    )


def _as_bool(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "t")
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def compute_correspondence_exclusion(meta: Any, subject: Any) -> dict[str, Any]:
    """Compute human-meaningful exclusion/visibility info for a correspondence row.

    This mirrors (in Python) the behavior of `build_correspondence_visibility_filter()` plus
    the default suppression of Outlook system items like `IPM.*`.

    Returns a dict suitable for embedding in API responses.
    """

    m: dict[str, Any] = meta if isinstance(meta, dict) else {}
    subject_text = "" if subject is None else str(subject)

    status = m.get("status")
    status_text = None if status is None else str(status)

    is_hidden_raw = m.get("is_hidden")
    is_hidden_text = None if is_hidden_raw is None else str(is_hidden_raw)

    spam_meta = m.get("spam")
    spam = spam_meta if isinstance(spam_meta, dict) else {}
    spam_user_override = spam.get("user_override")
    override_text = None if spam_user_override is None else str(spam_user_override)

    ai_excluded = _as_bool(m.get("ai_excluded"))
    ai_exclude_reason = m.get("ai_exclude_reason")
    ai_exclude_reason_text = (
        None if ai_exclude_reason is None else str(ai_exclude_reason)
    )

    # Determine whether this row would be hidden by default correspondence rules.
    reasons: list[str] = []
    excluded = False

    # Outlook system/activity items are not real emails for correspondence review.
    if subject_text.startswith("IPM."):
        excluded = True
        reasons.append("system_item:ipm")

    if not excluded:
        if override_text == "hidden":
            excluded = True
            reasons.append("spam_override:hidden")
        elif override_text == "visible":
            excluded = False
        else:
            if status_text is not None and status_text != "active":
                excluded = True
                reasons.append(f"status:{status_text}")
            if is_hidden_text == "true":
                excluded = True
                reasons.append("is_hidden:true")

    # Pick a primary label for UI display.
    primary = reasons[0] if reasons else None
    label = None
    if primary:
        if primary.startswith("system_item:"):
            label = "System Item"
        elif primary.startswith("spam_override:") or primary.startswith("status:spam"):
            label = "Spam"
        elif primary.startswith("status:other_project"):
            label = "Other Project"
        elif primary == "status:duplicate":
            label = "Duplicate"
        elif primary.startswith("status:excluded_person"):
            label = "Excluded Person"
        elif primary.startswith("status:"):
            label = "Excluded"
        elif primary.startswith("is_hidden:"):
            label = "Hidden"
        else:
            label = "Excluded"

    return {
        "excluded": excluded,
        "excluded_label": label,
        "excluded_reason": primary,
        "excluded_reasons": reasons,
        "status": status_text,
        "is_hidden": is_hidden_text,
        "spam_user_override": override_text,
        "ai_excluded": ai_excluded,
        "ai_exclude_reason": ai_exclude_reason_text,
    }


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


class PSTMultipartAbortRequest(BaseModel):
    """Request to abort a multipart upload (cleanup / user cancel)."""

    pst_file_id: str
    upload_id: str


class PSTMultipartAbortResponse(BaseModel):
    """Response for aborting a multipart upload."""

    success: bool = True
    pst_file_id: str
    upload_id: str
    message: str


class PSTMultipartPartsResponse(BaseModel):
    """Response listing uploaded parts for resuming multipart uploads."""

    pst_file_id: str
    upload_id: str
    parts: list[dict[str, Any]]  # List of {ETag, PartNumber, Size}


class PSTProcessingStatus(BaseModel):
    """PST processing status"""

    pst_file_id: str
    status: str  # pending, processing, completed, failed
    current_phase: str | None = (
        None  # uploaded, extracting, parsing, indexing (UI hint)
    )
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

    # Convenience fields for grids
    attachment_count: int | None = None
    images_count: int | None = None
    linked_to_count: int | None = None
    claim_status: str | None = None

    # Additional AG Grid fields (editable/custom fields)
    programme_activity: str | None = None
    baseline_activity: str | None = None
    as_built_activity: str | None = None
    as_planned_finish_date: datetime | None = None
    as_built_finish_date: datetime | None = None
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
    pst_file_id: str | None = None
    pst_filename: str | None = None


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
