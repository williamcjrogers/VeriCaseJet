"""
Claims Module - Item Links + Comments

Endpoints for linking correspondence/evidence items to matters/claims,
and for managing comments (link comments, item comments, direct comments).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from .db import get_db
from .security import current_user
from .models import (
    User,
    ContentiousMatter,
    HeadOfClaim,
    ItemClaimLink,
    ItemComment,
    EmailMessage,
    EvidenceItem,
)
from .claims_schemas import (
    ItemLinkCreate,
    ItemLinkUpdate,
    ItemLinkResponse,
    CommentCreate,
    CommentUpdate,
    CommentResponse,
    _parse_uuid,
    _log_claim_activity,
    _normalize_lane,
)

router = APIRouter(tags=["claims-links"])


# ---------------------------------------------------------------------------
# Item Link Endpoints
# ---------------------------------------------------------------------------


@router.get("/links")
async def list_item_links(
    contentious_matter_id: Optional[str] = Query(None),
    head_of_claim_id: Optional[str] = Query(None),
    item_type: Optional[str] = Query(None),
    item_id: Optional[str] = Query(None),
    link_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List item links with filtering"""
    query = db.query(ItemClaimLink).filter(ItemClaimLink.status == "active")

    if contentious_matter_id:
        query = query.filter(
            ItemClaimLink.contentious_matter_id == uuid.UUID(contentious_matter_id)
        )
    if head_of_claim_id:
        query = query.filter(
            ItemClaimLink.head_of_claim_id == uuid.UUID(head_of_claim_id)
        )
    if item_type:
        query = query.filter(ItemClaimLink.item_type == item_type)
    if item_id:
        query = query.filter(ItemClaimLink.item_id == uuid.UUID(item_id))
    if link_type:
        query = query.filter(ItemClaimLink.link_type == link_type)

    total = query.count()
    links = (
        query.order_by(ItemClaimLink.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    for link in links:
        # Get item details
        item_title = None
        item_date = None

        if link.item_type == "correspondence":
            email = (
                db.query(EmailMessage).filter(EmailMessage.id == link.item_id).first()
            )
            if email:
                item_title = email.subject
                item_date = email.date_sent
        elif link.item_type == "evidence":
            evidence = (
                db.query(EvidenceItem).filter(EvidenceItem.id == link.item_id).first()
            )
            if evidence:
                item_title = evidence.title or evidence.filename
                item_date = evidence.document_date

        # Get matter/claim names
        matter_name = None
        claim_name = None

        if link.contentious_matter_id:
            matter_name = (
                db.query(ContentiousMatter.name)
                .filter(ContentiousMatter.id == link.contentious_matter_id)
                .scalar()
            )

        if link.head_of_claim_id:
            claim_name = (
                db.query(HeadOfClaim.name)
                .filter(HeadOfClaim.id == link.head_of_claim_id)
                .scalar()
            )

        comment_count = (
            db.query(func.count(ItemComment.id))
            .filter(ItemComment.item_claim_link_id == link.id)
            .scalar()
            or 0
        )

        result.append(
            ItemLinkResponse(
                id=str(link.id),
                item_type=link.item_type,
                item_id=str(link.item_id),
                item_title=item_title,
                item_date=item_date,
                contentious_matter_id=(
                    str(link.contentious_matter_id)
                    if link.contentious_matter_id
                    else None
                ),
                contentious_matter_name=matter_name,
                head_of_claim_id=(
                    str(link.head_of_claim_id) if link.head_of_claim_id else None
                ),
                head_of_claim_name=claim_name,
                link_type=link.link_type or "supporting",
                relevance_score=link.relevance_score,
                notes=link.notes,
                status=link.status,
                created_at=link.created_at,
                created_by=str(link.created_by) if link.created_by else None,
                comment_count=comment_count,
            )
        )

    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.post("/links")
async def create_item_link(
    request: ItemLinkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Link a correspondence or evidence item to a matter or claim"""
    if not request.contentious_matter_id and not request.head_of_claim_id:
        raise HTTPException(
            400, "Either contentious_matter_id or head_of_claim_id is required"
        )

    # Check for existing link
    target_filters = []
    if request.contentious_matter_id:
        target_filters.append(
            ItemClaimLink.contentious_matter_id
            == uuid.UUID(request.contentious_matter_id)
        )
    if request.head_of_claim_id:
        target_filters.append(
            ItemClaimLink.head_of_claim_id == uuid.UUID(request.head_of_claim_id)
        )

    existing = (
        db.query(ItemClaimLink)
        .filter(
            ItemClaimLink.item_type == request.item_type,
            ItemClaimLink.item_id == uuid.UUID(request.item_id),
            or_(*target_filters),
            ItemClaimLink.status == "active",
        )
        .first()
    )

    if existing:
        raise HTTPException(
            409, "This item is already linked to the specified matter/claim"
        )

    link = ItemClaimLink(
        item_type=request.item_type,
        item_id=uuid.UUID(request.item_id),
        contentious_matter_id=(
            uuid.UUID(request.contentious_matter_id)
            if request.contentious_matter_id
            else None
        ),
        head_of_claim_id=(
            uuid.UUID(request.head_of_claim_id) if request.head_of_claim_id else None
        ),
        link_type=request.link_type,
        relevance_score=request.relevance_score,
        notes=request.notes,
        created_by=user.id,
    )

    db.add(link)
    db.flush()

    # Log activity if linked to a claim
    if link.head_of_claim_id:
        _log_claim_activity(
            db,
            action="evidence.linked",
            claim_id=link.head_of_claim_id,
            user_id=user.id,
            details={
                "link_id": str(link.id),
                "item_type": link.item_type,
                "item_id": str(link.item_id),
                "link_type": link.link_type,
            },
        )
    db.commit()
    db.refresh(link)

    return {
        "id": str(link.id),
        "item_type": link.item_type,
        "item_id": str(link.item_id),
        "status": "created",
    }


@router.put("/links/{link_id}")
async def update_item_link(
    link_id: str,
    request: ItemLinkUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Update an item link"""
    link = (
        db.query(ItemClaimLink).filter(ItemClaimLink.id == uuid.UUID(link_id)).first()
    )

    if not link:
        raise HTTPException(404, "Item link not found")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(link, key, value)

    db.commit()
    return {"id": str(link.id), "status": "updated"}


@router.delete("/links/{link_id}")
async def delete_item_link(
    link_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Remove an item link (soft delete)"""
    link = (
        db.query(ItemClaimLink).filter(ItemClaimLink.id == uuid.UUID(link_id)).first()
    )

    if not link:
        raise HTTPException(404, "Item link not found")

    link.status = "removed"
    db.commit()
    return {"id": link_id, "status": "removed"}


# ---------------------------------------------------------------------------
# Comment Endpoints
# ---------------------------------------------------------------------------


@router.get("/links/{link_id}/comments")
async def get_link_comments(
    link_id: str,
    lane: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get comments for an item link"""
    lane_filter = _normalize_lane(lane, default_core=False)
    query = db.query(ItemComment).filter(
        ItemComment.item_claim_link_id == uuid.UUID(link_id),
        ItemComment.parent_comment_id.is_(None),  # Top-level comments only
    )
    if lane_filter:
        query = query.filter(ItemComment.lane == lane_filter)

    comments = query.order_by(ItemComment.created_at.asc()).all()

    def build_comment_tree(comment):
        creator_name = None
        if comment.created_by:
            creator = db.query(User).filter(User.id == comment.created_by).first()
            if creator:
                creator_name = creator.display_name or creator.email

        reply_query = db.query(ItemComment).filter(
            ItemComment.parent_comment_id == comment.id
        )
        if lane_filter:
            reply_query = reply_query.filter(ItemComment.lane == lane_filter)

        replies = reply_query.order_by(ItemComment.created_at.asc()).all()

        return CommentResponse(
            id=str(comment.id),
            content=comment.content,
            item_claim_link_id=(
                str(comment.item_claim_link_id) if comment.item_claim_link_id else None
            ),
            item_type=comment.item_type,
            item_id=str(comment.item_id) if comment.item_id else None,
            parent_comment_id=(
                str(comment.parent_comment_id) if comment.parent_comment_id else None
            ),
            lane=comment.lane or "core",
            is_edited=comment.is_edited or False,
            edited_at=comment.edited_at,
            is_pinned=comment.is_pinned or False,
            pinned_at=comment.pinned_at,
            created_at=comment.created_at,
            created_by=str(comment.created_by) if comment.created_by else None,
            created_by_name=creator_name,
            replies=[build_comment_tree(reply) for reply in replies],
        )

    return [build_comment_tree(comment) for comment in comments]


@router.post("/links/{link_id}/comments")
async def add_link_comment(
    link_id: str,
    request: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Add a comment to an item link"""
    # Verify link exists
    link = (
        db.query(ItemClaimLink).filter(ItemClaimLink.id == uuid.UUID(link_id)).first()
    )
    if not link:
        raise HTTPException(404, "Item link not found")

    lane_value = _normalize_lane(request.lane)
    comment = ItemComment(
        item_claim_link_id=uuid.UUID(link_id),
        content=request.content,
        parent_comment_id=(
            uuid.UUID(request.parent_comment_id) if request.parent_comment_id else None
        ),
        lane=lane_value,
        created_by=user.id,
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {
        "id": str(comment.id),
        "content": comment.content,
        "lane": comment.lane,
        "status": "created",
    }


@router.get("/comments/{item_type}/{item_id}")
async def get_item_comments(
    item_type: str,
    item_id: str,
    lane: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get all comments for a specific item (correspondence or evidence)"""
    lane_filter = _normalize_lane(lane, default_core=False)
    # Get comments from linked items
    link_ids = (
        db.query(ItemClaimLink.id)
        .filter(
            ItemClaimLink.item_type == item_type,
            ItemClaimLink.item_id == uuid.UUID(item_id),
            ItemClaimLink.status == "active",
        )
        .all()
    )
    link_ids = [link.id for link in link_ids]

    # Get direct comments and linked comments
    comments_query = db.query(ItemComment).filter(
        or_(
            and_(
                ItemComment.item_type == item_type,
                ItemComment.item_id == uuid.UUID(item_id),
            ),
            ItemComment.item_claim_link_id.in_(link_ids),
        ),
        ItemComment.parent_comment_id.is_(None),
    )
    if lane_filter:
        comments_query = comments_query.filter(ItemComment.lane == lane_filter)
    if search and search.strip():
        comments_query = comments_query.filter(
            ItemComment.content.ilike(f"%{search.strip()}%")
        )

    comments = comments_query.order_by(ItemComment.created_at.asc()).all()

    def build_comment_tree(comment):
        creator_name = None
        if comment.created_by:
            creator = db.query(User).filter(User.id == comment.created_by).first()
            if creator:
                creator_name = creator.display_name or creator.email

        reply_query = db.query(ItemComment).filter(
            ItemComment.parent_comment_id == comment.id
        )
        if lane_filter:
            reply_query = reply_query.filter(ItemComment.lane == lane_filter)

        replies = reply_query.order_by(ItemComment.created_at.asc()).all()

        return CommentResponse(
            id=str(comment.id),
            content=comment.content,
            item_claim_link_id=(
                str(comment.item_claim_link_id) if comment.item_claim_link_id else None
            ),
            item_type=comment.item_type,
            item_id=str(comment.item_id) if comment.item_id else None,
            parent_comment_id=(
                str(comment.parent_comment_id) if comment.parent_comment_id else None
            ),
            lane=comment.lane or "core",
            is_edited=comment.is_edited or False,
            edited_at=comment.edited_at,
            is_pinned=comment.is_pinned or False,
            pinned_at=comment.pinned_at,
            created_at=comment.created_at,
            created_by=str(comment.created_by) if comment.created_by else None,
            created_by_name=creator_name,
            replies=[build_comment_tree(reply) for reply in replies],
        )

    return [build_comment_tree(comment) for comment in comments]


@router.post("/comments")
async def create_comment(
    request: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create a direct comment on an item"""
    lane_value = _normalize_lane(request.lane)
    comment = ItemComment(
        item_claim_link_id=(
            uuid.UUID(request.item_claim_link_id)
            if request.item_claim_link_id
            else None
        ),
        item_type=request.item_type,
        item_id=uuid.UUID(request.item_id) if request.item_id else None,
        parent_comment_id=(
            uuid.UUID(request.parent_comment_id) if request.parent_comment_id else None
        ),
        content=request.content,
        lane=lane_value,
        created_by=user.id,
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {
        "id": str(comment.id),
        "content": comment.content,
        "lane": comment.lane,
        "status": "created",
    }


@router.put("/comments/{comment_id}")
async def update_comment(
    comment_id: str,
    request: CommentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Update a comment"""
    comment = (
        db.query(ItemComment).filter(ItemComment.id == uuid.UUID(comment_id)).first()
    )

    if not comment:
        raise HTTPException(404, "Comment not found")

    # Only creator can edit
    if comment.created_by != user.id:
        raise HTTPException(403, "You can only edit your own comments")

    comment.content = request.content
    comment.is_edited = True
    comment.edited_at = datetime.utcnow()

    db.commit()
    return {"id": str(comment.id), "status": "updated"}


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Delete a comment"""
    comment = (
        db.query(ItemComment).filter(ItemComment.id == uuid.UUID(comment_id)).first()
    )

    if not comment:
        raise HTTPException(404, "Comment not found")

    # Only creator can delete
    if comment.created_by != user.id:
        raise HTTPException(403, "You can only delete your own comments")

    db.delete(comment)
    db.commit()
    return {"id": comment_id, "status": "deleted"}
