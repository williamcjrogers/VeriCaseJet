"""add_custom_deadlines_update_roles

Revision ID: 0019
Revises: 0018
Create Date: 2026-01-13 14:00:00.000000

Updates UserRole enum:
- ADMIN (unchanged)
- EDITOR -> POWER_USER
- VIEWER -> USER
- NEW: MANAGEMENT_USER

Adds custom_deadlines table for Control Centre deadline management.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def enum_value_exists(enum_name: str, value: str) -> bool:
    """Check if an enum value already exists."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = :value
                AND enumtypid = (SELECT oid FROM pg_type WHERE typname = :enum_name)
            )
            """
        ),
        {"value": value, "enum_name": enum_name},
    )
    return bool(result.scalar())


def upgrade():
    # Step 1: Add new enum values to user_role enum (note: underscore, not userrole)
    # We need to commit the current transaction, add enum values, then start new transaction
    # because ALTER TYPE ... ADD VALUE cannot run inside a transaction
    op.execute("COMMIT")

    # Add values to both enum types that exist (user_role and userrole)
    if not enum_value_exists("user_role", "POWER_USER"):
        op.execute("ALTER TYPE user_role ADD VALUE 'POWER_USER'")
    if not enum_value_exists("user_role", "MANAGEMENT_USER"):
        op.execute("ALTER TYPE user_role ADD VALUE 'MANAGEMENT_USER'")
    if not enum_value_exists("user_role", "USER"):
        op.execute("ALTER TYPE user_role ADD VALUE 'USER'")

    # Also add to userrole if it exists (for backwards compatibility)
    if not enum_value_exists("userrole", "POWER_USER"):
        op.execute("ALTER TYPE userrole ADD VALUE 'POWER_USER'")
    if not enum_value_exists("userrole", "MANAGEMENT_USER"):
        op.execute("ALTER TYPE userrole ADD VALUE 'MANAGEMENT_USER'")
    if not enum_value_exists("userrole", "USER"):
        op.execute("ALTER TYPE userrole ADD VALUE 'USER'")

    # Start a new transaction for the rest of the migration
    op.execute("BEGIN")

    # Step 2: Migrate existing users from old roles to new roles
    # EDITOR -> POWER_USER, VIEWER -> USER
    op.execute(
        """
        UPDATE users
        SET role = 'POWER_USER'
        WHERE role = 'EDITOR'
    """
    )
    op.execute(
        """
        UPDATE users
        SET role = 'USER'
        WHERE role = 'VIEWER'
    """
    )

    # Also update user_invitations table
    op.execute(
        """
        UPDATE user_invitations
        SET role = 'POWER_USER'
        WHERE role = 'EDITOR'
    """
    )
    op.execute(
        """
        UPDATE user_invitations
        SET role = 'USER'
        WHERE role = 'VIEWER'
    """
    )

    # Step 3: Create custom_deadlines table
    op.create_table(
        "custom_deadlines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "deadline_type",
            sa.String(length=50),
            nullable=False,
            server_default="task",
        ),
        sa.Column(
            "priority", sa.String(length=20), nullable=False, server_default="medium"
        ),
        # Optional links
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Ownership
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_to_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Status
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for custom_deadlines
    op.create_index(
        "idx_custom_deadline_due_status",
        "custom_deadlines",
        ["due_date", "status"],
    )
    op.create_index(
        "idx_custom_deadline_created_by",
        "custom_deadlines",
        ["created_by_id", "status"],
    )
    op.create_index(
        "ix_custom_deadlines_workspace_id",
        "custom_deadlines",
        ["workspace_id"],
    )
    op.create_index(
        "ix_custom_deadlines_case_id",
        "custom_deadlines",
        ["case_id"],
    )
    op.create_index(
        "ix_custom_deadlines_due_date",
        "custom_deadlines",
        ["due_date"],
    )


def downgrade():
    # Drop custom_deadlines table
    op.drop_index("ix_custom_deadlines_due_date", table_name="custom_deadlines")
    op.drop_index("ix_custom_deadlines_case_id", table_name="custom_deadlines")
    op.drop_index("ix_custom_deadlines_workspace_id", table_name="custom_deadlines")
    op.drop_index("idx_custom_deadline_created_by", table_name="custom_deadlines")
    op.drop_index("idx_custom_deadline_due_status", table_name="custom_deadlines")
    op.drop_table("custom_deadlines")

    # Migrate roles back: POWER_USER -> EDITOR, USER -> VIEWER
    op.execute(
        """
        UPDATE users
        SET role = 'EDITOR'
        WHERE role = 'POWER_USER'
    """
    )
    op.execute(
        """
        UPDATE users
        SET role = 'VIEWER'
        WHERE role = 'USER'
    """
    )
    op.execute(
        """
        UPDATE user_invitations
        SET role = 'EDITOR'
        WHERE role = 'POWER_USER'
    """
    )
    op.execute(
        """
        UPDATE user_invitations
        SET role = 'VIEWER'
        WHERE role = 'USER'
    """
    )

    # Note: PostgreSQL doesn't support removing enum values directly
    # The new enum values (POWER_USER, MANAGEMENT_USER, USER) will remain
    # but won't be used after downgrade
