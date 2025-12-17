"""Add stakeholder_roles table for custom role management.

Revision ID: 0002_add_stakeholder_roles
Revises: 0001_vericase_baseline
Create Date: 2024-12-11

This migration creates the stakeholder_roles table which allows users
to define custom party role categories per project/case with display
colors and ordering.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0002_add_stakeholder_roles"
down_revision: str = "0001_vericase_baseline"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

# Default system roles with their colors
DEFAULT_ROLES = [
    {
        "name": "Client",
        "color_bg": "#fef3c7",
        "color_text": "#92400e",
        "display_order": 1,
    },
    {
        "name": "Main Contractor",
        "color_bg": "#dbeafe",
        "color_text": "#1e40af",
        "display_order": 2,
    },
    {
        "name": "Subcontractor",
        "color_bg": "#dcfce7",
        "color_text": "#166534",
        "display_order": 3,
    },
    {
        "name": "Architect",
        "color_bg": "#ffe4e6",
        "color_text": "#be123c",
        "display_order": 4,
    },
    {
        "name": "Structural Engineer",
        "color_bg": "#e0e7ff",
        "color_text": "#3730a3",
        "display_order": 5,
    },
    {
        "name": "M&E Consultant",
        "color_bg": "#f3e8ff",
        "color_text": "#7c3aed",
        "display_order": 6,
    },
    {
        "name": "Quantity Surveyor",
        "color_bg": "#fef9c3",
        "color_text": "#854d0e",
        "display_order": 7,
    },
    {
        "name": "Project Manager",
        "color_bg": "#cffafe",
        "color_text": "#0e7490",
        "display_order": 8,
    },
    {
        "name": "Building Control",
        "color_bg": "#fee2e2",
        "color_text": "#991b1b",
        "display_order": 9,
    },
    {
        "name": "Council / Local Authority",
        "color_bg": "#f5f5f4",
        "color_text": "#44403c",
        "display_order": 10,
    },
    {
        "name": "Legal / Solicitor",
        "color_bg": "#fce7f3",
        "color_text": "#9d174d",
        "display_order": 11,
    },
    {
        "name": "Insurance",
        "color_bg": "#ecfdf5",
        "color_text": "#065f46",
        "display_order": 12,
    },
    {
        "name": "Supplier",
        "color_bg": "#fff7ed",
        "color_text": "#9a3412",
        "display_order": 13,
    },
    {
        "name": "Consultant",
        "color_bg": "#f3e8ff",
        "color_text": "#7c3aed",
        "display_order": 14,
    },
    {
        "name": "Internal",
        "color_bg": "#f1f5f9",
        "color_text": "#475569",
        "display_order": 15,
    },
    {
        "name": "Other",
        "color_bg": "#f3f4f6",
        "color_text": "#374151",
        "display_order": 99,
    },
]


def upgrade() -> None:
    """Create stakeholder_roles table and seed with default system roles."""
    # Create the table
    op.create_table(
        "stakeholder_roles",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
        sa.Column(
            "case_id", UUID(as_uuid=True), sa.ForeignKey("cases.id"), nullable=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("color_bg", sa.String(20), nullable=True, server_default="#f3f4f6"),
        sa.Column("color_text", sa.String(20), nullable=True, server_default="#374151"),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # Create indexes
    op.create_index("idx_stakeholder_role_project", "stakeholder_roles", ["project_id"])
    op.create_index("idx_stakeholder_role_case", "stakeholder_roles", ["case_id"])

    # Insert default system roles (global, no project_id or case_id)
    # These are system-level defaults that apply when no project-specific roles exist
    stakeholder_roles = sa.table(
        "stakeholder_roles",
        sa.column("name", sa.String),
        sa.column("color_bg", sa.String),
        sa.column("color_text", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_system", sa.Boolean),
    )

    op.bulk_insert(
        stakeholder_roles,
        [
            {
                "name": role["name"],
                "color_bg": role["color_bg"],
                "color_text": role["color_text"],
                "display_order": role["display_order"],
                "is_system": True,
            }
            for role in DEFAULT_ROLES
        ],
    )


def downgrade() -> None:
    """Drop stakeholder_roles table."""
    op.drop_index("idx_stakeholder_role_case", table_name="stakeholder_roles")
    op.drop_index("idx_stakeholder_role_project", table_name="stakeholder_roles")
    op.drop_table("stakeholder_roles")
