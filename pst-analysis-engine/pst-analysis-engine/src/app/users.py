"""
User Management API Endpoints
Handles user profile, password changes, and admin operations
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from .security import get_db, current_user, hash_password, verify_password, sign_token
from .models import User, UserRole, UserInvitation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

# Pydantic models for requests/responses
class UserProfile(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UserListItem(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None

class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: str = "viewer"

class InvitationResponse(BaseModel):
    token: str
    email: str
    role: str
    expires_at: datetime
    created_at: datetime

# Helper to require admin role
def require_admin(user: User = Depends(current_user)):
    role_val = getattr(user, 'role', None)
    if role_val != UserRole.ADMIN:
        raise HTTPException(403, "admin access required")
    return user

# Current user endpoints
@router.get("/me", response_model=UserProfile)
def get_current_user_profile(user: User = Depends(current_user)):
    """Get current user's profile"""
    role_val = getattr(user, 'role', UserRole.VIEWER)
    return UserProfile(
        id=str(user.id),
        email=getattr(user, 'email', ''),
        display_name=getattr(user, 'display_name', None),
        role=role_val.value,
        is_active=getattr(user, 'is_active', False),
        created_at=getattr(user, 'created_at', datetime.now(timezone.utc)),
        last_login_at=getattr(user, 'last_login_at', None)
    )

