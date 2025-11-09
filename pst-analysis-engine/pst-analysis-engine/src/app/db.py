from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import logging

# Initialize logger first
logger = logging.getLogger(__name__)

# Import settings with error handling
try:
    from .config import settings
except Exception as e:
    logger.critical(f"Failed to load configuration: {e}")
    raise RuntimeError(f"Configuration loading failed: {e}") from e

# Create database engine with comprehensive error handling
try:
    if not settings.DATABASE_URL:
        raise ValueError("DATABASE_URL is not configured")
    
    engine = create_engine(
        settings.DATABASE_URL, 
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=3600
    )
    logger.info("Database engine created successfully")
except ValueError as e:
    logger.critical(f"Invalid database configuration: {e}")
    raise RuntimeError(f"Database configuration error: {e}") from e
except Exception as e:
    logger.critical(f"Failed to create database engine: {e}")
    raise RuntimeError(f"Database connection failed: {e}") from e

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Database dependency for FastAPI"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        raise
    finally:
        db.close()
