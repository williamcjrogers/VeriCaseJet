-- Migration: Add canonical body and hash fields for email messages and attachments
-- Created: 2025-11-24
-- Description:
--   * Adds body_text_clean and content_hash to email_messages
--   * Adds attachment_hash, is_inline, content_id, is_duplicate to email_attachments
--   * Adds supporting indexes for fast lookup and deduplication

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    -- EmailMessage: canonical body and content hash
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_messages' AND column_name = 'body_text_clean'
        ) THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN body_text_clean TEXT';
        END IF;

        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_messages' AND column_name = 'content_hash'
        ) THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN content_hash VARCHAR(128)';
        END IF;

        -- Indexes for deduplication and fast querying
        IF NOT EXISTS (
            SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_case_content_hash'
        ) THEN
            EXECUTE 'CREATE INDEX idx_email_case_content_hash ON email_messages (case_id, content_hash)';
        END IF;

        IF NOT EXISTS (
            SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_project_content_hash'
        ) THEN
            EXECUTE 'CREATE INDEX idx_email_project_content_hash ON email_messages (project_id, content_hash)';
        END IF;
    END IF;

    -- EmailAttachment: attachment hash and inline flags
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_attachments') THEN
        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_attachments' AND column_name = 'attachment_hash'
        ) THEN
            EXECUTE 'ALTER TABLE email_attachments ADD COLUMN attachment_hash VARCHAR(128)';
        END IF;

        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_attachments' AND column_name = 'is_inline'
        ) THEN
            EXECUTE 'ALTER TABLE email_attachments ADD COLUMN is_inline BOOLEAN DEFAULT FALSE';
        END IF;

        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_attachments' AND column_name = 'content_id'
        ) THEN
            EXECUTE 'ALTER TABLE email_attachments ADD COLUMN content_id VARCHAR(512)';
        END IF;

        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = 'email_attachments' AND column_name = 'is_duplicate'
        ) THEN
            EXECUTE 'ALTER TABLE email_attachments ADD COLUMN is_duplicate BOOLEAN DEFAULT FALSE';
        END IF;

        -- Index for attachment-level deduplication
        IF NOT EXISTS (
            SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_email_attachment_hash'
        ) THEN
            EXECUTE 'CREATE INDEX idx_email_attachment_hash ON email_attachments (attachment_hash)';
        END IF;
    END IF;
END
$$;

