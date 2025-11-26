-- Active: 1763739336777@@localhost@55432
-- Add thread_id field to email_messages table for email threading (USP feature)
-- Migration: 20251114_add_thread_id_to_email_messages.sql
-- Date: 2025-11-14

DO $$
BEGIN
    -- Ensure email_messages table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        
        -- 1. Add thread_id column if it doesn't exist
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'thread_id') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN thread_id VARCHAR(100)';
        END IF;

        -- 2. Create index for thread_id
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_thread_id ON email_messages(thread_id) WHERE thread_id IS NOT NULL';

        -- 3. Create composite index for case + thread (if case_id exists)
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'case_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_case_thread ON email_messages(case_id, thread_id) WHERE case_id IS NOT NULL AND thread_id IS NOT NULL';
        END IF;

        -- 4. Create composite index for project + thread (if project_id exists)
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'project_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_project_thread ON email_messages(project_id, thread_id) WHERE project_id IS NOT NULL AND thread_id IS NOT NULL';
        END IF;

        -- 5. Add comment
        EXECUTE 'COMMENT ON COLUMN email_messages.thread_id IS ''Computed thread ID for grouping related emails using Message-ID, In-Reply-To, References, and Conversation-Index''';
        
    END IF;
END $$;
