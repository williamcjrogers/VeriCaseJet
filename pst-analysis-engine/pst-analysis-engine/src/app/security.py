import datetime, uuid
from typing import Optional
from jose import jwt
from passlib.hash import pbkdf2_sha256 as hasher
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .config import settings
from .db import SessionLocal
from .models import User
bearer = HTTPBearer(auto_error=True)
def hash_password(p: str) -> str: return hasher.hash(p)
def verify_password(p: str, h: str) -> bool: return hasher.verify(p, h)
def sign_token(user_id: str, email: str) -> str:
    now = datetime.datetime.utcnow()
    payload = {"sub": user_id, "email": email, "iss": settings.JWT_ISSUER, "iat": now, "exp": now + datetime.timedelta(minutes=settings.JWT_EXPIRE_MIN)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(creds.credentials, settings.JWT_SECRET, algorithms=["HS256"], issuer=settings.JWT_ISSUER)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    import uuid as _u
    user = db.query(User).filter(User.id == _u.UUID(payload["sub"])).first()
    if not user: raise HTTPException(status_code=401, detail="User not found")
    return user

# Alias for compatibility with cases.py
get_current_user = current_user
