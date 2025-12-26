"""Add canonical raw/occurrence/derived message tables.

Revision ID: 0009_message_raw_derived
Revises: 0008_case_project_link
Create Date: 2025-12-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0009_message_raw_derived"
down_revision: str = "0008_case_project_link"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = :table
            )
            """
        ),
        {"table": table},
    )
    return bool(result.scalar())


def _uuid_type():
    conn = op.get_bind()
    if getattr(conn.dialect, "name", "") == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def _json_type():
    conn = op.get_bind()
    if getattr(conn.dialect, "name", "") == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.JSONB
    return sa.JSON


def upgrade() -> None:
    uuid_type = _uuid_type()
    json_type = _json_type()

    if not _table_exists("message_raw"):
        op.create_table(
            "message_raw",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("source_hash", sa.String(length=128), nullable=False),
            sa.Column("storage_uri", sa.String(length=2048), nullable=True),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("extraction_tool_version", sa.String(length=64), nullable=True),
            sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_metadata", json_type, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        try:
            op.create_index(
                "idx_message_raw_source_hash", "message_raw", ["source_hash"]
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_raw_source_type", "message_raw", ["source_type"]
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_raw_extracted_at", "message_raw", ["extracted_at"]
            )
        except Exception:
            pass

    if not _table_exists("message_occurrences"):
        op.create_table(
            "message_occurrences",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "raw_id", uuid_type, sa.ForeignKey("message_raw.id"), nullable=False
            ),
            sa.Column("ingest_run_id", sa.String(length=128), nullable=False),
            sa.Column("source_location", sa.Text(), nullable=True),
            sa.Column(
                "seen_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column("case_id", uuid_type, sa.ForeignKey("cases.id"), nullable=True),
            sa.Column(
                "project_id", uuid_type, sa.ForeignKey("projects.id"), nullable=True
            ),
        )
        try:
            op.create_index(
                "idx_message_occurrences_raw_id", "message_occurrences", ["raw_id"]
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_occurrences_ingest_run",
                "message_occurrences",
                ["ingest_run_id"],
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_occurrences_case", "message_occurrences", ["case_id"]
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_occurrences_project",
                "message_occurrences",
                ["project_id"],
            )
        except Exception:
            pass

    if not _table_exists("message_derived"):
        op.create_table(
            "message_derived",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "raw_id", uuid_type, sa.ForeignKey("message_raw.id"), nullable=False
            ),
            sa.Column("normalizer_version", sa.String(length=64), nullable=False),
            sa.Column("normalizer_ruleset_hash", sa.String(length=64), nullable=True),
            sa.Column("parser_version", sa.String(length=64), nullable=True),
            sa.Column("canonical_subject", sa.Text(), nullable=True),
            sa.Column("canonical_participants", json_type, nullable=True),
            sa.Column("canonical_body_preview", sa.Text(), nullable=True),
            sa.Column("canonical_body_full", sa.Text(), nullable=True),
            sa.Column("banner_stripped_body", sa.Text(), nullable=True),
            sa.Column("quote_blocks", json_type, nullable=True),
            sa.Column("user_blocks", json_type, nullable=True),
            sa.Column("content_hash_phase1", sa.String(length=128), nullable=True),
            sa.Column("content_hash_phase2", sa.String(length=128), nullable=True),
            sa.Column("thread_id_header", sa.String(length=128), nullable=True),
            sa.Column("thread_confidence", sa.String(length=32), nullable=True),
            sa.Column("qc_flags", json_type, nullable=True),
            sa.Column(
                "derived_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        try:
            op.create_index("idx_message_derived_raw_id", "message_derived", ["raw_id"])
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_derived_hash_p1",
                "message_derived",
                ["content_hash_phase1"],
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_derived_hash_p2",
                "message_derived",
                ["content_hash_phase2"],
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_message_derived_thread_header",
                "message_derived",
                ["thread_id_header"],
            )
        except Exception:
            pass

    if not _table_exists("attachment_raw"):
        op.create_table(
            "attachment_raw",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "raw_id", uuid_type, sa.ForeignKey("message_raw.id"), nullable=False
            ),
            sa.Column("attachment_hash", sa.String(length=128), nullable=True),
            sa.Column("storage_uri", sa.String(length=2048), nullable=True),
            sa.Column("mime_type", sa.String(length=255), nullable=True),
            sa.Column("filename_normalized", sa.String(length=512), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        try:
            op.create_index("idx_attachment_raw_message", "attachment_raw", ["raw_id"])
        except Exception:
            pass
        try:
            op.create_index(
                "idx_attachment_raw_hash", "attachment_raw", ["attachment_hash"]
            )
        except Exception:
            pass

    if not _table_exists("enrichment_artefacts"):
        op.create_table(
            "enrichment_artefacts",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column(
                "derived_id",
                uuid_type,
                sa.ForeignKey("message_derived.id"),
                nullable=False,
            ),
            sa.Column("artefact_type", sa.String(length=64), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=True),
            sa.Column("storage_uri", sa.String(length=2048), nullable=True),
            sa.Column("metadata", json_type, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        try:
            op.create_index(
                "idx_enrichment_artefacts_derived",
                "enrichment_artefacts",
                ["derived_id"],
            )
        except Exception:
            pass
        try:
            op.create_index(
                "idx_enrichment_artefacts_type",
                "enrichment_artefacts",
                ["artefact_type"],
            )
        except Exception:
            pass


def downgrade() -> None:
    for index_name, table in [
        ("idx_enrichment_artefacts_type", "enrichment_artefacts"),
        ("idx_enrichment_artefacts_derived", "enrichment_artefacts"),
        ("idx_attachment_raw_hash", "attachment_raw"),
        ("idx_attachment_raw_message", "attachment_raw"),
        ("idx_message_derived_thread_header", "message_derived"),
        ("idx_message_derived_hash_p2", "message_derived"),
        ("idx_message_derived_hash_p1", "message_derived"),
        ("idx_message_derived_raw_id", "message_derived"),
        ("idx_message_occurrences_project", "message_occurrences"),
        ("idx_message_occurrences_case", "message_occurrences"),
        ("idx_message_occurrences_ingest_run", "message_occurrences"),
        ("idx_message_occurrences_raw_id", "message_occurrences"),
        ("idx_message_raw_extracted_at", "message_raw"),
        ("idx_message_raw_source_type", "message_raw"),
        ("idx_message_raw_source_hash", "message_raw"),
    ]:
        try:
            op.drop_index(index_name, table_name=table)
        except Exception:
            pass

    for table in [
        "enrichment_artefacts",
        "attachment_raw",
        "message_derived",
        "message_occurrences",
        "message_raw",
    ]:
        if _table_exists(table):
            try:
                op.drop_table(table)
            except Exception:
                pass
