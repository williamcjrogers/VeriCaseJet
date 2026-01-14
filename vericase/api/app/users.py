"""
User Management API Endpoints
Handles user profile, password changes, and admin operations
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from .db import get_db
from .security import current_user, hash_password, verify_password, sign_token
from .models import User, UserRole, UserInvitation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


# Pydantic models for requests/responses
class UserProfile(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserListItem(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    display_name: str | None = None


class CreateUserRequest(BaseModel):
    email: str
    display_name: str | None = None
    role: str | None = "VIEWER"
    send_invite: bool = True


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
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "admin access required")
    return user


# Current user endpoints
@router.get("/me", response_model=UserProfile)
def get_current_user_profile(user: User = Depends(current_user)):
    """Get current user's profile"""
    return UserProfile(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.patch("/me", response_model=UserProfile)
def update_current_user_profile(
    data: UpdateProfileRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Update current user's profile"""
    if data.display_name is not None:
        user.display_name = data.display_name.strip() or None

    db.commit()
    db.refresh(user)

    return UserProfile(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post("/me/password")
def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Change current user's password"""
    # Verify current password
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(401, "current password is incorrect")

    # Validate new password
    if len(data.new_password) < 8:
        raise HTTPException(400, "new password must be at least 8 characters")

    if len(data.new_password) > 128:
        raise HTTPException(400, "new password must be at most 128 characters")

    # Update password
    user.password_hash = hash_password(data.new_password)
    db.commit()

    return {"message": "password changed successfully"}


# Admin endpoints
@router.post("", response_model=UserListItem)
def create_user(
    data: CreateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Create a new user (admin only)"""
    from .models import User as UserModel

    # Validate email
    email_lower = str(data.email).lower()
    if db.query(UserModel).filter(UserModel.email == email_lower).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Generate temporary password
    from .security_enhanced import generate_token, hash_password

    temp_password = generate_token()[:12]  # Use first 12 chars of token

    # Create user
    user = UserModel(
        email=email_lower,
        password_hash=hash_password(temp_password),
        display_name=data.display_name,
        role=UserRole(data.role) if data.role else UserRole.USER,
        is_active=True,
        email_verified=False,
        verification_token=generate_token(),
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)

        # Send welcome email with temp password if requested
        if data.send_invite:
            # TODO: Create welcome email template with temp password
            safe_email = user.email.replace("\n", "").replace("\r", "")
            logger.info(
                f"Welcome email would be sent to {safe_email} with temp password"
            )

        # Sanitize emails for logging to prevent log injection
        safe_user_email = user.email.replace("\n", "").replace("\r", "")
        safe_admin_email = admin.email.replace("\n", "").replace("\r", "")
        logger.info(f"User {safe_user_email} created by admin {safe_admin_email}")

        return UserListItem(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            role=user.role.value,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")


@router.get("", response_model=list[UserListItem])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """List all users (admin only)"""
    users = db.query(User).order_by(User.created_at.desc()).all()

    return [
        UserListItem(
            id=str(u.id),
            email=u.email,
            display_name=u.display_name,
            role=u.role.value,
            is_active=u.is_active,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
        )
        for u in users
    ]


@router.patch("/{user_id}", response_model=UserListItem)
def update_user(
    user_id: str,
    data: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
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
    if user.id == admin.id and data.is_active is False:
        raise HTTPException(400, "cannot deactivate your own account")

    # Prevent admin from demoting themselves
    if user.id == admin.id and data.role and data.role != UserRole.ADMIN.value:
        raise HTTPException(400, "cannot change your own role")

    # Update fields
    if data.role is not None:
        try:
            user.role = UserRole(data.role)
        except ValueError:
            raise HTTPException(400, "invalid role value")

    if data.is_active is not None:
        user.is_active = data.is_active

    if data.display_name is not None:
        user.display_name = data.display_name.strip() or None

    db.commit()
    db.refresh(user)

    return UserListItem(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


# Invitation endpoints
@router.post("/invitations", response_model=InvitationResponse)
def create_invitation(
    data: CreateInvitationRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Create user invitation (admin only)"""
    # Check if user already exists
    email_lower = str(data.email).lower()
    existing_user = db.query(User).filter(User.email == email_lower).first()
    if existing_user:
        raise HTTPException(409, "user with this email already exists")

    # Check if invitation already exists
    from datetime import timezone

    existing_invite = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.email.is_(email_lower),
            UserInvitation.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if existing_invite:
        raise HTTPException(409, "active invitation already exists for this email")

    # Validate role
    try:
        role = UserRole(data.role)
    except ValueError:
        raise HTTPException(400, f"invalid role: {data.role}")

    # Create invitation
    from datetime import timezone

    token = uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    invitation = UserInvitation(
        token=token,
        email=email_lower,
        role=role,
        invited_by=admin.id,
        expires_at=expires_at,
    )

    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    # TODO: Send invitation email
    # Sanitize emails for logging to prevent log injection
    safe_email = str(data.email).replace("\n", "").replace("\r", "")
    safe_admin_email = admin.email.replace("\n", "").replace("\r", "")
    logger.info(f"Invitation created for {safe_email} by {safe_admin_email}")

    return InvitationResponse(
        token=invitation.token,
        email=invitation.email,
        role=invitation.role.value,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@router.get("/invitations", response_model=list[InvitationResponse])
def list_invitations(
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    """List all active invitations (admin only)"""
    now = datetime.now(timezone.utc)
    invitations = (
        db.query(UserInvitation)
        .filter(UserInvitation.expires_at > now)
        .order_by(UserInvitation.created_at.desc())
        .all()
    )

    return [
        InvitationResponse(
            token=inv.token,
            email=inv.email,
            role=inv.role.value,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )
        for inv in invitations
    ]


@router.delete("/invitations/{token}")
def revoke_invitation(
    token: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    """Revoke invitation (admin only)"""
    invitation = db.query(UserInvitation).filter(UserInvitation.token == token).first()

    if not invitation:
        raise HTTPException(404, "invitation not found")

    db.delete(invitation)
    db.commit()

    return {"message": "invitation revoked"}


@router.get("/invitations/{token}/validate")
def validate_invitation(token: str, db: Session = Depends(get_db)):
    """Validate invitation token (public endpoint)"""
    now = datetime.now(timezone.utc)
    invitation = (
        db.query(UserInvitation)
        .filter(UserInvitation.token == token, UserInvitation.expires_at > now)
        .first()
    )

    if not invitation:
        raise HTTPException(404, "invalid or expired invitation")

    return {
        "email": invitation.email,
        "role": invitation.role.value,
        "expires_at": invitation.expires_at,
    }


@router.post("/invitations/{token}/accept")
def accept_invitation(
    token: str, password: str = Body(..., embed=True), db: Session = Depends(get_db)
):
    """Accept invitation and create account (public endpoint)"""
    now = datetime.now(timezone.utc)
    invitation = (
        db.query(UserInvitation)
        .filter(UserInvitation.token == token, UserInvitation.expires_at > now)
        .first()
    )

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
        is_active=True,
    )

    db.add(user)
    db.delete(invitation)
    db.commit()
    db.refresh(user)

    # Generate token
    jwt_token = sign_token(str(user.id), user.email)

    return {
        "token": jwt_token,
        "user": {"id": str(user.id), "email": user.email, "role": user.role.value},
    }
