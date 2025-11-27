from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from .config import settings
import os
from typing import Any

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
    
    # Optimized connection pooling for high-performance
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_pre_ping=True,           # Verify connections before using
        pool_size=20,                  # Base number of connections to keep open
        max_overflow=30,               # Allow up to 30 extra connections during peak load
        pool_timeout=30,               # Wait up to 30s for a connection
        pool_recycle=1800,             # Recycle connections every 30 min to avoid stale connections
        echo=False,                    # Disable SQL logging for performance
    )
except Exception as e:
    import logging
    logging.error(f"Failed to create database engine: {e}")
    # Re-raise the exception as this is critical
    raise
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base: Any = declarative_base()


def get_db():
    """Database dependency for FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
