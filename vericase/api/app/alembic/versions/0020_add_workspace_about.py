"""Add workspace_about cache table.

Revision ID: 0020
Revises: 0019
Create Date: 2026-01-20

This migration creates a workspace_about table used to cache AI-generated
workspace context ("About" tab) including summary + structured insights,
and user-provided authoritative notes.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str = "0019"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


def upgrade() -> None:
    if table_exists("workspace_about"):
        return

    op.create_table(
        "workspace_about",
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
        sa.Column("status", sa.String(32), nullable=False, server_default="empty"),
        sa.Column("summary_md", sa.Text, nullable=True),
        sa.Column("data", JSONB, nullable=True),
        sa.Column("user_notes", sa.Text, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
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
    op.create_index(
        "ix_workspace_about_workspace_id", "workspace_about", ["workspace_id"], unique=True
    )


def downgrade() -> None:
    # Best-effort: only drop if it exists
    if table_exists("workspace_about"):
        op.drop_index("ix_workspace_about_workspace_id", table_name="workspace_about")
        op.drop_table("workspace_about")

