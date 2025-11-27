from __future__ import annotations

"""
Admin settings management endpoints
Allows admins to modify application settings like Textract page threshold
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import AppSetting, User, UserRole
from .security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])

DbSession = Annotated[Session, Depends(get_db)]


class SettingResponse(BaseModel):
    key: str
    value: str
    description: str | None
    updated_at: str | None
    updated_by: str | None


class SettingUpdate(BaseModel):
    value: str
    description: str | None = None


def _require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """Ensure user is an admin"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


AdminDep = Annotated[User, Depends(_require_admin)]


@router.get("", response_model=list[SettingResponse])
def list_settings(
    db: DbSession,
    admin: AdminDep,
):
    """List all application settings"""
    settings = db.query(AppSetting).order_by(AppSetting.key).all()
    return [
        SettingResponse(
            key=s.key,
            value=s.value,
            description=s.description,
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
            updated_by=str(s.updated_by) if s.updated_by else None
        )
        for s in settings
    ]


@router.get("/{key}", response_model=SettingResponse)
def get_setting(
    key: str,
    db: DbSession,
    admin: AdminDep,
):
    """Get a specific setting by key"""
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    
    return SettingResponse(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
        updated_by=str(setting.updated_by) if setting.updated_by else None
    )


@router.put("/{key}", response_model=SettingResponse)
def update_setting(
    key: str,
    db: DbSession,
    admin: AdminDep,
    update: Annotated[SettingUpdate, Body(...)],
):
    """Update a setting (creates if doesn't exist)"""
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    
    if setting:
        setting.value = update.value
        if update.description is not None:
            setting.description = update.description
        setting.updated_by = admin.id
    else:
        setting = AppSetting(
            key=key,
            value=update.value,
            description=update.description,
            updated_by=admin.id
        )
        db.add(setting)
    
    db.commit()
    db.refresh(setting)
    
    logger.info(f"Admin {admin.email} updated setting '{key}' to '{update.value}'")
    
    return SettingResponse(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
        updated_by=str(setting.updated_by) if setting.updated_by else None
    )


def get_setting_value(key: str, default: str, db: Session) -> str:
    """Helper function to get setting value from DB with fallback to default"""
    try:
        setting = db.query(AppSetting).filter(AppSetting.key == key).first()
        if setting:
            return setting.value
    except Exception as e:
        logger.debug(f"Failed to get setting '{key}' from DB: {e}")
    return default

