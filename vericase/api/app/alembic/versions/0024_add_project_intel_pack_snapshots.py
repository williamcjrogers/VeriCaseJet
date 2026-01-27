"""Add project_intel_pack_snapshots table.

Revision ID: 0024
Revises: 0023
Create Date: 2026-01-26
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str = "0023"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'project_intel_pack_snapshots'
            ) THEN
                EXECUTE 'CREATE TABLE project_intel_pack_snapshots (
                    id UUID PRIMARY KEY,
                    project_id UUID NOT NULL,
                    run_id UUID NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT ''ready'',
                    summary_md TEXT,
                    data JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'project_intel_pack_snapshots')
               AND EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
                EXECUTE 'ALTER TABLE project_intel_pack_snapshots
                         ADD CONSTRAINT project_intel_pack_snapshots_project_id_fkey
                         FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE';
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
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'project_intel_pack_snapshots') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_intel_pack_snapshots_project_id ON project_intel_pack_snapshots(project_id)';
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_intel_pack_snapshots_run_id ON project_intel_pack_snapshots(run_id)';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_intel_pack_snapshots CASCADE;")
