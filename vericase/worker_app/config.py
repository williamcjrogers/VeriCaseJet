import os


def _normalize_redis_url(url: str | None) -> str | None:
    """Normalize Redis SSL query params to match redis-py expectations.

    Some environments set `ssl_cert_reqs=CERT_REQUIRED` (etc.) in REDIS_URL. redis-py
    expects `required|optional|none` (or None). Normalizing here keeps Celery stable.
    """
    if not url:
        return url
    return (
        url.replace("ssl_cert_reqs=CERT_REQUIRED", "ssl_cert_reqs=required")
        .replace("ssl_cert_reqs=CERT_OPTIONAL", "ssl_cert_reqs=optional")
        .replace("ssl_cert_reqs=CERT_NONE", "ssl_cert_reqs=none")
    )


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
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "vericase-data")
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
    REDIS_URL = _normalize_redis_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))
    # Default queue name matches the worker's default binding ("celery")
    CELERY_QUEUE = os.getenv("CELERY_QUEUE", "celery")
    # Dedicated queue for PST processing (kept separate for scalability)
    CELERY_PST_QUEUE = os.getenv("CELERY_PST_QUEUE", "pst_processing")
    TIKA_URL = os.getenv("TIKA_URL", "http://tika:9998")

    # PST task guardrails (prevents "stuck for days" tasks).
    # Soft limit raises in-task; hard limit force-kills the worker process.
    PST_TASK_SOFT_TIME_LIMIT_S = int(
        os.getenv("PST_TASK_SOFT_TIME_LIMIT_S", "21600") or "21600"
    )  # default 6h
    PST_TASK_TIME_LIMIT_S = int(
        os.getenv("PST_TASK_TIME_LIMIT_S", "22200") or "22200"
    )  # default 6h10m

    # If a PST is marked "processing" longer than this, it is likely orphaned and safe
    # for a new worker to reclaim (used to avoid "stuck for days" records).
    PST_PROCESSING_STALE_AFTER_HOURS = float(
        os.getenv("PST_PROCESSING_STALE_AFTER_HOURS", "12") or "12"
    )

    # Optional post-OCR enrichment (non-blocking, best-effort)
    ENABLE_DOCUMENT_ENRICHMENT = (
        os.getenv("ENABLE_DOCUMENT_ENRICHMENT", "false").lower() == "true"
    )

    # Bedrock LLM enrichment (fallback/default when BDA not configured)
    BEDROCK_DOC_ENRICH_ENABLED = (
        os.getenv("BEDROCK_DOC_ENRICH_ENABLED", "false").lower() == "true"
    )
    BEDROCK_DOC_ENRICH_MODEL_ID = os.getenv(
        "BEDROCK_DOC_ENRICH_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
    )
    BEDROCK_DOC_ENRICH_MAX_TOKENS = int(
        os.getenv("BEDROCK_DOC_ENRICH_MAX_TOKENS", "800") or "800"
    )
    BEDROCK_DOC_ENRICH_MAX_CHARS = int(
        os.getenv("BEDROCK_DOC_ENRICH_MAX_CHARS", "20000") or "20000"
    )
    BEDROCK_DOC_ENRICH_MIN_CHARS = int(
        os.getenv("BEDROCK_DOC_ENRICH_MIN_CHARS", "500") or "500"
    )

    # Bedrock Data Automation (BDA) enrichment (requires a project/profile/KMS config)
    BDA_DOC_ENRICH_ENABLED = (
        os.getenv("BDA_DOC_ENRICH_ENABLED", "false").lower() == "true"
    )
    BDA_REGION = os.getenv("BDA_REGION", os.getenv("AWS_REGION", "us-east-1"))
    BDA_PROJECT_ARN = os.getenv("BDA_PROJECT_ARN", "")
    BDA_PROFILE_ARN = os.getenv("BDA_PROFILE_ARN", "")
    BDA_STAGE = os.getenv("BDA_STAGE", "LIVE")
    BDA_BLUEPRINT_ARN = os.getenv("BDA_BLUEPRINT_ARN", "")
    BDA_BLUEPRINT_VERSION = os.getenv("BDA_BLUEPRINT_VERSION", "")
    BDA_BLUEPRINT_STAGE = os.getenv("BDA_BLUEPRINT_STAGE", "LIVE")
    BDA_KMS_KEY_ID = os.getenv("BDA_KMS_KEY_ID", "")
    # Separate queue so enrichment never starves OCR/PST extraction
    ENRICHMENT_QUEUE = os.getenv("ENRICHMENT_QUEUE", "enrichment")


settings = Settings()
