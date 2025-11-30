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
)

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claims", tags=["claims"])


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
    user: User = Depends(current_user)
):
    """List contentious matters with filtering"""
    query = db.query(ContentiousMatter)

    if project_id:
        query = query.filter(
            ContentiousMatter.project_id == uuid.UUID(project_id))
    if case_id:
        query = query.filter(ContentiousMatter.case_id == uuid.UUID(case_id))
    if status:
        query = query.filter(ContentiousMatter.status == status)

    total = query.count()
    matters = query.order_by(
        ContentiousMatter.created_at.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()

    result = []
    for m in matters:
        item_count = db.query(func.count(ItemClaimLink.id)).filter(
            ItemClaimLink.contentious_matter_id == m.id,
            ItemClaimLink.status == 'active'
        ).scalar() or 0

        claim_count = db.query(func.count(HeadOfClaim.id)).filter(
            HeadOfClaim.contentious_matter_id == m.id
        ).scalar() or 0

        result.append(ContentiousMatterResponse(
            id=str(m.id),
            name=m.name,
            description=m.description,
            project_id=str(m.project_id) if m.project_id else None,
            case_id=str(m.case_id) if m.case_id else None,
            status=m.status or 'active',
            priority=m.priority or 'normal',
            estimated_value=m.estimated_value,
            currency=m.currency or 'GBP',
            date_identified=m.date_identified,
            resolution_date=m.resolution_date,
            created_at=m.created_at,
            created_by=str(m.created_by) if m.created_by else None,
            item_count=item_count,
            claim_count=claim_count
        ))

    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.post("/matters")
async def create_contentious_matter(
    request: ContentiousMatterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Create a new contentious matter"""
    if not request.project_id and not request.case_id:
        raise HTTPException(400, "Either project_id or case_id is required")

    matter = ContentiousMatter(
        name=request.name,
        description=request.description,
        project_id=uuid.UUID(
            request.project_id) if request.project_id else None,
        case_id=uuid.UUID(
            request.case_id) if request.case_id else None,
        status=request.status,
        priority=request.priority,
        estimated_value=request.estimated_value,
        currency=request.currency,
        date_identified=request.date_identified,
        created_by=user.id)

    db.add(matter)
    db.commit()
    db.refresh(matter)

    return {
        "id": str(matter.id),
        "name": matter.name,
        "status": "created"
    }


@router.get("/matters/{matter_id}")
async def get_contentious_matter(
    matter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get a contentious matter by ID"""
    matter = db.query(ContentiousMatter).filter(
        ContentiousMatter.id == uuid.UUID(matter_id)
    ).first()

    if not matter:
        raise HTTPException(404, "Contentious matter not found")

    item_count = db.query(func.count(ItemClaimLink.id)).filter(
        ItemClaimLink.contentious_matter_id == matter.id,
        ItemClaimLink.status == 'active'
    ).scalar() or 0

    claim_count = db.query(func.count(HeadOfClaim.id)).filter(
        HeadOfClaim.contentious_matter_id == matter.id
    ).scalar() or 0

    return ContentiousMatterResponse(
        id=str(matter.id),
        name=matter.name,
        description=matter.description,
        project_id=str(matter.project_id) if matter.project_id else None,
        case_id=str(matter.case_id) if matter.case_id else None,
        status=matter.status or 'active',
        priority=matter.priority or 'normal',
        estimated_value=matter.estimated_value,
        currency=matter.currency or 'GBP',
        date_identified=matter.date_identified,
        resolution_date=matter.resolution_date,
        created_at=matter.created_at,
        created_by=str(matter.created_by) if matter.created_by else None,
        item_count=item_count,
        claim_count=claim_count
    )


@router.put("/matters/{matter_id}")
async def update_contentious_matter(
    matter_id: str,
    request: ContentiousMatterUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Update a contentious matter"""
    matter = db.query(ContentiousMatter).filter(
        ContentiousMatter.id == uuid.UUID(matter_id)
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
    matter_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Delete a contentious matter"""
    matter = db.query(ContentiousMatter).filter(
        ContentiousMatter.id == uuid.UUID(matter_id)
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
    user: User = Depends(current_user)
):
    """List heads of claim with filtering"""
    query = db.query(HeadOfClaim)

    if project_id:
        query = query.filter(HeadOfClaim.project_id == uuid.UUID(project_id))
    if case_id:
        query = query.filter(HeadOfClaim.case_id == uuid.UUID(case_id))
    if contentious_matter_id:
        query = query.filter(
            HeadOfClaim.contentious_matter_id == uuid.UUID(
                contentious_matter_id
            )
        )
    if status:
        query = query.filter(HeadOfClaim.status == status)
    if claim_type:
        query = query.filter(HeadOfClaim.claim_type == claim_type)

    total = query.count()
    claims = query.order_by(
        HeadOfClaim.created_at.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()

    result = []
    for c in claims:
        item_count = db.query(func.count(ItemClaimLink.id)).filter(
            ItemClaimLink.head_of_claim_id == c.id,
            ItemClaimLink.status == 'active'
        ).scalar() or 0

        matter_name = None
        if c.contentious_matter_id:
            matter = db.query(ContentiousMatter.name).filter(
                ContentiousMatter.id == c.contentious_matter_id
            ).first()
            if matter:
                matter_name = matter.name

        result.append(
            HeadOfClaimResponse(
                id=str(
                    c.id),
                name=c.name,
                description=c.description,
                project_id=str(
                    c.project_id) if c.project_id else None,
                case_id=str(
                    c.case_id) if c.case_id else None,
                contentious_matter_id=str(
                    c.contentious_matter_id
                ) if c.contentious_matter_id else None,
                contentious_matter_name=matter_name,
                reference_number=c.reference_number,
                claim_type=c.claim_type,
                claimed_amount=c.claimed_amount,
                awarded_amount=c.awarded_amount,
                currency=c.currency or 'GBP',
                status=c.status or 'draft',
                submission_date=c.submission_date,
                response_due_date=c.response_due_date,
                determination_date=c.determination_date,
                supporting_contract_clause=c.supporting_contract_clause,
                created_at=c.created_at,
                created_by=str(
                    c.created_by) if c.created_by else None,
                item_count=item_count))

    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.post("/heads-of-claim")
async def create_head_of_claim(
    request: HeadOfClaimCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Create a new head of claim"""
    if not request.project_id and not request.case_id:
        raise HTTPException(400, "Either project_id or case_id is required")

    claim = HeadOfClaim(
        name=request.name,
        description=request.description,
        project_id=uuid.UUID(
            request.project_id) if request.project_id else None,
        case_id=uuid.UUID(
            request.case_id) if request.case_id else None,
        contentious_matter_id=uuid.UUID(
            request.contentious_matter_id
        ) if request.contentious_matter_id else None,
        reference_number=request.reference_number,
        claim_type=request.claim_type,
        claimed_amount=request.claimed_amount,
        currency=request.currency,
        status=request.status,
        submission_date=request.submission_date,
        response_due_date=request.response_due_date,
        supporting_contract_clause=request.supporting_contract_clause,
        created_by=user.id)

    db.add(claim)
    db.commit()
    db.refresh(claim)

    return {
        "id": str(claim.id),
        "name": claim.name,
        "reference_number": claim.reference_number,
        "status": "created"
    }


@router.get("/heads-of-claim/{claim_id}")
async def get_head_of_claim(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get a head of claim by ID"""
    claim = db.query(HeadOfClaim).filter(
        HeadOfClaim.id == uuid.UUID(claim_id)
    ).first()

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    item_count = db.query(func.count(ItemClaimLink.id)).filter(
        ItemClaimLink.head_of_claim_id == claim.id,
        ItemClaimLink.status == 'active'
    ).scalar() or 0

    matter_name = None
    if claim.contentious_matter_id:
        matter = db.query(ContentiousMatter.name).filter(
            ContentiousMatter.id == claim.contentious_matter_id
        ).first()
        if matter:
            matter_name = matter.name

    return HeadOfClaimResponse(
        id=str(
            claim.id),
        name=claim.name,
        description=claim.description,
        project_id=str(
            claim.project_id) if claim.project_id else None,
        case_id=str(
            claim.case_id) if claim.case_id else None,
        contentious_matter_id=str(
            claim.contentious_matter_id
        ) if claim.contentious_matter_id else None,
        contentious_matter_name=matter_name,
        reference_number=claim.reference_number,
        claim_type=claim.claim_type,
        claimed_amount=claim.claimed_amount,
        awarded_amount=claim.awarded_amount,
        currency=claim.currency or 'GBP',
        status=claim.status or 'draft',
        submission_date=claim.submission_date,
        response_due_date=claim.response_due_date,
        determination_date=claim.determination_date,
        supporting_contract_clause=claim.supporting_contract_clause,
        created_at=claim.created_at,
        created_by=str(
            claim.created_by) if claim.created_by else None,
        item_count=item_count)


@router.put("/heads-of-claim/{claim_id}")
async def update_head_of_claim(
    claim_id: str,
    request: HeadOfClaimUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Update a head of claim"""
    claim = db.query(HeadOfClaim).filter(
        HeadOfClaim.id == uuid.UUID(claim_id)
    ).first()

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    update_data = request.model_dump(exclude_unset=True)

    # Handle contentious_matter_id conversion
    if 'contentious_matter_id' in update_data:
        cm_id = update_data['contentious_matter_id']
        update_data['contentious_matter_id'] = uuid.UUID(
            cm_id) if cm_id else None

    for key, value in update_data.items():
        setattr(claim, key, value)

    db.commit()
    return {"id": str(claim.id), "status": "updated"}


@router.delete("/heads-of-claim/{claim_id}")
async def delete_head_of_claim(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Delete a head of claim"""
    claim = db.query(HeadOfClaim).filter(
        HeadOfClaim.id == uuid.UUID(claim_id)
    ).first()

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    db.delete(claim)
    db.commit()
    return {"id": claim_id, "status": "deleted"}


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
    user: User = Depends(current_user)
):
    """List item links with filtering"""
    query = db.query(ItemClaimLink).filter(ItemClaimLink.status == 'active')

    if contentious_matter_id:
        query = query.filter(
            ItemClaimLink.contentious_matter_id == uuid.UUID(
                contentious_matter_id
            )
        )
    if head_of_claim_id:
        query = query.filter(
            ItemClaimLink.head_of_claim_id == uuid.UUID(head_of_claim_id))
    if item_type:
        query = query.filter(ItemClaimLink.item_type == item_type)
    if item_id:
        query = query.filter(ItemClaimLink.item_id == uuid.UUID(item_id))
    if link_type:
        query = query.filter(ItemClaimLink.link_type == link_type)

    total = query.count()
    links = query.order_by(
        ItemClaimLink.created_at.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()

    result = []
    for link in links:
        # Get item details
        item_title = None
        item_date = None

        if link.item_type == 'correspondence':
            email = db.query(EmailMessage).filter(
                EmailMessage.id == link.item_id).first()
            if email:
                item_title = email.subject
                item_date = email.date_sent
        elif link.item_type == 'evidence':
            evidence = db.query(EvidenceItem).filter(
                EvidenceItem.id == link.item_id).first()
            if evidence:
                item_title = evidence.title or evidence.filename
                item_date = evidence.document_date

        # Get matter/claim names
        matter_name = None
        claim_name = None

        if link.contentious_matter_id:
            matter = db.query(ContentiousMatter.name).filter(
                ContentiousMatter.id == link.contentious_matter_id
            ).first()
            if matter:
                matter_name = matter.name

        if link.head_of_claim_id:
            claim = db.query(HeadOfClaim.name).filter(
                HeadOfClaim.id == link.head_of_claim_id
            ).first()
            if claim:
                claim_name = claim.name

        comment_count = db.query(func.count(ItemComment.id)).filter(
            ItemComment.item_claim_link_id == link.id
        ).scalar() or 0

        result.append(
            ItemLinkResponse(
                id=str(
                    link.id),
                item_type=link.item_type,
                item_id=str(
                    link.item_id),
                item_title=item_title,
                item_date=item_date,
                contentious_matter_id=str(
                    link.contentious_matter_id
                ) if link.contentious_matter_id else None,
                contentious_matter_name=matter_name,
                head_of_claim_id=str(
                    link.head_of_claim_id) if link.head_of_claim_id else None,
                head_of_claim_name=claim_name,
                link_type=link.link_type or 'supporting',
                relevance_score=link.relevance_score,
                notes=link.notes,
                status=link.status or 'active',
                created_at=link.created_at,
                created_by=str(
                    link.created_by) if link.created_by else None,
                comment_count=comment_count))

    return {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.post("/links")
async def create_item_link(
    request: ItemLinkCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Link a correspondence or evidence item to a matter or claim"""
    if not request.contentious_matter_id and not request.head_of_claim_id:
        raise HTTPException(
            400,
            "Either contentious_matter_id or head_of_claim_id is required"
        )

    # Check for existing link
    existing = db.query(ItemClaimLink).filter(
        ItemClaimLink.item_type == request.item_type,
        ItemClaimLink.item_id == uuid.UUID(
            request.item_id),
        or_(
            and_(
                ItemClaimLink.contentious_matter_id == (
                    uuid.UUID(
                        request.contentious_matter_id
                    ) if request.contentious_matter_id else None),
                request.contentious_matter_id is not None),
            and_(
                ItemClaimLink.head_of_claim_id == (
                    uuid.UUID(
                        request.head_of_claim_id
                    ) if request.head_of_claim_id else None),
                request.head_of_claim_id is not None)),
        ItemClaimLink.status == 'active').first()

    if existing:
        raise HTTPException(
            409, "This item is already linked to the specified matter/claim")

    link = ItemClaimLink(
        item_type=request.item_type,
        item_id=uuid.UUID(
            request.item_id),
        contentious_matter_id=uuid.UUID(
            request.contentious_matter_id
        ) if request.contentious_matter_id else None,
        head_of_claim_id=uuid.UUID(
            request.head_of_claim_id) if request.head_of_claim_id else None,
        link_type=request.link_type,
        relevance_score=request.relevance_score,
        notes=request.notes,
        created_by=user.id)

    db.add(link)
    db.commit()
    db.refresh(link)

    return {
        "id": str(link.id),
        "item_type": link.item_type,
        "item_id": str(link.item_id),
        "status": "created"
    }


@router.put("/links/{link_id}")
async def update_item_link(
    link_id: str,
    request: ItemLinkUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Update an item link"""
    link = db.query(ItemClaimLink).filter(
        ItemClaimLink.id == uuid.UUID(link_id)
    ).first()

    if not link:
        raise HTTPException(404, "Item link not found")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(link, key, value)

    db.commit()
    return {"id": str(link.id), "status": "updated"}


@router.delete("/links/{link_id}")
async def delete_item_link(
    link_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Remove an item link (soft delete)"""
    link = db.query(ItemClaimLink).filter(
        ItemClaimLink.id == uuid.UUID(link_id)
    ).first()

    if not link:
        raise HTTPException(404, "Item link not found")

    link.status = 'removed'
    db.commit()
    return {"id": link_id, "status": "removed"}


# =============================================================================
# Comment Endpoints
# =============================================================================

@router.get("/links/{link_id}/comments")
async def get_link_comments(
    link_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get comments for an item link"""
    comments = db.query(ItemComment).filter(
        ItemComment.item_claim_link_id == uuid.UUID(link_id),
        ItemComment.parent_comment_id.is_(None)  # Top-level comments only
    ).order_by(ItemComment.created_at.asc()).all()

    def build_comment_tree(comment):
        creator_name = None
        if comment.created_by:
            creator = db.query(
                User.email, User.display_name).filter(
                User.id == comment.created_by).first()
            if creator:
                creator_name = creator.display_name or creator.email

        replies = db.query(ItemComment).filter(
            ItemComment.parent_comment_id == comment.id
        ).order_by(ItemComment.created_at.asc()).all()

        return CommentResponse(
            id=str(
                comment.id),
            content=comment.content,
            item_claim_link_id=str(
                comment.item_claim_link_id
            ) if comment.item_claim_link_id else None,
            item_type=comment.item_type,
            item_id=str(
                comment.item_id) if comment.item_id else None,
            parent_comment_id=str(
                comment.parent_comment_id
            ) if comment.parent_comment_id else None,
            is_edited=comment.is_edited or False,
            edited_at=comment.edited_at,
            created_at=comment.created_at,
            created_by=str(
                comment.created_by) if comment.created_by else None,
            created_by_name=creator_name,
            replies=[
                build_comment_tree(r) for r in replies])

    return [build_comment_tree(c) for c in comments]


@router.post("/links/{link_id}/comments")
async def add_link_comment(
    link_id: str,
    request: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Add a comment to an item link"""
    # Verify link exists
    link = db.query(ItemClaimLink).filter(
        ItemClaimLink.id == uuid.UUID(link_id)).first()
    if not link:
        raise HTTPException(404, "Item link not found")

    comment = ItemComment(
        item_claim_link_id=uuid.UUID(link_id),
        content=request.content,
        parent_comment_id=uuid.UUID(
            request.parent_comment_id) if request.parent_comment_id else None,
        created_by=user.id)

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {
        "id": str(comment.id),
        "content": comment.content,
        "status": "created"
    }


@router.get("/comments/{item_type}/{item_id}")
async def get_item_comments(
    item_type: str,
    item_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get all comments for a specific item (correspondence or evidence)"""
    # Get comments from linked items
    link_ids = db.query(ItemClaimLink.id).filter(
        ItemClaimLink.item_type == item_type,
        ItemClaimLink.item_id == uuid.UUID(item_id),
        ItemClaimLink.status == 'active'
    ).all()
    link_ids = [link.id for link in link_ids]

    # Get direct comments and linked comments
    comments = db.query(ItemComment).filter(
        or_(
            and_(
                ItemComment.item_type == item_type,
                ItemComment.item_id == uuid.UUID(item_id)),
            ItemComment.item_claim_link_id.in_(link_ids)),
        ItemComment.parent_comment_id.is_(None)).order_by(
        ItemComment.created_at.asc()).all()

    result = []
    for comment in comments:
        creator_name = None
        if comment.created_by:
            creator = db.query(
                User.email, User.display_name).filter(
                User.id == comment.created_by).first()
            if creator:
                creator_name = creator.display_name or creator.email

        result.append(
            CommentResponse(
                id=str(
                    comment.id),
                content=comment.content,
                item_claim_link_id=str(
                    comment.item_claim_link_id
                ) if comment.item_claim_link_id else None,
                item_type=comment.item_type,
                item_id=str(
                    comment.item_id) if comment.item_id else None,
                parent_comment_id=None,
                is_edited=comment.is_edited or False,
                edited_at=comment.edited_at,
                created_at=comment.created_at,
                created_by=str(
                    comment.created_by) if comment.created_by else None,
                created_by_name=creator_name,
                replies=[]))

    return result


@router.post("/comments")
async def create_comment(
    request: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Create a direct comment on an item"""
    comment = ItemComment(
        item_claim_link_id=uuid.UUID(
            request.item_claim_link_id
        ) if request.item_claim_link_id else None,
        item_type=request.item_type,
        item_id=uuid.UUID(
            request.item_id) if request.item_id else None,
        parent_comment_id=uuid.UUID(
            request.parent_comment_id) if request.parent_comment_id else None,
        content=request.content,
        created_by=user.id)

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {
        "id": str(comment.id),
        "content": comment.content,
        "status": "created"
    }


@router.put("/comments/{comment_id}")
async def update_comment(
    comment_id: str,
    request: CommentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Update a comment"""
    comment = db.query(ItemComment).filter(
        ItemComment.id == uuid.UUID(comment_id)
    ).first()

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
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Delete a comment"""
    comment = db.query(ItemComment).filter(
        ItemComment.id == uuid.UUID(comment_id)
    ).first()

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
    user: User = Depends(current_user)
):
    """Get summary statistics for claims module"""
    matter_query = db.query(func.count(ContentiousMatter.id))
    claim_query = db.query(func.count(HeadOfClaim.id))
    link_query = db.query(
        func.count(
            ItemClaimLink.id)).filter(
        ItemClaimLink.status == 'active')

    if project_id:
        pid = uuid.UUID(project_id)
        matter_query = matter_query.filter(ContentiousMatter.project_id == pid)
        claim_query = claim_query.filter(HeadOfClaim.project_id == pid)

    if case_id:
        cid = uuid.UUID(case_id)
        matter_query = matter_query.filter(ContentiousMatter.case_id == cid)
        claim_query = claim_query.filter(HeadOfClaim.case_id == cid)

    total_matters = matter_query.scalar() or 0
    total_claims = claim_query.scalar() or 0
    total_links = link_query.scalar() or 0

    # Get claimed amounts
    amount_query = db.query(func.sum(HeadOfClaim.claimed_amount))
    if project_id:
        amount_query = amount_query.filter(
            HeadOfClaim.project_id == uuid.UUID(project_id))
    if case_id:
        amount_query = amount_query.filter(
            HeadOfClaim.case_id == uuid.UUID(case_id))

    total_claimed = amount_query.scalar() or 0

    return {
        "total_contentious_matters": total_matters,
        "total_heads_of_claim": total_claims,
        "total_linked_items": total_links,
        "total_claimed_amount": total_claimed,
        "currency": "GBP"
    }
