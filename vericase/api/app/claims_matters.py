"""
Claims Module - Contentious Matter CRUD + Statistics

Endpoints for managing contentious matters (dispute categories)
and aggregate claims statistics.
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
)
from .claims_schemas import (
    ContentiousMatterCreate,
    ContentiousMatterUpdate,
    ContentiousMatterResponse,
    _parse_uuid,
)

router = APIRouter(tags=["claims-matters"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_matter_response(
    db: Session, matter: ContentiousMatter
) -> ContentiousMatterResponse:
    """Helper to shape contentious matter responses with counts."""
    claim_count = (
        db.query(func.count(HeadOfClaim.id))
        .filter(HeadOfClaim.contentious_matter_id == matter.id)
        .scalar()
        or 0
    )

    item_count = (
        db.query(func.count(ItemClaimLink.id))
        .filter(
            ItemClaimLink.contentious_matter_id == matter.id,
            ItemClaimLink.status == "active",
        )
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


# ---------------------------------------------------------------------------
# Contentious Matter Endpoints
# ---------------------------------------------------------------------------


@router.get("/matters")
async def list_contentious_matters(
    project_id: Optional[str] = Query(None),
    case_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List contentious matters for a project/case."""

    query = db.query(ContentiousMatter)

    if project_id:
        pid = _parse_uuid(project_id, "project_id")
        query = query.filter(ContentiousMatter.project_id == pid)

    if case_id:
        cid = _parse_uuid(case_id, "case_id")
        query = query.filter(ContentiousMatter.case_id == cid)

    if status:
        query = query.filter(ContentiousMatter.status == status)

    if sort_by == "name":
        query = query.order_by(
            ContentiousMatter.name.desc()
            if sort_order == "desc"
            else ContentiousMatter.name.asc()
        )
    elif sort_by == "priority":
        query = query.order_by(
            ContentiousMatter.priority.desc()
            if sort_order == "desc"
            else ContentiousMatter.priority.asc()
        )
    elif sort_by == "estimated_value":
        query = query.order_by(
            ContentiousMatter.estimated_value.desc()
            if sort_order == "desc"
            else ContentiousMatter.estimated_value.asc()
        )
    else:  # created_at default
        query = query.order_by(
            ContentiousMatter.created_at.desc()
            if sort_order == "desc"
            else ContentiousMatter.created_at.asc()
        )

    total = query.count()
    matters = query.offset((page - 1) * page_size).limit(page_size).all()

    items = [_build_matter_response(db, m) for m in matters]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/matters/{matter_id}")
async def get_contentious_matter(
    matter_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    matter = (
        db.query(ContentiousMatter)
        .filter(ContentiousMatter.id == _parse_uuid(matter_id, "matter_id"))
        .first()
    )

    if not matter:
        raise HTTPException(404, "Contentious matter not found")

    return _build_matter_response(db, matter)


@router.post("/matters")
async def create_contentious_matter(
    request: ContentiousMatterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    data = request.model_dump()

    if data.get("project_id"):
        data["project_id"] = _parse_uuid(data["project_id"], "project_id")
    if data.get("case_id"):
        data["case_id"] = _parse_uuid(data["case_id"], "case_id")

    matter = ContentiousMatter(
        **data,
        created_by=user.id,
    )

    db.add(matter)
    db.commit()
    db.refresh(matter)

    return {"id": str(matter.id), "status": "created"}


@router.put("/matters/{matter_id}")
async def update_contentious_matter(
    matter_id: str,
    request: ContentiousMatterUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    matter = (
        db.query(ContentiousMatter)
        .filter(ContentiousMatter.id == _parse_uuid(matter_id, "matter_id"))
        .first()
    )

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
    matter_uuid = _parse_uuid(matter_id, "matter_id")
    matter = (
        db.query(ContentiousMatter).filter(ContentiousMatter.id == matter_uuid).first()
    )

    if not matter:
        raise HTTPException(404, "Contentious matter not found")

    # Remove linked claims and item links for a clean deletion
    deleted_links = (
        db.query(ItemClaimLink)
        .filter(ItemClaimLink.contentious_matter_id == matter_uuid)
        .delete()
    )
    deleted_claims = (
        db.query(HeadOfClaim)
        .filter(HeadOfClaim.contentious_matter_id == matter_uuid)
        .delete()
    )

    db.delete(matter)
    db.commit()

    return {
        "id": matter_id,
        "status": "deleted",
        "deleted_claims": deleted_claims,
        "deleted_links": deleted_links,
    }


# ---------------------------------------------------------------------------
# Statistics Endpoint
# ---------------------------------------------------------------------------


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
        pid = _parse_uuid(project_id, "project_id")
        amount_query = amount_query.filter(HeadOfClaim.project_id == pid)
    if case_id:
        cid = _parse_uuid(case_id, "case_id")
        amount_query = amount_query.filter(HeadOfClaim.case_id == cid)

    total_claimed = amount_query.scalar() or 0

    return {
        "total_contentious_matters": total_matters,
        "total_heads_of_claim": total_claims,
        "total_linked_items": total_links,
        "total_claimed_amount": total_claimed,
        "currency": "GBP",
    }
