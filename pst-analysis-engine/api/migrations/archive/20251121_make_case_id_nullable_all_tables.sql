-- Active: 1763739336777@@localhost@55432
-- cspell:ignore schemaname conname
-- Make case_id nullable across all PST-related tables to support project-only workflows
-- This follows the pattern established by email_messages, stakeholders, and keywords

-- 0. Ensure project_id columns exist in all tables
DO $$
BEGIN
    -- programmes table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'programmes' AND column_name = 'project_id') THEN
            ALTER TABLE programmes ADD COLUMN project_id UUID REFERENCES projects(id) ON DELETE SET NULL;
            CREATE INDEX IF NOT EXISTS idx_programmes_project ON programmes(project_id);
        END IF;
    END IF;

    -- delay_events table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'delay_events') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'delay_events' AND column_name = 'project_id') THEN
            ALTER TABLE delay_events ADD COLUMN project_id UUID REFERENCES projects(id) ON DELETE SET NULL;
            CREATE INDEX IF NOT EXISTS idx_delay_events_project ON delay_events(project_id);
        END IF;
    END IF;

    -- delay_events_pst table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'delay_events_pst') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'delay_events_pst' AND column_name = 'project_id') THEN
            ALTER TABLE delay_events_pst ADD COLUMN project_id UUID REFERENCES projects(id) ON DELETE SET NULL;
            CREATE INDEX IF NOT EXISTS idx_delay_events_pst_project ON delay_events_pst(project_id);
        END IF;
    END IF;
END $$;

-- 1. PST FILES table
ALTER TABLE pst_files
    ALTER COLUMN case_id DROP NOT NULL,
    ALTER COLUMN uploaded_by DROP NOT NULL;

-- 2. PROGRAMMES table (construction/project programmes)
ALTER TABLE programmes
    ALTER COLUMN case_id DROP NOT NULL;

-- 3. PROGRAMMES_PST table
ALTER TABLE programmes_pst
    ALTER COLUMN case_id DROP NOT NULL;

-- 4. DELAY_EVENTS table
ALTER TABLE delay_events
    ALTER COLUMN case_id DROP NOT NULL;

-- 5. DELAY_EVENTS_PST table
ALTER TABLE delay_events_pst
    ALTER COLUMN case_id DROP NOT NULL;

-- Add database-level constraints to ensure data integrity
-- We want to ensure that at least one of case_id or project_id is present
DO $$
BEGIN
    -- pst_files constraint
    IF NOT EXISTS (SELECT 1 AS val FROM pg_constraint WHERE conname = 'check_pst_files_parent') THEN
        ALTER TABLE pst_files ADD CONSTRAINT check_pst_files_parent 
            CHECK (case_id IS NOT NULL OR project_id IS NOT NULL);
    END IF;

    -- programmes constraint
    IF NOT EXISTS (SELECT 1 AS val FROM pg_constraint WHERE conname = 'check_programmes_parent') THEN
        ALTER TABLE programmes ADD CONSTRAINT check_programmes_parent 
            CHECK (case_id IS NOT NULL OR project_id IS NOT NULL);
    END IF;

    -- programmes_pst constraint
    IF NOT EXISTS (SELECT 1 AS val FROM pg_constraint WHERE conname = 'check_programmes_pst_parent') THEN
        ALTER TABLE programmes_pst ADD CONSTRAINT check_programmes_pst_parent 
            CHECK (case_id IS NOT NULL OR project_id IS NOT NULL);
    END IF;

    -- delay_events constraint
    IF NOT EXISTS (SELECT 1 AS val FROM pg_constraint WHERE conname = 'check_delay_events_parent') THEN
        ALTER TABLE delay_events ADD CONSTRAINT check_delay_events_parent 
            CHECK (case_id IS NOT NULL OR project_id IS NOT NULL);
    END IF;

    -- delay_events_pst constraint
    IF NOT EXISTS (SELECT 1 AS val FROM pg_constraint WHERE conname = 'check_delay_events_pst_parent') THEN
        ALTER TABLE delay_events_pst ADD CONSTRAINT check_delay_events_pst_parent 
            CHECK (case_id IS NOT NULL OR project_id IS NOT NULL);
    END IF;
END $$;

-- Add informational comments
COMMENT ON COLUMN pst_files.case_id IS 'Case ID (nullable) - constraint enforces case_id OR project_id requirement';
COMMENT ON COLUMN pst_files.project_id IS 'Project ID (nullable) - constraint enforces case_id OR project_id requirement';
