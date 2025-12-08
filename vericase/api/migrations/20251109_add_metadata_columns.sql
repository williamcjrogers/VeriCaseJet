-- Active: 1763739336777@@localhost@55432
-- Add metadata JSON columns for storing refinement and other flexible data
-- Refactored for safety and idempotency

DO $$
BEGIN
    -- Add metadata to projects table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'metadata') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN metadata JSONB DEFAULT ''{}''';
        END IF;
        
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_metadata ON projects USING gin (metadata)';
        EXECUTE 'COMMENT ON COLUMN projects.metadata IS ''JSON storage for flexible project data including refinement filters''';
    END IF;

    -- Add metadata to email_messages table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'metadata') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN metadata JSONB DEFAULT ''{}''';
        END IF;
        
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_metadata ON email_messages USING gin (metadata)';
        EXECUTE 'COMMENT ON COLUMN email_messages.metadata IS ''JSON storage for flexible email data including refinement exclusions''';
    END IF;
END $$;
