"""Add lane column to item_comments for collaboration lanes.

Revision ID: 0010_add_item_comment_lanes
Revises: 0009_message_raw_derived
Create Date: 2025-12-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0010_add_item_comment_lanes"
down_revision: str = "0009_message_raw_derived"
branch_labels = None
depends_on = None


def column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table
              AND column_name = :column
        )
        """
        ),
        {"table": table, "column": column},
    )
    return bool(result.scalar())


def index_exists(index_name: str) -> bool:
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
    return bool(result.scalar())


def upgrade() -> None:
    if not column_exists("item_comments", "lane"):
        op.add_column(
            "item_comments",
            sa.Column(
                "lane",
                sa.String(length=20),
                nullable=False,
                server_default="core",
            ),
        )

    # Backfill any legacy rows that might be NULL.
    op.execute(sa.text("UPDATE item_comments SET lane = 'core' WHERE lane IS NULL"))

    if not index_exists("idx_item_comments_item_lane_created"):
        op.create_index(
            "idx_item_comments_item_lane_created",
            "item_comments",
            ["item_type", "item_id", "lane", "created_at"],
        )
    if not index_exists("idx_item_comments_link_lane_created"):
        op.create_index(
            "idx_item_comments_link_lane_created",
            "item_comments",
            ["item_claim_link_id", "lane", "created_at"],
        )


def downgrade() -> None:
    if index_exists("idx_item_comments_link_lane_created"):
        op.drop_index(
            "idx_item_comments_link_lane_created",
            table_name="item_comments",
        )
    if index_exists("idx_item_comments_item_lane_created"):
        op.drop_index(
            "idx_item_comments_item_lane_created",
            table_name="item_comments",
        )
    if column_exists("item_comments", "lane"):
        op.drop_column("item_comments", "lane")
