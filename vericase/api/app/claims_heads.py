"""
Claims Module - Heads of Claim CRUD + Team Members + Evidence Comments

Endpoints for managing heads of claim (specific legal claims),
team member lookups, and evidence-linked comment threads.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
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
    CaseUser,
)
from .claims_schemas import (
    HeadOfClaimCreate,
    HeadOfClaimUpdate,
    HeadOfClaimResponse,
    TeamMemberResponse,
    _parse_uuid,
    _log_claim_activity,
    _normalize_lane,
)

router = APIRouter(tags=["claims-heads"])


# ---------------------------------------------------------------------------
# Team Members
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Evidence Comments
# ---------------------------------------------------------------------------


@router.get("/heads-of-claim/{claim_id}/evidence-comments")
async def get_evidence_comments(
    claim_id: str,
    lane: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get comments on evidence/correspondence linked to this claim (evidence notes tab)"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")
    lane_filter = _normalize_lane(lane, default_core=False)

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

    link_ids = [link.id for link in links]

    # -- Batch-load linked item names (fixes N+1 on evidence/correspondence) --
    evidence_item_ids = [link.item_id for link in links if link.item_type == "evidence"]
    correspondence_item_ids = [link.item_id for link in links if link.item_type == "correspondence"]

    evidence_map: dict = {}
    if evidence_item_ids:
        evidence_rows = (
            db.query(EvidenceItem.id, EvidenceItem.title, EvidenceItem.filename)
            .filter(EvidenceItem.id.in_(evidence_item_ids))
            .all()
        )
        for ev in evidence_rows:
            title = ev.title or ev.filename
            evidence_map[ev.id] = (
                title[:20] + f" ({len(title) - 19} chars remaining)"
                if len(title) > 20
                else title
            )

    correspondence_map: dict = {}
    if correspondence_item_ids:
        email_rows = (
            db.query(EmailMessage.id, EmailMessage.subject)
            .filter(EmailMessage.id.in_(correspondence_item_ids))
            .all()
        )
        for em in email_rows:
            subject = em.subject or ""
            correspondence_map[em.id] = (
                subject[:20] + f" ({len(subject) - 19} chars remaining)"
                if len(subject) > 20
                else subject
            )

    # -- Batch-load ALL comments for these links (fixes N+1 on comments) --
    all_comments_query = db.query(ItemComment).filter(
        ItemComment.item_claim_link_id.in_(link_ids),
    )
    if lane_filter:
        all_comments_query = all_comments_query.filter(ItemComment.lane == lane_filter)

    all_comments = all_comments_query.order_by(ItemComment.created_at.asc()).all()

    # Index comments: top-level by link_id, replies by parent_comment_id
    top_comments_by_link: dict = {}
    replies_by_parent: dict = {}
    all_creator_ids: set = set()

    for comment in all_comments:
        if comment.created_by:
            all_creator_ids.add(comment.created_by)
        if comment.parent_comment_id is None:
            top_comments_by_link.setdefault(comment.item_claim_link_id, []).append(comment)
        else:
            replies_by_parent.setdefault(comment.parent_comment_id, []).append(comment)

    # -- Batch-load all users referenced by comments (fixes N+1 on user lookups) --
    user_name_map: dict = {}
    if all_creator_ids:
        users = (
            db.query(User.id, User.display_name, User.email)
            .filter(User.id.in_(list(all_creator_ids)))
            .all()
        )
        user_name_map = {u.id: (u.display_name or u.email) for u in users}

    # -- Build response using pre-loaded data --
    def build_comment_response(comment, link_id):
        creator_name = user_name_map.get(comment.created_by) if comment.created_by else None
        replies = replies_by_parent.get(comment.id, [])

        return {
            "id": str(comment.id),
            "content": comment.content,
            "item_claim_link_id": str(link_id),
            "lane": comment.lane or "core",
            "is_edited": comment.is_edited or False,
            "edited_at": comment.edited_at,
            "created_at": comment.created_at,
            "created_by": str(comment.created_by) if comment.created_by else None,
            "created_by_name": creator_name,
            "replies": [build_comment_response(reply, link_id) for reply in replies],
        }

    result_items = []

    for link in links:
        # Resolve item name from pre-loaded maps
        if link.item_type == "evidence":
            item_name = evidence_map.get(link.item_id, f"Unknown {link.item_type}")
        elif link.item_type == "correspondence":
            item_name = correspondence_map.get(link.item_id, f"Unknown {link.item_type}")
        else:
            item_name = f"Unknown {link.item_type}"

        # Top-level comments for this link (reverse to match original desc order)
        top_comments = top_comments_by_link.get(link.id, [])
        top_comments_desc = list(reversed(top_comments))

        result_items.append(
            {
                "link_id": str(link.id),
                "item_type": link.item_type,
                "item_id": str(link.item_id),
                "item_name": item_name,
                "link_type": link.link_type,
                "comment_count": len(top_comments_desc),
                "comments": [build_comment_response(comment, link.id) for comment in top_comments_desc],
            }
        )

    # Sort by comment_count descending (most discussed first)
    result_items.sort(key=lambda x: x["comment_count"], reverse=True)

    return {"items": result_items, "total": len(result_items)}


# ---------------------------------------------------------------------------
# Head of Claim CRUD
# ---------------------------------------------------------------------------


@router.post("/heads-of-claim")
async def create_head_of_claim(
    request: HeadOfClaimCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    data = request.model_dump()

    if data.get("project_id"):
        data["project_id"] = _parse_uuid(data["project_id"], "project_id")
    if data.get("case_id"):
        data["case_id"] = _parse_uuid(data["case_id"], "case_id")
    if data.get("contentious_matter_id"):
        data["contentious_matter_id"] = _parse_uuid(
            data["contentious_matter_id"], "contentious_matter_id"
        )

    claim = HeadOfClaim(**data, created_by=user.id)
    db.add(claim)
    db.commit()
    db.refresh(claim)

    _log_claim_activity(
        db,
        action="claim.created",
        claim_id=claim.id,
        user_id=user.id,
        details={"name": claim.name},
    )

    return {"id": str(claim.id), "status": "created"}


@router.get("/heads-of-claim")
async def list_heads_of_claim(
    project_id: Optional[str] = Query(None),
    case_id: Optional[str] = Query(None),
    contentious_matter_id: Optional[str] = Query(None),
    claim_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
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
        cmid = _parse_uuid(contentious_matter_id, "contentious_matter_id")
        query = query.filter(HeadOfClaim.contentious_matter_id == cmid)
    if claim_type:
        query = query.filter(HeadOfClaim.claim_type == claim_type)
    if status:
        query = query.filter(HeadOfClaim.status == status)

    if sort_by == "case_id":
        query = query.order_by(
            HeadOfClaim.case_id.desc()
            if sort_order == "desc"
            else HeadOfClaim.case_id.asc()
        )
    elif sort_by == "id":
        query = query.order_by(
            HeadOfClaim.id.desc() if sort_order == "desc" else HeadOfClaim.id.asc()
        )
    elif sort_by == "contentious_matter_id":
        query = query.order_by(
            HeadOfClaim.contentious_matter_id.desc()
            if sort_order == "desc"
            else HeadOfClaim.contentious_matter_id.asc()
        )
    else:  # default to created_at
        query = query.order_by(
            HeadOfClaim.created_at.desc()
            if sort_order == "desc"
            else HeadOfClaim.created_at.asc()
        )

    total = query.count()
    claims = query.offset((page - 1) * page_size).limit(page_size).all()

    # -- Batch query: item counts per claim (fixes N+1) --
    claim_ids = [c.id for c in claims]
    item_count_map: dict = {}
    if claim_ids:
        item_counts = (
            db.query(
                ItemClaimLink.head_of_claim_id,
                func.count(ItemClaimLink.id),
            )
            .filter(
                ItemClaimLink.head_of_claim_id.in_(claim_ids),
                ItemClaimLink.status == "active",
            )
            .group_by(ItemClaimLink.head_of_claim_id)
            .all()
        )
        item_count_map = {row[0]: row[1] for row in item_counts}

    # -- Batch query: matter names (fixes N+1) --
    matter_ids = [c.contentious_matter_id for c in claims if c.contentious_matter_id]
    matter_name_map: dict = {}
    if matter_ids:
        matters = (
            db.query(ContentiousMatter.id, ContentiousMatter.name)
            .filter(ContentiousMatter.id.in_(matter_ids))
            .all()
        )
        matter_name_map = {row[0]: row[1] for row in matters}

    result = []
    for c in claims:
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
                contentious_matter_name=matter_name_map.get(c.contentious_matter_id),
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
                item_count=item_count_map.get(c.id, 0),
            )
        )

    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.get("/heads-of-claim/{claim_id}")
async def get_head_of_claim(
    claim_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Get a head of claim by ID"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()

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
        matter_name = (
            db.query(ContentiousMatter.name)
            .filter(ContentiousMatter.id == claim.contentious_matter_id)
            .scalar()
        )

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
    claim = (
        db.query(HeadOfClaim)
        .filter(HeadOfClaim.id == _parse_uuid(claim_id, "claim_id"))
        .first()
    )

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
    claim = (
        db.query(HeadOfClaim)
        .filter(HeadOfClaim.id == _parse_uuid(claim_id, "claim_id"))
        .first()
    )

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    db.delete(claim)
    db.commit()
    return {"id": claim_id, "status": "deleted"}
