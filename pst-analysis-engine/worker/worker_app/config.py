import os

from .logging_utils import install_log_sanitizer

install_log_sanitizer()


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"{var_name} environment variable is required")
    return value


class Settings:
    """Minimal settings loader with enforced env-only secrets."""

    def __init__(self) -> None:
        # AWS mode flag - when true, use AWS S3 (IRSA) instead of MinIO
        self.USE_AWS_SERVICES = os.getenv("USE_AWS_SERVICES", "false").lower() == "true"
        
        # S3/MinIO settings
        self.MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
        self.MINIO_PUBLIC_ENDPOINT = os.getenv("MINIO_PUBLIC_ENDPOINT", "")
        self.MINIO_BUCKET = os.getenv("MINIO_BUCKET", "vericase-docs")
        self.S3_ATTACHMENTS_BUCKET = os.getenv("S3_ATTACHMENTS_BUCKET")
        self.AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
        self.MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
        self.MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
        if not self.USE_AWS_SERVICES:
            if not self.MINIO_ACCESS_KEY:
                raise RuntimeError("MINIO_ACCESS_KEY must be set when USE_AWS_SERVICES is false")
            if not self.MINIO_SECRET_KEY:
                raise RuntimeError("MINIO_SECRET_KEY must be set when USE_AWS_SERVICES is false")
        elif not self.MINIO_BUCKET:
            raise RuntimeError("MINIO_BUCKET (storage bucket) must be set")
        
        # Database
        self.DATABASE_URL = _require_env("DATABASE_URL")
        
        # OpenSearch settings
        self.OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "opensearch")
        self.OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
        self.OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
        self.OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
        self.OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "documents")
        
        # Other services
        self.REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.CELERY_QUEUE = os.getenv("CELERY_QUEUE", "ocr")
        self.TIKA_URL = os.getenv("TIKA_URL", "http://tika:9998")


settings = Settings()
