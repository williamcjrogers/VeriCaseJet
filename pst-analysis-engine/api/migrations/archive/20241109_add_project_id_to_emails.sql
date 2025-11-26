-- Add project_id to email_messages table to support PST files linked to projects safely
DO $$
BEGIN
    -- Add project_id if it doesn't exist
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'project_id') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN project_id UUID REFERENCES projects(id)';
        END IF;
    END IF;
END $$;

-- Make case_id nullable since we can have either case_id OR project_id
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        -- Check if case_id exists first to avoid errors
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'case_id') THEN
             EXECUTE 'ALTER TABLE email_messages ALTER COLUMN case_id DROP NOT NULL';
        END IF;
    END IF;
END $$;

-- Add check constraint to ensure we have either case_id or project_id safely
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        IF NOT EXISTS (SELECT FROM pg_constraint WHERE conname = 'check_case_or_project') THEN
            EXECUTE 'ALTER TABLE email_messages 
            ADD CONSTRAINT check_case_or_project CHECK (
                (case_id IS NOT NULL AND project_id IS NULL) OR 
                (case_id IS NULL AND project_id IS NOT NULL)
            )';
        END IF;
    END IF;
END $$;

-- Add index on project_id for performance safely
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
         EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_project_id ON email_messages(project_id)';
    END IF;
END $$;

-- Update existing emails to link to projects through their PST files
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') AND
       EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'pst_files') THEN
       
       -- Check columns exist
       IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'project_id') AND
          EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 'project_id') THEN
          
            EXECUTE 'UPDATE email_messages em
            SET project_id = pf.project_id
            FROM pst_files pf
            WHERE em.pst_file_id = pf.id
            AND pf.project_id IS NOT NULL
            AND em.project_id IS NULL';
       END IF;
    END IF;
END $$;
