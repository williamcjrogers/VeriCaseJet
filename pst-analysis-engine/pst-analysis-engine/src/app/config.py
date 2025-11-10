from pydantic_settings import BaseSettings  # type: ignore
from pydantic import Field, field_validator, model_validator, ValidationError
import os
import logging

from .logging_utils import install_log_sanitizer

install_log_sanitizer()

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # AWS mode flag - when true, use AWS S3 (IRSA) instead of MinIO
    USE_AWS_SERVICES: bool = False
    
    # S3/MinIO settings
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str | None = Field(default=None, description="MinIO access key from environment")
    MINIO_SECRET_KEY: str | None = Field(default=None, description="MinIO secret key from environment")
    MINIO_BUCKET: str = "vericase-docs"
    
    S3_BUCKET: str = "vericase-docs"
    S3_ENDPOINT: str = "http://minio:9000"
    S3_ACCESS_KEY: str | None = Field(default=None, description="S3 access key from environment")
    S3_SECRET_KEY: str | None = Field(default=None, description="S3 secret key from environment")
    S3_ATTACHMENTS_BUCKET: str | None = None
    AWS_REGION: str = "us-east-1"
    
    AWS_ACCESS_KEY_ID: str = Field(default="")
    AWS_SECRET_ACCESS_KEY: str = Field(default="")
    AWS_DEFAULT_REGION: str = "us-east-1"
    
    DATABASE_URL: str = Field(..., min_length=1)
    
    @field_validator('DATABASE_URL')
    @classmethod
    def convert_postgres_url(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+psycopg2:// for SQLAlchemy"""
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError("DATABASE_URL cannot be empty")
        if v.startswith('postgresql://'):
            return v.replace('postgresql://', 'postgresql+psycopg2://', 1)
        return v
    
    @field_validator('MINIO_ACCESS_KEY', 'MINIO_SECRET_KEY', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'DATABASE_URL')
    @classmethod
    def validate_secrets_not_default(cls, v: str | None, info):
        """Prevent use of default/weak credentials in production"""
        if v is None:
            return v
        
        try:
            env = os.getenv("ENV", "development").lower()
        except (AttributeError, TypeError):
            env = "development"
        
        if env == "production":
            # Check for common default credentials
            if info.field_name in {"MINIO_ACCESS_KEY", "S3_ACCESS_KEY"} and v == "admin":
                raise ValueError(f"{info.field_name} must not use default 'admin' in production")
            if info.field_name in {"MINIO_SECRET_KEY", "S3_SECRET_KEY"} and v == "changeme":
                raise ValueError(f"{info.field_name} must not use default 'changeme' in production")
            if info.field_name == "DATABASE_URL" and "vericase:vericase@" in (v or ""):
                raise ValueError("DATABASE_URL uses default credentials in production")
        return v
    
    @model_validator(mode="after")
    def ensure_required_credentials(self) -> "Settings":
        """Ensure storage and database secrets are provided via environment variables."""
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set via environment variables")
        
        try:
            use_aws = self.USE_AWS_SERVICES or not self.MINIO_ENDPOINT
        except (AttributeError, TypeError):
            use_aws = False
        
        if not use_aws:
            if not self.MINIO_ACCESS_KEY:
                raise ValueError("MINIO_ACCESS_KEY must be set when USE_AWS_SERVICES is false")
            if not self.MINIO_SECRET_KEY:
                raise ValueError("MINIO_SECRET_KEY must be set when USE_AWS_SERVICES is false")
        else:
            if not self.MINIO_BUCKET:
                raise ValueError("MINIO_BUCKET (storage bucket name) is required")
        
        if not self.S3_ACCESS_KEY:
            self.S3_ACCESS_KEY = self.MINIO_ACCESS_KEY
        if not self.S3_SECRET_KEY:
            self.S3_SECRET_KEY = self.MINIO_SECRET_KEY
        
        return self
    
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
    JWT_SECRET: str = Field(..., min_length=1)
    JWT_ISSUER: str = "vericase-docs"
    JWT_EXPIRE_MIN: int = 7200
    
    @field_validator('JWT_SECRET')
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Validate JWT_SECRET is secure and not empty"""
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError("JWT_SECRET cannot be empty")
        if len(v) < 32:
            logger.warning("JWT_SECRET is too short. Recommended minimum: 32 characters")
        
        # Check for default/weak secrets
        weak_secrets = ["change-this-secret", "secret", "changeme", "default"]
        if v.lower() in weak_secrets:
            try:
                env_value = os.getenv("ENV", "development")
                if env_value and env_value.lower() == "production":
                    raise ValueError("JWT_SECRET must be changed from default value in production")
            except (AttributeError, TypeError):
                pass
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
        valid_models = ['gemini', 'claude', 'openai', 'grok', 'perplexity']
        if v and v not in valid_models:
            logger.warning("Invalid AI_DEFAULT_MODEL, using 'gemini'")
            return 'gemini'
        return v or 'gemini'
    
    @field_validator('AWS_REGION', 'AWS_DEFAULT_REGION')
    @classmethod
    def validate_aws_region(cls, v: str) -> str:
        """Validate AWS region is valid"""
        valid_regions = [
            'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
            'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1',
            'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1',
            'ca-central-1', 'sa-east-1'
        ]
        if v and v not in valid_regions:
            logger.warning(f"AWS region '{v}' may not be valid. Common regions: {', '.join(valid_regions[:5])}")
        return v or 'us-east-1'
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Initialize settings with error handling
try:
    settings = Settings()  # type: ignore[call-arg]
    logger.info("Settings loaded successfully")
except ValidationError as e:
    logger.error("Settings validation error: %s", str(e))
    raise
except Exception as e:
    logger.error("Unexpected error loading settings: %s", str(e))
    try:
        env = os.getenv("ENV", "development").lower()
    except (AttributeError, TypeError):
        env = "development"
    
    if env == "production":
        raise
    raise
