"""Add collaboration features: reactions, read tracking, pins, notification prefs.

Revision ID: 0005_collaboration_features
Revises: 0004_threading_metadata
Create Date: 2025-12-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0005_collaboration_features"
down_revision: str = "0004_threading_metadata"
branch_labels = None
depends_on = None


def column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = :table AND column_name = :column
        )
    """
        ),
        {"table": table, "column": column},
    )
    return result.scalar()


def index_exists(index_name: str) -> bool:
    """Check if an index exists."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
        SELECT EXISTS (
            SELECT 1 FROM pg_indexes WHERE indexname = :index_name
        )
    """
        ),
        {"index_name": index_name},
    )
    return result.scalar()


def constraint_exists(constraint_name: str) -> bool:
    """Check if a constraint exists."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.table_constraints 
            WHERE constraint_name = :constraint_name
        )
    """
        ),
        {"constraint_name": constraint_name},
    )
    return result.scalar()


def table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_name = :table_name
        )
    """
        ),
        {"table_name": table_name},
    )
    return result.scalar()


def upgrade() -> None:
    # ==========================================================================
    # Add pinning columns to item_comments (idempotent)
    # ==========================================================================
    if not column_exists("item_comments", "is_pinned"):
        op.add_column(
            "item_comments",
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                server_default=sa.sql.expression.false(),
                nullable=False,
            ),
        )
    if not column_exists("item_comments", "pinned_at"):
        op.add_column(
            "item_comments",
            sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not column_exists("item_comments", "pinned_by"):
        op.add_column(
            "item_comments",
            sa.Column("pinned_by", UUID(as_uuid=True), nullable=True),
        )
    if not constraint_exists("fk_item_comments_pinned_by"):
        op.create_foreign_key(
            "fk_item_comments_pinned_by",
            "item_comments",
            "users",
            ["pinned_by"],
            ["id"],
        )
    if not index_exists("idx_item_comments_pinned"):
        op.create_index(
            "idx_item_comments_pinned",
            "item_comments",
            ["is_pinned"],
        )

    # ==========================================================================
    # Create comment_reactions table (idempotent)
    # ==========================================================================
    if not table_exists("comment_reactions"):
        op.create_table(
            "comment_reactions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "comment_id",
                UUID(as_uuid=True),
                sa.ForeignKey("item_comments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("emoji", sa.String(10), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "comment_id", "user_id", "emoji", name="uq_comment_reaction"
            ),
        )
    if not index_exists("idx_comment_reactions_comment"):
        op.create_index(
            "idx_comment_reactions_comment",
            "comment_reactions",
            ["comment_id"],
        )
    if not index_exists("idx_comment_reactions_user"):
        op.create_index(
            "idx_comment_reactions_user",
            "comment_reactions",
            ["user_id"],
        )

    # ==========================================================================
    # Create comment_read_status table (idempotent)
    # ==========================================================================
    if not table_exists("comment_read_status"):
        op.create_table(
            "comment_read_status",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "claim_id",
                UUID(as_uuid=True),
                sa.ForeignKey("heads_of_claim.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "last_read_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("user_id", "claim_id", name="uq_comment_read_status"),
        )
    if not index_exists("idx_comment_read_user"):
        op.create_index(
            "idx_comment_read_user",
            "comment_read_status",
            ["user_id"],
        )
    if not index_exists("idx_comment_read_claim"):
        op.create_index(
            "idx_comment_read_claim",
            "comment_read_status",
            ["claim_id"],
        )

    # ==========================================================================
    # Create user_notification_preferences table (idempotent)
    # ==========================================================================
    if not table_exists("user_notification_preferences"):
        op.create_table(
            "user_notification_preferences",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column(
                "email_mentions",
                sa.Boolean(),
                server_default=sa.sql.expression.true(),
                nullable=False,
            ),
            sa.Column(
                "email_replies",
                sa.Boolean(),
                server_default=sa.sql.expression.true(),
                nullable=False,
            ),
            sa.Column(
                "email_claim_updates",
                sa.Boolean(),
                server_default=sa.sql.expression.true(),
                nullable=False,
            ),
            sa.Column(
                "email_daily_digest",
                sa.Boolean(),
                server_default=sa.sql.expression.false(),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                onupdate=sa.func.now(),
            ),
        )
    if not index_exists("idx_notification_prefs_user"):
        op.create_index(
            "idx_notification_prefs_user",
            "user_notification_preferences",
            ["user_id"],
        )


def downgrade() -> None:
    # Drop tables in reverse order (idempotent)
    if index_exists("idx_notification_prefs_user"):
        op.drop_index(
            "idx_notification_prefs_user", table_name="user_notification_preferences"
        )
    if table_exists("user_notification_preferences"):
        op.drop_table("user_notification_preferences")

    if index_exists("idx_comment_read_claim"):
        op.drop_index("idx_comment_read_claim", table_name="comment_read_status")
    if index_exists("idx_comment_read_user"):
        op.drop_index("idx_comment_read_user", table_name="comment_read_status")
    if table_exists("comment_read_status"):
        op.drop_table("comment_read_status")

    if index_exists("idx_comment_reactions_user"):
        op.drop_index("idx_comment_reactions_user", table_name="comment_reactions")
    if index_exists("idx_comment_reactions_comment"):
        op.drop_index("idx_comment_reactions_comment", table_name="comment_reactions")
    if table_exists("comment_reactions"):
        op.drop_table("comment_reactions")

    # Drop pinning columns from item_comments (idempotent)
    if index_exists("idx_item_comments_pinned"):
        op.drop_index("idx_item_comments_pinned", table_name="item_comments")
    if constraint_exists("fk_item_comments_pinned_by"):
        op.drop_constraint(
            "fk_item_comments_pinned_by", "item_comments", type_="foreignkey"
        )
    if column_exists("item_comments", "pinned_by"):
        op.drop_column("item_comments", "pinned_by")
    if column_exists("item_comments", "pinned_at"):
        op.drop_column("item_comments", "pinned_at")
    if column_exists("item_comments", "is_pinned"):
        op.drop_column("item_comments", "is_pinned")
