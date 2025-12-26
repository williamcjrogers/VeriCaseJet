-- Migration: Add email_thread_links table for deterministic threading evidence
-- Created: 2025-12-21
-- Description:
--   * Stores parent-child links with evidence vectors for email threading

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_thread_links'
    ) THEN
        EXECUTE $SQL$
            CREATE TABLE email_thread_links (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                child_email_id UUID NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
                parent_email_id UUID REFERENCES email_messages(id) ON DELETE SET NULL,
                methods JSONB,
                evidence JSONB,
                alternatives JSONB,
                confidence DOUBLE PRECISION,
                run_id VARCHAR(64),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        $SQL$;
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_thread_links_child'
    ) THEN
        EXECUTE 'CREATE INDEX idx_email_thread_links_child ON email_thread_links (child_email_id)';
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_thread_links_parent'
    ) THEN
        EXECUTE 'CREATE INDEX idx_email_thread_links_parent ON email_thread_links (parent_email_id)';
    END IF;
END
$$;
