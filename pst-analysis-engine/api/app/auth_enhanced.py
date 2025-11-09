"""
Enhanced authentication endpoints with security features
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Body, Path
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, Dict
import uuid
import logging
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr, Field

from .db import get_db
from .models import User, UserSession, PasswordHistory
from .security_enhanced import (
    hash_password, verify_password, validate_password_strength,
    check_password_history, generate_token, sign_jwt_token,
    verify_token, current_user_enhanced, record_login_attempt,
    is_account_locked, handle_failed_login, handle_successful_login,
    rate_limit, EMAIL_VERIFY_DAYS, PASSWORD_RESET_HOURS
)
from .security import current_user  # For compatibility
from .config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth-enhanced"])

# Pydantic models
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: Optional[str] = None
    organization: Optional[str] = None

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class RefreshTokenRequest(BaseModel):
    token: str

# Enhanced login with security features
@router.post("/login-secure")
@rate_limit(max_attempts=5, window=900)  # 5 attempts per 15 minutes
async def login_secure(
    request: Request,
    data: LoginRequest,
    db: Session = Depends(get_db)
):
    """Enhanced login with rate limiting and account lockout"""
    # Get request info
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent", "")
    
    # Find user
    user = db.query(User).filter(User.email == data.email.lower()).first()
    
    if not user:
        # Record failed attempt even for non-existent users (prevent enumeration)
        record_login_attempt(
            email=data.email.lower(),
            success=False,
            failure_reason="user_not_found",
            ip_address=client_ip,
            user_agent=user_agent,
            db=db
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Check if account is locked
    if is_account_locked(user):
        remaining_minutes = int((user.locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is locked. Try again in {remaining_minutes} minutes."
        )
    
    # Verify password
    if not verify_password(data.password, user.password_hash):
        handle_failed_login(user, db)
        record_login_attempt(
            email=data.email.lower(),
            success=False,
            user_id=user.id,
            failure_reason="invalid_password",
            ip_address=client_ip,
            user_agent=user_agent,
            db=db
        )
        
        attempts_remaining = 5 - (user.failed_login_attempts or 0)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid credentials. {attempts_remaining} attempts remaining."
        )
    
    # Check if email is verified
    if not user.email_verified:
        logger.warning(f"Unverified email login attempt for {user.email}")
        # Still allow login but include warning in response
    
    # Successful login
    handle_successful_login(user, db)
    
    # Create JWT and session
    token, jti = sign_jwt_token(str(user.id), user.email, data.remember_me)
    
    # Create session record
    session = UserSession(
        user_id=user.id,
        token_jti=jti,
        ip_address=client_ip,
        user_agent=user_agent,
        expires_at=datetime.now(timezone.utc) + timedelta(
            days=30 if data.remember_me else 1
        )
    )
    db.add(session)
    db.commit()
    
    # Record successful login
    record_login_attempt(
        email=data.email.lower(),
        success=True,
        user_id=user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        db=db
    )
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "email_verified": user.email_verified,
            "role": user.role.value if user.role else "EDITOR"
        },
        "warning": None if user.email_verified else "Please verify your email address"
    }

# Logout endpoint
@router.post("/logout")
async def logout(
    user: User = Depends(current_user_enhanced),
    db: Session = Depends(get_db)
):
    """Logout and invalidate current session"""
    # Get current token from context
    # In production, you'd extract the JTI from the current request token
    # For now, we'll revoke all active sessions for the user
    active_sessions = db.query(UserSession).filter(
        and_(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(timezone.utc)
        )
    ).all()
    
    for session in active_sessions:
        session.revoked_at = datetime.now(timezone.utc)
    
    db.commit()
    
    return {"message": "Successfully logged out"}

# Token refresh endpoint
@router.post("/refresh")
async def refresh_token(
    data: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """Refresh access token before expiry"""
    try:
        # Verify current token
        payload = verify_token(data.token)
        
        # Check if session is still valid
        session = db.query(UserSession).filter(
            and_(
                UserSession.token_jti == payload.get("jti"),
                UserSession.revoked_at.is_(None)
            )
        ).first()
        
        if not session or session.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session"
            )
        
        # Get user
        user = db.query(User).filter(User.id == uuid.UUID(payload["sub"])).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user"
            )
        
        # Issue new token
        new_token, new_jti = sign_jwt_token(str(user.id), user.email, False)
        
        # Create new session and revoke old one
        session.revoked_at = datetime.now(timezone.utc)
        
        new_session = UserSession(
            user_id=user.id,
            token_jti=new_jti,
            ip_address=session.ip_address,
            user_agent=session.user_agent,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        )
        db.add(new_session)
        db.commit()
        
        return {
            "access_token": new_token,
            "token_type": "bearer"
        }
        
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to refresh token"
        )

# Request password reset
@router.post("/request-reset")
@rate_limit(max_attempts=3, window=3600)  # 3 attempts per hour
async def request_password_reset(
    request: Request,
    data: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """Request password reset email"""
    user = db.query(User).filter(User.email == data.email.lower()).first()
    
    # Always return success to prevent email enumeration
    if user:
        # Generate reset token
        reset_token = generate_token()
        user.reset_token = reset_token
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_HOURS)
        db.commit()
        
        # Send reset email
        from .email_service import email_service
        email_service.send_password_reset(
            to_email=user.email,
            user_name=user.display_name or user.email.split('@')[0],
            reset_token=reset_token
        )
        logger.info(f"Password reset email sent to {user.email}")
    
    return {
        "message": "If the email exists, a password reset link has been sent."
    }

# Complete password reset
@router.post("/reset-password")
async def reset_password(
    data: PasswordResetConfirm,
    db: Session = Depends(get_db)
):
    """Complete password reset with token"""
    # Find user by reset token
    user = db.query(User).filter(
        and_(
            User.reset_token == data.token,
            User.reset_token_expires > datetime.now(timezone.utc)
        )
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    
    # Validate new password
    validation = validate_password_strength(data.new_password)
    if not validation['valid']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Password does not meet requirements", "errors": validation['errors']}
        )
    
    # Check password history
    if not check_password_history(user.id, data.new_password, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password was recently used. Please choose a different password."
        )
    
    # Update password
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.reset_token = None
    user.reset_token_expires = None
    
    # Add to password history
    history = PasswordHistory(
        user_id=user.id,
        password_hash=user.password_hash
    )
    db.add(history)
    
    # Revoke all existing sessions
    db.query(UserSession).filter(
        and_(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None)
        )
    ).update({"revoked_at": datetime.now(timezone.utc)})
    
    db.commit()
    
    return {
        "message": "Password successfully reset. Please login with your new password."
    }

# Change password (authenticated)
@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(current_user_enhanced),
    db: Session = Depends(get_db)
):
    """Change password for authenticated user"""
    # Verify current password
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )
    
    # Validate new password
    validation = validate_password_strength(data.new_password)
    if not validation['valid']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Password does not meet requirements", "errors": validation['errors']}
        )
    
    # Check password history
    if not check_password_history(user.id, data.new_password, db):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password was recently used. Please choose a different password."
        )
    
    # Update password
    user.password_hash = hash_password(data.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    
    # Add to password history
    history = PasswordHistory(
        user_id=user.id,
        password_hash=user.password_hash
    )
    db.add(history)
    db.commit()
    
    return {
        "message": "Password successfully changed"
    }

# Email verification endpoint
@router.post("/verify-email/{token}")
async def verify_email(
    token: str = Path(...),
    db: Session = Depends(get_db)
):
    """Verify email address with token"""
    user = db.query(User).filter(User.verification_token == token).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token"
        )
    
    # Check if already verified
    if user.email_verified:
        return {"message": "Email already verified"}
    
    # Verify email
    user.email_verified = True
    user.verification_token = None
    db.commit()
    
    return {
        "message": "Email successfully verified. You can now login."
    }

# List user sessions
@router.get("/sessions")
async def list_sessions(
    user: User = Depends(current_user_enhanced),
    db: Session = Depends(get_db)
):
    """List active sessions for current user"""
    sessions = db.query(UserSession).filter(
        and_(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(timezone.utc)
        )
    ).order_by(UserSession.last_activity.desc()).all()
    
    return {
        "sessions": [
            {
                "id": str(session.id),
                "ip_address": session.ip_address,
                "user_agent": session.user_agent,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "expires_at": session.expires_at.isoformat()
            }
            for session in sessions
        ]
    }

# Revoke specific session
@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str = Path(...),
    user: User = Depends(current_user_enhanced),
    db: Session = Depends(get_db)
):
    """Revoke a specific session"""
    session = db.query(UserSession).filter(
        and_(
            UserSession.id == uuid.UUID(session_id),
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None)
        )
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    
    return {"message": "Session revoked"}

# Password strength check endpoint
@router.post("/check-password-strength")
async def check_password_strength(password: str = Body(..., embed=True)):
    """Check password strength without storing it"""
    validation = validate_password_strength(password)
    return {
        "valid": validation['valid'],
        "score": validation['score'],
        "strength": validation['strength'],
        "errors": validation['errors']
    }
