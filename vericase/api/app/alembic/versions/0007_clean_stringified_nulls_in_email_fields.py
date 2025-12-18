"""Clean legacy stringified nulls in email_messages fields.

Revision ID: 0007_clean_stringified_nulls_in_email_fields
Revises: 0006_add_email_finish_dates
Create Date: 2025-12-18

This is a data backfill / hygiene migration.

Historically some rows ended up with literal strings like "None"/"null" in
email sender/recipient fields. The API layer is defensive, but we also want the
data at rest to be clean so downstream consumers (and future code paths) don't
re-surface the artifacts.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0007_clean_stringified_nulls_in_email_fields"
down_revision: str = "0006_add_email_finish_dates"
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
    conn = op.get_bind()
    dialect = getattr(conn.dialect, "name", "")

    # Sender fields: set sentinel strings to SQL NULL.
    if column_exists("email_messages", "sender_email"):
        op.execute(
            sa.text(
                """
                UPDATE email_messages
                SET sender_email = NULL
                WHERE sender_email IS NOT NULL
                  AND btrim(lower(sender_email)) IN ('', 'none', 'null')
                """
            )
        )

    if column_exists("email_messages", "sender_name"):
        op.execute(
            sa.text(
                """
                UPDATE email_messages
                SET sender_name = NULL
                WHERE sender_name IS NOT NULL
                  AND btrim(lower(sender_name)) IN ('', 'none', 'null')
                """
            )
        )

    # Recipient arrays: remove sentinel values (postgres-only).
    if dialect != "postgresql":
        return

    def clean_recipient_array(column: str) -> None:
        if not column_exists("email_messages", column):
            return

        # Remove sentinel values (and blanks) from the array; if empty -> NULL.
        op.execute(
            sa.text(
                f"""
                UPDATE email_messages
                SET {column} = (
                    SELECT
                        CASE WHEN COUNT(*) = 0 THEN NULL
                             ELSE ARRAY_AGG(v ORDER BY ord)
                        END
                    FROM (
                        SELECT v, ord
                        FROM unnest({column}) WITH ORDINALITY AS t(v, ord)
                        WHERE btrim(lower(v)) NOT IN ('', 'none', 'null')
                    ) filtered
                )
                WHERE {column} IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM unnest({column}) AS u(v)
                      WHERE btrim(lower(v)) IN ('', 'none', 'null')
                  )
                """
            )
        )

    clean_recipient_array("recipients_to")
    clean_recipient_array("recipients_cc")
    clean_recipient_array("recipients_bcc")


def downgrade() -> None:
    # Data hygiene migration is intentionally not reversible.
    pass
