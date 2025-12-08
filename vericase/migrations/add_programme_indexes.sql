-- Active: 1763739336777@@localhost@55432
-- cspell:ignore indexdef
-- Migration: Add indexes to programmes table for performance optimization
-- Date: 2024-11-09
-- Description: Adds indexes on case_id and project_id columns to speed up common lookups

DO $$
BEGIN
    -- Check if table exists using information_schema to avoid pg_catalog dependency issues in some tools
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'programmes') THEN
        
        -- Index on case_id
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='case_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_case_id ON programmes(case_id)';
        END IF;

        -- Index on project_id
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='project_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_project_id ON programmes(project_id)';
        END IF;

        -- Index on uploaded_by (or uploaded_by_id if renamed)
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_uploaded_by ON programmes(uploaded_by)';
        ELSIF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_uploaded_by_id ON programmes(uploaded_by_id)';
        END IF;
        
    END IF;
END $$;

-- Verify indexes were created (uncomment to run)
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'programmes';
