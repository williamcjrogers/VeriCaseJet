import os


class Settings:
    # AWS mode flag - when true, use AWS S3 (IRSA) instead of MinIO
    USE_AWS_SERVICES = os.getenv("USE_AWS_SERVICES", "false").lower() == "true"

    # Text extraction feature flag
    # New canonical name (mirrors api/app/config.Settings.USE_TEXTRACT)
    USE_TEXTRACT = os.getenv("USE_TEXTRACT", "true").lower() == "true"

    # Backwards-compatible alias for older code/docs that used `settings.use_textract`
    @property
    def use_textract(self) -> bool:  # pragma: no cover - simple alias
        return self.USE_TEXTRACT

    # S3/MinIO settings
    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "changeme")
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "vericase-docs")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

    # Database
    DATABASE_URL = os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://vericase:vericase@postgres:5432/vericase"
    )

    # OpenSearch settings
    OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "opensearch")
    OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
    OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
    OPENSEARCH_VERIFY_CERTS = (
        os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
    )
    OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "documents")

    # Other services
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
    # Default queue name matches the worker's default binding ("celery")
    CELERY_QUEUE = os.getenv("CELERY_QUEUE", "celery")
    TIKA_URL = os.getenv("TIKA_URL", "http://tika:9998")


settings = Settings()
