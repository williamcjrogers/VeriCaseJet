"""Link cases to projects via cases.project_id.

Revision ID: 0008_case_project_link
Revises: 0007_email_nulls_cleanup
Create Date: 2025-12-22

Adds an optional `project_id` foreign key on `cases` so a legal Case can be
associated with its underlying evidence Project (emails/evidence/PSTs).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0008_case_project_link"
down_revision: str = "0007_email_nulls_cleanup"
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
    conn = op.get_bind()
    dialect = getattr(conn.dialect, "name", "")

    if not column_exists("cases", "project_id"):
        if dialect == "postgresql":
            from sqlalchemy.dialects import postgresql

            col_type = postgresql.UUID(as_uuid=True)
        else:
            # Fallback for non-Postgres dev DBs.
            col_type = sa.String(length=36)

        op.add_column("cases", sa.Column("project_id", col_type, nullable=True))

    # Best-effort index + FK (idempotent-ish)
    try:
        op.create_index("ix_cases_project_id", "cases", ["project_id"], unique=False)
    except Exception:
        pass

    if dialect == "postgresql":
        try:
            op.create_foreign_key(
                "fk_cases_project_id_projects",
                "cases",
                "projects",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )
        except Exception:
            pass


def downgrade() -> None:
    conn = op.get_bind()
    dialect = getattr(conn.dialect, "name", "")

    # Drop FK first
    if dialect == "postgresql":
        try:
            op.drop_constraint(
                "fk_cases_project_id_projects", "cases", type_="foreignkey"
            )
        except Exception:
            pass

    try:
        op.drop_index("ix_cases_project_id", table_name="cases")
    except Exception:
        pass

    if column_exists("cases", "project_id"):
        try:
            op.drop_column("cases", "project_id")
        except Exception:
            pass
