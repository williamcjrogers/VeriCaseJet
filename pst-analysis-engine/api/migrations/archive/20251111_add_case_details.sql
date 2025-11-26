-- Active: 1763739336777@@localhost@55432
-- Add extended case metadata fields for wizard workflow
-- Migration: 20251111_add_case_details.sql

DO $$
BEGIN
    -- Ensure cases table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
        
        -- Add columns safely
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'case_id_custom') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN case_id_custom VARCHAR(100)';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'case_status') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN case_status VARCHAR(50)';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'resolution_route') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN resolution_route VARCHAR(100)';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'claimant') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN claimant VARCHAR(255)';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'defendant') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN defendant VARCHAR(255)';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'client') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN client VARCHAR(255)';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'legal_team') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN legal_team JSONB';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'heads_of_claim') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN heads_of_claim JSONB';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'deadlines') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN deadlines JSONB';
        END IF;

        -- Add index
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'case_id_custom') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_cases_case_id_custom ON cases(case_id_custom)';
        END IF;

    END IF;
END $$;

