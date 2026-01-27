"""Add project_intel_packs table for project intel snapshots.

Revision ID: 0022
Revises: 0021
Create Date: 2026-01-26
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str = "0021"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'project_intel_packs'
            ) THEN
                EXECUTE 'CREATE TABLE project_intel_packs (
                    id UUID PRIMARY KEY,
                    project_id UUID NOT NULL UNIQUE,
                    status VARCHAR(32) NOT NULL DEFAULT ''empty'',
                    purpose_text TEXT,
                    instructions_evidence_id UUID NULL,
                    summary_md TEXT,
                    data JSONB,
                    last_error TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'project_intel_packs')
               AND EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
                EXECUTE 'ALTER TABLE project_intel_packs
                         ADD CONSTRAINT project_intel_packs_project_id_fkey
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
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'project_intel_packs')
               AND EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evidence_items') THEN
                EXECUTE 'ALTER TABLE project_intel_packs
                         ADD CONSTRAINT project_intel_packs_instructions_evidence_id_fkey
                         FOREIGN KEY (instructions_evidence_id) REFERENCES evidence_items(id) ON DELETE SET NULL';
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
            IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'project_intel_packs') THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_intel_packs_project_id ON project_intel_packs(project_id)';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_intel_packs CASCADE;")
