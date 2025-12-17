"""Baseline Alembic revision for existing VeriCase schema.

This revision is intentionally a no-op. It is meant to be used to:
- mark the current database schema as the starting point for Alembic
- allow future revisions to build on top of the existing production schema

For existing databases, you should typically run:
    alembic stamp 0001_vericase_baseline
to record this version without applying any schema changes.
"""

from __future__ import annotations

from alembic import op  # noqa: F401  (kept for future reference)
import sqlalchemy as sa  # noqa: F401  (kept for future reference)

# revision identifiers, used by Alembic.
revision: str = "0001_vericase_baseline"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    """Baseline revision applies no schema changes."""
    pass


def downgrade() -> None:
    """Baseline revision has no downgrade steps."""
    pass
