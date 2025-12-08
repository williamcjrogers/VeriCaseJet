-- Active: 1763739336777@@localhost@55432
-- Add storage optimization columns and indexes to email_messages table
-- Migration: 20251109_add_storage_optimizations.sql

DO $$
BEGIN
    -- Ensure email_messages table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        
        -- Add columns for optimized storage
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'body_preview') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN body_preview TEXT';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'body_full_s3_key') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN body_full_s3_key VARCHAR(512)';
        END IF;

        -- Add indexes for performance
        -- Check columns for indexes before creating them
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'case_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'date_sent') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_case_date ON email_messages (case_id, date_sent)';
        END IF;

        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'matched_stakeholders') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_stakeholders ON email_messages USING gin (matched_stakeholders)';
        END IF;

        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'matched_keywords') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_keywords ON email_messages USING gin (matched_keywords)';
        END IF;

        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'case_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'has_attachments') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_has_attachments ON email_messages (case_id, has_attachments)';
        END IF;

        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'case_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'conversation_index') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_conversation ON email_messages (case_id, conversation_index)';
        END IF;

        -- Add comments
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'body_preview') THEN
            EXECUTE 'COMMENT ON COLUMN email_messages.body_preview IS ''First 10KB of email body for quick display''';
        END IF;
        
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'body_full_s3_key') THEN
            EXECUTE 'COMMENT ON COLUMN email_messages.body_full_s3_key IS ''S3 key for full email body if larger than 10KB''';
        END IF;

    END IF;
END $$;
