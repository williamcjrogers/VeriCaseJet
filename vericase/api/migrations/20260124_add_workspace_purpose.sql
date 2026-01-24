-- Migration: Workspace Purpose baseline
-- Date: 2026-01-24
-- Description: Adds workspace_purpose table for baseline instructions and tracking
-- SQL Dialect: PostgreSQL

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'workspace_purpose'
    ) THEN
        EXECUTE 'CREATE TABLE workspace_purpose (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL UNIQUE,
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

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'workspace_purpose')
       AND EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'workspaces') THEN
        EXECUTE 'ALTER TABLE workspace_purpose
                 ADD CONSTRAINT workspace_purpose_workspace_id_fkey
                 FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE';
    END IF;
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'workspace_purpose')
       AND EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evidence_items') THEN
        EXECUTE 'ALTER TABLE workspace_purpose
                 ADD CONSTRAINT workspace_purpose_instructions_evidence_id_fkey
                 FOREIGN KEY (instructions_evidence_id) REFERENCES evidence_items(id) ON DELETE SET NULL';
    END IF;
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'workspace_purpose') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_workspace_purpose_workspace_id ON workspace_purpose(workspace_id)';
    END IF;
END $$;
