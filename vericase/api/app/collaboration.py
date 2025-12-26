"""
Enhanced Collaboration System for VeriCase
- Real-time comments and annotations
- Activity streams
- @mentions and notifications
- Case/Evidence sharing
- Team workspaces
- Task assignments
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, func

from .db import get_db
from .models import (
    User,
    Document,
    Case,
    DocumentComment,
    DocumentAnnotation,
    CollaborationActivity,
    DocumentShare,
)
from .security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


# ============================================================================
# Pydantic Models
# ============================================================================


class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[str] = None  # For threaded comments
    mentions: List[str] = []  # User IDs or emails mentioned


class CommentResponse(BaseModel):
    id: str
    content: str
    author_id: str
    author_name: str
    author_email: str
    created_at: datetime
    updated_at: Optional[datetime]
    parent_id: Optional[str]
    replies_count: int
    mentions: List[dict]  # [{user_id, user_name, user_email}]
    is_edited: bool


class CommentUpdate(BaseModel):
    content: str
    mentions: List[str] = []


class MentionResolveResponse(BaseModel):
    user_id: str
    user_email: str
    user_name: str


class AnnotationCreate(BaseModel):
    page_number: int
    x: float
    y: float
    width: float
    height: float
    content: str
    color: str = "#FFD700"


class AnnotationResponse(BaseModel):
    id: str
    document_id: str
    page_number: int
    x: float
    y: float
    width: float
    height: float
    content: str
    color: str
    author_id: str
    author_name: str
    created_at: datetime


class AnnotationUpdate(BaseModel):
    page_number: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    content: Optional[str] = None
    color: Optional[str] = None


class ActivityResponse(BaseModel):
    id: str
    action: str  # created, updated, shared, commented, annotated
    resource_type: str  # document, case, evidence
    resource_id: str
    resource_name: str
    actor_id: str
    actor_name: str
    timestamp: datetime
    details: Dict[str, Any]


class CaseShareRequest(BaseModel):
    user_email: EmailStr
    role: str = "viewer"  # viewer, editor, admin


class CaseShareResponse(BaseModel):
    id: str
    case_id: str
    case_name: str
    user_email: str
    role: str
    shared_by: str
    shared_at: datetime


class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    member_emails: List[EmailStr] = []


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    owner_id: str
    owner_name: str
    member_count: int
    created_at: datetime


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assigned_to_email: EmailStr
    due_date: Optional[datetime] = None
    priority: str = "medium"  # low, medium, high, urgent


class TaskResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    status: str  # pending, in_progress, completed, cancelled
    assigned_to_id: str
    assigned_to_name: str
    assigned_by_id: str
    assigned_by_name: str
    created_at: datetime
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    priority: str


class NotificationResponse(BaseModel):
    id: str
    type: str  # mention, comment, share, task, activity
    title: str
    message: str
    link: Optional[str]
    read: bool
    created_at: datetime


# ============================================================================
# Comments & Annotations (DB-backed)
# ============================================================================


def _require_document_access(db: Session, doc_id: str, user: User) -> Document:
    try:
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "Invalid document ID")

    doc = db.get(Document, doc_uuid)
    if not doc:
        raise HTTPException(404, "Document not found")

    has_access = (
        doc.owner_user_id == user.id
        or db.query(DocumentShare)
        .filter(
            DocumentShare.document_id == doc.id, DocumentShare.shared_with == user.id
        )
        .first()
        is not None
    )
    if not has_access:
        raise HTTPException(403, "Access denied")
    return doc


def _log_collaboration_activity(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: UUID,
    user_id: UUID | None,
    details: dict[str, Any] | None = None,
) -> None:
    entry = CollaborationActivity(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        details=details or {},
    )
    db.add(entry)


def _serialize_comment(
    comment: DocumentComment,
    replies_count: int,
    mention_users: dict[UUID, User],
) -> CommentResponse:
    mention_info = []
    for mid in comment.mentions or []:
        try:
            uid = UUID(str(mid))
        except ValueError:
            continue
        u = mention_users.get(uid)
        if u:
            mention_info.append(
                {
                    "user_id": str(u.id),
                    "user_name": u.display_name or u.email,
                    "user_email": u.email,
                }
            )
    return CommentResponse(
        id=str(comment.id),
        content=comment.content,
        author_id=str(comment.author_id),
        author_name=comment.author.display_name or comment.author.email,
        author_email=comment.author.email,
        created_at=comment.created_at or datetime.now(timezone.utc),
        updated_at=comment.updated_at,
        parent_id=str(comment.parent_comment_id) if comment.parent_comment_id else None,
        replies_count=replies_count,
        mentions=mention_info,
        is_edited=comment.is_edited,
    )


def _normalize_mentions(db: Session, mentions: List[str]) -> List[str]:
    if not mentions:
        return []

    normalized_ids: list[UUID] = []
    seen: set[UUID] = set()
    emails: list[str] = []

    for mention in mentions:
        if not mention:
            continue
        value = str(mention).strip().lstrip("@")
        if not value:
            continue
        try:
            uid = UUID(value)
            if uid not in seen:
                normalized_ids.append(uid)
                seen.add(uid)
            continue
        except ValueError:
            pass
        if "@" in value:
            emails.append(value.lower())

    if emails:
        users = db.query(User).filter(User.email.in_(emails)).all()
        user_by_email = {u.email.lower(): u for u in users}
        for email in emails:
            user = user_by_email.get(email)
            if user and user.id not in seen:
                normalized_ids.append(user.id)
                seen.add(user.id)

    return [str(uid) for uid in normalized_ids]


def _has_edit_access(db: Session, doc: Document, user: User) -> bool:
    if doc.owner_user_id == user.id:
        return True
    share = (
        db.query(DocumentShare)
        .filter(
            DocumentShare.document_id == doc.id,
            DocumentShare.shared_with == user.id,
            DocumentShare.permission.in_(["edit", "owner"]),
        )
        .first()
    )
    return share is not None


@router.get("/mentions/resolve")
async def resolve_mentions(
    emails: str = Query(..., description="Comma-separated list of emails"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> List[MentionResolveResponse]:
    """Resolve emails to user IDs for mentions."""
    raw_emails = [e.strip().lower() for e in emails.split(",") if e.strip()]
    if not raw_emails:
        return []

    users = db.query(User).filter(User.email.in_(raw_emails)).all()
    user_by_email = {u.email.lower(): u for u in users}

    results: list[MentionResolveResponse] = []
    for email in raw_emails:
        user_match = user_by_email.get(email)
        if not user_match:
            continue
        results.append(
            MentionResolveResponse(
                user_id=str(user_match.id),
                user_email=user_match.email,
                user_name=user_match.display_name or user_match.email,
            )
        )
    return results


@router.post("/documents/{doc_id}/comments")
async def create_document_comment(
    doc_id: str,
    comment: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CommentResponse:
    """Create a comment on a document (persisted in document_comments)."""
    doc = _require_document_access(db, doc_id, user)

    parent_uuid: UUID | None = None
    if comment.parent_id:
        try:
            parent_uuid = UUID(comment.parent_id)
        except ValueError:
            raise HTTPException(400, "Invalid parent comment ID")
        parent = db.get(DocumentComment, parent_uuid)
        if not parent or parent.document_id != doc.id:
            raise HTTPException(404, "Parent comment not found for this document")

    normalized_mentions = _normalize_mentions(db, comment.mentions)
    db_comment = DocumentComment(
        document_id=doc.id,
        parent_comment_id=parent_uuid,
        content=comment.content,
        mentions=normalized_mentions,
        author_id=user.id,
    )
    db.add(db_comment)
    _log_collaboration_activity(
        db,
        action="comment.created",
        resource_type="document",
        resource_id=doc.id,
        user_id=user.id,
        details={"comment_id": str(db_comment.id), "parent_id": comment.parent_id},
    )
    db.commit()
    db.refresh(db_comment)

    mention_ids = []
    for mid in db_comment.mentions or []:
        try:
            mention_ids.append(UUID(str(mid)))
        except ValueError:
            continue
    mention_users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(mention_ids)).all()}
        if mention_ids
        else {}
    )

    if mention_ids:
        _create_mention_notifications(
            db, [str(mid) for mid in mention_ids], user, doc_id, comment.content
        )

    return _serialize_comment(db_comment, replies_count=0, mention_users=mention_users)


@router.get("/documents/{doc_id}/comments")
async def get_document_comments(
    doc_id: str,
    parent_id: Optional[str] = Query(
        None, description="Limit results to replies of this comment"
    ),
    include_replies: bool = Query(
        False, description="Include replies when parent_id is not provided"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> List[CommentResponse]:
    """Paginated comments for a document."""
    doc = _require_document_access(db, doc_id, user)

    query = db.query(DocumentComment).filter(DocumentComment.document_id == doc.id)
    if parent_id:
        try:
            parent_uuid = UUID(parent_id)
        except ValueError:
            raise HTTPException(400, "Invalid parent comment ID")
        query = query.filter(DocumentComment.parent_comment_id == parent_uuid)
    elif not include_replies:
        query = query.filter(DocumentComment.parent_comment_id.is_(None))

    # Replies count map
    reply_counts = dict(
        db.query(DocumentComment.parent_comment_id, func.count(DocumentComment.id))
        .filter(
            DocumentComment.document_id == doc.id,
            DocumentComment.parent_comment_id.is_not(None),
        )
        .group_by(DocumentComment.parent_comment_id)
        .all()
    )

    comments = (
        query.order_by(DocumentComment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    mention_ids: set[UUID] = set()
    for c in comments:
        for mid in c.mentions or []:
            try:
                mention_ids.add(UUID(str(mid)))
            except ValueError:
                continue

    mention_users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(mention_ids)).all()}
        if mention_ids
        else {}
    )

    return [
        _serialize_comment(
            c, replies_count=reply_counts.get(c.id, 0), mention_users=mention_users
        )
        for c in comments
    ]


@router.patch("/documents/{doc_id}/comments/{comment_id}")
async def update_document_comment(
    doc_id: str,
    comment_id: str,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CommentResponse:
    """Edit an existing comment (author-only)."""
    doc = _require_document_access(db, doc_id, user)
    try:
        cid = UUID(comment_id)
    except ValueError:
        raise HTTPException(400, "Invalid comment ID")

    db_comment = db.get(DocumentComment, cid)
    if not db_comment or db_comment.document_id != doc.id:
        raise HTTPException(404, "Comment not found")
    if db_comment.author_id != user.id:
        raise HTTPException(403, "Only the author can edit this comment")

    normalized_mentions = _normalize_mentions(db, payload.mentions)
    db_comment.content = payload.content
    db_comment.mentions = normalized_mentions
    db_comment.is_edited = True
    db_comment.edited_at = datetime.now(timezone.utc)
    _log_collaboration_activity(
        db,
        action="comment.updated",
        resource_type="document",
        resource_id=doc.id,
        user_id=user.id,
        details={"comment_id": str(db_comment.id)},
    )
    db.commit()
    db.refresh(db_comment)

    mention_ids = []
    for mid in db_comment.mentions or []:
        try:
            mention_ids.append(UUID(str(mid)))
        except ValueError:
            continue
    mention_users = (
        {u.id: u for u in db.query(User).filter(User.id.in_(mention_ids)).all()}
        if mention_ids
        else {}
    )
    return _serialize_comment(
        db_comment, replies_count=len(db_comment.replies), mention_users=mention_users
    )


@router.delete("/documents/{doc_id}/comments/{comment_id}")
async def delete_document_comment(
    doc_id: str,
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Delete a comment (author or document owner)."""
    doc = _require_document_access(db, doc_id, user)
    try:
        cid = UUID(comment_id)
    except ValueError:
        raise HTTPException(400, "Invalid comment ID")

    db_comment = db.get(DocumentComment, cid)
    if not db_comment or db_comment.document_id != doc.id:
        raise HTTPException(404, "Comment not found")

    if db_comment.author_id != user.id and doc.owner_user_id != user.id:
        raise HTTPException(403, "Only the author or document owner can delete")

    db.delete(db_comment)
    _log_collaboration_activity(
        db,
        action="comment.deleted",
        resource_type="document",
        resource_id=doc.id,
        user_id=user.id,
        details={"comment_id": comment_id},
    )
    db.commit()
    return {"status": "deleted", "comment_id": comment_id}


