"""Add as-planned/as-built finish dates to email_messages.

Revision ID: 0006_add_email_finish_dates
Revises: 0005_collaboration_features
Create Date: 2025-12-18

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0006_add_email_finish_dates"
down_revision: str = "0005_collaboration_features"
branch_labels = None
depends_on = None


def column_exists(table: str, column: str) -> bool:
    """Check if a column exists in a table."""
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
    # Add finish date columns (idempotent)
    if not column_exists("email_messages", "as_planned_finish_date"):
        op.add_column(
            "email_messages",
            sa.Column(
                "as_planned_finish_date", sa.DateTime(timezone=True), nullable=True
            ),
        )

    if not column_exists("email_messages", "as_built_finish_date"):
        op.add_column(
            "email_messages",
            sa.Column(
                "as_built_finish_date", sa.DateTime(timezone=True), nullable=True
            ),
        )


def downgrade() -> None:
    # Best-effort downgrade (not idempotent by design)
    with op.batch_alter_table("email_messages") as batch_op:
        try:
            batch_op.drop_column("as_built_finish_date")
        except Exception:
            pass
        try:
            batch_op.drop_column("as_planned_finish_date")
        except Exception:
            pass
