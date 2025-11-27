from __future__ import annotations

"""
Admin User Approval System
Allows admins to review and approve/reject pending user registrations
"""
import logging
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .email_service import email_service
from .models import User, UserRole
from .security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin-approval"])

DbSession = Annotated[Session, Depends(get_db)]


def _str_or_none(value: object | None) -> str | None:
    return value if isinstance(value, str) else None


def _coerce_meta(source: object | None) -> dict[str, object]:
    if isinstance(source, Mapping):
        typed_source = cast(Mapping[object, object], source)
        normalized: dict[str, object] = {}
        for key_obj, value_obj in typed_source.items():
            if isinstance(key_obj, str):
                normalized[key_obj] = value_obj
        return normalized
    return {}


class PendingUserInfo(BaseModel):
    """Pending user information for admin review"""

    id: str
    email: str
    display_name: str | None
    first_name: str | None
    last_name: str | None
    company: str | None
    role_description: str | None
    signup_reason: str | None
    signup_date: str | None
    created_at: datetime


class ApprovalRequest(BaseModel):
    """Request to approve or reject a user"""

    user_id: str
    approved: bool | None = None
    role: str = "VIEWER"  # ADMIN, EDITOR, VIEWER
    rejection_reason: str | None = None


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """Dependency to require admin role"""

    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin access required")
    return user


AdminUserDep = Annotated[User, Depends(require_admin)]


@router.get("/pending", response_model=list[PendingUserInfo])
async def list_pending_users(
    admin: AdminUserDep,
    db: DbSession,
) -> list[PendingUserInfo]:
    """List all pending user registrations awaiting approval"""

    # Get inactive users (pending approval)
    pending_users = db.query(User).filter(
        User.is_active == False,
        User.email_verified == False
    ).order_by(User.created_at.desc()).all()

    result: list[PendingUserInfo] = []
    for user in pending_users:
        # Extract meta info
        meta = _coerce_meta(getattr(user, "meta", None))

        result.append(PendingUserInfo(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            first_name=_str_or_none(meta.get('first_name')),
            last_name=_str_or_none(meta.get('last_name')),
            company=_str_or_none(meta.get('company')),
            role_description=_str_or_none(meta.get('role_description')),
            signup_reason=_str_or_none(meta.get('signup_reason')),
            signup_date=_str_or_none(meta.get('signup_date')),
            created_at=user.created_at or datetime.now(timezone.utc)
        ))

    return result


@router.post("/approve")
async def approve_or_reject_user(
    request: ApprovalRequest,
    admin: AdminUserDep,
    db: DbSession,
) -> dict[str, str]:
    """Approve or reject a pending user registration"""

    # Get user
    user = db.query(User).filter_by(id=request.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    if request.approved:
        # Approve user
        user.is_active = True
        user.email_verified = True
        
        # Set role
        if request.role == "ADMIN":
            user.role = UserRole.ADMIN
        elif request.role == "EDITOR":
            user.role = UserRole.EDITOR
        else:
            user.role = UserRole.VIEWER
        
        # Update meta
        meta_dict = _coerce_meta(getattr(user, 'meta', None))
        user.meta = meta_dict

        meta_dict['approval_status'] = 'approved'
        meta_dict['approved_by'] = str(admin.id)
        meta_dict['approved_at'] = datetime.now(timezone.utc).isoformat()
        
        db.commit()
        
        # Send approval email
        try:
            email_service.send_approval_email(
                to_email=user.email,
                user_name=user.display_name or user.email.split('@')[0],
                approved=True
            )
        except Exception as e:
            logger.error("Failed to send approval email: %s", e)

        logger.info("Admin %s approved user %s", admin.email, user.email)
        
        return {
            "message": f"User {user.email} approved successfully",
            "user_id": str(user.id),
            "email": user.email,
            "role": user.role.value
        }
    
    else:
        # Reject user
        rejection_reason = request.rejection_reason or "Your registration was not approved"
        
        # Send rejection email
        try:
            email_service.send_approval_email(
                to_email=user.email,
                user_name=user.display_name or user.email.split('@')[0],
                approved=False,
                reason=rejection_reason
            )
        except Exception as e:
            logger.error("Failed to send rejection email: %s", e)

        logger.info("Admin %s rejected user %s", admin.email, user.email)
        
        # Delete the user
        db.delete(user)
        db.commit()
        
        return {
            "message": f"User {user.email} rejected and removed",
            "user_id": str(user.id),
            "email": user.email
        }


@router.get("/all")
async def list_all_users(
    admin: AdminUserDep,
    db: DbSession,
):
    """List all users (for admin management)"""
    
    users = db.query(User).order_by(User.created_at.desc()).all()
    
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "role": u.role.value if u.role else "VIEWER",
            "is_active": u.is_active,
            "email_verified": u.email_verified,
            "created_at": u.created_at,
            "last_login_at": u.last_login_at
        }
        for u in users
    ]