@router.post("/documents/{doc_id}/annotations")
async def create_annotation(
    doc_id: str,
    annotation: AnnotationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnnotationResponse:
    """Create an annotation on a document."""
    doc = _require_document_access(db, doc_id, user)
    if not _has_edit_access(db, doc, user):
        raise HTTPException(403, "Edit access required")
    db_annotation = DocumentAnnotation(
        document_id=doc.id,
        page_number=annotation.page_number,
        x=annotation.x,
        y=annotation.y,
        width=annotation.width,
        height=annotation.height,
        content=annotation.content,
        color=annotation.color,
        author_id=user.id,
    )
    db.add(db_annotation)
    _log_collaboration_activity(
        db,
        action="annotation.created",
        resource_type="document",
        resource_id=doc.id,
        user_id=user.id,
        details={
            "annotation_id": str(db_annotation.id),
            "page": annotation.page_number,
        },
    )
    db.commit()
    db.refresh(db_annotation)

    return AnnotationResponse(
        id=str(db_annotation.id),
        document_id=str(doc.id),
        page_number=db_annotation.page_number,
        x=db_annotation.x,
        y=db_annotation.y,
        width=db_annotation.width,
        height=db_annotation.height,
        content=db_annotation.content,
        color=db_annotation.color,
        author_id=str(user.id),
        author_name=user.display_name or user.email,
        created_at=db_annotation.created_at or datetime.now(timezone.utc),
    )


@router.get("/documents/{doc_id}/annotations")
async def get_annotations(
    doc_id: str,
    page_number: Optional[int] = Query(
        None, description="Optional page filter for annotations"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> List[AnnotationResponse]:
    """Paginated annotations for a document."""
    doc = _require_document_access(db, doc_id, user)

    query = db.query(DocumentAnnotation).filter(
        DocumentAnnotation.document_id == doc.id
    )
    if page_number is not None:
        query = query.filter(DocumentAnnotation.page_number == page_number)

    annotations = (
        query.order_by(DocumentAnnotation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    author_ids = {a.author_id for a in annotations}
    authors = (
        {u.id: u for u in db.query(User).filter(User.id.in_(author_ids)).all()}
        if author_ids
        else {}
    )

    results: List[AnnotationResponse] = []
    for a in annotations:
        author = authors.get(a.author_id)
        results.append(
            AnnotationResponse(
                id=str(a.id),
                document_id=str(doc.id),
                page_number=a.page_number,
                x=a.x,
                y=a.y,
                width=a.width,
                height=a.height,
                content=a.content,
                color=a.color,
                author_id=str(a.author_id),
                author_name=author.display_name if author else "Unknown",
                created_at=a.created_at or datetime.now(timezone.utc),
            )
        )
    return results


@router.patch("/documents/{doc_id}/annotations/{annotation_id}")
async def update_annotation(
    doc_id: str,
    annotation_id: str,
    payload: AnnotationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AnnotationResponse:
    """Update an annotation (author-only)."""
    doc = _require_document_access(db, doc_id, user)
    if not _has_edit_access(db, doc, user):
        raise HTTPException(403, "Edit access required")
    try:
        aid = UUID(annotation_id)
    except ValueError:
        raise HTTPException(400, "Invalid annotation ID")

    db_annotation = db.get(DocumentAnnotation, aid)
    if not db_annotation or db_annotation.document_id != doc.id:
        raise HTTPException(404, "Annotation not found")
    if db_annotation.author_id != user.id:
        raise HTTPException(403, "Only the author can edit this annotation")

    for field in ["page_number", "x", "y", "width", "height", "content", "color"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(db_annotation, field, value)

    _log_collaboration_activity(
        db,
        action="annotation.updated",
        resource_type="document",
        resource_id=doc.id,
        user_id=user.id,
        details={"annotation_id": str(db_annotation.id)},
    )
    db.commit()
    db.refresh(db_annotation)

    author = db.get(User, db_annotation.author_id)
    return AnnotationResponse(
        id=str(db_annotation.id),
        document_id=str(doc.id),
        page_number=db_annotation.page_number,
        x=db_annotation.x,
        y=db_annotation.y,
        width=db_annotation.width,
        height=db_annotation.height,
        content=db_annotation.content,
        color=db_annotation.color,
        author_id=str(db_annotation.author_id),
        author_name=(author.display_name if author else "Unknown"),
        created_at=db_annotation.created_at or datetime.now(timezone.utc),
    )


@router.delete("/documents/{doc_id}/annotations/{annotation_id}")
async def delete_annotation(
    doc_id: str,
    annotation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Delete an annotation (author or document owner)."""
    doc = _require_document_access(db, doc_id, user)
    if not _has_edit_access(db, doc, user):
        raise HTTPException(403, "Edit access required")
    try:
        aid = UUID(annotation_id)
    except ValueError:
        raise HTTPException(400, "Invalid annotation ID")

    db_annotation = db.get(DocumentAnnotation, aid)
    if not db_annotation or db_annotation.document_id != doc.id:
        raise HTTPException(404, "Annotation not found")

    if db_annotation.author_id != user.id and doc.owner_user_id != user.id:
        raise HTTPException(403, "Only the author or document owner can delete")

    db.delete(db_annotation)
    _log_collaboration_activity(
        db,
        action="annotation.deleted",
        resource_type="document",
        resource_id=doc.id,
        user_id=user.id,
        details={"annotation_id": annotation_id},
    )
    db.commit()
    return {"status": "deleted", "annotation_id": annotation_id}


# ============================================================================
# Case Sharing
# ============================================================================


@router.post("/cases/{case_id}/share")
async def share_case(
    case_id: str,
    share_req: CaseShareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> CaseShareResponse:
    """Share a case with another user"""
    try:
        case_uuid = UUID(case_id)
    except ValueError:
        raise HTTPException(400, "Invalid case ID")

    case = db.get(Case, case_uuid)
    if not case:
        raise HTTPException(404, "Case not found")

    # Check if user is case owner
    if case.owner_id != user.id:
        raise HTTPException(403, "Only case owner can share")

    # Get target user
    target = db.query(User).filter(User.email == share_req.user_email.lower()).first()
    if not target:
        raise HTTPException(404, f"User not found: {share_req.user_email}")

    if target.id == user.id:
        raise HTTPException(400, "Cannot share with yourself")

    # Create or update case user
    from .models import CaseUser

    existing = (
        db.query(CaseUser)
        .filter(CaseUser.case_id == case.id, CaseUser.user_id == target.id)
        .first()
    )

    share_id = str(uuid4())
    if existing:
        existing.role = share_req.role
        existing.updated_at = datetime.now(timezone.utc)
        share_id = str(existing.id)
    else:
        case_user = CaseUser(case_id=case.id, user_id=target.id, role=share_req.role)
        db.add(case_user)
        db.flush()
        share_id = str(case_user.id)

    db.commit()

    logger.info(f"Case {case_id} shared with {target.email} as {share_req.role}")

    return CaseShareResponse(
        id=share_id,
        case_id=case_id,
        case_name=case.name or "Untitled",
        user_email=target.email,
        role=share_req.role,
        shared_by=user.display_name or user.email,
        shared_at=datetime.now(timezone.utc),
    )


@router.get("/cases/{case_id}/shares")
async def list_case_shares(
    case_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> List[CaseShareResponse]:
    """List all users with access to a case"""
    try:
        case_uuid = UUID(case_id)
    except ValueError:
        raise HTTPException(400, "Invalid case ID")

    case = db.get(Case, case_uuid)
    if not case:
        raise HTTPException(404, "Case not found")

    # Check access
    if case.owner_id != user.id:
        raise HTTPException(403, "Only case owner can view shares")

    from .models import CaseUser

    case_users = db.query(CaseUser).filter(CaseUser.case_id == case.id).all()

    result = []
    for cu in case_users:
        shared_user = db.get(User, cu.user_id)
        if shared_user:
            result.append(
                CaseShareResponse(
                    id=str(cu.id),
                    case_id=case_id,
                    case_name=case.name or "Untitled",
                    user_email=shared_user.email,
                    role=cu.role,
                    shared_by=user.display_name or user.email,
                    shared_at=cu.created_at or datetime.now(timezone.utc),
                )
            )

    return result


# ============================================================================
# Activity Stream
# ============================================================================


@router.get("/activity")
async def get_activity_stream(
    limit: int = Query(default=50, le=100),
    resource_type: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> List[ActivityResponse]:
    """Get activity stream for user's accessible resources"""
    # Use CollaborationActivity as the source of truth.
    from .models import DocumentShare

    doc_ids = (
        db.query(Document.id)
        .filter(
            or_(
                Document.owner_user_id == user.id,
                Document.id.in_(
                    db.query(DocumentShare.document_id).filter(
                        DocumentShare.shared_with == user.id
                    )
                ),
            )
        )
        .all()
    )
    accessible_doc_ids = [row[0] for row in doc_ids]

    query = db.query(CollaborationActivity)

    if resource_type:
        query = query.filter(CollaborationActivity.resource_type == resource_type)

    if resource_type is None:
        if accessible_doc_ids:
            query = query.filter(
                or_(
                    CollaborationActivity.resource_type != "document",
                    CollaborationActivity.resource_id.in_(accessible_doc_ids),
                )
            )
        else:
            query = query.filter(CollaborationActivity.resource_type != "document")
    elif resource_type == "document":
        if not accessible_doc_ids:
            return []
        query = query.filter(
            CollaborationActivity.resource_type == "document",
            CollaborationActivity.resource_id.in_(accessible_doc_ids),
        )

    activities = (
        query.order_by(desc(CollaborationActivity.created_at)).limit(limit).all()
    )

    document_ids = [a.resource_id for a in activities if a.resource_type == "document"]
    documents = (
        db.query(Document).filter(Document.id.in_(document_ids)).all()
        if document_ids
        else []
    )
    doc_by_id = {d.id: d for d in documents}

    actor_ids = {a.user_id for a in activities if a.user_id}
    actors = db.query(User).filter(User.id.in_(actor_ids)).all() if actor_ids else []
    actor_by_id = {u.id: u for u in actors}

    results: list[ActivityResponse] = []
    for activity in activities:
        actor = actor_by_id.get(activity.user_id)
        resource_name = "Unknown"
        if activity.resource_type == "document":
            doc = doc_by_id.get(activity.resource_id)
            if doc:
                resource_name = doc.filename
        elif activity.details and activity.details.get("resource_name"):
            resource_name = activity.details["resource_name"]

        results.append(
            ActivityResponse(
                id=str(activity.id),
                action=activity.action,
                resource_type=activity.resource_type,
                resource_id=str(activity.resource_id),
                resource_name=resource_name,
                actor_id=str(activity.user_id) if activity.user_id else "",
                actor_name=(actor.display_name or actor.email) if actor else "Unknown",
                timestamp=activity.created_at or datetime.now(timezone.utc),
                details=activity.details or {},
            )
        )

    return results


# ============================================================================
# Helper Functions
# ============================================================================


def _create_mention_notifications(
    db: Session, mentioned_ids: List[str], author: User, doc_id: str, content: str
):
    """Create notifications for mentioned users"""
    # This would populate a notifications table
    # Simplified for now - just log
    for user_id in mentioned_ids:
        logger.info(f"User {user_id} mentioned by {author.email} in doc {doc_id}")
