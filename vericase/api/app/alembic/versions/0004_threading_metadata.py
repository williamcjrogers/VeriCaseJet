"""Add email threading metadata columns.

Revision ID: 0004_threading_metadata
Revises: 0003_ocr_corrections
Create Date: 2025-12-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0004_threading_metadata"
down_revision: str = "0003_ocr_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_messages",
        sa.Column("thread_group_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "email_messages",
        sa.Column("thread_path", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "email_messages",
        sa.Column("thread_position", sa.Integer(), nullable=True),
    )
    op.add_column(
        "email_messages",
        sa.Column("parent_message_id", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "email_messages",
        sa.Column(
            "is_inclusive", sa.Boolean(), server_default=sa.sql.expression.true(), nullable=False
        ),
    )

    op.create_index(
        "idx_email_thread_group",
        "email_messages",
        ["thread_group_id"],
    )
    op.create_index(
        "idx_email_thread_path",
        "email_messages",
        ["thread_group_id", "thread_path"],
    )


def downgrade() -> None:
    op.drop_index("idx_email_thread_path", table_name="email_messages")
    op.drop_index("idx_email_thread_group", table_name="email_messages")
    op.drop_column("email_messages", "is_inclusive")
    op.drop_column("email_messages", "parent_message_id")
    op.drop_column("email_messages", "thread_position")
    op.drop_column("email_messages", "thread_path")
    op.drop_column("email_messages", "thread_group_id")
