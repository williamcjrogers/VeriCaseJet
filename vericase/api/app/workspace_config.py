from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import get_db
from .models import Case, Keyword, Project, Stakeholder, User, UserRole
from .security import current_user

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]

router = APIRouter(prefix="/api/wizard", tags=["workspace-config"])


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


def _is_admin(user: User) -> bool:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    return str(role_val).upper() == UserRole.ADMIN.value


def _require_project(db: Session, project_id: str, user: User) -> Project:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_user_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def _require_case(db: Session, case_id: str, user: User) -> Case:
    case_uuid = _parse_uuid(case_id, "case_id")
    case = db.query(Case).filter(Case.id == case_uuid).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Access denied")
    return case


def _normalize_optional(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


class StakeholderCreate(BaseModel):
    role: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=512)
    email: str | None = None
    organization: str | None = None


class StakeholderUpdate(BaseModel):
    role: str | None = Field(default=None, min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=512)
    email: str | None = None
    organization: str | None = None


class KeywordCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    definition: str | None = None
    variations: str | None = None
    is_regex: bool | None = None


class KeywordUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    definition: str | None = None
    variations: str | None = None
    is_regex: bool | None = None


@router.get("/projects/{project_id}/stakeholders")
def list_project_stakeholders(
    project_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, str | None]]:
    project = _require_project(db, project_id, user)
    items = (
        db.query(Stakeholder)
        .filter(Stakeholder.project_id == project.id)
        .order_by(Stakeholder.name.asc())
        .all()
    )
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "role": s.role,
            "email": s.email,
            "organization": s.organization,
        }
        for s in items
    ]


@router.post("/projects/{project_id}/stakeholders")
def create_project_stakeholder(
    project_id: str,
    payload: StakeholderCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | None]:
    project = _require_project(db, project_id, user)
    email_value = _normalize_optional(payload.email)
    email_domain = email_value.split("@")[-1].lower() if email_value else None
    stakeholder = Stakeholder(
        project_id=project.id,
        case_id=None,
        role=payload.role,
        name=payload.name,
        email=email_value,
        organization=_normalize_optional(payload.organization),
        email_domain=email_domain,
    )
    db.add(stakeholder)
    db.commit()
    db.refresh(stakeholder)
    return {
        "id": str(stakeholder.id),
        "name": stakeholder.name,
        "role": stakeholder.role,
        "email": stakeholder.email,
        "organization": stakeholder.organization,
    }


@router.put("/projects/{project_id}/stakeholders/{stakeholder_id}")
def update_project_stakeholder(
    project_id: str,
    stakeholder_id: str,
    payload: StakeholderUpdate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | None]:
    project = _require_project(db, project_id, user)
    stakeholder_uuid = _parse_uuid(stakeholder_id, "stakeholder_id")
    stakeholder = (
        db.query(Stakeholder)
        .filter(
            Stakeholder.id == stakeholder_uuid,
            Stakeholder.project_id == project.id,
        )
        .first()
    )
    if not stakeholder:
        raise HTTPException(status_code=404, detail="Stakeholder not found")

    if payload.role is not None:
        stakeholder.role = payload.role
    if payload.name is not None:
        stakeholder.name = payload.name
    if payload.email is not None:
        email_value = _normalize_optional(payload.email)
        stakeholder.email = email_value
        stakeholder.email_domain = (
            email_value.split("@")[-1].lower() if email_value else None
        )
    if payload.organization is not None:
        stakeholder.organization = _normalize_optional(payload.organization)

    db.commit()
    db.refresh(stakeholder)
    return {
        "id": str(stakeholder.id),
        "name": stakeholder.name,
        "role": stakeholder.role,
        "email": stakeholder.email,
        "organization": stakeholder.organization,
    }


@router.delete("/projects/{project_id}/stakeholders/{stakeholder_id}")
def delete_project_stakeholder(
    project_id: str,
    stakeholder_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    project = _require_project(db, project_id, user)
    stakeholder_uuid = _parse_uuid(stakeholder_id, "stakeholder_id")
    stakeholder = (
        db.query(Stakeholder)
        .filter(
            Stakeholder.id == stakeholder_uuid,
            Stakeholder.project_id == project.id,
        )
        .first()
    )
    if not stakeholder:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    db.delete(stakeholder)
    db.commit()
    return {"status": "success"}


@router.get("/cases/{case_id}/stakeholders")
def list_case_stakeholders(
    case_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, str | None]]:
    case = _require_case(db, case_id, user)
    items = (
        db.query(Stakeholder)
        .filter(Stakeholder.case_id == case.id)
        .order_by(Stakeholder.name.asc())
        .all()
    )
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "role": s.role,
            "email": s.email,
            "organization": s.organization,
        }
        for s in items
    ]


