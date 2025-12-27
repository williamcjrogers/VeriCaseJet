"""Add project and case configuration fields.

Revision ID: 0013_add_project_case_config_fields
Revises: 0012_add_workspaces
Create Date: 2025-12-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0013_add_project_case_config_fields"
down_revision: str = "0012_add_workspaces"
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
    # Project contract configuration fields
    if not column_exists("projects", "contract_family"):
        op.add_column(
            "projects", sa.Column("contract_family", sa.String(100), nullable=True)
        )

    if not column_exists("projects", "contract_form"):
        op.add_column(
            "projects", sa.Column("contract_form", sa.String(255), nullable=True)
        )

    if not column_exists("projects", "contract_form_custom"):
        op.add_column(
            "projects", sa.Column("contract_form_custom", sa.String(255), nullable=True)
        )

    # Case position field (Upstream/Downstream)
    if not column_exists("cases", "position"):
        op.add_column("cases", sa.Column("position", sa.String(50), nullable=True))


def downgrade() -> None:
    if column_exists("projects", "contract_family"):
        op.drop_column("projects", "contract_family")

    if column_exists("projects", "contract_form"):
        op.drop_column("projects", "contract_form")

    if column_exists("projects", "contract_form_custom"):
        op.drop_column("projects", "contract_form_custom")

    if column_exists("cases", "position"):
        op.drop_column("cases", "position")
