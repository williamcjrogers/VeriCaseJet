"""Add cases.case_id_custom column (for workspace/case features).

Revision ID: 0015_add_case_id_custom
Revises: 0014_expand_thread_path
Create Date: 2026-01-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0015_add_case_id_custom"
down_revision: str = "0014_expand_thread_path"
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
    if not column_exists("cases", "case_id_custom"):
        op.add_column(
            "cases", sa.Column("case_id_custom", sa.String(100), nullable=True)
        )

    # Best-effort index (idempotent-ish)
    try:
        op.create_index(
            "idx_cases_case_id_custom", "cases", ["case_id_custom"], unique=False
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("idx_cases_case_id_custom", table_name="cases")
    except Exception:
        pass

    if column_exists("cases", "case_id_custom"):
        try:
            op.drop_column("cases", "case_id_custom")
        except Exception:
            pass