@router.post("/cases/{case_id}/stakeholders")
def create_case_stakeholder(
    case_id: str,
    payload: StakeholderCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | None]:
    case = _require_case(db, case_id, user)
    email_value = _normalize_optional(payload.email)
    email_domain = email_value.split("@")[-1].lower() if email_value else None
    stakeholder = Stakeholder(
        project_id=None,
        case_id=case.id,
        role=payload.role,
        name=payload.name,
        email=email_value,
        organization=_normalize_optional(payload.organization),
        email_domain=email_domain,
    )
    db.add(stakeholder)
    db.commit()
    db.refresh(stakeholder)
    return {
        "id": str(stakeholder.id),
        "name": stakeholder.name,
        "role": stakeholder.role,
        "email": stakeholder.email,
        "organization": stakeholder.organization,
    }


@router.put("/cases/{case_id}/stakeholders/{stakeholder_id}")
def update_case_stakeholder(
    case_id: str,
    stakeholder_id: str,
    payload: StakeholderUpdate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | None]:
    case = _require_case(db, case_id, user)
    stakeholder_uuid = _parse_uuid(stakeholder_id, "stakeholder_id")
    stakeholder = (
        db.query(Stakeholder)
        .filter(Stakeholder.id == stakeholder_uuid, Stakeholder.case_id == case.id)
        .first()
    )
    if not stakeholder:
        raise HTTPException(status_code=404, detail="Stakeholder not found")

    if payload.role is not None:
        stakeholder.role = payload.role
    if payload.name is not None:
        stakeholder.name = payload.name
    if payload.email is not None:
        email_value = _normalize_optional(payload.email)
        stakeholder.email = email_value
        stakeholder.email_domain = (
            email_value.split("@")[-1].lower() if email_value else None
        )
    if payload.organization is not None:
        stakeholder.organization = _normalize_optional(payload.organization)

    db.commit()
    db.refresh(stakeholder)
    return {
        "id": str(stakeholder.id),
        "name": stakeholder.name,
        "role": stakeholder.role,
        "email": stakeholder.email,
        "organization": stakeholder.organization,
    }


@router.delete("/cases/{case_id}/stakeholders/{stakeholder_id}")
def delete_case_stakeholder(
    case_id: str,
    stakeholder_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    case = _require_case(db, case_id, user)
    stakeholder_uuid = _parse_uuid(stakeholder_id, "stakeholder_id")
    stakeholder = (
        db.query(Stakeholder)
        .filter(Stakeholder.id == stakeholder_uuid, Stakeholder.case_id == case.id)
        .first()
    )
    if not stakeholder:
        raise HTTPException(status_code=404, detail="Stakeholder not found")
    db.delete(stakeholder)
    db.commit()
    return {"status": "success"}


@router.get("/projects/{project_id}/keywords")
def list_project_keywords(
    project_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, str | bool | None]]:
    project = _require_project(db, project_id, user)
    items = (
        db.query(Keyword)
        .filter(Keyword.project_id == project.id)
        .order_by(Keyword.keyword_name.asc())
        .all()
    )
    return [
        {
            "id": str(k.id),
            "name": k.keyword_name,
            "definition": k.definition,
            "variations": k.variations,
            "is_regex": bool(k.is_regex),
        }
        for k in items
    ]


