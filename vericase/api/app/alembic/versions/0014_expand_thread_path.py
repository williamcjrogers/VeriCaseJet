"""Expand email thread_path column to avoid truncation.

Revision ID: 0014_expand_thread_path
Revises: 0013_project_case_config
Create Date: 2026-01-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0014_expand_thread_path"
down_revision: str = "0013_project_case_config"
branch_labels = None
depends_on = None


def _thread_path_varchar_length() -> int | None:
    """Return current VARCHAR length for email_messages.thread_path, else None."""
    conn = op.get_bind()
    row = (
        conn.execute(
            sa.text(
                """
            SELECT data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = 'email_messages'
              AND column_name = 'thread_path'
            """
            )
        )
        .mappings()
        .first()
    )
    if not row:
        return None
    data_type = (row.get("data_type") or "").lower()
    if data_type not in ("character varying", "varchar"):
        return None
    length = row.get("character_maximum_length")
    try:
        return int(length) if length is not None else None
    except (TypeError, ValueError):
        return None


def upgrade() -> None:
    target_len = 2048
    existing_len = _thread_path_varchar_length()
    if existing_len is None:
        return
    if existing_len >= target_len:
        return

    op.alter_column(
        "email_messages",
        "thread_path",
        existing_type=sa.String(length=existing_len),
        type_=sa.String(length=target_len),
        existing_nullable=True,
    )


def downgrade() -> None:
    # NOTE: Downgrade truncates values. This is acceptable for a downgrade path,
    # but production should not downgrade without understanding the data loss.
    conn = op.get_bind()
    row = (
        conn.execute(
            sa.text(
                """
            SELECT data_type, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = 'email_messages'
              AND column_name = 'thread_path'
            """
            )
        )
        .mappings()
        .first()
    )
    if not row:
        return

    data_type = (row.get("data_type") or "").lower()
    length = row.get("character_maximum_length")
    try:
        current_len = int(length) if length is not None else None
    except (TypeError, ValueError):
        current_len = None

    if data_type in ("character varying", "varchar") and current_len == 64:
        return

    op.execute(
        sa.text(
            "ALTER TABLE email_messages "
            "ALTER COLUMN thread_path TYPE VARCHAR(64) "
            "USING LEFT(COALESCE(thread_path, ''), 64)"
        )
    )
