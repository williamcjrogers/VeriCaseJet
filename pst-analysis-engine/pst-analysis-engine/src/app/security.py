import datetime
import uuid
import logging
from typing import Optional
from jose import jwt, JWTError
from passlib.hash import pbkdf2_sha256 as hasher
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .config import settings
from .db import SessionLocal
from .models import User

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=True)


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256"""
    try:
        return hasher.hash(password)
    except Exception as e:
        logger.error(f"Password hashing failed: {e}")
        raise


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash"""
    try:
        return hasher.verify(password, password_hash)
    except Exception as e:
        logger.error(f"Password verification failed: {e}")
        return False


def sign_token(user_id: str, email: str) -> str:
    """Generate a JWT token for a user"""
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "sub": user_id,
            "email": email,
            "iss": settings.JWT_ISSUER,
            "iat": now,
            "exp": now + datetime.timedelta(minutes=settings.JWT_EXPIRE_MIN)
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    except Exception as e:
        logger.error(f"Token signing failed: {e}")
        raise


def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from JWT token"""
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            issuer=settings.JWT_ISSUER
        )
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Unexpected error decoding token: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        user_uuid = uuid.UUID(payload["sub"])
    except (ValueError, KeyError) as e:
        logger.warning(f"Invalid user ID in token: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        logger.warning(f"User not found: {user_uuid}")
        raise HTTPException(status_code=401, detail="User not found")
    
    return user


# Alias for compatibility with cases.py
get_current_user = current_user