@router.post("/projects/{project_id}/keywords")
def create_project_keyword(
    project_id: str,
    payload: KeywordCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | bool | None]:
    project = _require_project(db, project_id, user)
    keyword = Keyword(
        project_id=project.id,
        case_id=None,
        keyword_name=payload.name,
        definition=_normalize_optional(payload.definition),
        variations=_normalize_optional(payload.variations),
        is_regex=bool(payload.is_regex) if payload.is_regex is not None else False,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return {
        "id": str(keyword.id),
        "name": keyword.keyword_name,
        "definition": keyword.definition,
        "variations": keyword.variations,
        "is_regex": bool(keyword.is_regex),
    }


@router.put("/projects/{project_id}/keywords/{keyword_id}")
def update_project_keyword(
    project_id: str,
    keyword_id: str,
    payload: KeywordUpdate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | bool | None]:
    project = _require_project(db, project_id, user)
    keyword_uuid = _parse_uuid(keyword_id, "keyword_id")
    keyword = (
        db.query(Keyword)
        .filter(Keyword.id == keyword_uuid, Keyword.project_id == project.id)
        .first()
    )
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")

    if payload.name is not None:
        keyword.keyword_name = payload.name
    if payload.definition is not None:
        keyword.definition = _normalize_optional(payload.definition)
    if payload.variations is not None:
        keyword.variations = _normalize_optional(payload.variations)
    if payload.is_regex is not None:
        keyword.is_regex = bool(payload.is_regex)

    db.commit()
    db.refresh(keyword)
    return {
        "id": str(keyword.id),
        "name": keyword.keyword_name,
        "definition": keyword.definition,
        "variations": keyword.variations,
        "is_regex": bool(keyword.is_regex),
    }


@router.delete("/projects/{project_id}/keywords/{keyword_id}")
def delete_project_keyword(
    project_id: str,
    keyword_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    project = _require_project(db, project_id, user)
    keyword_uuid = _parse_uuid(keyword_id, "keyword_id")
    keyword = (
        db.query(Keyword)
        .filter(Keyword.id == keyword_uuid, Keyword.project_id == project.id)
        .first()
    )
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    db.delete(keyword)
    db.commit()
    return {"status": "success"}


@router.get("/cases/{case_id}/keywords")
def list_case_keywords(
    case_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, str | bool | None]]:
    case = _require_case(db, case_id, user)
    items = (
        db.query(Keyword)
        .filter(Keyword.case_id == case.id)
        .order_by(Keyword.keyword_name.asc())
        .all()
    )
    return [
        {
            "id": str(k.id),
            "name": k.keyword_name,
            "definition": k.definition,
            "variations": k.variations,
            "is_regex": bool(k.is_regex),
        }
        for k in items
    ]


@router.post("/cases/{case_id}/keywords")
def create_case_keyword(
    case_id: str,
    payload: KeywordCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | bool | None]:
    case = _require_case(db, case_id, user)
    keyword = Keyword(
        project_id=None,
        case_id=case.id,
        keyword_name=payload.name,
        definition=_normalize_optional(payload.definition),
        variations=_normalize_optional(payload.variations),
        is_regex=bool(payload.is_regex) if payload.is_regex is not None else False,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return {
        "id": str(keyword.id),
        "name": keyword.keyword_name,
        "definition": keyword.definition,
        "variations": keyword.variations,
        "is_regex": bool(keyword.is_regex),
    }


@router.put("/cases/{case_id}/keywords/{keyword_id}")
def update_case_keyword(
    case_id: str,
    keyword_id: str,
    payload: KeywordUpdate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str | bool | None]:
    case = _require_case(db, case_id, user)
    keyword_uuid = _parse_uuid(keyword_id, "keyword_id")
    keyword = (
        db.query(Keyword)
        .filter(Keyword.id == keyword_uuid, Keyword.case_id == case.id)
        .first()
    )
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")

    if payload.name is not None:
        keyword.keyword_name = payload.name
    if payload.definition is not None:
        keyword.definition = _normalize_optional(payload.definition)
    if payload.variations is not None:
        keyword.variations = _normalize_optional(payload.variations)
    if payload.is_regex is not None:
        keyword.is_regex = bool(payload.is_regex)

    db.commit()
    db.refresh(keyword)
    return {
        "id": str(keyword.id),
        "name": keyword.keyword_name,
        "definition": keyword.definition,
        "variations": keyword.variations,
        "is_regex": bool(keyword.is_regex),
    }


@router.delete("/cases/{case_id}/keywords/{keyword_id}")
def delete_case_keyword(
    case_id: str,
    keyword_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    case = _require_case(db, case_id, user)
    keyword_uuid = _parse_uuid(keyword_id, "keyword_id")
    keyword = (
        db.query(Keyword)
        .filter(Keyword.id == keyword_uuid, Keyword.case_id == case.id)
        .first()
    )
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    db.delete(keyword)
    db.commit()
    return {"status": "success"}
