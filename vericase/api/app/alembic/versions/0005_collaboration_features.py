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


def upgrade() -> None:
    # ==========================================================================
    # Add pinning columns to item_comments
    # ==========================================================================
    op.add_column(
        "item_comments",
        sa.Column(
            "is_pinned",
            sa.Boolean(),
            server_default=sa.sql.expression.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "item_comments",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "item_comments",
        sa.Column("pinned_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_item_comments_pinned_by",
        "item_comments",
        "users",
        ["pinned_by"],
        ["id"],
    )
    op.create_index(
        "idx_item_comments_pinned",
        "item_comments",
        ["is_pinned"],
    )

    # ==========================================================================
    # Create comment_reactions table
    # ==========================================================================
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
        sa.UniqueConstraint("comment_id", "user_id", "emoji", name="uq_comment_reaction"),
    )
    op.create_index(
        "idx_comment_reactions_comment",
        "comment_reactions",
        ["comment_id"],
    )
    op.create_index(
        "idx_comment_reactions_user",
        "comment_reactions",
        ["user_id"],
    )

    # ==========================================================================
    # Create comment_read_status table
    # ==========================================================================
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
    op.create_index(
        "idx_comment_read_user",
        "comment_read_status",
        ["user_id"],
    )
    op.create_index(
        "idx_comment_read_claim",
        "comment_read_status",
        ["claim_id"],
    )

    # ==========================================================================
    # Create user_notification_preferences table
    # ==========================================================================
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
    op.create_index(
        "idx_notification_prefs_user",
        "user_notification_preferences",
        ["user_id"],
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index("idx_notification_prefs_user", table_name="user_notification_preferences")
    op.drop_table("user_notification_preferences")

    op.drop_index("idx_comment_read_claim", table_name="comment_read_status")
    op.drop_index("idx_comment_read_user", table_name="comment_read_status")
    op.drop_table("comment_read_status")

    op.drop_index("idx_comment_reactions_user", table_name="comment_reactions")
    op.drop_index("idx_comment_reactions_comment", table_name="comment_reactions")
    op.drop_table("comment_reactions")

    # Drop pinning columns from item_comments
    op.drop_index("idx_item_comments_pinned", table_name="item_comments")
    op.drop_constraint("fk_item_comments_pinned_by", "item_comments", type_="foreignkey")
    op.drop_column("item_comments", "pinned_by")
    op.drop_column("item_comments", "pinned_at")
    op.drop_column("item_comments", "is_pinned")