@router.patch("/me", response_model=UserProfile)
def update_current_user_profile(
    data: UpdateProfileRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Update current user's profile"""
    try:
        if data.display_name is not None:
            # Validate and sanitize display name
            display_name = data.display_name.strip()
            if len(display_name) > 255:
                raise HTTPException(status_code=400, detail="Display name too long (max 255 characters)")
            setattr(user, 'display_name', display_name or None)
        
        db.commit()
        db.refresh(user)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update user profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile")
    
    role_val = getattr(user, 'role', UserRole.VIEWER)
    return UserProfile(
        id=str(user.id),
        email=getattr(user, 'email', ''),
        display_name=getattr(user, 'display_name', None),
        role=role_val.value,
        is_active=getattr(user, 'is_active', False),
        created_at=getattr(user, 'created_at', datetime.now(timezone.utc)),
        last_login_at=getattr(user, 'last_login_at', None)
    )

@router.post("/me/password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Change current user's password"""
    # Verify current password with error handling
    try:
        password_hash_val = getattr(user, 'password_hash', '')
        if not verify_password(data.current_password, password_hash_val):
            logger.warning(f"Failed password change attempt for user {user.id}")
            raise HTTPException(status_code=401, detail="Current password is incorrect")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        raise HTTPException(status_code=500, detail="Password verification failed")
    
    # Validate new password
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    
    if len(data.new_password) > 128:
        raise HTTPException(status_code=400, detail="New password must be at most 128 characters")
    
    # Check password complexity
    if data.new_password.lower() == data.current_password.lower():
        raise HTTPException(status_code=400, detail="New password must be different from current password")
    
    # Update password with error handling
    try:
        setattr(user, 'password_hash', hash_password(data.new_password))
        setattr(user, 'last_login_at', datetime.now(timezone.utc))  # Update last activity
        db.commit()
        logger.info(f"Password changed successfully for user {user.id}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update password for user {user.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update password")
    
    return {"message": "Password changed successfully"}

# Admin endpoints
@router.get("", response_model=List[UserListItem])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all users (admin only)"""
    try:
        # Add pagination and limit to prevent performance issues
        users = db.query(User).order_by(User.created_at.desc()).limit(1000).all()
        
        return [
            UserListItem(
                id=str(u.id),
                email=getattr(u, 'email', ''),
                display_name=getattr(u, 'display_name', None),
                role=getattr(u, 'role', UserRole.VIEWER).value,
                is_active=getattr(u, 'is_active', False),
                created_at=getattr(u, 'created_at', datetime.now(timezone.utc)),
                last_login_at=getattr(u, 'last_login_at', None)
            )
            for u in users
        ]
    except Exception as e:
        logger.error(f"Database error while listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch users")

@router.patch("/{user_id}", response_model=UserListItem)
def update_user(
    user_id: str,
    data: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Update user (admin only)"""
    from uuid import UUID
    
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "invalid user id")
    
    user = db.get(User, user_uuid)
    if not user:
        raise HTTPException(404, "user not found")
    
    # Prevent admin from deactivating themselves
    is_active_val = getattr(user, 'is_active', True)
    if user.id == admin.id and data.is_active is False:
        raise HTTPException(400, "cannot deactivate your own account")
    
    # Prevent admin from demoting themselves
    role_val = getattr(user, 'role', UserRole.VIEWER)
    if user.id == admin.id and data.role and data.role != UserRole.ADMIN.value:
        raise HTTPException(400, "cannot change your own role")
    
    # Update fields with comprehensive error handling
    try:
        if data.role is not None:
            try:
                setattr(user, 'role', UserRole(data.role))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid role value: {data.role}")
        
        if data.is_active is not None:
            setattr(user, 'is_active', data.is_active)
        
        if data.display_name is not None:
            display_name = data.display_name.strip()
            if len(display_name) > 255:
                raise HTTPException(status_code=400, detail="Display name too long (max 255 characters)")
            setattr(user, 'display_name', display_name or None)
        
        db.commit()
        db.refresh(user)
        logger.info(f"User {user_id} updated by admin {admin.id}")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user")
    
    role_val = getattr(user, 'role', UserRole.VIEWER)
    return UserListItem(
        id=str(user.id),
        email=getattr(user, 'email', ''),
        display_name=getattr(user, 'display_name', None),
        role=role_val.value,
        is_active=getattr(user, 'is_active', False),
        created_at=getattr(user, 'created_at', datetime.now(timezone.utc)),
        last_login_at=getattr(user, 'last_login_at', None)
    )

# Invitation endpoints
@router.post("/invitations", response_model=InvitationResponse)
def create_invitation(
    data: CreateInvitationRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Create user invitation (admin only)"""
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == data.email.lower()).first()
    if existing_user:
        raise HTTPException(409, "user with this email already exists")
    
    # Check if invitation already exists
    existing_invite = db.query(UserInvitation).filter(
        UserInvitation.email == data.email.lower(),
        UserInvitation.expires_at > datetime.now(timezone.utc)
    ).first()
    if existing_invite:
        raise HTTPException(409, "active invitation already exists for this email")
    
    # Validate role
    try:
        role = UserRole(data.role)
    except ValueError:
        raise HTTPException(400, f"invalid role: {data.role}")
    
    # Create invitation
    token = uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    
    invitation = UserInvitation(
        token=token,
        email=data.email.lower(),
        role=role,
        invited_by=admin.id,
        expires_at=expires_at
    )
    
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    
    # TODO: Send invitation email
    # Sanitize emails for logging (prevent log injection)
    safe_invited_email = str(data.email).replace('\n', '').replace('\r', '')
    safe_admin_email = admin.email.replace('\n', '').replace('\r', '')
    logger.info(f"Invitation created for {safe_invited_email} by {safe_admin_email}")
    
    role_val = getattr(invitation, 'role', UserRole.VIEWER)
    return InvitationResponse(
        token=getattr(invitation, 'token', ''),
        email=getattr(invitation, 'email', ''),
        role=role_val.value,
        expires_at=getattr(invitation, 'expires_at', datetime.now(timezone.utc)),
        created_at=getattr(invitation, 'created_at', datetime.now(timezone.utc))
    )

@router.get("/invitations", response_model=List[InvitationResponse])
def list_invitations(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """List all active invitations (admin only)"""
    now = datetime.now(timezone.utc)
    try:
        # Query uses parameterized SQLAlchemy ORM (SQL injection safe)
        invitations = db.query(UserInvitation).filter(
            UserInvitation.expires_at > now
        ).order_by(UserInvitation.created_at.desc()).all()
    except Exception as e:
        logger.error(f"Database error fetching invitations: {e}")
        raise HTTPException(500, "Failed to fetch invitations")
    
    return [
        InvitationResponse(
            token=getattr(inv, 'token', ''),
            email=getattr(inv, 'email', ''),
            role=getattr(inv, 'role', UserRole.VIEWER).value,
            expires_at=getattr(inv, 'expires_at', datetime.now(timezone.utc)),
            created_at=getattr(inv, 'created_at', datetime.now(timezone.utc))
        )
        for inv in invitations
    ]

@router.delete("/invitations/{token}")
def revoke_invitation(
    token: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Revoke invitation (admin only)"""
    invitation = db.query(UserInvitation).filter(
        UserInvitation.token == token
    ).first()
    
    if not invitation:
        raise HTTPException(404, "invitation not found")
    
    db.delete(invitation)
    db.commit()
    
    return {"message": "invitation revoked"}

@router.get("/invitations/{token}/validate")
def validate_invitation(token: str, db: Session = Depends(get_db)):
    """Validate invitation token (public endpoint)"""
    # Validate token format (hex string, 32 chars)
    if not token or not isinstance(token, str) or len(token) != 32:
        raise HTTPException(400, "invalid token format")
    if not all(c in '0123456789abcdef' for c in token.lower()):
        raise HTTPException(400, "invalid token format")
    
    now = datetime.now(timezone.utc)
    invitation = db.query(UserInvitation).filter(
        UserInvitation.token == token,
        UserInvitation.expires_at > now
    ).first()
    
    if not invitation:
        raise HTTPException(404, "invalid or expired invitation")
    
    return {
        "email": invitation.email,
        "role": invitation.role.value,
        "expires_at": invitation.expires_at
    }

@router.post("/invitations/{token}/accept")
def accept_invitation(
    token: str,
    password: str = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Accept invitation and create account (public endpoint)"""
    now = datetime.now(timezone.utc)
    invitation = db.query(UserInvitation).filter(
        UserInvitation.token == token,
        UserInvitation.expires_at > now
    ).first()
    
    if not invitation:
        raise HTTPException(404, "invalid or expired invitation")
    
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == invitation.email).first()
    if existing_user:
        raise HTTPException(409, "user already exists")
    
    # Validate password
    if len(password) < 8:
        raise HTTPException(400, "password must be at least 8 characters")
    
    if len(password) > 128:
        raise HTTPException(400, "password must be at most 128 characters")
    
    # Create user
    user = User(
        email=invitation.email,
        password_hash=hash_password(password),
        role=invitation.role,
        is_active=True
    )
    
    db.add(user)
    db.delete(invitation)
    db.commit()
    db.refresh(user)
    
    # Generate token
    email_val = getattr(user, 'email', '')
    jwt_token = sign_token(str(user.id), email_val)
    
    return {
        "token": jwt_token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role.value
        }
    }
