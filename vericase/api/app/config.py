# pyright: reportCallIssue=false, reportConstantRedefinition=false
# pyright: reportGeneralTypeIssues=false, reportUnnecessaryIsInstance=false
# pyright: reportArgumentType=false, reportUnnecessaryTypeIgnoreComment=false
from typing import Self
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator, ValidationInfo
import os
import logging

from .logging_utils import install_log_sanitizer

install_log_sanitizer()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )
    # AWS mode flag - when true, use AWS S3 (IRSA) instead of MinIO
    USE_AWS_SERVICES: bool = False

    # S3/MinIO settings
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str | None = Field(
        default=None,
        description=("MinIO/S3 access key - MUST be provided via environment variable"),
    )
    MINIO_SECRET_KEY: str | None = Field(
        default=None,
        description=("MinIO/S3 secret key - MUST be provided via environment variable"),
    )
    MINIO_BUCKET: str = "vericase-docs"
    S3_BUCKET: str = "vericase-docs"  # Alias for MINIO_BUCKET
    S3_ENDPOINT: str = "http://minio:9000"  # Alias for MINIO_ENDPOINT
    S3_ACCESS_KEY: str | None = Field(
        default=None,
        description="S3 access key - MUST be provided via environment variable",
    )
    S3_SECRET_KEY: str | None = Field(
        default=None,
        description="S3 secret key - MUST be provided via environment variable",
    )
    S3_ATTACHMENTS_BUCKET: str | None = None
    S3_PST_BUCKET: str | None = None
    S3_REGION: str = "us-east-1"  # S3 bucket region (can differ from AWS_REGION)
    AWS_REGION: str = "us-east-1"

    # AWS Credentials (optional - for non-IRSA deployments)
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_DEFAULT_REGION: str = "us-east-1"
    AWS_SECRET_NAME: str = ""  # Secrets Manager secret name (optional)

    # Database - Railway provides postgresql://, we need postgresql+psycopg2://
    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://vericase:vericase@postgres:5432/vericase",
        description=("SQLAlchemy connection URL; defaults to local postgres for dev"),
        min_length=1,
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def convert_postgres_url(cls, v: str) -> str:
        """Convert postgresql:// to postgresql+psycopg2:// for SQLAlchemy"""
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v

    @field_validator(
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "DATABASE_URL",
    )
    @classmethod
    def validate_secrets_not_default(cls, v: str | None, info: ValidationInfo):
        """Prevent use of weak/default credentials in any environment."""
        if v is None:
            return v

        try:
            env = os.getenv("ENV", "development").lower()
        except (AttributeError, TypeError):
            env = "development"

        # Define weak/default credentials to block
        weak_access_keys = {"admin", "minioadmin", "root", "user"}
        weak_secret_keys = {"changeme", "password", "secret", "minioadmin"}

        # Block weak credentials in production
        if env == "production":
            if info.field_name in {"MINIO_ACCESS_KEY", "S3_ACCESS_KEY"}:
                if v.lower() in weak_access_keys:
                    raise ValueError(
                        f"{info.field_name} uses weak/default value in production"
                    )

            if info.field_name in {"MINIO_SECRET_KEY", "S3_SECRET_KEY"}:
                if v.lower() in weak_secret_keys:
                    raise ValueError(
                        f"{info.field_name} uses weak/default value in production"
                    )

            if info.field_name == "DATABASE_URL":
                weak_db_patterns = [
                    "vericase:vericase@",
                    "postgres:postgres@",
                    "admin:admin@",
                ]
                if any(pattern in (v or "") for pattern in weak_db_patterns):
                    raise ValueError(
                        "DATABASE_URL uses default credentials in production"
                    )
        else:
            # Warn in non-production environments
            if (
                info.field_name
                in {
                    "MINIO_ACCESS_KEY",
                    "S3_ACCESS_KEY",
                }
                and v.lower() in weak_access_keys
            ):
                logging.warning(
                    "%s uses default value - override via environment variable",
                    info.field_name,
                )
            if (
                info.field_name
                in {
                    "MINIO_SECRET_KEY",
                    "S3_SECRET_KEY",
                }
                and v.lower() in weak_secret_keys
            ):
                logging.warning(
                    "%s uses default value - override via environment variable",
                    info.field_name,
                )

        return v

    @model_validator(mode="after")
    def ensure_required_credentials(self) -> Self:
        """
        Ensure secrets are provided exclusively via environment variables.
        """
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set via environment variables")

        use_aws = self.USE_AWS_SERVICES or not self.MINIO_ENDPOINT
        if not use_aws:
            if not self.MINIO_ACCESS_KEY:
                raise ValueError(
                    "MINIO_ACCESS_KEY must be set when USE_AWS_SERVICES is false"
                )
            if not self.MINIO_SECRET_KEY:
                raise ValueError(
                    "MINIO_SECRET_KEY must be set when USE_AWS_SERVICES is false"
                )
        else:
            # Allow AWS IRSA without explicit keys, but normalize aliases if
            # provided
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
    # Celery queue name; use "celery" so the default worker binds without
    # extra flags
    CELERY_QUEUE: str = "celery"
    # Dedicated queue for PST processing (can be same as CELERY_QUEUE)
    CELERY_PST_QUEUE: str = "pst_processing"
    TIKA_URL: str = "http://tika:9998"

    # PST ingestion performance
    # When true (default), pre-traverse the PST to count total messages for progress %
    # tracking. Disable to avoid the extra full pass on very large PSTs.
    PST_PRECOUNT_MESSAGES: bool = (
        True  # Enable progress-friendly total email counts (counts folders, not every message)
    )

    # PST processing optimization settings
    PST_BATCH_COMMIT_SIZE: int = 2500  # Messages per DB commit batch
    # Parallel S3 upload threads (0 = auto sized based on CPU, capped).
    PST_UPLOAD_WORKERS: int = 0
    PST_SKIP_SEMANTIC_INDEXING: bool = True  # Skip during ingestion (run in background)
    # Threading/dedupe scope: "pst" (fast) or "project"/"case" (global, slower).
    PST_THREADING_SCOPE: str = "pst"
    PST_DEDUPE_SCOPE: str = "pst"
    # Inline (CID) images are usually signatures/disclaimers and are extremely costly/noisy.
    # Default off for speed + evidence signal-to-noise; set true if you want to retain them.
    PST_INCLUDE_INLINE_ATTACHMENTS: bool = False
    # Skip non-email MAPI items (tasks/appointments/etc) during PST ingest for speed and signal quality.
    # Set false if you need to ingest *all* IPM.* items for a forensic workflow.
    PST_SKIP_NON_EMAIL_ITEMS: bool = True
    PST_AGENT_LOG_ENABLED: bool = False  # Disable local debug logging in production
    PST_AGENT_LOG_PATH: str | None = None  # Optional file path for local debug logs

    # PST local temp storage
    # Large PSTs are downloaded locally before pypff can open them. In containers,
    # the default temp dir may be too small for multi-GB PSTs.
    PST_TEMP_DIR: str | None = None  # e.g. "/mnt/pst-tmp" (must be writable)
    PST_KEEP_TEMP_ON_ERROR: bool = False  # for debugging only; can fill disk quickly

    # AWS Textract settings
    USE_TEXTRACT: bool = True  # Use Textract as primary, Tika as fallback
    TEXTRACT_MAX_FILE_SIZE_MB: int = 500  # Textract limit: 500MB total
    TEXTRACT_MAX_PAGE_SIZE_MB: int = 10  # Textract limit: 10MB per page
    TEXTRACT_MAX_PAGES: int = 500  # Textract limit: 500 pages
    # Use Tika for PDFs over this many pages (cost/speed optimization)
    TEXTRACT_PAGE_THRESHOLD: int = 100
    AWS_REGION_FOR_TEXTRACT: str = "eu-west-2"  # Default region for Textract

    # AWS Bedrock Knowledge Base settings
    # Bedrock Knowledge Base ID (e.g., "VERICASE-KB-001")
    BEDROCK_KB_ID: str = ""
    BEDROCK_DS_ID: str = ""  # Bedrock Data Source ID (e.g., "VERICASE-DS-001")
    BEDROCK_AGENT_ID: str = ""  # Bedrock Agent ID (e.g., "AGENT123456")
    BEDROCK_AGENT_ALIAS_ID: str = ""  # Bedrock Agent Alias ID (e.g., "TSTALIASID")
    BEDROCK_EMBEDDING_MODEL: str = (
        "amazon.titan-embed-text-v1"  # Embedding model for KB
    )
    # When true, AI endpoints will attempt to augment prompts from the KB
    USE_KNOWLEDGE_BASE: bool = True

    # Ops / monitoring defaults (optional)
    EKS_CLUSTER_NAME: str = ""
    RDS_INSTANCE_ID: str = ""
    CLOUDWATCH_LOG_GROUP: str = ""

    # AWS Step Functions settings
    STEP_FUNCTION_ARN: str = ""  # ARN of the evidence processing state machine

    # AWS EventBridge settings
    EVENT_BUS_NAME: str = "vericase-events"  # Custom event bus name

    # AWS OpenSearch Serverless settings
    OPENSEARCH_COLLECTION_ARN: str = ""  # OpenSearch Serverless collection ARN
    OPENSEARCH_COLLECTION_ENDPOINT: str = ""  # OpenSearch Serverless endpoint
    OPENSEARCH_VECTOR_INDEX: str = "vericase-evidence-index"  # Vector index name

    # AWS QuickSight settings
    QUICKSIGHT_DASHBOARD_ID: str = ""  # QuickSight dashboard ID
    QUICKSIGHT_DATASET_ID: str = ""  # QuickSight dataset ID

    # AWS Macie settings
    MACIE_ENABLED: bool = False  # Enable Macie sensitive data scanning

    # Deployment Settings (SSH automation)
    STAGING_HOST: str = ""
    STAGING_KEY_PATH: str = ""
    PRODUCTION_HOST: str = ""
    PRODUCTION_KEY_PATH: str = ""

    # AWS Lambda function names (for Step Functions)
    LAMBDA_TEXTRACT_PROCESSOR: str = "vericase-textract-processor"
    LAMBDA_COMPREHEND_ANALYZER: str = "vericase-comprehend-analyzer"
    LAMBDA_DOCUMENT_CLASSIFIER: str = "vericase-document-classifier"
    LAMBDA_DATABASE_UPDATER: str = "vericase-database-updater"
    LAMBDA_KB_INGESTER: str = "vericase-kb-ingester"

    # S3 Buckets for AWS services
    S3_KNOWLEDGE_BASE_BUCKET: str = ""  # S3 bucket for Bedrock KB documents
    S3_TRANSCRIBE_OUTPUT_BUCKET: str = ""  # S3 bucket for Transcribe output

    # Backwards-compatible alias for older code/docs that used
    # `settings.use_textract`
    @property
    def use_textract(self) -> bool:  # pragma: no cover - simple alias
        return self.USE_TEXTRACT

    # API settings
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = ""
    JWT_SECRET: str = Field(
        default="c3bef73578895c08045f8848192958b2dbfaf55a57f97509553c3d5324a7d2b1",
        description="JWT signing secret - override via environment variable",
        min_length=32,
    )

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Validate JWT_SECRET is secure."""
        if not v or not isinstance(v, str):
            raise ValueError("JWT_SECRET cannot be empty")

        # Check for weak secrets
        weak_secrets = {
            "secret",
            "changeme",
            "default",
            "jwt-secret",
            "change-this-secret",
        }
        if v.lower() in weak_secrets:
            try:
                env = os.getenv("ENV", "development").lower()
                if env == "production":
                    raise ValueError("JWT_SECRET uses weak/default value in production")
                else:
                    logging.warning(
                        "JWT_SECRET uses weak value - change via environment variable"
                    )
            except (AttributeError, TypeError):
                pass

        if len(v) < 32:
            logging.warning("JWT_SECRET is shorter than recommended 32 characters")

        return v

    JWT_ISSUER: str = "vericase-docs"
    JWT_EXPIRE_MIN: int = 7200

    # =========================================================================
    # AI MODEL API KEYS — 6 PROVIDERS
    # =========================================================================
    # OpenAI (GPT-5.x, GPT-4o, o1, embeddings)
    OPENAI_API_KEY: str = ""
    # Anthropic (Claude 4.x, Sonnet, Opus, Haiku)
    CLAUDE_API_KEY: str = ""
    # Google (Gemini 3/2.5 Pro, Flash, Lite)
    GEMINI_API_KEY: str = ""
    # xAI (Grok 4.x — 2M context)
    XAI_API_KEY: str = ""
    GROK_API_KEY: str = ""  # Alias for XAI_API_KEY
    # Perplexity (Sonar - real-time web search)
    PERPLEXITY_API_KEY: str = ""
    # Lex API (legislation/caselaw search)
    LEX_API_BASE_URL: str = ""
    LEX_API_TOKEN: str = ""
    LEX_API_AUTH_HEADER: str = "Authorization"
    LEX_API_AUTH_SCHEME: str = "Bearer"
    LEX_API_TIMEOUT_S: float = 20.0
    LEX_API_OPERATION_MAP: str = ""

    # =========================================================================
    # AMAZON BEDROCK (Claude via AWS, Nova, Titan, Cohere embeddings)
    # =========================================================================
    BEDROCK_ENABLED: bool = False
    BEDROCK_REGION: str = "us-east-1"
    # Route Claude requests through Bedrock instead of direct Anthropic API
    BEDROCK_ROUTE_CLAUDE: bool = False

    # =========================================================================
    # EMBEDDING / VECTOR SEARCH
    # =========================================================================
    EMBEDDING_PROVIDER: str = "bedrock"  # bedrock | sentence-transformers
    BEDROCK_EMBEDDING_MODEL: str = "cohere.embed-english-v3"
    MULTI_VECTOR_ENABLED: bool = True

    # =========================================================================
    # AI FEATURE FLAGS
    # =========================================================================
    ENABLE_AI_AUTO_CLASSIFY: bool = True
    ENABLE_AI_DATASET_INSIGHTS: bool = True
    ENABLE_AI_NATURAL_LANGUAGE_QUERY: bool = True
    AI_DEFAULT_MODEL: str = (
        "gemini"  # gemini | openai | anthropic | bedrock | xai | perplexity
    )
    AI_WEB_ACCESS_ENABLED: bool = False
    AI_TASK_COMPLEXITY_DEFAULT: str = (
        "basic"  # basic | moderate | deep_research | advanced
    )
    AI_MODEL_PREFERENCES: dict[str, str] = Field(default_factory=dict)

    # =========================================================================
    # AI FALLBACK + ROUTING + ORCHESTRATION
    # =========================================================================
    AI_FALLBACK_ENABLED: bool = True
    AI_FALLBACK_LOG_ATTEMPTS: bool = True
    AI_ROUTING_STRATEGY: str = (
        "balanced"  # performance | cost | latency | quality | balanced | pinned | fallback
    )
    AI_PREFER_BEDROCK: bool = True
    AI_ENABLE_MULTI_MODEL: bool = False
    AI_ENABLE_VALIDATION: bool = True


try:
    settings = Settings()  # pyright: ignore[reportCallIssue]
except Exception as exc:
    logging.critical("Failed to load settings: %s", exc)
    raise
