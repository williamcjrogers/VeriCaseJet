from pydantic_settings import BaseSettings  # type: ignore
from pydantic import field_validator, ValidationError
import os
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # AWS mode flag - when true, use AWS S3 (IRSA) instead of MinIO
    USE_AWS_SERVICES: bool = False
    
    # S3/MinIO settings
    # Note: S3_* fields are aliases for MINIO_* fields for backward compatibility
    # Default values are for development only - override in production via environment variables
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = "admin"  # Override in production
    MINIO_SECRET_KEY: str = "changeme"  # Override in production
    MINIO_BUCKET: str = "vericase-docs"
    
    # S3 aliases (for backward compatibility)
    # Default values are for development only - override in production via environment variables
    S3_BUCKET: str = "vericase-docs"
    S3_ENDPOINT: str = "http://minio:9000"
    S3_ACCESS_KEY: str = "admin"  # Override in production
    S3_SECRET_KEY: str = "changeme"  # Override in production
    AWS_REGION: str = "us-east-1"
    
    # Database - Railway provides postgresql://, we need postgresql+psycopg2://
    # Default value is for development only - override in production via environment variables
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
        except (AttributeError, TypeError) as e:
            logger.error(f"Error validating DATABASE_URL: {e}")
            raise ValueError(f"Invalid DATABASE_URL format: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error validating DATABASE_URL: {e}")
            raise
    
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
        """Validate JWT_SECRET is secure and not empty"""
        if not v or not v.strip():
            raise ValueError("JWT_SECRET cannot be empty")
        
        # Check minimum length for security
        if len(v) < 32:
            logger.warning(f"JWT_SECRET is too short ({len(v)} chars). Recommended minimum: 32 characters")
        
        # Warn about default value
        if v == "change-this-secret":
            logger.warning("JWT_SECRET is using default value - INSECURE for production!")
            
            # Check if we're in production
            try:
                env_value = os.getenv("ENV", "development")
                if env_value and env_value.lower() == "production":
                    raise ValueError("JWT_SECRET must be changed from default value in production")
            except (AttributeError, TypeError) as e:
                logger.error(f"Error checking environment: {e}")
        
        return v
    
    @field_validator('JWT_EXPIRE_MIN')
    @classmethod
    def validate_jwt_expire(cls, v: int) -> int:
        """Validate JWT expiration time is reasonable"""
        if not isinstance(v, int):
            raise ValueError(f"JWT_EXPIRE_MIN must be an integer, got {type(v).__name__}")
        
        if v <= 0:
            raise ValueError(f"JWT_EXPIRE_MIN must be positive, got {v}")
        
        if v < 5:
            logger.warning(f"JWT_EXPIRE_MIN is very short ({v} minutes). Consider a longer duration")
        
        if v > 43200:  # 30 days
            logger.warning(f"JWT_EXPIRE_MIN is very long ({v} minutes = {v/1440:.1f} days)")
        
        return v
    
    @field_validator('JWT_ISSUER')
    @classmethod
    def validate_jwt_issuer(cls, v: str) -> str:
        """Validate JWT issuer is not empty"""
        if not v or not v.strip():
            raise ValueError("JWT_ISSUER cannot be empty")
        return v.strip()
    
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
