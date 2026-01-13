"""Add corpus_learning_results table for caching learned corpus profiles.

Revision ID: 0016_add_corpus_learning_results
Revises: 0015_add_case_id_custom
Create Date: 2026-01-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "0016_add_corpus_learning_results"
down_revision: str = "0015_add_case_id_custom"
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
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
        {"table": table_name},
    )
    return bool(result.scalar())


def upgrade() -> None:
    if table_exists("corpus_learning_results"):
        return

    op.create_table(
        "corpus_learning_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("cases.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        # Corpus statistics
        sa.Column("email_count", sa.Integer, nullable=False, default=0),
        sa.Column(
            "learned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Learned data (JSONB for flexibility)
        sa.Column("entity_distributions", JSONB, nullable=True),
        sa.Column("cluster_data", JSONB, nullable=True),
        sa.Column("corpus_centroid", JSONB, nullable=True),
        sa.Column("communication_graph", JSONB, nullable=True),
        sa.Column("domain_distribution", JSONB, nullable=True),
        sa.Column("core_domains", JSONB, nullable=True),
        sa.Column("sentiment_baseline", JSONB, nullable=True),
        # Statistics for outlier detection
        sa.Column("avg_emails_per_sender", sa.Float, nullable=True),
        sa.Column("std_emails_per_sender", sa.Float, nullable=True),
        # Content hash for cache invalidation
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Create indexes
    op.create_index(
        "idx_corpus_learning_project",
        "corpus_learning_results",
        ["project_id"],
    )
    op.create_index(
        "idx_corpus_learning_case",
        "corpus_learning_results",
        ["case_id"],
    )
    op.create_index(
        "idx_corpus_learning_hash",
        "corpus_learning_results",
        ["content_hash"],
    )


def downgrade() -> None:
    if not table_exists("corpus_learning_results"):
        return

    # Drop indexes first
    try:
        op.drop_index("idx_corpus_learning_hash", table_name="corpus_learning_results")
    except Exception:
        pass
    try:
        op.drop_index("idx_corpus_learning_case", table_name="corpus_learning_results")
    except Exception:
        pass
    try:
        op.drop_index(
            "idx_corpus_learning_project", table_name="corpus_learning_results"
        )
    except Exception:
        pass

    # Drop table
    op.drop_table("corpus_learning_results")
