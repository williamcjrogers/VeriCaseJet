"""
Enhanced security module with password policies, rate limiting, and session management
"""

from __future__ import annotations

import base64
import logging
import re
import secrets
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from functools import wraps
from time import time
from typing import Annotated, Any, Concatenate, ParamSpec, TypeVar

from fastapi import Depends, HTTPException, Request  # type: ignore[attr-defined]
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import status  # type: ignore[attr-defined]
from jose import JWTError, jwt
from passlib.hash import pbkdf2_sha256 as hasher
from sqlalchemy import and_
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import LoginAttempt, PasswordHistory, User, UserSession

logger = logging.getLogger(__name__)
P = ParamSpec("P")
T = TypeVar("T")

# Security settings
MAX_LOGIN_ATTEMPTS: int = getattr(settings, "MAX_LOGIN_ATTEMPTS", 5)
LOCKOUT_DURATION_MIN: int = getattr(settings, "LOCKOUT_DURATION_MIN", 30)
PASSWORD_RESET_HOURS: int = getattr(settings, "PASSWORD_RESET_HOURS", 24)
EMAIL_VERIFY_DAYS: int = getattr(settings, "EMAIL_VERIFY_DAYS", 7)
SESSION_REMEMBER_DAYS: int = getattr(settings, "SESSION_REMEMBER_DAYS", 0)

# Common passwords to block (top 100 most common)
COMMON_PASSWORDS = {
    "password",
    "123456",
    "password123",
    "12345678",
    "qwerty",
    "abc123",
    "Password1",
    "password1",
    "123456789",
    "welcome",
    "admin",
    "letmein",
    "monkey",
    "1234567890",
    "password123!",
    "qwerty123",
    "dragon",
    "baseball",
    "iloveyou",
    "trustno1",
    "sunshine",
    "master",
    "hello",
    "freedom",
    "whatever",
}

bearer = HTTPBearer(auto_error=True)

# Rate limiting storage (in production, use Redis)
_rate_limit_storage: defaultdict[str, list[float]] = defaultdict(list)


def clean_old_attempts(attempts: list[float], window: int = 3600) -> list[float]:
    """Remove attempts older than window seconds"""
    cutoff = time() - window
    return [t for t in attempts if t > cutoff]


def rate_limit(max_attempts: int = 10, window: int = 3600) -> Callable[
    [Callable[Concatenate[Request, P], Awaitable[T]]],
    Callable[Concatenate[Request, P], Awaitable[T]],
]:
    """Rate limiting decorator"""

    def decorator(
        func: Callable[Concatenate[Request, P], Awaitable[T]],
    ) -> Callable[Concatenate[Request, P], Awaitable[T]]:
        @wraps(func)
        async def wrapper(request: Request, *args: P.args, **kwargs: P.kwargs) -> T:
            # Get client IP
            client_ip = request.client.host if request.client else "unknown"
            key = f"{func.__name__}:{client_ip}"

            # Clean old attempts
            _rate_limit_storage[key] = clean_old_attempts(
                _rate_limit_storage[key], window
            )

            # Check rate limit
            if len(_rate_limit_storage[key]) >= max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Try again later.",
                )

            # Record attempt
            _rate_limit_storage[key].append(time())

            return await func(request, *args, **kwargs)

        return wrapper

    return decorator


def hash_password(password: str) -> str:
    """Hash password with pbkdf2_sha256"""
    return hasher.hash(password)


def verify_password(password: str, hash: str) -> bool:
    """Verify password against hash"""
    try:
        return hasher.verify(password, hash)
    except Exception:
        return False


