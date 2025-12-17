from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from .config import settings
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    # DEBUG: Print environment variables (only in debug mode)
    if os.getenv("DEBUG", "false").lower() == "true":
        logger.debug("=" * 80)
        logger.debug("DEBUG: Environment Variables")
        logger.debug("=" * 80)
        for key, value in sorted(os.environ.items()):
            if "DATABASE" in key or "POSTGRES" in key or "RAILWAY" in key:
                # Mask sensitive parts of the value
                if "PASSWORD" in key or "SECRET" in key:
                    masked_value = (
                        value[:3] + "*" * (len(value) - 6) + value[-3:]
                        if len(value) > 6
                        else "*" * len(value)
                    )
                    logger.debug(f"{key} = {masked_value}")
                else:
                    logger.debug(f"{key} = {value}")
        logger.debug("=" * 80)
        logger.debug(f"DEBUG: settings.DATABASE_URL = '{settings.DATABASE_URL}'")
        logger.debug(f"DEBUG: Length of DATABASE_URL: {len(settings.DATABASE_URL)}")
        logger.debug("=" * 80)

    # Optimized connection pooling for high-performance
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_pre_ping=True,  # Verify connections before using
        pool_size=20,  # Base number of connections to keep open
        max_overflow=30,  # Allow up to 30 extra connections during peak load
        pool_timeout=30,  # Wait up to 30s for a connection
        pool_recycle=1800,  # Recycle connections every 30 min to avoid stale connections
        echo=False,  # Disable SQL logging for performance
    )
except Exception as e:
    logger.error(f"Failed to create database engine: {e}")
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
