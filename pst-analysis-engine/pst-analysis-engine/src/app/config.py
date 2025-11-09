from pydantic_settings import BaseSettings
from pydantic import field_validator, ValidationError
import os
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # AWS mode flag - when true, use AWS S3 (IRSA) instead of MinIO
    USE_AWS_SERVICES: bool = False
    
    # S3/MinIO settings
    # Note: S3_* fields are aliases for MINIO_* fields for backward compatibility
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = "admin"
    MINIO_SECRET_KEY: str = "changeme"
    MINIO_BUCKET: str = "vericase-docs"
    
    # S3 aliases (for backward compatibility)
    S3_BUCKET: str = "vericase-docs"
    S3_ENDPOINT: str = "http://minio:9000"
    S3_ACCESS_KEY: str = "admin"
    S3_SECRET_KEY: str = "changeme"
    AWS_REGION: str = "us-east-1"
    
    # Database - Railway provides postgresql://, we need postgresql+psycopg2://
    DATABASE_URL: str = "postgresql+psycopg2://vericase:vericase@postgres:5432/vericase"
    
    @field_validator('DATABASE_URL')
    @classmethod
    def convert_postgres_url(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+psycopg2:// for SQLAlchemy"""
        try:
            if not v or not v.strip():
                raise ValueError("DATABASE_URL cannot be empty")
            if v.startswith('postgresql://'):
                return v.replace('postgresql://', 'postgresql+psycopg2://', 1)
            return v
        except Exception as e:
            logger.error(f"Error validating DATABASE_URL: {e}")
            raise ValueError(f"Invalid DATABASE_URL configuration: {e}")
    
    # OpenSearch settings
    OPENSEARCH_HOST: str = "opensearch"
    OPENSEARCH_PORT: int = 9200
    OPENSEARCH_USE_SSL: bool = False
    OPENSEARCH_VERIFY_CERTS: bool = False
    OPENSEARCH_INDEX: str = "documents"
    
    # Other services
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_QUEUE: str = "ocr"
    TIKA_URL: str = "http://tika:9998"
    
    # API settings
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = ""
    JWT_SECRET: str = "change-this-secret"
    JWT_ISSUER: str = "vericase-docs"
    JWT_EXPIRE_MIN: int = 7200
    
    @field_validator('JWT_SECRET')
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Warn if JWT_SECRET is using default value"""
        try:
            if v == "change-this-secret":
                logger.warning("JWT_SECRET is using default value - INSECURE for production!")
                if os.getenv("ENV", "development").lower() == "production":
                    raise ValueError("JWT_SECRET must be changed in production")
            return v
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error validating JWT_SECRET: {e}")
            return v
    
    # AI Model API Keys
    GEMINI_API_KEY: str = ""
    CLAUDE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROK_API_KEY: str = ""
    PERPLEXITY_API_KEY: str = ""
    
    # AI Feature Flags
    ENABLE_AI_AUTO_CLASSIFY: bool = True
    ENABLE_AI_DATASET_INSIGHTS: bool = True
    ENABLE_AI_NATURAL_LANGUAGE_QUERY: bool = True
    AI_DEFAULT_MODEL: str = "gemini"
    
    @field_validator('AI_DEFAULT_MODEL')
    @classmethod
    def validate_ai_model(cls, v: str) -> str:
        """Validate AI model selection"""
        try:
            valid_models = ['gemini', 'claude', 'openai', 'grok', 'perplexity']
            if v and v not in valid_models:
                logger.warning(f"Invalid AI_DEFAULT_MODEL '{v}', using 'gemini'")
                return 'gemini'
            return v or 'gemini'
        except Exception as e:
            logger.error(f"Error validating AI_DEFAULT_MODEL: {e}")
            return 'gemini'
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Initialize settings with error handling
try:
    settings = Settings()
    logger.info("Settings loaded successfully")
except ValidationError as e:
    logger.error(f"Settings validation error: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error loading settings: {e}")
    raise
