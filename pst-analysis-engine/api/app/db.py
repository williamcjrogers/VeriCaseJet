from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings
import os

try:
    # DEBUG: Print environment variables (only in debug mode)
    if os.getenv("DEBUG", "false").lower() == "true":
        print("=" * 80)
        print("DEBUG: Environment Variables")
        print("=" * 80)
        for key, value in sorted(os.environ.items()):
            if 'DATABASE' in key or 'POSTGRES' in key or 'RAILWAY' in key:
                # Mask sensitive parts of the value
                if 'PASSWORD' in key or 'SECRET' in key:
                    masked_value = value[:3] + '*' * (len(value) - 6) + value[-3:] if len(value) > 6 else '*' * len(value)
                    print(f"{key} = {masked_value}")
                else:
                    print(f"{key} = {value}")
        print("=" * 80)
        print(f"DEBUG: settings.DATABASE_URL = '{settings.DATABASE_URL}'")
        print(f"DEBUG: Length of DATABASE_URL: {len(settings.DATABASE_URL)}")
        print("=" * 80)
    
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
except Exception as e:
    import logging
    logging.error(f"Failed to create database engine: {e}")
    # Re-raise the exception as this is critical
    raise
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Database dependency for FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
