"""Add definition column to keywords.

Revision ID: 0011_add_keyword_definition
Revises: 0010_add_item_comment_lanes
Create Date: 2025-12-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0011_add_keyword_definition"
down_revision: str = "0010_add_item_comment_lanes"
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


def upgrade() -> None:
    if not column_exists("keywords", "definition"):
        op.add_column("keywords", sa.Column("definition", sa.Text(), nullable=True))


def downgrade() -> None:
    if column_exists("keywords", "definition"):
        op.drop_column("keywords", "definition")
