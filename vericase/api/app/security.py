# pyright: reportArgumentType=false
import logging
import uuid

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Annotated, cast

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from passlib.hash import pbkdf2_sha256 as hasher
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import User

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=True)  # Require auth header
BearerCreds = Annotated[HTTPAuthorizationCredentials, Depends(bearer)]


def hash_password(p: str) -> str:
    return hasher.hash(p)


def verify_password(p: str, h: str) -> bool:
    return hasher.verify(p, h)


def sign_token(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iss": settings.JWT_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MIN),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DBSessionDep = Annotated[Session, Depends(get_db)]


def current_user(creds: BearerCreds, db: DBSessionDep) -> User:
    """
    Validate JWT token and return the authenticated user.
    Raises HTTPException 401 if authentication fails.
    """
    token = creds.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            issuer=settings.JWT_ISSUER,
        )
        user_id_str = cast(str, payload["sub"])
        user = db.query(User).filter(User.id == uuid.UUID(user_id_str)).first()
        if user:
            if not user.is_active:
                raise HTTPException(
                    status_code=401,
                    detail="User account is disabled",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return user
        else:
            logger.warning(f"User not found for token sub: {user_id_str}")
            raise HTTPException(
                status_code=401,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during authentication: {e}")
        raise HTTPException(
            status_code=401,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


# Alias for compatibility with cases.py
get_current_user = current_user

# Optional bearer for endpoints that can work with or without authentication
OptionalBearerCreds = Annotated[
    HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
]


def optional_current_user(creds: OptionalBearerCreds, db: DBSessionDep) -> User | None:
    """
    Returns user if valid token provided, None otherwise.
    Use for endpoints that can work with or without authentication.
    """
    if not creds:
        return None
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            issuer=settings.JWT_ISSUER,
        )
        user_id_str = cast(str, payload["sub"])
        user = db.query(User).filter(User.id == uuid.UUID(user_id_str)).first()
        if user and user.is_active:
            return user
        return None
    except JWTError:
        logger.debug("Optional auth: Invalid JWT token")
        return None
    except Exception as e:
        logger.debug(f"Optional auth: Unexpected error: {e}")
        return None
