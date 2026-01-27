"""Allow project-scoped chronology items.

Revision ID: 0023
Revises: 0022
Create Date: 2026-01-26
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str = "0022"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'chronology_items') THEN
                EXECUTE 'ALTER TABLE chronology_items ADD COLUMN IF NOT EXISTS project_id UUID NULL';
                EXECUTE 'ALTER TABLE chronology_items ALTER COLUMN case_id DROP NOT NULL';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'chronology_items')
               AND EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
                EXECUTE 'ALTER TABLE chronology_items
                         ADD CONSTRAINT chronology_items_project_id_fkey
                         FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL';
            END IF;
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'chronology_items') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_chronology_items_project_id ON chronology_items(project_id)';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'chronology_items') THEN
                EXECUTE 'ALTER TABLE chronology_items DROP COLUMN IF EXISTS project_id';
                EXECUTE 'ALTER TABLE chronology_items ALTER COLUMN case_id SET NOT NULL';
            END IF;
        END $$;
        """
    )
