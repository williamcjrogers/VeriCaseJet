"""
Workspaces API
Manages workspace entities that group Projects and Cases together
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from .db import get_db
from .models import (
    Workspace,
    WorkspaceKeyword,
    WorkspaceTeamMember,
    WorkspaceKeyDate,
    Project,
    Case,
    User,
    UserRole,
    Stakeholder,
)
from .security import current_user

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


def _is_admin(user: User) -> bool:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    return str(role_val).upper() == UserRole.ADMIN.value


def _require_workspace(db: Session, workspace_id: str, user: User) -> Workspace:
    workspace_uuid = _parse_uuid(workspace_id, "workspace_id")
    workspace = db.query(Workspace).filter(Workspace.id == workspace_uuid).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace.owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Access denied")
    return workspace


# Pydantic models
class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    contract_type: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    contract_type: str | None = None
    status: str | None = None


class KeywordCreate(BaseModel):
    keyword_name: str = Field(..., min_length=1, max_length=255)
    definition: str | None = None
    variations: str | None = None
    is_regex: bool | None = False


class TeamMemberCreate(BaseModel):
    user_id: str | None = None
    role: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=512)
    email: str | None = None
    organization: str | None = None


class KeyDateCreate(BaseModel):
    date_type: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=255)
    date_value: datetime
    description: str | None = None


# CRUD Endpoints
@router.get("")
def list_workspaces(
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """List all workspaces accessible to the user"""
    if _is_admin(user):
        workspaces = db.query(Workspace).all()
    else:
        workspaces = db.query(Workspace).filter(Workspace.owner_id == user.id).all()

    result = []
    for ws in workspaces:
        # Count projects and cases
        project_count = (
            db.query(func.count(Project.id))
            .filter(Project.workspace_id == ws.id)
            .scalar()
            or 0
        )
        case_count = (
            db.query(func.count(Case.id)).filter(Case.workspace_id == ws.id).scalar()
            or 0
        )

        # Get projects and cases for this workspace
        projects = db.query(Project).filter(Project.workspace_id == ws.id).all()
        cases = db.query(Case).filter(Case.workspace_id == ws.id).all()

        project_ids = [p.id for p in projects]
        case_ids = [c.id for c in cases]

        from .models import EmailMessage, EvidenceItem

        email_count = 0
        evidence_count = 0
        if project_ids:
            email_count += (
                db.query(func.count(EmailMessage.id))
                .filter(EmailMessage.project_id.in_(project_ids))
                .scalar()
                or 0
            )
        if case_ids:
            email_count += (
                db.query(func.count(EmailMessage.id))
                .filter(EmailMessage.case_id.in_(case_ids))
                .scalar()
                or 0
            )
        if project_ids:
            evidence_count += (
                db.query(func.count(EvidenceItem.id))
                .filter(EvidenceItem.project_id.in_(project_ids))
                .scalar()
                or 0
            )
        if case_ids:
            evidence_count += (
                db.query(func.count(EvidenceItem.id))
                .filter(EvidenceItem.case_id.in_(case_ids))
                .scalar()
                or 0
            )

        result.append(
            {
                "id": str(ws.id),
                "name": ws.name,
                "code": ws.code,
                "description": ws.description,
                "contract_type": ws.contract_type,
                "status": ws.status,
                "project_count": project_count,
                "case_count": case_count,
                "email_count": email_count,
                "evidence_count": evidence_count,
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
                "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
                # Include nested projects and cases for frontend navigation
                "projects": [
                    {
                        "id": str(p.id),
                        "name": p.project_name,
                        "code": p.project_code,
                    }
                    for p in projects
                ],
                "cases": [
                    {
                        "id": str(c.id),
                        "name": c.case_name,
                        "case_number": c.case_number,
                    }
                    for c in cases
                ],
            }
        )

    return result


@router.post("")
def create_workspace(
    payload: WorkspaceCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Create a new workspace"""
    # Check if code already exists
    existing = db.query(Workspace).filter(Workspace.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Workspace code already exists")

    workspace = Workspace(
        name=payload.name,
        code=payload.code,
        description=payload.description,
        contract_type=payload.contract_type,
        owner_id=user.id,
        status="active",
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "code": workspace.code,
        "description": workspace.description,
        "contract_type": workspace.contract_type,
        "status": workspace.status,
        "created_at": (
            workspace.created_at.isoformat() if workspace.created_at else None
        ),
        "updated_at": (
            workspace.updated_at.isoformat() if workspace.updated_at else None
        ),
    }


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Get workspace details with nested projects and cases"""
    workspace = _require_workspace(db, workspace_id, user)

    # Get projects
    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()
    project_list = []
    for p in projects:
        from .models import EmailMessage, EvidenceItem

        email_count = (
            db.query(func.count(EmailMessage.id))
            .filter(EmailMessage.project_id == p.id)
            .scalar()
            or 0
        )
        evidence_count = (
            db.query(func.count(EvidenceItem.id))
            .filter(EvidenceItem.project_id == p.id)
            .scalar()
            or 0
        )
        project_list.append(
            {
                "id": str(p.id),
                "name": p.project_name,
                "code": p.project_code,
                "description": None,  # Projects don't have description in current model
                "email_count": email_count,
                "evidence_count": evidence_count,
            }
        )

    # Get cases
    cases = db.query(Case).filter(Case.workspace_id == workspace.id).all()
    case_list = []
    for c in cases:
        from .models import EmailMessage, EvidenceItem

        email_count = (
            db.query(func.count(EmailMessage.id))
            .filter(EmailMessage.case_id == c.id)
            .scalar()
            or 0
        )
        evidence_count = (
            db.query(func.count(EvidenceItem.id))
            .filter(EvidenceItem.case_id == c.id)
            .scalar()
            or 0
        )
        case_list.append(
            {
                "id": str(c.id),
                "name": c.name,
                "code": c.case_number,
                "description": c.description,
                "project_id": str(c.project_id) if c.project_id else None,
                "project_name": c.project_name,
                "email_count": email_count,
                "evidence_count": evidence_count,
            }
        )

    # Get keywords
    keywords = (
        db.query(WorkspaceKeyword)
        .filter(WorkspaceKeyword.workspace_id == workspace.id)
        .all()
    )
    keyword_list = [
        {
            "id": str(k.id),
            "keyword_name": k.keyword_name,
            "definition": k.definition,
            "variations": k.variations,
            "is_regex": k.is_regex,
        }
        for k in keywords
    ]

    # Get team members
    team = (
        db.query(WorkspaceTeamMember)
        .filter(WorkspaceTeamMember.workspace_id == workspace.id)
        .all()
    )
    team_list = [
        {
            "id": str(t.id),
            "user_id": str(t.user_id) if t.user_id else None,
            "role": t.role,
            "name": t.name,
            "email": t.email,
            "organization": t.organization,
        }
        for t in team
    ]

    # Get key dates
    dates = (
        db.query(WorkspaceKeyDate)
        .filter(WorkspaceKeyDate.workspace_id == workspace.id)
        .all()
    )
    date_list = [
        {
            "id": str(d.id),
            "date_type": d.date_type,
            "label": d.label,
            "date_value": d.date_value.isoformat() if d.date_value else None,
            "description": d.description,
        }
        for d in dates
    ]

    # Get stakeholders (JCT categories)
    stakeholders = (
        db.query(Stakeholder)
        .filter(Stakeholder.project_id.in_([p.id for p in projects]))
        .all()
    )
    stakeholder_list = [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization,
        }
        for s in stakeholders
    ]

    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "code": workspace.code,
        "description": workspace.description,
        "contract_type": workspace.contract_type,
        "status": workspace.status,
        "projects": project_list,
        "cases": case_list,
        "keywords": keyword_list,
        "team_members": team_list,
        "key_dates": date_list,
        "stakeholders": stakeholder_list,
        "created_at": (
            workspace.created_at.isoformat() if workspace.created_at else None
        ),
        "updated_at": (
            workspace.updated_at.isoformat() if workspace.updated_at else None
        ),
    }


@router.put("/{workspace_id}")
def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Update workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    if payload.code is not None and payload.code != workspace.code:
        # Check if new code already exists
        existing = db.query(Workspace).filter(Workspace.code == payload.code).first()
        if existing:
            raise HTTPException(status_code=400, detail="Workspace code already exists")
        workspace.code = payload.code

    if payload.name is not None:
        workspace.name = payload.name
    if payload.description is not None:
        workspace.description = payload.description
    if payload.contract_type is not None:
        workspace.contract_type = payload.contract_type
    if payload.status is not None:
        workspace.status = payload.status

    db.commit()
    db.refresh(workspace)

    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "code": workspace.code,
        "description": workspace.description,
        "contract_type": workspace.contract_type,
        "status": workspace.status,
        "updated_at": (
            workspace.updated_at.isoformat() if workspace.updated_at else None
        ),
    }


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    """Delete workspace (cascade deletes related config items)"""
    workspace = _require_workspace(db, workspace_id, user)
    db.delete(workspace)
    db.commit()
    return {"status": "success"}


# Keywords endpoints
@router.put("/{workspace_id}/keywords")
def update_workspace_keywords(
    workspace_id: str,
    keywords: list[KeywordCreate],
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Replace all keywords for a workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    # Delete existing keywords
    db.query(WorkspaceKeyword).filter(
        WorkspaceKeyword.workspace_id == workspace.id
    ).delete()

    # Create new keywords
    result = []
    for kw in keywords:
        keyword = WorkspaceKeyword(
            workspace_id=workspace.id,
            keyword_name=kw.keyword_name,
            definition=kw.definition,
            variations=kw.variations,
            is_regex=kw.is_regex or False,
        )
        db.add(keyword)
        result.append(
            {
                "id": str(keyword.id),
                "keyword_name": keyword.keyword_name,
                "definition": keyword.definition,
                "variations": keyword.variations,
                "is_regex": keyword.is_regex,
            }
        )

    db.commit()
    return result


# Team members endpoints
@router.put("/{workspace_id}/team")
def update_workspace_team(
    workspace_id: str,
    team: list[TeamMemberCreate],
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Replace all team members for a workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    # Delete existing team members
    db.query(WorkspaceTeamMember).filter(
        WorkspaceTeamMember.workspace_id == workspace.id
    ).delete()

    # Create new team members
    result = []
    for tm in team:
        user_id = _parse_uuid(tm.user_id, "user_id") if tm.user_id else None
        member = WorkspaceTeamMember(
            workspace_id=workspace.id,
            user_id=user_id,
            role=tm.role,
            name=tm.name,
            email=tm.email,
            organization=tm.organization,
        )
        db.add(member)
        result.append(
            {
                "id": str(member.id),
                "user_id": str(member.user_id) if member.user_id else None,
                "role": member.role,
                "name": member.name,
                "email": member.email,
                "organization": member.organization,
            }
        )

    db.commit()
    return result


# Key dates endpoints
@router.put("/{workspace_id}/dates")
def update_workspace_dates(
    workspace_id: str,
    dates: list[KeyDateCreate],
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Replace all key dates for a workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    # Delete existing dates
    db.query(WorkspaceKeyDate).filter(
        WorkspaceKeyDate.workspace_id == workspace.id
    ).delete()

    # Create new dates
    result = []
    for d in dates:
        key_date = WorkspaceKeyDate(
            workspace_id=workspace.id,
            date_type=d.date_type,
            label=d.label,
            date_value=d.date_value,
            description=d.description,
        )
        db.add(key_date)
        result.append(
            {
                "id": str(key_date.id),
                "date_type": key_date.date_type,
                "label": key_date.label,
                "date_value": (
                    key_date.date_value.isoformat() if key_date.date_value else None
                ),
                "description": key_date.description,
            }
        )

    db.commit()
    return result


# Stakeholders endpoints - for JCT categories
@router.get("/{workspace_id}/stakeholders")
def get_workspace_stakeholders(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Get stakeholders for a workspace (aggregated from projects)"""
    workspace = _require_workspace(db, workspace_id, user)
    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()

    if not projects:
        return []

    project_ids = [p.id for p in projects]
    stakeholders = (
        db.query(Stakeholder).filter(Stakeholder.project_id.in_(project_ids)).all()
    )

    return [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization,
        }
        for s in stakeholders
    ]
