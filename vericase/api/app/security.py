# pyright: reportArgumentType=false
"""
Unified security re-export module.

All authentication primitives live in ``security_enhanced`` (password
hashing, JWT signing, rate-limiting, session management) and ``db``
(database session helpers).  This module re-exports every public name
so that existing ``from .security import ...`` statements across the
codebase continue to work without modification.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, cast

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, get_db  # noqa: F401 – re-export
from .models import User

# ---------------------------------------------------------------------------
# Re-exports from security_enhanced
# ---------------------------------------------------------------------------
from .security_enhanced import (  # noqa: F401 – re-export
    bearer,
    check_password_history,
    clean_old_attempts,
    current_user,
    current_user_enhanced,
    generate_token,
    get_current_user,
    handle_failed_login,
    handle_successful_login,
    hash_password,
    is_account_locked,
    rate_limit,
    record_login_attempt,
    sign_jwt_token,
    sign_token,
    validate_password_strength,
    verify_password,
    verify_token,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases kept for backward compatibility
# ---------------------------------------------------------------------------
BearerCreds = Annotated[HTTPAuthorizationCredentials, Depends(bearer)]
DBSessionDep = Annotated[Session, Depends(get_db)]

# Optional bearer for endpoints that can work with or without authentication
OptionalBearerCreds = Annotated[
    HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
]


# ---------------------------------------------------------------------------
# Functions that have no equivalent in security_enhanced
# ---------------------------------------------------------------------------
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


def get_current_user_email(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> str:
    """Get current user's email from token (moved from auth.py)."""
    user = current_user(creds, db)
    return user.email
