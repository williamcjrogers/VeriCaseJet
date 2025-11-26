"""
Admin User Approval System
Allows admins to review and approve/reject pending user registrations
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .models import User, UserRole
from .db import get_db
from .security import current_user
from .email_service import email_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/users", tags=["admin-approval"])


class PendingUserInfo(BaseModel):
    """Pending user information for admin review"""
    id: str
    email: str
    display_name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    company: Optional[str]
    role_description: Optional[str]
    signup_reason: Optional[str]
    signup_date: Optional[str]
    created_at: datetime


class ApprovalRequest(BaseModel):
    """Request to approve or reject a user"""
    user_id: str
    approved: bool
    role: Optional[str] = "VIEWER"  # ADMIN, EDITOR, VIEWER
    rejection_reason: Optional[str] = None


def require_admin(user: User = Depends(current_user)):
    """Dependency to require admin role"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin access required")
    return user


@router.get("/pending", response_model=List[PendingUserInfo])
async def list_pending_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """List all pending user registrations awaiting approval"""
    
    # Get inactive users (pending approval)
    pending_users = db.query(User).filter(
        User.is_active == False,
        User.email_verified == False
    ).order_by(User.created_at.desc()).all()
    
    result = []
    for user in pending_users:
        # Extract meta info
        meta = user.meta if hasattr(user, 'meta') and user.meta else {}
        
        result.append(PendingUserInfo(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            first_name=meta.get('first_name'),
            last_name=meta.get('last_name'),
            company=meta.get('company'),
            role_description=meta.get('role_description'),
            signup_reason=meta.get('signup_reason'),
            signup_date=meta.get('signup_date'),
            created_at=user.created_at
        ))
    
    return result


@router.post("/approve")
async def approve_or_reject_user(
    request: ApprovalRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
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
        if hasattr(user, 'meta') and user.meta:
            user.meta['approval_status'] = 'approved'
            user.meta['approved_by'] = str(admin.id)
            user.meta['approved_at'] = datetime.now(timezone.utc).isoformat()
        
        db.commit()
        
        # Send approval email
        try:
            email_service.send_approval_email(
                to_email=user.email,
                user_name=user.display_name or user.email.split('@')[0],
                approved=True
            )
        except Exception as e:
            logger.error("Failed to send approval email: {e}")
        
        logger.info("Admin {admin.email} approved user {user.email}")
        
        return {
            "message": "User {user.email} approved successfully",
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
            logger.error("Failed to send rejection email: {e}")
        
        logger.info("Admin {admin.email} rejected user {user.email}")
        
        # Delete the user
        db.delete(user)
        db.commit()
        
        return {
            "message": "User {user.email} rejected and removed",
            "user_id": str(user.id),
            "email": user.email
        }


@router.get("/all")
async def list_all_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
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

