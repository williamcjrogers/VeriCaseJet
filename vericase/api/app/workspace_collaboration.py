"""
Collaborative Workspace Hub

Provides a dedicated collaboration surface for a case/project workspace:
- Workspace discussion (threaded, 3-lane)
- Unified activity feed (documents + claims/evidence comments)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    Case,
    CaseUser,
    CollaborationActivity,
    ContentiousMatter,
    Document,
    EmailMessage,
    EvidenceItem,
    HeadOfClaim,
    ItemClaimLink,
    ItemComment,
    Project,
    User,
    UserRole,
)
from .security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

WorkspaceType = Literal["case", "project"]
ALLOWED_LANES: set[str] = {"core", "counsel", "expert"}


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(400, f"Invalid {field} format. Expected UUID.") from exc


def _normalize_lane(lane: str | None, *, default_core: bool = True) -> str | None:
    if lane is None or not lane.strip():
        return "core" if default_core else None

    lane_value = lane.strip().lower()
    if lane_value not in ALLOWED_LANES:
        allowed = ", ".join(sorted(ALLOWED_LANES))
        raise HTTPException(400, f"Invalid lane. Allowed: {allowed}")
    return lane_value


def _require_case_access(db: Session, case_id: str, user: User) -> Case:
    case_uuid = _parse_uuid(case_id, "case_id")
    case = db.get(Case, case_uuid)
    if not case:
        raise HTTPException(404, "Case not found")

    if user.role == UserRole.ADMIN:
        return case

    if case.owner_id == user.id:
        return case

    membership = (
        db.query(CaseUser.id)
        .filter(CaseUser.case_id == case.id, CaseUser.user_id == user.id)
        .first()
    )
    if not membership:
        raise HTTPException(403, "Access denied")

    return case


def _require_project_access(db: Session, project_id: str, user: User) -> Project:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.get(Project, project_uuid)
    if not project:
        raise HTTPException(404, "Project not found")

    if user.role == UserRole.ADMIN:
        return project

    owner_id = getattr(project, "owner_user_id", None)
    if owner_id == user.id:
        return project

    raise HTTPException(403, "Access denied")


def _require_workspace(
    db: Session, workspace_type: str, workspace_id: str, user: User
) -> tuple[WorkspaceType, uuid.UUID, str]:
    if workspace_type == "case":
        case = _require_case_access(db, workspace_id, user)
        return "case", case.id, case.name or "Untitled case"
    if workspace_type == "project":
        project = _require_project_access(db, workspace_id, user)
        project_name = getattr(project, "project_name", None) or getattr(
            project, "name", None
        )
        return "project", project.id, project_name or "Untitled project"

    raise HTTPException(400, "workspace_type must be 'case' or 'project'")


class WorkspaceCommentCreate(BaseModel):
    content: str = Field(..., min_length=1)
    lane: str | None = None
    parent_comment_id: str | None = None


class WorkspaceCommentUpdate(BaseModel):
    content: str = Field(..., min_length=1)


class WorkspaceCommentResponse(BaseModel):
    id: str
    content: str
    lane: str
    parent_comment_id: str | None
    created_at: datetime | None
    created_by: str | None
    created_by_name: str | None
    is_edited: bool
    edited_at: datetime | None
    replies: list["WorkspaceCommentResponse"] = Field(default_factory=list)


class WorkspaceMemberResponse(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None
    role: str
    is_owner: bool = False


class WorkspaceActivityItem(BaseModel):
    id: str
    source: str  # collaboration_activity | item_comment
    action: str
    resource_type: str
    resource_id: str
    resource_name: str
    actor_id: str | None = None
    actor_name: str | None = None
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)


def _comment_to_response(
    comment: ItemComment,
    *,
    user_by_id: dict[uuid.UUID, User],
    children_by_parent: dict[uuid.UUID | None, list[ItemComment]],
) -> WorkspaceCommentResponse:
    creator_name = None
    if comment.created_by and comment.created_by in user_by_id:
        u = user_by_id[comment.created_by]
        creator_name = u.display_name or u.email

    replies = children_by_parent.get(comment.id, [])
    return WorkspaceCommentResponse(
        id=str(comment.id),
        content=comment.content,
        lane=(comment.lane or "core"),
        parent_comment_id=(
            str(comment.parent_comment_id) if comment.parent_comment_id else None
        ),
        created_at=comment.created_at,
        created_by=str(comment.created_by) if comment.created_by else None,
        created_by_name=creator_name,
        is_edited=bool(comment.is_edited),
        edited_at=comment.edited_at,
        replies=[
            _comment_to_response(
                reply, user_by_id=user_by_id, children_by_parent=children_by_parent
            )
            for reply in replies
        ],
    )


@router.get("/cases/{case_id}/team")
def get_case_team(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    case = _require_case_access(db, case_id, user)

    memberships = db.query(CaseUser).filter(CaseUser.case_id == case.id).all()
    user_ids: set[uuid.UUID] = {case.owner_id, *[m.user_id for m in memberships]}
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_by_id = {u.id: u for u in users}

    items: list[WorkspaceMemberResponse] = []

    owner_user = user_by_id.get(case.owner_id)
    if owner_user:
        items.append(
            WorkspaceMemberResponse(
                user_id=str(owner_user.id),
                email=owner_user.email,
                display_name=owner_user.display_name,
                role="owner",
                is_owner=True,
            )
        )

    for m in memberships:
        member_user = user_by_id.get(m.user_id)
        if not member_user or member_user.id == case.owner_id:
            continue
        items.append(
            WorkspaceMemberResponse(
                user_id=str(member_user.id),
                email=member_user.email,
                display_name=member_user.display_name,
                role=m.role,
                is_owner=False,
            )
        )

    items.sort(key=lambda x: (not x.is_owner, (x.role or "").lower(), x.email.lower()))

    return {
        "case_id": str(case.id),
        "case_name": case.name,
        "items": [i.model_dump() for i in items],
    }


@router.get(
    "/{workspace_type}/{workspace_id}/discussion",
    response_model=list[WorkspaceCommentResponse],
)
def get_workspace_discussion(
    workspace_type: str,
    workspace_id: str,
    lane: str | None = Query(None),
    search: str | None = Query(None),
    include_replies: bool = Query(True),
    page_size: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[WorkspaceCommentResponse]:
    ws_type, ws_uuid, _ws_name = _require_workspace(
        db, workspace_type, workspace_id, user
    )
    lane_filter = _normalize_lane(lane, default_core=False)

    base_query = db.query(ItemComment).filter(
        ItemComment.item_type == ws_type,
        ItemComment.item_id == ws_uuid,
    )
    if lane_filter:
        base_query = base_query.filter(ItemComment.lane == lane_filter)

    all_comments = (
        base_query.order_by(ItemComment.created_at.asc()).limit(page_size).all()
    )
    if not all_comments:
        return []

    children_by_parent: dict[uuid.UUID | None, list[ItemComment]] = {}
    for c in all_comments:
        children_by_parent.setdefault(c.parent_comment_id, []).append(c)

    top_level = children_by_parent.get(None, [])
    if search and search.strip():
        needle = search.strip().lower()
        top_level = [c for c in top_level if needle in (c.content or "").lower()]

    if not include_replies:
        children_by_parent = {None: top_level}

    actor_ids = {c.created_by for c in all_comments if c.created_by}
    users = db.query(User).filter(User.id.in_(actor_ids)).all() if actor_ids else []
    user_by_id = {u.id: u for u in users}

    return [
        _comment_to_response(
            c, user_by_id=user_by_id, children_by_parent=children_by_parent
        )
        for c in top_level
    ]


@router.post("/{workspace_type}/{workspace_id}/discussion")
def create_workspace_comment(
    workspace_type: str,
    workspace_id: str,
    request: WorkspaceCommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    ws_type, ws_uuid, _ws_name = _require_workspace(
        db, workspace_type, workspace_id, user
    )
    lane_value = _normalize_lane(request.lane, default_core=True) or "core"

    content = request.content.strip()
    if not content:
        raise HTTPException(400, "content is required")

    parent_uuid = (
        _parse_uuid(request.parent_comment_id, "parent_comment_id")
        if request.parent_comment_id
        else None
    )

    if parent_uuid:
        parent = db.get(ItemComment, parent_uuid)
        if not parent or parent.item_type != ws_type or parent.item_id != ws_uuid:
            raise HTTPException(400, "Invalid parent_comment_id for this workspace")

    comment = ItemComment(
        item_type=ws_type,
        item_id=ws_uuid,
        parent_comment_id=parent_uuid,
        content=content,
        lane=lane_value,
        created_by=user.id,
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {"id": str(comment.id), "status": "created"}


@router.put("/comments/{comment_id}")
def update_workspace_comment(
    comment_id: str,
    request: WorkspaceCommentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    comment_uuid = _parse_uuid(comment_id, "comment_id")
    comment = db.get(ItemComment, comment_uuid)
    if not comment:
        raise HTTPException(404, "Comment not found")

    if comment.created_by != user.id:
        raise HTTPException(403, "You can only edit your own comments")

    if comment.item_type not in ("case", "project") or comment.item_id is None:
        raise HTTPException(400, "Not a workspace discussion comment")

    _require_workspace(db, comment.item_type, str(comment.item_id), user)

    content = request.content.strip()
    if not content:
        raise HTTPException(400, "content is required")

    comment.content = content
    comment.is_edited = True
    comment.edited_at = datetime.now(timezone.utc)
    db.commit()

    return {"id": str(comment.id), "status": "updated"}


@router.delete("/comments/{comment_id}")
def delete_workspace_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    comment_uuid = _parse_uuid(comment_id, "comment_id")
    comment = db.get(ItemComment, comment_uuid)
    if not comment:
        raise HTTPException(404, "Comment not found")

    if comment.created_by != user.id:
        raise HTTPException(403, "You can only delete your own comments")

    if comment.item_type not in ("case", "project") or comment.item_id is None:
        raise HTTPException(400, "Not a workspace discussion comment")

    _require_workspace(db, comment.item_type, str(comment.item_id), user)

    db.delete(comment)
    db.commit()
    return {"id": comment_id, "status": "deleted"}


@router.get(
    "/{workspace_type}/{workspace_id}/activity",
    response_model=list[WorkspaceActivityItem],
)
def get_workspace_activity(
    workspace_type: str,
    workspace_id: str,
    limit: int = Query(100, ge=1, le=500),
    focus_type: str | None = Query(None),
    focus_id: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[WorkspaceActivityItem]:
    ws_type, ws_uuid, ws_name = _require_workspace(
        db, workspace_type, workspace_id, user
    )

    focus_type_value = (focus_type or "").strip().lower()
    focus_uuid: uuid.UUID | None = None
    if focus_type_value:
        if focus_type_value not in {"claim", "matter"}:
            raise HTTPException(400, "focus_type must be 'claim' or 'matter'")
        if not focus_id:
            raise HTTPException(400, "focus_id is required when focus_type is set")
        focus_uuid = _parse_uuid(focus_id, "focus_id")

    # Documents uploaded into this workspace (documents.meta.profile_type/profile_id).
    doc_ids_list: list[uuid.UUID] = []
    if not focus_type_value:
        doc_ids = (
            db.query(Document.id)
            .filter(
                Document.meta["profile_type"].as_string() == ws_type,
                Document.meta["profile_id"].as_string() == str(ws_uuid),
            )
            .all()
        )
        doc_ids_list = [row[0] for row in doc_ids]

    # Claims/matters/items associated with this workspace.
    claim_fk = HeadOfClaim.case_id if ws_type == "case" else HeadOfClaim.project_id
    matter_fk = (
        ContentiousMatter.case_id if ws_type == "case" else ContentiousMatter.project_id
    )
    claim_ids_list: list[uuid.UUID] = []
    matter_ids_list: list[uuid.UUID] = []

    if focus_type_value == "claim" and focus_uuid:
        claim = (
            db.query(HeadOfClaim)
            .filter(HeadOfClaim.id == focus_uuid, claim_fk == ws_uuid)
            .first()
        )
        if not claim:
            raise HTTPException(404, "Head of claim not found in this workspace")
        claim_ids_list = [claim.id]
        if claim.contentious_matter_id:
            matter_ids_list = [claim.contentious_matter_id]
    elif focus_type_value == "matter" and focus_uuid:
        matter = (
            db.query(ContentiousMatter)
            .filter(ContentiousMatter.id == focus_uuid, matter_fk == ws_uuid)
            .first()
        )
        if not matter:
            raise HTTPException(404, "Contentious matter not found in this workspace")
        matter_ids_list = [matter.id]
        claim_ids = (
            db.query(HeadOfClaim.id)
            .filter(HeadOfClaim.contentious_matter_id == matter.id)
            .all()
        )
        claim_ids_list = [row[0] for row in claim_ids]
    else:
        claim_ids = db.query(HeadOfClaim.id).filter(claim_fk == ws_uuid).all()
        claim_ids_list = [row[0] for row in claim_ids]

        matter_ids = db.query(ContentiousMatter.id).filter(matter_fk == ws_uuid).all()
        matter_ids_list = [row[0] for row in matter_ids]

    evidence_ids_list: list[uuid.UUID] = []
    email_ids_list: list[uuid.UUID] = []
    if not focus_type_value:
        evidence_fk = (
            EvidenceItem.case_id if ws_type == "case" else EvidenceItem.project_id
        )
        evidence_ids = db.query(EvidenceItem.id).filter(evidence_fk == ws_uuid).all()
        evidence_ids_list = [row[0] for row in evidence_ids]

        email_fk = (
            EmailMessage.case_id if ws_type == "case" else EmailMessage.project_id
        )
        email_ids = db.query(EmailMessage.id).filter(email_fk == ws_uuid).all()
        email_ids_list = [row[0] for row in email_ids]

    # Links in this workspace (used for claim-context evidence notes).
    link_filters = []
    if claim_ids_list:
        link_filters.append(ItemClaimLink.head_of_claim_id.in_(claim_ids_list))
    if matter_ids_list:
        link_filters.append(ItemClaimLink.contentious_matter_id.in_(matter_ids_list))
    link_ids_list: list[uuid.UUID] = []
    if link_filters:
        link_ids = (
            db.query(ItemClaimLink.id)
            .filter(or_(*link_filters), ItemClaimLink.status == "active")
            .all()
        )
        link_ids_list = [row[0] for row in link_ids]

    # --- CollaborationActivity (documents + claim-level events) ---
    activity_filters = []
    if doc_ids_list:
        activity_filters.append(
            and_(
                CollaborationActivity.resource_type == "document",
                CollaborationActivity.resource_id.in_(doc_ids_list),
            )
        )
    if claim_ids_list:
        activity_filters.append(
            and_(
                CollaborationActivity.resource_type == "claim",
                CollaborationActivity.resource_id.in_(claim_ids_list),
            )
        )
    collab_activities: list[CollaborationActivity] = []
    if activity_filters:
        collab_activities = (
            db.query(CollaborationActivity)
            .filter(or_(*activity_filters))
            .order_by(desc(CollaborationActivity.created_at))
            .limit(limit)
            .all()
        )

    # --- ItemComment-derived activity (claim/evidence/correspondence + workspace discussion) ---
    comment_filters = []
    if claim_ids_list:
        comment_filters.append(
            and_(
                ItemComment.item_type == "claim",
                ItemComment.item_id.in_(claim_ids_list),
            )
        )
    if matter_ids_list:
        comment_filters.append(
            and_(
                ItemComment.item_type == "matter",
                ItemComment.item_id.in_(matter_ids_list),
            )
        )
    if evidence_ids_list:
        comment_filters.append(
            and_(
                ItemComment.item_type == "evidence",
                ItemComment.item_id.in_(evidence_ids_list),
            )
        )
    if email_ids_list:
        comment_filters.append(
            and_(
                ItemComment.item_type == "correspondence",
                ItemComment.item_id.in_(email_ids_list),
            )
        )
    if link_ids_list:
        comment_filters.append(ItemComment.item_claim_link_id.in_(link_ids_list))

    # Always include workspace discussion comments unless a focus filter is set.
    if not focus_type_value:
        comment_filters.append(
            and_(ItemComment.item_type == ws_type, ItemComment.item_id == ws_uuid)
        )

    comments = (
        db.query(ItemComment)
        .filter(or_(*comment_filters))
        .order_by(desc(ItemComment.created_at))
        .limit(limit)
        .all()
    )

    # Prefetch names + users for rendering.
    actor_ids: set[uuid.UUID] = {
        a.user_id for a in collab_activities if a.user_id is not None
    }
    actor_ids |= {c.created_by for c in comments if c.created_by is not None}  # type: ignore[arg-type]
    actors = db.query(User).filter(User.id.in_(actor_ids)).all() if actor_ids else []
    actor_by_id = {u.id: u for u in actors}

    docs = (
        db.query(Document).filter(Document.id.in_(doc_ids_list)).all()
        if doc_ids_list
        else []
    )
    doc_by_id = {d.id: d for d in docs}

    claims = (
        db.query(HeadOfClaim).filter(HeadOfClaim.id.in_(claim_ids_list)).all()
        if claim_ids_list
        else []
    )
    claim_by_id = {c.id: c for c in claims}

    matters = (
        db.query(ContentiousMatter)
        .filter(ContentiousMatter.id.in_(matter_ids_list))
        .all()
        if matter_ids_list
        else []
    )
    matter_by_id = {m.id: m for m in matters}

    evidence_items = (
        db.query(EvidenceItem).filter(EvidenceItem.id.in_(evidence_ids_list)).all()
        if evidence_ids_list
        else []
    )
    evidence_by_id = {e.id: e for e in evidence_items}

    emails = (
        db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids_list)).all()
        if email_ids_list
        else []
    )
    email_by_id = {e.id: e for e in emails}

    links = (
        db.query(ItemClaimLink).filter(ItemClaimLink.id.in_(link_ids_list)).all()
        if link_ids_list
        else []
    )
    link_by_id = {link.id: link for link in links}

    items: list[WorkspaceActivityItem] = []

    for activity in collab_activities:
        actor = actor_by_id.get(activity.user_id) if activity.user_id else None
        actor_name = (actor.display_name or actor.email) if actor else None

        resource_name = "Unknown"
        if activity.resource_type == "document":
            doc = doc_by_id.get(activity.resource_id)
            if doc:
                resource_name = doc.filename
        elif activity.resource_type == "claim":
            claim = claim_by_id.get(activity.resource_id)
            if claim:
                resource_name = claim.name
        elif activity.details and activity.details.get("resource_name"):
            resource_name = str(activity.details["resource_name"])

        items.append(
            WorkspaceActivityItem(
                id=f"collab:{activity.id}",
                source="collaboration_activity",
                action=activity.action,
                resource_type=activity.resource_type,
                resource_id=str(activity.resource_id),
                resource_name=resource_name,
                actor_id=str(activity.user_id) if activity.user_id else None,
                actor_name=actor_name,
                timestamp=activity.created_at or datetime.now(timezone.utc),
                details=activity.details or {},
            )
        )

    for comment in comments:
        actor = actor_by_id.get(comment.created_by) if comment.created_by else None
        actor_name = (actor.display_name or actor.email) if actor else None

        resource_type = "workspace"
        resource_id = str(ws_uuid)
        resource_name = ws_name
        details: dict[str, Any] = {
            "comment_id": str(comment.id),
            "lane": (comment.lane or "core"),
            "is_reply": bool(comment.parent_comment_id),
        }

        if comment.item_claim_link_id:
            link = link_by_id.get(comment.item_claim_link_id)
            if link:
                resource_type = link.item_type
                resource_id = str(link.item_id)
                details["link_id"] = str(link.id)
                details["link_type"] = link.link_type
                if link.head_of_claim_id and link.head_of_claim_id in claim_by_id:
                    details["claim_id"] = str(link.head_of_claim_id)
                    details["claim_name"] = claim_by_id[link.head_of_claim_id].name
                if link.item_type == "evidence":
                    ev = evidence_by_id.get(link.item_id)
                    if ev:
                        resource_name = ev.title or ev.filename
                elif link.item_type == "correspondence":
                    em = email_by_id.get(link.item_id)
                    if em:
                        resource_name = em.subject or "(no subject)"
        elif comment.item_type == "claim" and comment.item_id:
            resource_type = "claim"
            resource_id = str(comment.item_id)
            claim = claim_by_id.get(comment.item_id)
            if claim:
                resource_name = claim.name
        elif comment.item_type == "matter" and comment.item_id:
            resource_type = "matter"
            resource_id = str(comment.item_id)
            matter = matter_by_id.get(comment.item_id)
            if matter:
                resource_name = matter.name
        elif comment.item_type == "evidence" and comment.item_id:
            resource_type = "evidence"
            resource_id = str(comment.item_id)
            ev = evidence_by_id.get(comment.item_id)
            if ev:
                resource_name = ev.title or ev.filename
        elif comment.item_type == "correspondence" and comment.item_id:
            resource_type = "correspondence"
            resource_id = str(comment.item_id)
            em = email_by_id.get(comment.item_id)
            if em:
                resource_name = em.subject or "(no subject)"
        elif comment.item_type in ("case", "project"):
            resource_type = "workspace"
            resource_id = str(comment.item_id or ws_uuid)
            resource_name = ws_name
            details["workspace_type"] = comment.item_type

        items.append(
            WorkspaceActivityItem(
                id=f"comment:{comment.id}",
                source="item_comment",
                action="comment.edited" if comment.is_edited else "comment.created",
                resource_type=resource_type,
                resource_id=resource_id,
                resource_name=resource_name,
                actor_id=str(comment.created_by) if comment.created_by else None,
                actor_name=actor_name,
                timestamp=comment.created_at or datetime.now(timezone.utc),
                details=details,
            )
        )

    items.sort(key=lambda x: x.timestamp, reverse=True)
    return items[:limit]
