"""Add workspaces and related tables.

Revision ID: 0012_add_workspaces
Revises: 0011_add_keyword_definition
Create Date: 2025-01-22

This migration creates the workspaces table and related configuration tables,
and adds workspace_id foreign keys to projects and cases tables.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0012_add_workspaces"
down_revision: str = "0011_add_keyword_definition"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


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
    """Create workspaces table and related configuration tables."""

    # Create workspaces table
    if not table_exists("workspaces"):
        op.create_table(
            "workspaces",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("code", sa.String(100), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("contract_type", sa.String(100), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="active"),
            sa.Column(
                "owner_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
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
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_workspaces_code", "workspaces", ["code"], unique=True)
        op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    # Create workspace_keywords table
    if not table_exists("workspace_keywords"):
        op.create_table(
            "workspace_keywords",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "workspace_id",
                UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("keyword_name", sa.String(255), nullable=False),
            sa.Column("definition", sa.Text, nullable=True),
            sa.Column("variations", sa.Text, nullable=True),
            sa.Column("is_regex", sa.Boolean, nullable=False, server_default="false"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_workspace_keywords_workspace_id", "workspace_keywords", ["workspace_id"]
        )

    # Create workspace_team_members table
    if not table_exists("workspace_team_members"):
        op.create_table(
            "workspace_team_members",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "workspace_id",
                UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("role", sa.String(255), nullable=False),
            sa.Column("name", sa.String(512), nullable=False),
            sa.Column("email", sa.String(512), nullable=True),
            sa.Column("organization", sa.String(512), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_workspace_team_members_workspace_id",
            "workspace_team_members",
            ["workspace_id"],
        )

    # Create workspace_key_dates table
    if not table_exists("workspace_key_dates"):
        op.create_table(
            "workspace_key_dates",
            sa.Column(
                "id",
                UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "workspace_id",
                UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("date_type", sa.String(100), nullable=False),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("date_value", sa.DateTime(timezone=True), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_workspace_key_dates_workspace_id",
            "workspace_key_dates",
            ["workspace_id"],
        )

    # Add workspace_id to projects table
    if not column_exists("projects", "workspace_id"):
        op.add_column(
            "projects",
            sa.Column(
                "workspace_id",
                UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id"),
                nullable=True,
            ),
        )
        op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])

    # Add workspace_id to cases table
    if not column_exists("cases", "workspace_id"):
        op.add_column(
            "cases",
            sa.Column(
                "workspace_id",
                UUID(as_uuid=True),
                sa.ForeignKey("workspaces.id"),
                nullable=True,
            ),
        )
        op.create_index("ix_cases_workspace_id", "cases", ["workspace_id"])

    # Migrate existing data: Create a workspace for each existing project
    # This ensures backward compatibility
    if table_exists("projects") and table_exists("workspaces"):
        conn = op.get_bind()
        # Check if there are any projects without workspaces
        result = conn.execute(
            sa.text("SELECT COUNT(*) FROM projects WHERE workspace_id IS NULL")
        )
        count = result.scalar()
        if count > 0:
            # Create workspaces for existing projects
            conn.execute(
                sa.text(
                    """
                    INSERT INTO workspaces (id, name, code, description, contract_type, status, owner_id, created_at, updated_at)
                    SELECT 
                        gen_random_uuid(),
                        project_name,
                        project_code,
                        NULL,
                        contract_type,
                        'active',
                        owner_user_id,
                        created_at,
                        updated_at
                    FROM projects
                    WHERE workspace_id IS NULL
                    RETURNING id, code
                """
                )
            )
            # Link projects to their workspaces
            conn.execute(
                sa.text(
                    """
                    UPDATE projects
                    SET workspace_id = w.id
                    FROM workspaces w
                    WHERE projects.project_code = w.code
                    AND projects.workspace_id IS NULL
                """
                )
            )
            # Link cases to workspaces via their project
            conn.execute(
                sa.text(
                    """
                    UPDATE cases
                    SET workspace_id = p.workspace_id
                    FROM projects p
                    WHERE cases.project_id = p.id
                    AND cases.workspace_id IS NULL
                    AND p.workspace_id IS NOT NULL
                """
                )
            )


def downgrade() -> None:
    """Drop workspace-related tables and columns."""

    # Drop indexes first
    op.drop_index("ix_cases_workspace_id", table_name="cases")
    op.drop_index("ix_projects_workspace_id", table_name="projects")
    op.drop_index(
        "ix_workspace_key_dates_workspace_id",
        table_name="workspace_key_dates",
        if_exists=True,
    )
    op.drop_index(
        "ix_workspace_team_members_workspace_id",
        table_name="workspace_team_members",
        if_exists=True,
    )
    op.drop_index(
        "ix_workspace_keywords_workspace_id",
        table_name="workspace_keywords",
        if_exists=True,
    )
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces", if_exists=True)
    op.drop_index("ix_workspaces_code", table_name="workspaces", if_exists=True)

    # Drop columns
    if column_exists("cases", "workspace_id"):
        op.drop_column("cases", "workspace_id")
    if column_exists("projects", "workspace_id"):
        op.drop_column("projects", "workspace_id")

    # Drop tables
    if table_exists("workspace_key_dates"):
        op.drop_table("workspace_key_dates")
    if table_exists("workspace_team_members"):
        op.drop_table("workspace_team_members")
    if table_exists("workspace_keywords"):
        op.drop_table("workspace_keywords")
    if table_exists("workspaces"):
        op.drop_table("workspaces")
