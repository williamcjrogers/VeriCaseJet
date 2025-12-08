"""
Authentication helpers for case management and programmes
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .security import current_user, get_db

bearer = HTTPBearer()

CredentialsDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer)]
DbSessionDep = Annotated[Session, Depends(get_db)]


def get_current_user_email(
    creds: CredentialsDep,
    db: DbSessionDep,
) -> str:
    """Get current user's email from token"""
    user = current_user(creds, db)
    return user.email
