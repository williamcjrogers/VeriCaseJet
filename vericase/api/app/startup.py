"""Application startup logic (DB bootstrap, migrations, AI settings sync).

Extracted from main.py to reduce module size.
"""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import text

from .config import settings
from .db import Base, engine, SessionLocal
from .models import AppSetting
from .storage import ensure_bucket_once

logger = logging.getLogger(__name__)


def _populate_ai_settings_from_env(force_update: bool = False):
    """
    Populate AI settings in database from environment variables.
    This ensures Admin Settings UI shows the configured API keys.

    Args:
        force_update: If True, update existing settings even if they have values.
                     Used after loading from AWS Secrets Manager.
    """
    db = SessionLocal()
    try:
        # If older/stale model IDs made it into the database, they can cause
        # provider test calls to fail (e.g., 404 model not found). We auto-fix
        # known-bad values on startup.
        deprecated_value_replacements: dict[str, dict[str, str]] = {
            # Anthropic: update to latest Claude 4.5 model IDs (December 2025)
            "anthropic_model": {
                "claude-sonnet-4.5": "claude-sonnet-4.5-20251201",
                "claude-opus-4.5": "claude-opus-4.5-20251201",
                "claude-haiku-4.5": "claude-haiku-4.5-20251201",
                "claude-sonnet-4-20250514": "claude-sonnet-4.5-20251201",
                "claude-opus-4-20250514": "claude-opus-4.5-20251201",
            },
        }

        # Map of database setting keys to environment variable names and descriptions
        ai_settings_map = {
            "openai_api_key": {
                "env_var": "OPENAI_API_KEY",
                "config_attr": "OPENAI_API_KEY",
                "description": "OpenAI API key for GPT models",
                "is_api_key": True,
            },
            "anthropic_api_key": {
                "env_var": "CLAUDE_API_KEY",
                "config_attr": "CLAUDE_API_KEY",
                "description": "Anthropic API key for Claude models",
                "is_api_key": True,
            },
            "gemini_api_key": {
                "env_var": "GEMINI_API_KEY",
                "config_attr": "GEMINI_API_KEY",
                "description": "Google API key for Gemini models",
                "is_api_key": True,
            },
            # Bedrock settings (uses IAM credentials, not API keys)
            "bedrock_enabled": {
                "env_var": "BEDROCK_ENABLED",
                "config_attr": "BEDROCK_ENABLED",
                "description": "Enable Amazon Bedrock AI provider",
                "default": "false",
            },
            "bedrock_region": {
                "env_var": "BEDROCK_REGION",
                "config_attr": "BEDROCK_REGION",
                "description": "AWS region for Bedrock",
                "default": "us-east-1",
            },
            # Default models - Updated December 2025
            "openai_model": {
                "default": "gpt-5.2-instant",
                "description": "Default OpenAI model",
            },
            "anthropic_model": {
                "default": "claude-sonnet-4.5-20251201",
                "description": "Default Anthropic model (Claude Sonnet 4.5 - December 2025)",
            },
            "gemini_model": {
                "default": "gemini-2.5-flash",
                "description": "Default Gemini model",
            },
            "bedrock_model": {
                "default": "amazon.nova-pro-v1:0",
                "description": "Default Bedrock model",
            },
            # Default provider
            "ai_default_provider": {
                "default": "anthropic",
                "description": "Default AI provider to use",
            },
        }

        populated_count = 0

        for key, config in ai_settings_map.items():
            # Check if setting already exists
            existing = db.query(AppSetting).filter(AppSetting.key == key).first()

            # If an existing value is known-deprecated, we will replace it even
            # when not force-updating.
            replacement = None
            if existing and existing.value:
                replacement = deprecated_value_replacements.get(key, {}).get(
                    existing.value
                )

            # Skip if setting exists and has value (unless force_update for API keys)
            if existing and existing.value:
                if config.get("is_api_key"):
                    if not force_update:
                        continue
                else:
                    if not replacement:
                        continue

            # Get value from environment or config
            value = None

            if "env_var" in config:
                # Try environment variable first
                value = os.getenv(config["env_var"])

                # Also accept ANTHROPIC_API_KEY for compatibility with docs/common naming.
                if not value and key == "anthropic_api_key":
                    value = os.getenv("ANTHROPIC_API_KEY")

                # Fall back to config settings
                if not value and "config_attr" in config:
                    value = getattr(settings, config["config_attr"], None)
            elif "default" in config:
                # Use default value for model settings
                value = replacement or config["default"]

            if value:
                if existing:
                    # Update existing setting
                    if existing.value != value:
                        existing.value = value
                        logger.info(f"Updated AI setting: {key}")
                        populated_count += 1
                else:
                    # Create new setting
                    new_setting = AppSetting(
                        key=key, value=value, description=config.get("description", "")
                    )
                    db.add(new_setting)
                    logger.info(f"Created AI setting: {key}")
                    populated_count += 1

        if populated_count > 0:
            db.commit()
            logger.info(f"Populated {populated_count} AI settings from environment")
        else:
            logger.debug("AI settings already configured, no changes needed")

    except Exception as e:
        logger.error(f"Error populating AI settings: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def startup():
    """FastAPI startup event handler -- DB bootstrap, migrations, AI settings sync."""
    logger.info("Starting VeriCase API...")

    # IMPORTANT (K8s deploy reliability):
    # When running in production we start the container via `/code/start.sh`, which already:
    # - waits for Postgres
    # - runs Alembic migrations
    # - optionally runs legacy SQL migrations
    # - bootstraps the admin user
    # - syncs AI settings
    #
    # This FastAPI startup hook performs additional *schema/infra bootstrap* work
    # (create_all, ALTER TABLEs, auto-schema-sync, etc). Those operations can block on
    # Postgres locks (especially ALTER TABLE) and prevent Uvicorn from binding to :8000,
    # which causes Kubernetes startup/readiness probes to fail and rollouts to hang.
    #
    # We treat `SKIP_SQL_MIGRATIONS=true` as "fast production startup" and skip the
    # FastAPI startup bootstrap entirely.
    if os.getenv("SKIP_SQL_MIGRATIONS", "").strip().lower() in ("1", "true", "yes"):
        logger.info(
            "SKIP_SQL_MIGRATIONS=true -> skipping FastAPI startup bootstrap to keep startup non-blocking"
        )
        return

    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created")

        # Best-effort bucket provisioning/verification for local MinIO and AWS S3.
        # Upload endpoints (PST + evidence) require the bucket(s) to exist.
        try:
            candidate_buckets = {
                getattr(settings, "MINIO_BUCKET", None),
                getattr(settings, "S3_BUCKET", None),
                getattr(settings, "S3_PST_BUCKET", None),
                getattr(settings, "S3_ATTACHMENTS_BUCKET", None),
                "vericase-data",  # Production AWS bucket
            }
            for b in sorted({b for b in candidate_buckets if b}):
                ensure_bucket_once(b)
            logger.info("Storage bucket(s) verified")
        except Exception as bucket_err:
            logger.warning(
                "Storage bucket initialization skipped (non-fatal): %s", bucket_err
            )

        # Load AI keys from AWS Secrets Manager FIRST (if configured)
        # This ensures production gets keys from Secrets Manager before DB sync.
        force_update_ai_keys = (
            os.getenv("AI_FORCE_UPDATE_AI_KEYS", "").lower()
            in (
                "1",
                "true",
                "yes",
            )
            # If AWS Secrets Manager is configured, keys should be treated as
            # source-of-truth on each startup (rotated secrets should win).
            or bool(
                os.getenv("AWS_SECRETS_MANAGER_AI_KEYS") or os.getenv("AWS_SECRET_NAME")
            )
        )

        if os.getenv("AWS_SECRETS_MANAGER_AI_KEYS") or os.getenv("AWS_SECRET_NAME"):
            try:
                from app.config_production import load_ai_keys_from_secrets_manager

                load_ai_keys_from_secrets_manager(force_update=force_update_ai_keys)
                logger.info("✓ AWS Secrets Manager keys loaded before AI settings sync")
            except Exception as secrets_err:
                logger.warning(f"AWS Secrets load skipped (non-fatal): {secrets_err}")

        # Keep DB-backed AI settings in sync with environment/defaults.
        # Without this, Admin Settings UI can show stale values and runtime may
        # continue using older DB overrides even after env/templates change.
        try:
            _populate_ai_settings_from_env(force_update=force_update_ai_keys)
        except Exception as ai_seed_err:
            logger.warning(f"AI settings population skipped (non-fatal): {ai_seed_err}")

        # Run schema migrations for BigInt support
        with engine.connect() as conn:
            logger.info("Running schema migrations for Large File support...")

            # 1. Documents
            try:
                conn.execute(
                    text("ALTER TABLE documents ALTER COLUMN size TYPE BIGINT")
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration skipped for documents: {e}")
                conn.rollback()

            # 2. PST Files
            try:
                conn.execute(
                    text(
                        "ALTER TABLE pst_files ALTER COLUMN file_size_bytes TYPE BIGINT"
                    )
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration skipped for pst_files: {e}")
                conn.rollback()

            try:
                conn.execute(
                    text(
                        "ALTER TABLE pst_files ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"
                    )
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration skipped for pst_files uploaded_at: {e}")
                conn.rollback()

            # 3. Email Attachments
            try:
                conn.execute(
                    text(
                        "ALTER TABLE email_attachments ALTER COLUMN file_size_bytes TYPE BIGINT"
                    )
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration skipped for email_attachments: {e}")
                conn.rollback()

            # 4. Evidence Items
            try:
                conn.execute(
                    text(
                        "ALTER TABLE evidence_items ALTER COLUMN file_size TYPE BIGINT"
                    )
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration skipped for evidence_items: {e}")
                conn.rollback()

            # 4b. Evidence Items string column sizes (prevents truncation on long types)
            # NOTE: `v_evidence_with_links` depends on evidence_items (SELECT ei.*),
            # so we must drop/recreate it before altering column types.
            try:
                file_type_len_row = conn.execute(
                    text(
                        """
                        SELECT character_maximum_length
                        FROM information_schema.columns
                        WHERE table_name = 'evidence_items' AND column_name = 'file_type'
                        """
                    )
                ).fetchone()
                mime_type_len_row = conn.execute(
                    text(
                        """
                        SELECT character_maximum_length
                        FROM information_schema.columns
                        WHERE table_name = 'evidence_items' AND column_name = 'mime_type'
                        """
                    )
                ).fetchone()

                file_type_len = file_type_len_row[0] if file_type_len_row else None
                mime_type_len = mime_type_len_row[0] if mime_type_len_row else None

                needs_file_type_widen = (
                    file_type_len is not None and int(file_type_len) < 255
                )
                needs_mime_type_widen = (
                    mime_type_len is not None and int(mime_type_len) < 255
                )

                if needs_file_type_widen or needs_mime_type_widen:
                    with conn.begin():
                        conn.execute(text("DROP VIEW IF EXISTS v_evidence_with_links"))
                        if needs_file_type_widen:
                            conn.execute(
                                text(
                                    "ALTER TABLE evidence_items ALTER COLUMN file_type TYPE VARCHAR(255)"
                                )
                            )
                        if needs_mime_type_widen:
                            conn.execute(
                                text(
                                    "ALTER TABLE evidence_items ALTER COLUMN mime_type TYPE VARCHAR(255)"
                                )
                            )

                        conn.execute(
                            text(
                                """
                                CREATE OR REPLACE VIEW v_evidence_with_links AS
                                SELECT
                                    ei.*,
                                    COALESCE(link_counts.correspondence_count, 0) as correspondence_count,
                                    COALESCE(link_counts.verified_link_count, 0) as verified_link_count,
                                    COALESCE(rel_counts.relation_count, 0) as relation_count
                                FROM evidence_items ei
                                LEFT JOIN (
                                    SELECT
                                        evidence_item_id,
                                        COUNT(*) as correspondence_count,
                                        COUNT(*) FILTER (WHERE is_verified) as verified_link_count
                                    FROM evidence_correspondence_links
                                    GROUP BY evidence_item_id
                                ) link_counts ON ei.id = link_counts.evidence_item_id
                                LEFT JOIN (
                                    SELECT
                                        source_evidence_id as evidence_id,
                                        COUNT(*) as relation_count
                                    FROM evidence_relations
                                    GROUP BY source_evidence_id
                                ) rel_counts ON ei.id = rel_counts.evidence_id
                                """
                            )
                        )
            except Exception as e:
                logger.warning(
                    "Migration skipped for evidence_items file_type/mime_type: %s", e
                )
                conn.rollback()

            # 5. Ensure Default Data (Robust Seeding)
            try:
                # Get admin user ID for ownership - check both admin accounts
                result = conn.execute(
                    text(
                        "SELECT id FROM users WHERE email IN ('admin@vericase.com', 'admin@veri-case.com') ORDER BY created_at DESC LIMIT 1"
                    )
                )
                admin_row = result.fetchone()

                if admin_row:
                    admin_id = str(admin_row[0])
                    # Default Case (with owner_id)
                    conn.execute(
                        text(
                            """
                        INSERT INTO cases (id, name, case_number, description, owner_id, created_at, updated_at)
                        VALUES ('dca0d854-1655-4498-97f3-399b47a4d65f', 'Default Case', 'DEFAULT-001', 'Auto-generated default case', :owner_id, NOW(), NOW())
                        ON CONFLICT (id) DO NOTHING;
                    """
                        ),
                        {"owner_id": admin_id},
                    )

                    # Default Project (linked to Default Case, with owner)
                    conn.execute(
                        text(
                            """
                        INSERT INTO projects (id, project_name, project_code, description, owner_user_id, created_at, updated_at)
                        VALUES ('dbae0b15-8b63-46f7-bb2e-1b5a4de13ed8', 'Default Project', 'DEFAULT-PROJECT', 'Auto-generated default project', :owner_id, NOW(), NOW())
                        ON CONFLICT (id) DO NOTHING;
                    """
                        ),
                        {"owner_id": admin_id},
                    )
                    conn.commit()
                    logger.info("Verified/Created default Case and Project")
                else:
                    logger.warning(
                        "Admin user not found, skipping default data seeding"
                    )
            except Exception as e:
                logger.warning(f"Failed to seed default data: {e}")
                conn.rollback()

            # 5. Evidence Sources
            try:
                conn.execute(
                    text(
                        "ALTER TABLE evidence_sources ALTER COLUMN original_size TYPE BIGINT"
                    )
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"Migration skipped for evidence_sources: {e}")
                conn.rollback()

            logger.info("Schema migration attempts completed")

            # AUTO-SYNC: Add any missing columns from SQLAlchemy models
            logger.info("Running auto-schema-sync for missing columns...")
            try:
                from sqlalchemy import inspect

                inspector = inspect(engine)

                # Get all model classes from Base
                for table_name, table in Base.metadata.tables.items():
                    try:
                        existing_columns = {
                            col["name"] for col in inspector.get_columns(table_name)
                        }
                        model_columns = {col.name for col in table.columns}
                        missing_columns = model_columns - existing_columns

                        for col_name in missing_columns:
                            col = table.columns[col_name]
                            # Build column type string - convert SQLAlchemy types to PostgreSQL
                            col_type = str(col.type)
                            # Fix SQLAlchemy DATETIME -> PostgreSQL TIMESTAMP
                            if col_type.upper() == "DATETIME":
                                col_type = "TIMESTAMP WITH TIME ZONE"
                            _nullable = "NULL" if col.nullable else "NOT NULL"
                            default = ""
                            if col.default is not None:
                                if hasattr(col.default, "arg"):
                                    default_val = col.default.arg
                                    if callable(default_val):
                                        default = ""  # Skip callable defaults
                                    elif isinstance(default_val, bool):
                                        default = str(default_val).upper()
                                    elif isinstance(default_val, str):
                                        default = f"'{default_val}'"
                                    else:
                                        default = str(default_val)

                            sql = f'ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS "{col_name}" {col_type} {_nullable} {default}'
                            logger.info(f"  Adding column: {table_name}.{col_name}")
                            conn.execute(text(sql))
                            conn.commit()
                    except Exception as col_err:
                        logger.debug(f"Column sync skipped for {table_name}: {col_err}")
                        conn.rollback()

                logger.info("Auto-schema-sync completed")
            except Exception as sync_err:
                logger.warning(f"Auto-schema-sync failed: {sync_err}")
                conn.rollback()

    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")

    logger.info("Startup complete")
