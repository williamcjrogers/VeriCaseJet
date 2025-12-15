# pyright: reportAny=false
"""
Contentious Matters and Heads of Claim Module

API endpoints for managing:
- Contentious Matters (dispute categories)
- Heads of Claim (specific legal claims)
- Item Links (linking correspondence/evidence to matters/claims)
- Comments (audit trail with comment history)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
    CollaborationActivity,
    CaseUser,
    CommentReaction,
    CommentReadStatus,
    UserNotificationPreferences,
)

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claims", tags=["claims"])


def _parse_uuid(value: Optional[str], field: str) -> Optional[uuid.UUID]:
    """Safely parse UUID strings and surface a 400 instead of 500 on bad input."""
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(value)
    except Exception:
        raise HTTPException(400, f"Invalid {field} format. Expected UUID.")


# =============================================================================
# Pydantic Models
# =============================================================================


# Contentious Matter Models
class ContentiousMatterCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    case_id: Optional[str] = None
    status: str = "active"
    priority: str = "normal"
    estimated_value: Optional[int] = None  # In cents/pence
    currency: str = "GBP"
    date_identified: Optional[datetime] = None


class ContentiousMatterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    estimated_value: Optional[int] = None
    currency: Optional[str] = None
    date_identified: Optional[datetime] = None
    resolution_date: Optional[datetime] = None


class ContentiousMatterResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    project_id: Optional[str]
    case_id: Optional[str]
    status: str
    priority: str
    estimated_value: Optional[int]
    currency: str
    date_identified: Optional[datetime]
    resolution_date: Optional[datetime]
    created_at: datetime
    created_by: Optional[str]
    item_count: int = 0
    claim_count: int = 0


# Head of Claim Models
class HeadOfClaimCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    case_id: Optional[str] = None
    contentious_matter_id: Optional[str] = None
    reference_number: Optional[str] = None
    claim_type: Optional[str] = None
    claimed_amount: Optional[int] = None  # In cents/pence
    currency: str = "GBP"
    status: str = "draft"
    submission_date: Optional[datetime] = None
    response_due_date: Optional[datetime] = None
    supporting_contract_clause: Optional[str] = None


class HeadOfClaimUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    contentious_matter_id: Optional[str] = None
    reference_number: Optional[str] = None
    claim_type: Optional[str] = None
    claimed_amount: Optional[int] = None
    awarded_amount: Optional[int] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    submission_date: Optional[datetime] = None
    response_due_date: Optional[datetime] = None
    determination_date: Optional[datetime] = None
    supporting_contract_clause: Optional[str] = None


class HeadOfClaimResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    project_id: Optional[str]
    case_id: Optional[str]
    contentious_matter_id: Optional[str]
    contentious_matter_name: Optional[str] = None
    reference_number: Optional[str]
    claim_type: Optional[str]
    claimed_amount: Optional[int]
    awarded_amount: Optional[int]
    currency: str
    status: str
    submission_date: Optional[datetime]
    response_due_date: Optional[datetime]
    determination_date: Optional[datetime]
    supporting_contract_clause: Optional[str]
    created_at: datetime
    created_by: Optional[str]
    item_count: int = 0


# Item Link Models
class ItemLinkCreate(BaseModel):
    item_type: str  # 'correspondence' or 'evidence'
    item_id: str
    contentious_matter_id: Optional[str] = None
    head_of_claim_id: Optional[str] = None
    link_type: str = "supporting"  # supporting, contradicting, neutral, key
    relevance_score: Optional[int] = None
    notes: Optional[str] = None


class ItemLinkUpdate(BaseModel):
    link_type: Optional[str] = None
    relevance_score: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class ItemLinkResponse(BaseModel):
    id: str
    item_type: str
    item_id: str
    item_title: Optional[str] = None
    item_date: Optional[datetime] = None
    contentious_matter_id: Optional[str]
    contentious_matter_name: Optional[str] = None
    head_of_claim_id: Optional[str]
    head_of_claim_name: Optional[str] = None
    link_type: str
    relevance_score: Optional[int]
    notes: Optional[str]
    status: str
    created_at: datetime
    created_by: Optional[str]
    comment_count: int = 0


# Comment Models
class CommentCreate(BaseModel):
    content: str
    item_claim_link_id: Optional[str] = None
    item_type: Optional[str] = None
    item_id: Optional[str] = None
    parent_comment_id: Optional[str] = None


class CommentUpdate(BaseModel):
    content: str


class CommentResponse(BaseModel):
    id: str
    content: str
    item_claim_link_id: Optional[str]
    item_type: Optional[str]
    item_id: Optional[str]
    parent_comment_id: Optional[str]
    is_edited: bool
    edited_at: Optional[datetime]
    is_pinned: bool = False
    pinned_at: Optional[datetime] = None
    created_at: datetime
    created_by: Optional[str]
    created_by_name: Optional[str] = None
    replies: List["CommentResponse"] = []


# =============================================================================
# Contentious Matter Endpoints
# =============================================================================


@router.get("/matters")
async def list_contentious_matters(
    project_id: Optional[str] = Query(None),
    case_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List contentious matters with filtering"""
    query = db.query(ContentiousMatter)

    if project_id:
        pid = _parse_uuid(project_id, "project_id")
        query = query.filter(ContentiousMatter.project_id == pid)
    if case_id:
        cid = _parse_uuid(case_id, "case_id")
        query = query.filter(ContentiousMatter.case_id == cid)
    if status:
        query = query.filter(ContentiousMatter.status == status)

    total = query.count()
    matters = (
        query.order_by(ContentiousMatter.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    for m in matters:
        item_count = (
            db.query(func.count(ItemClaimLink.id))
            .filter(
                ItemClaimLink.contentious_matter_id == m.id,
                ItemClaimLink.status == "active",
            )
            .scalar()
            or 0
        )

        claim_count = (
            db.query(func.count(HeadOfClaim.id))
            .filter(HeadOfClaim.contentious_matter_id == m.id)
            .scalar()
            or 0
        )

        result.append(
            ContentiousMatterResponse(
                id=str(m.id),
                name=m.name,
                description=m.description,
                project_id=str(m.project_id) if m.project_id else None,
                case_id=str(m.case_id) if m.case_id else None,
                status=m.status or "active",
                priority=m.priority or "normal",
                estimated_value=m.estimated_value,
                currency=m.currency or "GBP",
                date_identified=m.date_identified,
                resolution_date=m.resolution_date,
                created_at=m.created_at,
                created_by=str(m.created_by) if m.created_by else None,
                item_count=item_count,
                claim_count=claim_count,
            )
        )

    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.post("/matters")
async def create_contentious_matter(
    request: ContentiousMatterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create a new contentious matter"""
    if not request.project_id and not request.case_id:
        raise HTTPException(400, "Either project_id or case_id is required")

    matter = ContentiousMatter(
        name=request.name,
        description=request.description,
        project_id=_parse_uuid(request.project_id, "project_id"),
        case_id=_parse_uuid(request.case_id, "case_id"),
        status=request.status,
        priority=request.priority,
        estimated_value=request.estimated_value,
        currency=request.currency,
        date_identified=request.date_identified,
        created_by=user.id,
    )

    db.add(matter)
    db.commit()
    db.refresh(matter)

    return {"id": str(matter.id), "name": matter.name, "status": "created"}


@router.get("/matters/{matter_id}")
async def get_contentious_matter(
    matter_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Get a contentious matter by ID"""
    matter_uuid = _parse_uuid(matter_id, "matter_id")
    matter = (
        db.query(ContentiousMatter)
        .filter(ContentiousMatter.id == matter_uuid)
        .first()
    )

    if not matter:
        raise HTTPException(404, "Contentious matter not found")

    item_count = (
        db.query(func.count(ItemClaimLink.id))
        .filter(
            ItemClaimLink.contentious_matter_id == matter.id,
            ItemClaimLink.status == "active",
        )
        .scalar()
        or 0
    )

    claim_count = (
        db.query(func.count(HeadOfClaim.id))
        .filter(HeadOfClaim.contentious_matter_id == matter.id)
        .scalar()
        or 0
    )

    return ContentiousMatterResponse(
        id=str(matter.id),
        name=matter.name,
        description=matter.description,
        project_id=str(matter.project_id) if matter.project_id else None,
        case_id=str(matter.case_id) if matter.case_id else None,
        status=matter.status or "active",
        priority=matter.priority or "normal",
        estimated_value=matter.estimated_value,
        currency=matter.currency or "GBP",
        date_identified=matter.date_identified,
        resolution_date=matter.resolution_date,
        created_at=matter.created_at,
        created_by=str(matter.created_by) if matter.created_by else None,
        item_count=item_count,
        claim_count=claim_count,
    )


@router.put("/matters/{matter_id}")
async def update_contentious_matter(
    matter_id: str,
    request: ContentiousMatterUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Update a contentious matter"""
    matter = db.query(ContentiousMatter).filter(
        ContentiousMatter.id == _parse_uuid(matter_id, "matter_id")
    ).first()

    if not matter:
        raise HTTPException(404, "Contentious matter not found")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(matter, key, value)

    db.commit()
    return {"id": str(matter.id), "status": "updated"}


@router.delete("/matters/{matter_id}")
async def delete_contentious_matter(
    matter_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Delete a contentious matter"""
    matter = db.query(ContentiousMatter).filter(
        ContentiousMatter.id == _parse_uuid(matter_id, "matter_id")
    ).first()

    if not matter:
        raise HTTPException(404, "Contentious matter not found")

    db.delete(matter)
    db.commit()
    return {"id": matter_id, "status": "deleted"}


# =============================================================================
# Head of Claim Endpoints
# =============================================================================


@router.get("/heads-of-claim")
async def list_heads_of_claim(
    project_id: Optional[str] = Query(None),
    case_id: Optional[str] = Query(None),
    contentious_matter_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    claim_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List heads of claim with filtering"""
    query = db.query(HeadOfClaim)

    if project_id:
        pid = _parse_uuid(project_id, "project_id")
        query = query.filter(HeadOfClaim.project_id == pid)
    if case_id:
        cid = _parse_uuid(case_id, "case_id")
        query = query.filter(HeadOfClaim.case_id == cid)
    if contentious_matter_id:
        cm_id = _parse_uuid(contentious_matter_id, "contentious_matter_id")
        query = query.filter(HeadOfClaim.contentious_matter_id == cm_id)
    if status:
        query = query.filter(HeadOfClaim.status == status)
    if claim_type:
        query = query.filter(HeadOfClaim.claim_type == claim_type)

    total = query.count()
    claims = (
        query.order_by(HeadOfClaim.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
        for c in claims:
            item_count = (
                db.query(func.count(ItemClaimLink.id))
                .filter(
                    ItemClaimLink.head_of_claim_id == c.id, ItemClaimLink.status == "active"
                )
                .scalar()
                or 0
            )

            matter_name = None
            if c.contentious_matter_id:
                matter = (
                    db.query(ContentiousMatter.name)
                    .filter(ContentiousMatter.id == c.contentious_matter_id)
                    .first()
                )
                if matter:
                    matter_name = matter.name

            result.append(
                HeadOfClaimResponse(
                    id=str(c.id),
                    name=c.name,
                    description=c.description,
                    project_id=str(c.project_id) if c.project_id else None,
                    case_id=str(c.case_id) if c.case_id else None,
                    contentious_matter_id=(
                        str(c.contentious_matter_id) if c.contentious_matter_id else None
                    ),
                    contentious_matter_name=matter_name,
                    reference_number=c.reference_number,
                    claim_type=c.claim_type,
                    claimed_amount=c.claimed_amount,
                    awarded_amount=c.awarded_amount,
                    currency=c.currency or "GBP",
                    status=c.status or "draft",
                    submission_date=c.submission_date,
                    response_due_date=c.response_due_date,
                    determination_date=c.determination_date,
                    supporting_contract_clause=c.supporting_contract_clause,
                    created_at=c.created_at,
                    created_by=str(c.created_by) if c.created_by else None,
                    item_count=item_count,
                )
            )

    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.post("/heads-of-claim")
async def create_head_of_claim(
    request: HeadOfClaimCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create a new head of claim"""
    if not request.project_id and not request.case_id:
        raise HTTPException(400, "Either project_id or case_id is required")

    claim = HeadOfClaim(
        name=request.name,
        description=request.description,
        project_id=_parse_uuid(request.project_id, "project_id"),
        case_id=_parse_uuid(request.case_id, "case_id"),
        contentious_matter_id=_parse_uuid(
            request.contentious_matter_id, "contentious_matter_id"
        ),
        reference_number=request.reference_number,
        claim_type=request.claim_type,
        claimed_amount=request.claimed_amount,
        currency=request.currency,
        status=request.status,
        submission_date=request.submission_date,
        response_due_date=request.response_due_date,
        supporting_contract_clause=request.supporting_contract_clause,
        created_by=user.id,
    )

    db.add(claim)
    db.flush()  # Get the ID without committing

    # Log activity
    _log_claim_activity(
        db,
        action="claim.created",
        claim_id=claim.id,
        user_id=user.id,
        details={
            "name": claim.name,
            "reference_number": claim.reference_number,
            "claim_type": claim.claim_type,
            "claimed_amount": claim.claimed_amount,
        },
    )
    db.commit()
    db.refresh(claim)

    return {
        "id": str(claim.id),
        "name": claim.name,
        "reference_number": claim.reference_number,
        "status": "created",
    }


@router.get("/heads-of-claim/{claim_id}")
async def get_head_of_claim(
    claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Get a head of claim by ID"""
    claim = db.query(HeadOfClaim).filter(
        HeadOfClaim.id == _parse_uuid(claim_id, "claim_id")
    ).first()

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    item_count = (
        db.query(func.count(ItemClaimLink.id))
        .filter(
            ItemClaimLink.head_of_claim_id == claim.id, ItemClaimLink.status == "active"
        )
        .scalar()
        or 0
    )

    matter_name = None
    if claim.contentious_matter_id:
        matter = (
            db.query(ContentiousMatter.name)
            .filter(ContentiousMatter.id == claim.contentious_matter_id)
            .first()
        )
        if matter:
            matter_name = matter.name

    return HeadOfClaimResponse(
        id=str(claim.id),
        name=claim.name,
        description=claim.description,
        project_id=str(claim.project_id) if claim.project_id else None,
        case_id=str(claim.case_id) if claim.case_id else None,
        contentious_matter_id=(
            str(claim.contentious_matter_id) if claim.contentious_matter_id else None
        ),
        contentious_matter_name=matter_name,
        reference_number=claim.reference_number,
        claim_type=claim.claim_type,
        claimed_amount=claim.claimed_amount,
        awarded_amount=claim.awarded_amount,
        currency=claim.currency or "GBP",
        status=claim.status or "draft",
        submission_date=claim.submission_date,
        response_due_date=claim.response_due_date,
        determination_date=claim.determination_date,
        supporting_contract_clause=claim.supporting_contract_clause,
        created_at=claim.created_at,
        created_by=str(claim.created_by) if claim.created_by else None,
        item_count=item_count,
    )


@router.put("/heads-of-claim/{claim_id}")
async def update_head_of_claim(
    claim_id: str,
    request: HeadOfClaimUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Update a head of claim"""
    claim = db.query(HeadOfClaim).filter(
        HeadOfClaim.id == _parse_uuid(claim_id, "claim_id")
    ).first()

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    update_data = request.model_dump(exclude_unset=True)

    # Handle contentious_matter_id conversion
    if "contentious_matter_id" in update_data:
        cm_id = update_data["contentious_matter_id"]
        update_data["contentious_matter_id"] = (
            _parse_uuid(cm_id, "contentious_matter_id") if cm_id else None
        )

    for key, value in update_data.items():
        setattr(claim, key, value)

    # Log activity
    _log_claim_activity(
        db,
        action="claim.updated",
        claim_id=claim.id,
        user_id=user.id,
        details={"updated_fields": list(update_data.keys())},
    )
    db.commit()
    return {"id": str(claim.id), "status": "updated"}


@router.delete("/heads-of-claim/{claim_id}")
async def delete_head_of_claim(
    claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Delete a head of claim"""
    claim = db.query(HeadOfClaim).filter(
        HeadOfClaim.id == _parse_uuid(claim_id, "claim_id")
    ).first()

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    db.delete(claim)
    db.commit()
    return {"id": claim_id, "status": "deleted"}


# =============================================================================
# Team Members Endpoint (for @mention autocomplete)
# =============================================================================


class TeamMemberResponse(BaseModel):
    id: str
    email: str
    display_name: Optional[str]


@router.get("/heads-of-claim/{claim_id}/team-members")
async def get_claim_team_members(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get team members who can be @mentioned on this claim"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get team members from case_id if available
    team_members = []

    if claim.case_id:
        # Get all users linked to this case
        case_users = (
            db.query(User.id, User.email, User.display_name)
            .join(CaseUser, CaseUser.user_id == User.id)
            .filter(CaseUser.case_id == claim.case_id)
            .filter(User.is_active == True)
            .all()
        )
        for cu in case_users:
            team_members.append(
                TeamMemberResponse(
                    id=str(cu.id),
                    email=cu.email,
                    display_name=cu.display_name,
                )
            )

    # Always include current user if not already in list
    if not any(tm.id == str(user.id) for tm in team_members):
        team_members.append(
            TeamMemberResponse(
                id=str(user.id),
                email=user.email,
                display_name=user.display_name,
            )
        )

    # Sort by display_name or email
    team_members.sort(key=lambda x: (x.display_name or x.email).lower())

    return {"items": [tm.model_dump() for tm in team_members]}


@router.get("/heads-of-claim/{claim_id}/evidence-comments")
async def get_evidence_comments(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get comments on evidence/correspondence linked to this claim (evidence notes tab)"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get all links to this claim
    links = (
        db.query(ItemClaimLink)
        .filter(ItemClaimLink.head_of_claim_id == claim_uuid)
        .all()
    )

    if not links:
        return {"items": [], "total": 0}

    # Build response grouped by linked item
    result_items = []

    for link in links:
        # Get the linked item name
        item_name = f"Unknown {link.item_type}"
        if link.item_type == "evidence":
            evidence = db.query(EvidenceItem).filter(EvidenceItem.id == link.item_id).first()
            if evidence:
                item_name = evidence.name or evidence.original_filename or f"Evidence #{str(link.item_id)[:8]}"
        elif link.item_type == "correspondence":
            email = db.query(EmailMessage).filter(EmailMessage.id == link.item_id).first()
            if email:
                item_name = email.subject or f"Email #{str(link.item_id)[:8]}"

        # Get comments on this link
        comments = (
            db.query(ItemComment)
            .filter(
                ItemComment.item_claim_link_id == link.id,
                ItemComment.parent_comment_id.is_(None),
            )
            .order_by(ItemComment.created_at.desc())
            .all()
        )

        def build_comment_response(comment):
            creator_name = None
            if comment.created_by:
                creator = (
                    db.query(User.email, User.display_name)
                    .filter(User.id == comment.created_by)
                    .first()
                )
                if creator:
                    creator_name = creator.display_name or creator.email

            # Get replies
            replies = (
                db.query(ItemComment)
                .filter(ItemComment.parent_comment_id == comment.id)
                .order_by(ItemComment.created_at.asc())
                .all()
            )

            return {
                "id": str(comment.id),
                "content": comment.content,
                "item_claim_link_id": str(link.id),
                "is_edited": comment.is_edited or False,
                "edited_at": comment.edited_at,
                "created_at": comment.created_at,
                "created_by": str(comment.created_by) if comment.created_by else None,
                "created_by_name": creator_name,
                "replies": [build_comment_response(r) for r in replies],
            }

        result_items.append({
            "link_id": str(link.id),
            "item_type": link.item_type,
            "item_id": str(link.item_id),
            "item_name": item_name,
            "link_type": link.link_type,
            "comment_count": len(comments),
            "comments": [build_comment_response(c) for c in comments],
        })

    # Sort by comment_count descending (most discussed first)
    result_items.sort(key=lambda x: x["comment_count"], reverse=True)

    return {"items": result_items, "total": len(result_items)}


# =============================================================================
# Head of Claim Comments Endpoints
# =============================================================================


@router.get("/heads-of-claim/{claim_id}/comments")
async def get_claim_comments(
    claim_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search comments by content"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get comments directly on a head of claim (discussion tab)"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Build base query
    base_filter = [
        ItemComment.item_type == "claim",
        ItemComment.item_id == claim_uuid,
        ItemComment.parent_comment_id.is_(None),
    ]

    # Add search filter if provided
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        base_filter.append(ItemComment.content.ilike(search_term))

    # Get top-level comments on this claim
    comments = (
        db.query(ItemComment)
        .filter(*base_filter)
        .order_by(ItemComment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    total = (
        db.query(func.count(ItemComment.id))
        .filter(*base_filter)
        .scalar()
        or 0
    )

    def build_comment_tree(comment):
        creator_name = None
        if comment.created_by:
            creator = (
                db.query(User.email, User.display_name)
                .filter(User.id == comment.created_by)
                .first()
            )
            if creator:
                creator_name = creator.display_name or creator.email

        # Get replies
        replies = (
            db.query(ItemComment)
            .filter(ItemComment.parent_comment_id == comment.id)
            .order_by(ItemComment.created_at.asc())
            .all()
        )

        return CommentResponse(
            id=str(comment.id),
            content=comment.content,
            item_claim_link_id=None,
            item_type="claim",
            item_id=str(comment.item_id) if comment.item_id else None,
            parent_comment_id=(
                str(comment.parent_comment_id) if comment.parent_comment_id else None
            ),
            is_edited=comment.is_edited or False,
            edited_at=comment.edited_at,
            is_pinned=comment.is_pinned or False,
            pinned_at=comment.pinned_at,
            created_at=comment.created_at,
            created_by=str(comment.created_by) if comment.created_by else None,
            created_by_name=creator_name,
            replies=[build_comment_tree(r) for r in replies],
        )

    return {
        "items": [build_comment_tree(c) for c in comments],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/heads-of-claim/{claim_id}/comments")
async def create_claim_comment(
    claim_id: str,
    request: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create a comment directly on a head of claim"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Validate parent comment if provided
    parent_uuid = None
    if request.parent_comment_id:
        parent_uuid = _parse_uuid(request.parent_comment_id, "parent_comment_id")
        parent = db.query(ItemComment).filter(ItemComment.id == parent_uuid).first()
        if not parent:
            raise HTTPException(404, "Parent comment not found")

    comment = ItemComment(
        item_type="claim",
        item_id=claim_uuid,
        parent_comment_id=parent_uuid,
        content=request.content,
        created_by=user.id,
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Get creator info for response
    creator_name = user.display_name or user.email

    # Log activity
    _log_claim_activity(
        db,
        action="comment.created",
        claim_id=claim_uuid,
        user_id=user.id,
        details={"comment_id": str(comment.id), "content_preview": request.content[:100]},
    )

    # Process notifications (@mentions and replies)
    try:
        from .notifications import process_comment_notifications
        notification_result = process_comment_notifications(db, comment, user, claim)
        logger.info(f"Notifications processed: {notification_result}")
    except Exception as e:
        logger.error(f"Failed to process notifications: {e}")

    return {
        "id": str(comment.id),
        "content": comment.content,
        "item_type": "claim",
        "item_id": claim_id,
        "parent_comment_id": request.parent_comment_id,
        "created_by": str(user.id),
        "created_by_name": creator_name,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "status": "created",
    }


# =============================================================================
# Activity History Endpoints
# =============================================================================


def _log_claim_activity(
    db: Session,
    action: str,
    claim_id: uuid.UUID,
    user_id: uuid.UUID | None,
    details: dict | None = None,
) -> None:
    """Log an activity entry for a head of claim."""
    activity = CollaborationActivity(
        action=action,
        resource_type="claim",
        resource_id=claim_id,
        user_id=user_id,
        details=details or {},
    )
    db.add(activity)


class ActivityResponse(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str
    user_id: Optional[str]
    user_name: Optional[str]
    details: dict
    created_at: datetime


@router.get("/heads-of-claim/{claim_id}/activity")
async def get_claim_activity(
    claim_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get all-time activity history for a head of claim"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get activity entries for this claim
    activities = (
        db.query(CollaborationActivity)
        .filter(
            CollaborationActivity.resource_type == "claim",
            CollaborationActivity.resource_id == claim_uuid,
        )
        .order_by(CollaborationActivity.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    total = (
        db.query(func.count(CollaborationActivity.id))
        .filter(
            CollaborationActivity.resource_type == "claim",
            CollaborationActivity.resource_id == claim_uuid,
        )
        .scalar()
        or 0
    )

    # Also include link activities related to this claim
    link_activities = (
        db.query(CollaborationActivity)
        .join(ItemClaimLink, CollaborationActivity.resource_id == ItemClaimLink.id)
        .filter(
            CollaborationActivity.resource_type == "link",
            ItemClaimLink.head_of_claim_id == claim_uuid,
        )
        .order_by(CollaborationActivity.created_at.desc())
        .limit(page_size)
        .all()
    )

    # Combine and sort
    all_activities = activities + link_activities
    all_activities.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
    all_activities = all_activities[:page_size]

    # Get user names
    user_ids = {a.user_id for a in all_activities if a.user_id}
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u.display_name or u.email for u in users}

    result = []
    for activity in all_activities:
        result.append(
            ActivityResponse(
                id=str(activity.id),
                action=activity.action,
                resource_type=activity.resource_type,
                resource_id=str(activity.resource_id),
                user_id=str(activity.user_id) if activity.user_id else None,
                user_name=users_map.get(activity.user_id) if activity.user_id else None,
                details=activity.details or {},
                created_at=activity.created_at or datetime.utcnow(),
            )
        )

    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# =============================================================================
# Item Link Endpoints
# =============================================================================


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
            matter = (
                db.query(ContentiousMatter.name)
                .filter(ContentiousMatter.id == link.contentious_matter_id)
                .first()
            )
            if matter:
                matter_name = matter.name

        if link.head_of_claim_id:
            claim = (
                db.query(HeadOfClaim.name)
                .filter(HeadOfClaim.id == link.head_of_claim_id)
                .first()
            )
            if claim:
                claim_name = claim.name

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
                status=link.status or "active",
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
    existing = (
        db.query(ItemClaimLink)
        .filter(
            ItemClaimLink.item_type == request.item_type,
            ItemClaimLink.item_id == uuid.UUID(request.item_id),
            or_(
                and_(
                    ItemClaimLink.contentious_matter_id
                    == (
                        uuid.UUID(request.contentious_matter_id)
                        if request.contentious_matter_id
                        else None
                    ),
                    request.contentious_matter_id is not None,
                ),
                and_(
                    ItemClaimLink.head_of_claim_id
                    == (
                        uuid.UUID(request.head_of_claim_id)
                        if request.head_of_claim_id
                        else None
                    ),
                    request.head_of_claim_id is not None,
                ),
            ),
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


# =============================================================================
# Comment Endpoints
# =============================================================================


@router.get("/links/{link_id}/comments")
async def get_link_comments(
    link_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Get comments for an item link"""
    comments = (
        db.query(ItemComment)
        .filter(
            ItemComment.item_claim_link_id == uuid.UUID(link_id),
            ItemComment.parent_comment_id.is_(None),  # Top-level comments only
        )
        .order_by(ItemComment.created_at.asc())
        .all()
    )

    def build_comment_tree(comment):
        creator_name = None
        if comment.created_by:
            creator = (
                db.query(User.email, User.display_name)
                .filter(User.id == comment.created_by)
                .first()
            )
            if creator:
                creator_name = creator.display_name or creator.email

        replies = (
            db.query(ItemComment)
            .filter(ItemComment.parent_comment_id == comment.id)
            .order_by(ItemComment.created_at.asc())
            .all()
        )

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
            is_edited=comment.is_edited or False,
            edited_at=comment.edited_at,
            is_pinned=comment.is_pinned or False,
            pinned_at=comment.pinned_at,
            created_at=comment.created_at,
            created_by=str(comment.created_by) if comment.created_by else None,
            created_by_name=creator_name,
            replies=[build_comment_tree(r) for r in replies],
        )

    return [build_comment_tree(c) for c in comments]


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

    comment = ItemComment(
        item_claim_link_id=uuid.UUID(link_id),
        content=request.content,
        parent_comment_id=(
            uuid.UUID(request.parent_comment_id) if request.parent_comment_id else None
        ),
        created_by=user.id,
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {"id": str(comment.id), "content": comment.content, "status": "created"}


@router.get("/comments/{item_type}/{item_id}")
async def get_item_comments(
    item_type: str,
    item_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get all comments for a specific item (correspondence or evidence)"""
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
    comments = (
        db.query(ItemComment)
        .filter(
            or_(
                and_(
                    ItemComment.item_type == item_type,
                    ItemComment.item_id == uuid.UUID(item_id),
                ),
                ItemComment.item_claim_link_id.in_(link_ids),
            ),
            ItemComment.parent_comment_id.is_(None),
        )
        .order_by(ItemComment.created_at.asc())
        .all()
    )

    result = []
    for comment in comments:
        creator_name = None
        if comment.created_by:
            creator = (
                db.query(User.email, User.display_name)
                .filter(User.id == comment.created_by)
                .first()
            )
            if creator:
                creator_name = creator.display_name or creator.email

        result.append(
            CommentResponse(
                id=str(comment.id),
                content=comment.content,
                item_claim_link_id=(
                    str(comment.item_claim_link_id)
                    if comment.item_claim_link_id
                    else None
                ),
                item_type=comment.item_type,
                item_id=str(comment.item_id) if comment.item_id else None,
                parent_comment_id=None,
                is_edited=comment.is_edited or False,
                edited_at=comment.edited_at,
                created_at=comment.created_at,
                created_by=str(comment.created_by) if comment.created_by else None,
                created_by_name=creator_name,
                replies=[],
            )
        )

    return result


@router.post("/comments")
async def create_comment(
    request: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Create a direct comment on an item"""
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
        created_by=user.id,
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {"id": str(comment.id), "content": comment.content, "status": "created"}


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


# =============================================================================
# Statistics Endpoint
# =============================================================================


@router.get("/stats")
async def get_claims_stats(
    project_id: Optional[str] = Query(None),
    case_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get summary statistics for claims module"""
    matter_query = db.query(func.count(ContentiousMatter.id))
    claim_query = db.query(func.count(HeadOfClaim.id))
    link_query = db.query(func.count(ItemClaimLink.id)).filter(
        ItemClaimLink.status == "active"
    )

    if project_id:
        pid = _parse_uuid(project_id, "project_id")
        matter_query = matter_query.filter(ContentiousMatter.project_id == pid)
        claim_query = claim_query.filter(HeadOfClaim.project_id == pid)

    if case_id:
        cid = _parse_uuid(case_id, "case_id")
        matter_query = matter_query.filter(ContentiousMatter.case_id == cid)
        claim_query = claim_query.filter(HeadOfClaim.case_id == cid)

    total_matters = matter_query.scalar() or 0
    total_claims = claim_query.scalar() or 0
    total_links = link_query.scalar() or 0

    # Get claimed amounts
    amount_query = db.query(func.sum(HeadOfClaim.claimed_amount))
    if project_id:
        amount_query = amount_query.filter(HeadOfClaim.project_id == pid)
    if case_id:
        amount_query = amount_query.filter(HeadOfClaim.case_id == cid)

    total_claimed = amount_query.scalar() or 0

    return {
        "total_contentious_matters": total_matters,
        "total_heads_of_claim": total_claims,
        "total_linked_items": total_links,
        "total_claimed_amount": total_claimed,
        "currency": "GBP",
    }


# =============================================================================
# AI-Powered Collaboration Endpoints
# =============================================================================


class AISummarizeRequest(BaseModel):
    max_length: Optional[int] = 500


class AISuggestEvidenceRequest(BaseModel):
    context: Optional[str] = None


class AIDraftReplyRequest(BaseModel):
    context: Optional[str] = None
    tone: str = "professional"  # professional, formal, casual


class AIAutoTagRequest(BaseModel):
    content: str


class AIResponse(BaseModel):
    result: str
    tokens_used: Optional[int] = None
    model_used: Optional[str] = None


@router.post("/heads-of-claim/{claim_id}/ai/summarize")
async def ai_summarize_discussion(
    claim_id: str,
    request: AISummarizeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-powered summary of claim discussion threads"""
    from .ai_runtime import complete_chat
    from .ai_settings import get_ai_api_key

    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get all comments on this claim
    comments = (
        db.query(ItemComment)
        .filter(
            ItemComment.item_type == "claim",
            ItemComment.item_id == claim_uuid,
        )
        .order_by(ItemComment.created_at.asc())
        .all()
    )

    if not comments:
        return AIResponse(
            result="No discussion to summarize yet.",
            tokens_used=0,
            model_used=None,
        )

    # Build discussion text
    discussion_parts = []
    for comment in comments:
        creator = db.query(User).filter(User.id == comment.created_by).first()
        creator_name = creator.display_name or creator.email if creator else "Unknown"
        discussion_parts.append(f"[{creator_name}]: {comment.content}")

    discussion_text = "\n".join(discussion_parts)

    system_prompt = """You are an assistant summarizing legal claim discussions.
Provide a concise summary highlighting:
1. Key discussion points
2. Any decisions or agreements reached
3. Outstanding questions or action items
Keep the summary professional and factual."""

    prompt = f"""Summarize this discussion about claim "{claim.name}" (Reference: {claim.reference_number or 'N/A'}):

{discussion_text}

Provide a summary in no more than {request.max_length} words."""

    try:
        # Try to get an API key and make the call
        api_key = get_ai_api_key("openai", db) or get_ai_api_key("anthropic", db)
        if not api_key:
            raise HTTPException(503, "No AI provider configured")

        provider = "openai" if get_ai_api_key("openai", db) else "anthropic"
        model = "gpt-4o-mini" if provider == "openai" else "claude-sonnet-4-20250514"

        result = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=prompt,
            system_prompt=system_prompt,
            db=db,
            max_tokens=1000,
            temperature=0.3,
        )

        return AIResponse(
            result=result,
            model_used=f"{provider}/{model}",
        )
    except Exception as e:
        logger.error(f"AI summarize failed: {e}")
        raise HTTPException(503, f"AI service unavailable: {str(e)}")


@router.post("/heads-of-claim/{claim_id}/ai/suggest-evidence")
async def ai_suggest_evidence(
    claim_id: str,
    request: AISuggestEvidenceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-powered evidence suggestions based on claim discussion"""
    from .ai_runtime import complete_chat
    from .ai_settings import get_ai_api_key

    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get recent comments for context
    comments = (
        db.query(ItemComment)
        .filter(
            ItemComment.item_type == "claim",
            ItemComment.item_id == claim_uuid,
        )
        .order_by(ItemComment.created_at.desc())
        .limit(10)
        .all()
    )

    comment_text = "\n".join([c.content for c in comments]) if comments else ""

    # Get already linked evidence
    linked = (
        db.query(ItemClaimLink)
        .filter(
            ItemClaimLink.head_of_claim_id == claim_uuid,
            ItemClaimLink.status == "active",
        )
        .all()
    )
    linked_ids = {str(l.item_id) for l in linked}

    # Get available evidence not yet linked
    available_evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.project_id == claim.project_id)
        .limit(50)
        .all()
    )

    evidence_list = []
    for ev in available_evidence:
        if str(ev.id) not in linked_ids:
            evidence_list.append(f"- {ev.title or ev.filename} (Type: {ev.document_type or 'Unknown'})")

    if not evidence_list:
        return AIResponse(
            result="No additional evidence available to suggest.",
            model_used=None,
        )

    system_prompt = """You are a legal research assistant helping identify relevant evidence for claims.
Based on the claim details and discussion, suggest which evidence items would be most relevant to link."""

    prompt = f"""Claim: {claim.name}
Type: {claim.claim_type or 'General'}
Description: {claim.description or 'N/A'}
Contract Clause: {claim.supporting_contract_clause or 'N/A'}

Recent Discussion:
{comment_text or 'No discussion yet'}

Additional Context: {request.context or 'None provided'}

Available Evidence (not yet linked):
{chr(10).join(evidence_list[:20])}

Suggest which evidence items should be linked to this claim and why. Format as a numbered list."""

    try:
        api_key = get_ai_api_key("openai", db) or get_ai_api_key("anthropic", db)
        if not api_key:
            raise HTTPException(503, "No AI provider configured")

        provider = "openai" if get_ai_api_key("openai", db) else "anthropic"
        model = "gpt-4o-mini" if provider == "openai" else "claude-sonnet-4-20250514"

        result = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=prompt,
            system_prompt=system_prompt,
            db=db,
            max_tokens=1000,
            temperature=0.3,
        )

        return AIResponse(
            result=result,
            model_used=f"{provider}/{model}",
        )
    except Exception as e:
        logger.error(f"AI suggest evidence failed: {e}")
        raise HTTPException(503, f"AI service unavailable: {str(e)}")


@router.post("/heads-of-claim/{claim_id}/ai/draft-reply")
async def ai_draft_reply(
    claim_id: str,
    request: AIDraftReplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-assisted reply drafting for claim discussions"""
    from .ai_runtime import complete_chat
    from .ai_settings import get_ai_api_key

    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get recent comments
    comments = (
        db.query(ItemComment)
        .filter(
            ItemComment.item_type == "claim",
            ItemComment.item_id == claim_uuid,
        )
        .order_by(ItemComment.created_at.desc())
        .limit(5)
        .all()
    )

    recent_discussion = []
    for comment in reversed(comments):
        creator = db.query(User).filter(User.id == comment.created_by).first()
        creator_name = creator.display_name or creator.email if creator else "Unknown"
        recent_discussion.append(f"[{creator_name}]: {comment.content}")

    tone_guidance = {
        "professional": "Use a professional, clear tone suitable for business communication.",
        "formal": "Use formal language appropriate for legal/official correspondence.",
        "casual": "Use a friendly but professional tone.",
    }

    system_prompt = f"""You are an assistant helping draft replies in claim discussions.
{tone_guidance.get(request.tone, tone_guidance['professional'])}
Draft a thoughtful response that addresses the discussion points."""

    prompt = f"""Claim: {claim.name} ({claim.reference_number or 'N/A'})
Type: {claim.claim_type or 'General'}

Recent Discussion:
{chr(10).join(recent_discussion) or 'No prior discussion'}

Context for reply: {request.context or 'General response needed'}

Draft a reply for the current user to post. Keep it concise but comprehensive."""

    try:
        api_key = get_ai_api_key("openai", db) or get_ai_api_key("anthropic", db)
        if not api_key:
            raise HTTPException(503, "No AI provider configured")

        provider = "openai" if get_ai_api_key("openai", db) else "anthropic"
        model = "gpt-4o-mini" if provider == "openai" else "claude-sonnet-4-20250514"

        result = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=prompt,
            system_prompt=system_prompt,
            db=db,
            max_tokens=500,
            temperature=0.5,
        )

        return AIResponse(
            result=result,
            model_used=f"{provider}/{model}",
        )
    except Exception as e:
        logger.error(f"AI draft reply failed: {e}")
        raise HTTPException(503, f"AI service unavailable: {str(e)}")


@router.post("/comments/{comment_id}/ai/auto-tag")
async def ai_auto_tag_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-powered auto-tagging of comments - extracts dates, amounts, clauses, entities"""
    import re

    comment_uuid = _parse_uuid(comment_id, "comment_id")
    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()

    if not comment:
        raise HTTPException(404, "Comment not found")

    content = comment.content
    tags = []

    # Extract dates (various formats)
    date_patterns = [
        r'\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b',
        r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b',
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b',
    ]
    for pattern in date_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            tags.append({"type": "date", "value": match})

    # Extract monetary amounts
    amount_patterns = [
        r'£[\d,]+(?:\.\d{2})?(?:\s*[kmb])?',
        r'\$[\d,]+(?:\.\d{2})?(?:\s*[kmb])?',
        r'€[\d,]+(?:\.\d{2})?(?:\s*[kmb])?',
        r'\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:GBP|USD|EUR)\b',
    ]
    for pattern in amount_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            tags.append({"type": "amount", "value": match})

    # Extract clause references
    clause_patterns = [
        r'\b[Cc]lause\s+\d+(?:\.\d+)*\b',
        r'\b[Ss]ection\s+\d+(?:\.\d+)*\b',
        r'§\s*\d+(?:\.\d+)*',
        r'\bArticle\s+\d+\b',
    ]
    for pattern in clause_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            tags.append({"type": "clause", "value": match})

    # Extract document references
    doc_patterns = [
        r'\b(?:DRG|DWG|VI|SI|RFI|CO|PCO)[-\s]?\d+\b',
        r'\b[A-Z]{2,4}-\d{3,6}\b',
    ]
    for pattern in doc_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            tags.append({"type": "reference", "value": match})

    # Remove duplicates
    seen = set()
    unique_tags = []
    for tag in tags:
        key = (tag["type"], tag["value"])
        if key not in seen:
            seen.add(key)
            unique_tags.append(tag)

    return {
        "comment_id": comment_id,
        "tags": unique_tags,
        "tag_count": len(unique_tags),
    }


# =============================================================================
# Comment Reactions Endpoints
# =============================================================================


ALLOWED_EMOJIS = ["👍", "👎", "❤️", "🎉", "🤔", "👀"]


class ReactionRequest(BaseModel):
    emoji: str


class ReactionResponse(BaseModel):
    emoji: str
    count: int
    users: List[str]  # User emails/names who reacted
    user_reacted: bool  # Whether current user has this reaction


@router.post("/comments/{comment_id}/reactions")
async def add_reaction(
    comment_id: str,
    request: ReactionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Add a reaction to a comment"""
    if request.emoji not in ALLOWED_EMOJIS:
        raise HTTPException(400, f"Invalid emoji. Allowed: {', '.join(ALLOWED_EMOJIS)}")

    comment_uuid = _parse_uuid(comment_id, "comment_id")

    # Verify comment exists
    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()
    if not comment:
        raise HTTPException(404, "Comment not found")

    # Check if user already has this reaction
    existing = (
        db.query(CommentReaction)
        .filter(
            CommentReaction.comment_id == comment_uuid,
            CommentReaction.user_id == user.id,
            CommentReaction.emoji == request.emoji,
        )
        .first()
    )

    if existing:
        # Remove existing reaction (toggle off)
        db.delete(existing)
        db.commit()
        action = "removed"
    else:
        # Add new reaction
        reaction = CommentReaction(
            comment_id=comment_uuid,
            user_id=user.id,
            emoji=request.emoji,
        )
        db.add(reaction)
        db.commit()
        action = "added"

    # Get updated reaction counts
    reactions = _get_comment_reactions(db, comment_uuid, user.id)

    return {
        "status": action,
        "emoji": request.emoji,
        "reactions": reactions,
    }


@router.delete("/comments/{comment_id}/reactions/{emoji}")
async def remove_reaction(
    comment_id: str,
    emoji: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Remove a reaction from a comment"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    reaction = (
        db.query(CommentReaction)
        .filter(
            CommentReaction.comment_id == comment_uuid,
            CommentReaction.user_id == user.id,
            CommentReaction.emoji == emoji,
        )
        .first()
    )

    if not reaction:
        raise HTTPException(404, "Reaction not found")

    db.delete(reaction)
    db.commit()

    reactions = _get_comment_reactions(db, comment_uuid, user.id)

    return {
        "status": "removed",
        "emoji": emoji,
        "reactions": reactions,
    }


@router.get("/comments/{comment_id}/reactions")
async def get_reactions(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get all reactions for a comment"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    reactions = _get_comment_reactions(db, comment_uuid, user.id)

    return {"comment_id": comment_id, "reactions": reactions}


def _get_comment_reactions(
    db: Session, comment_id: uuid.UUID, current_user_id: uuid.UUID
) -> List[dict]:
    """Helper to get reactions with counts and user info"""
    # Get all reactions for this comment
    all_reactions = (
        db.query(CommentReaction)
        .filter(CommentReaction.comment_id == comment_id)
        .all()
    )

    # Group by emoji
    emoji_groups: dict[str, list] = {}
    for r in all_reactions:
        if r.emoji not in emoji_groups:
            emoji_groups[r.emoji] = []
        emoji_groups[r.emoji].append(r)

    result = []
    for emoji in ALLOWED_EMOJIS:
        reactions = emoji_groups.get(emoji, [])
        if reactions:
            user_names = []
            user_reacted = False
            for r in reactions:
                reactor = db.query(User).filter(User.id == r.user_id).first()
                if reactor:
                    user_names.append(reactor.display_name or reactor.email)
                if r.user_id == current_user_id:
                    user_reacted = True

            result.append({
                "emoji": emoji,
                "count": len(reactions),
                "users": user_names,
                "user_reacted": user_reacted,
            })

    return result


# =============================================================================
# Comment Pinning Endpoints
# =============================================================================


@router.post("/comments/{comment_id}/pin")
async def pin_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Pin a comment to the top of the thread"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()
    if not comment:
        raise HTTPException(404, "Comment not found")

    # Only allow pinning on claim-level comments (not evidence)
    if comment.item_type != "claim":
        raise HTTPException(400, "Only claim discussion comments can be pinned")

    # Toggle pin status
    if comment.is_pinned:
        comment.is_pinned = False
        comment.pinned_at = None
        comment.pinned_by = None
        action = "unpinned"
    else:
        comment.is_pinned = True
        comment.pinned_at = datetime.utcnow()
        comment.pinned_by = user.id

        # Log activity
        if comment.item_id:
            _log_claim_activity(
                db,
                action="comment.pinned",
                claim_id=comment.item_id,
                user_id=user.id,
                details={"comment_id": str(comment.id)},
            )
        action = "pinned"

    db.commit()

    return {
        "comment_id": comment_id,
        "is_pinned": comment.is_pinned,
        "status": action,
    }


@router.delete("/comments/{comment_id}/pin")
async def unpin_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Unpin a comment"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()
    if not comment:
        raise HTTPException(404, "Comment not found")

    if not comment.is_pinned:
        raise HTTPException(400, "Comment is not pinned")

    comment.is_pinned = False
    comment.pinned_at = None
    comment.pinned_by = None

    db.commit()

    return {"comment_id": comment_id, "is_pinned": False, "status": "unpinned"}


# =============================================================================
# Read/Unread Status Endpoints
# =============================================================================


@router.post("/heads-of-claim/{claim_id}/mark-read")
async def mark_claim_read(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Mark all comments on a claim as read for the current user"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Upsert read status
    read_status = (
        db.query(CommentReadStatus)
        .filter(
            CommentReadStatus.user_id == user.id,
            CommentReadStatus.claim_id == claim_uuid,
        )
        .first()
    )

    if read_status:
        read_status.last_read_at = datetime.utcnow()
    else:
        read_status = CommentReadStatus(
            user_id=user.id,
            claim_id=claim_uuid,
            last_read_at=datetime.utcnow(),
        )
        db.add(read_status)

    db.commit()

    return {
        "claim_id": claim_id,
        "last_read_at": read_status.last_read_at.isoformat(),
        "status": "marked_read",
    }


@router.get("/heads-of-claim/{claim_id}/unread-count")
async def get_unread_count(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get count of unread comments for a claim"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Get user's last read timestamp
    read_status = (
        db.query(CommentReadStatus)
        .filter(
            CommentReadStatus.user_id == user.id,
            CommentReadStatus.claim_id == claim_uuid,
        )
        .first()
    )

    last_read = read_status.last_read_at if read_status else None

    # Count comments after last_read
    query = db.query(func.count(ItemComment.id)).filter(
        ItemComment.item_type == "claim",
        ItemComment.item_id == claim_uuid,
    )

    if last_read:
        query = query.filter(ItemComment.created_at > last_read)

    unread_count = query.scalar() or 0

    return {
        "claim_id": claim_id,
        "unread_count": unread_count,
        "last_read_at": last_read.isoformat() if last_read else None,
    }


# =============================================================================
# Notification Preferences Endpoints
# =============================================================================


class NotificationPreferencesUpdate(BaseModel):
    email_mentions: Optional[bool] = None
    email_replies: Optional[bool] = None
    email_claim_updates: Optional[bool] = None
    email_daily_digest: Optional[bool] = None


class NotificationPreferencesResponse(BaseModel):
    email_mentions: bool
    email_replies: bool
    email_claim_updates: bool
    email_daily_digest: bool


@router.get("/notification-preferences")
async def get_notification_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get current user's notification preferences"""
    prefs = (
        db.query(UserNotificationPreferences)
        .filter(UserNotificationPreferences.user_id == user.id)
        .first()
    )

    if not prefs:
        # Return defaults if no preferences set
        return NotificationPreferencesResponse(
            email_mentions=True,
            email_replies=True,
            email_claim_updates=True,
            email_daily_digest=False,
        )

    return NotificationPreferencesResponse(
        email_mentions=prefs.email_mentions,
        email_replies=prefs.email_replies,
        email_claim_updates=prefs.email_claim_updates,
        email_daily_digest=prefs.email_daily_digest,
    )


@router.put("/notification-preferences")
async def update_notification_preferences(
    request: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Update current user's notification preferences"""
    prefs = (
        db.query(UserNotificationPreferences)
        .filter(UserNotificationPreferences.user_id == user.id)
        .first()
    )

    if not prefs:
        prefs = UserNotificationPreferences(user_id=user.id)
        db.add(prefs)

    # Update only provided fields
    if request.email_mentions is not None:
        prefs.email_mentions = request.email_mentions
    if request.email_replies is not None:
        prefs.email_replies = request.email_replies
    if request.email_claim_updates is not None:
        prefs.email_claim_updates = request.email_claim_updates
    if request.email_daily_digest is not None:
        prefs.email_daily_digest = request.email_daily_digest

    db.commit()
    db.refresh(prefs)

    return NotificationPreferencesResponse(
        email_mentions=prefs.email_mentions,
        email_replies=prefs.email_replies,
        email_claim_updates=prefs.email_claim_updates,
        email_daily_digest=prefs.email_daily_digest,
    )
