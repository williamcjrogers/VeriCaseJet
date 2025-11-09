from pydantic_settings import BaseSettings
from pydantic import field_validator
import os

class Settings(BaseSettings):
    # AWS mode flag - when true, use AWS S3 (IRSA) instead of MinIO
    USE_AWS_SERVICES: bool = False
    
    # S3/MinIO settings
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = "admin"
    MINIO_SECRET_KEY: str = "changeme"
    MINIO_BUCKET: str = "vericase-docs"
    S3_BUCKET: str = "vericase-docs"  # Alias for MINIO_BUCKET
    S3_ENDPOINT: str = "http://minio:9000"  # Alias for MINIO_ENDPOINT
    S3_ACCESS_KEY: str = "admin"  # Alias for MINIO_ACCESS_KEY
    S3_SECRET_KEY: str = "changeme"  # Alias for MINIO_SECRET_KEY
    AWS_REGION: str = "us-east-1"
    
    # Database - Railway provides postgresql://, we need postgresql+psycopg2://
    DATABASE_URL: str = "postgresql+psycopg2://vericase:vericase@postgres:5432/vericase"
    
    @field_validator('DATABASE_URL')
    @classmethod
    def convert_postgres_url(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+psycopg2:// for SQLAlchemy"""
        if v and v.startswith('postgresql://'):
            return v.replace('postgresql://', 'postgresql+psycopg2://', 1)
        return v
    
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

settings = Settings()
