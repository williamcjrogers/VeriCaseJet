-- Migration: Add email dedupe columns and decision log table
-- Created: 2025-12-22
-- Description:
--   * Adds canonical_email_id / is_duplicate / dedupe_level to email_messages
--   * Adds email_dedupe_decisions table for deterministic dedupe provenance

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_messages' AND column_name = 'canonical_email_id'
        ) THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN canonical_email_id UUID';
        END IF;

        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_messages' AND column_name = 'is_duplicate'
        ) THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN is_duplicate BOOLEAN DEFAULT FALSE';
        END IF;

        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_messages' AND column_name = 'dedupe_level'
        ) THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN dedupe_level VARCHAR(2)';
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_email_messages_canonical'
        ) THEN
            EXECUTE 'ALTER TABLE email_messages ADD CONSTRAINT fk_email_messages_canonical FOREIGN KEY (canonical_email_id) REFERENCES email_messages(id)';
        END IF;

        IF NOT EXISTS (
            SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_canonical'
        ) THEN
            EXECUTE 'CREATE INDEX idx_email_canonical ON email_messages (canonical_email_id)';
        END IF;

        IF NOT EXISTS (
            SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_is_duplicate'
        ) THEN
            EXECUTE 'CREATE INDEX idx_email_is_duplicate ON email_messages (is_duplicate)';
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_dedupe_decisions'
    ) THEN
        EXECUTE $SQL$
            CREATE TABLE email_dedupe_decisions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                winner_email_id UUID NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
                loser_email_id UUID NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
                level VARCHAR(2) NOT NULL,
                match_type VARCHAR(32),
                strict_hash VARCHAR(128),
                relaxed_hash VARCHAR(128),
                quoted_hash VARCHAR(128),
                evidence JSONB,
                alternatives JSONB,
                run_id VARCHAR(64),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        $SQL$;
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_dedupe_winner'
    ) THEN
        EXECUTE 'CREATE INDEX idx_email_dedupe_winner ON email_dedupe_decisions (winner_email_id)';
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_dedupe_loser'
    ) THEN
        EXECUTE 'CREATE INDEX idx_email_dedupe_loser ON email_dedupe_decisions (loser_email_id)';
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_dedupe_level'
    ) THEN
        EXECUTE 'CREATE INDEX idx_email_dedupe_level ON email_dedupe_decisions (level)';
    END IF;
END
$$;