def validate_password_strength(password: str) -> dict[str, Any]:
    """
    Validate password meets security requirements
    Returns dict with 'valid' bool and 'errors' list
    """
    errors = []

    # Length check
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    if len(password) > 128:
        errors.append("Password must be less than 128 characters")

    # Complexity checks
    has_upper = bool(re.search(r"[A-Z]", password))
    has_lower = bool(re.search(r"[a-z]", password))
    has_digit = bool(re.search(r"\d", password))
    has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))

    if not has_upper:
        errors.append("Password must contain at least one uppercase letter")
    if not has_lower:
        errors.append("Password must contain at least one lowercase letter")
    if not has_digit:
        errors.append("Password must contain at least one number")
    if not has_special:
        errors.append("Password must contain at least one special character")

    # Common password check
    if password.lower() in COMMON_PASSWORDS:
        errors.append("Password is too common. Please choose a more unique password")

    # Calculate strength score (0-100)
    score = 0
    if len(password) >= 8:
        score += 20
    if len(password) >= 12:
        score += 10
    if has_upper:
        score += 20
    if has_lower:
        score += 20
    if has_digit:
        score += 15
    if has_special:
        score += 15

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "score": score,
        "strength": "weak" if score < 50 else "medium" if score < 80 else "strong",
    }


def check_password_history(
    user_id: uuid.UUID, new_password: str, db: Session, history_count: int = 3
) -> bool:
    """Check if password was recently used"""
    recent_passwords = (
        db.query(PasswordHistory)
        .filter(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(history_count)
        .all()
    )

    for history_entry in recent_passwords:
        if verify_password(new_password, history_entry.password_hash):
            return False  # Password was recently used

    return True  # Password is okay to use


def generate_token() -> str:
    """Generate a secure random token"""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8")


def sign_jwt_token(
    user_id: str, email: str, remember_me: bool = False
) -> tuple[str, str]:
    """
    Sign JWT token and create session
    Returns (access_token, jti)
    """
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())  # JWT ID for session tracking

    # Extend expiration for "remember me"
    expire_minutes = settings.JWT_EXPIRE_MIN
    if remember_me and SESSION_REMEMBER_DAYS:
        expire_minutes = SESSION_REMEMBER_DAYS * 24 * 60

    payload = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    return token, jti


def verify_token(token: str) -> dict[str, Any]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=["HS256"], issuer=settings.JWT_ISSUER
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


def current_user_enhanced(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Enhanced current user with session validation"""
    try:
        # Verify token
        payload = verify_token(creds.credentials)

        # Check if session exists and is valid
        session = (
            db.query(UserSession)
            .filter(
                and_(
                    UserSession.token_jti == payload.get("jti"),
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > datetime.now(timezone.utc),
                )
            )
            .first()
        )

        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired or invalid",
            )

        # Get user
        user = db.query(User).filter(User.id == uuid.UUID(payload["sub"])).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
            )

        # Update session last activity
        session.last_activity = datetime.now(timezone.utc)
        db.commit()

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


def record_login_attempt(
    email: str,
    success: bool,
    user_id: uuid.UUID | None = None,
    failure_reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    db: Session | None = None,
) -> None:
    """Record login attempt for audit trail"""
    try:
        if db is None:
            return
        attempt = LoginAttempt(
            email=email,
            user_id=user_id,
            success=success,
            failure_reason=failure_reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(attempt)
        db.commit()
    except Exception as e:  # pragma: no cover - audit trail should not break auth
        logger.error(f"Failed to record login attempt: {e}")


def is_account_locked(user: User) -> bool:
    """Check if account is locked due to failed attempts"""
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        return True
    return False


def handle_failed_login(user: User, db: Session) -> None:
    """Update failed login counters and lock account if needed"""
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    user.last_failed_attempt = datetime.now(timezone.utc)

    if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(
            minutes=LOCKOUT_DURATION_MIN
        )
        logger.warning(
            f"Account locked for user {user.email} due to {user.failed_login_attempts} failed attempts"
        )

    db.commit()


def handle_successful_login(user: User, db: Session) -> None:
    """Reset failed login counters on successful login"""
    user.failed_login_attempts = 0
    user.last_failed_attempt = None
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()


# Maintain compatibility with existing code
def sign_token(user_id: str, email: str) -> str:
    """Compatibility wrapper for legacy callers."""
    token, _ = sign_jwt_token(user_id, email, False)
    return token


current_user = current_user_enhanced
get_current_user = current_user_enhanced
