from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings
import os

# DEBUG: Print environment variables
print("=" * 80)
print("DEBUG: Environment Variables")
print("=" * 80)
for key, value in sorted(os.environ.items()):
    if 'DATABASE' in key or 'POSTGRES' in key or 'RAILWAY' in key:
        print(f"{key} = {value}")
print("=" * 80)
print(f"DEBUG: settings.DATABASE_URL = '{settings.DATABASE_URL}'")
print(f"DEBUG: Length of DATABASE_URL: {len(settings.DATABASE_URL)}")
print("=" * 80)

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Database dependency for FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
