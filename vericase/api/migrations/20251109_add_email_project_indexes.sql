-- Active: 1763739336777@@localhost@55432
-- Additional performance indexes for email_messages table with project support
-- Created: 2025-11-09
-- Description: Adds optimized indexes for project-based queries on email_messages

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        -- Add composite indexes for project-based queries (matching case-based indexes)
        -- Check for columns before indexing
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='project_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='date_sent') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_project_date ON email_messages(project_id, date_sent)';
        END IF;

        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='project_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='has_attachments') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_project_has_attachments ON email_messages(project_id, has_attachments)';
        END IF;

        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='project_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='conversation_index') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_project_conversation ON email_messages(project_id, conversation_index)';
        END IF;

        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='project_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='sender_email') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_project_sender ON email_messages(project_id, sender_email)';
        END IF;

        -- Ensure basic project index exists
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='project_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_project_id ON email_messages(project_id)';
        END IF;
    END IF;
END $$;

-- Analyze table to update query planner statistics
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='email_messages') THEN ANALYZE email_messages; END IF; END $$;
