"""
Authentication helpers for case management and programmes
"""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .security import current_user, get_db
from .models import User

bearer = HTTPBearer()


def get_current_user_email(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db)
) -> str:
    """Get current user's email from token"""
    user = current_user(creds, db)
    return user.email
