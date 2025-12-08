-- Active: 1763739336777@@localhost@55432
-- Migration: Add Enhanced Case Fields
-- Created: 2025-11-10
-- Description: Adds fields for enhanced case creation from the configuration wizard
-- Refactored for static analysis safety and idempotency

DO $$
BEGIN
    -- 1. Add resolution route and dispute party fields to cases
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'resolution_route') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN resolution_route VARCHAR(100)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'claimant') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN claimant VARCHAR(512)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'defendant') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN defendant VARCHAR(512)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'cases' AND column_name = 'client') THEN
            EXECUTE 'ALTER TABLE cases ADD COLUMN client VARCHAR(512)';
        END IF;
        
        EXECUTE 'COMMENT ON COLUMN cases.resolution_route IS ''Type of resolution: adjudication, litigation, arbitration, mediation, settlement, TBC''';
        EXECUTE 'COMMENT ON COLUMN cases.claimant IS ''Name of the claimant party''';
        EXECUTE 'COMMENT ON COLUMN cases.defendant IS ''Name of the defendant party''';
        EXECUTE 'COMMENT ON COLUMN cases.client IS ''Top-level client party for whom we are acting''';
    END IF;

    -- 2. Create legal team table for case team members
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_legal_team') THEN
        EXECUTE 'CREATE TABLE case_legal_team (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            role VARCHAR(255) NOT NULL,
            name VARCHAR(512) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';
        EXECUTE 'COMMENT ON TABLE case_legal_team IS ''Legal team members assigned to a case''';
    END IF;

    -- Add FK and Index for case_legal_team
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_legal_team') THEN
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
             EXECUTE 'ALTER TABLE case_legal_team DROP CONSTRAINT IF EXISTS case_legal_team_case_id_fkey';
             EXECUTE 'ALTER TABLE case_legal_team ADD CONSTRAINT case_legal_team_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_legal_team_case ON case_legal_team(case_id)';
    END IF;

    -- 3. Create heads of claim table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'heads_of_claim') THEN
        EXECUTE 'CREATE TABLE heads_of_claim (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            head VARCHAR(512) NOT NULL,
            status VARCHAR(100) DEFAULT ''Discovery'',
            actions TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';
        EXECUTE 'COMMENT ON TABLE heads_of_claim IS ''Heads of claim for tracking case progress''';
    END IF;

    -- Add FK and Indexes for heads_of_claim
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'heads_of_claim') THEN
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
             EXECUTE 'ALTER TABLE heads_of_claim DROP CONSTRAINT IF EXISTS heads_of_claim_case_id_fkey';
             EXECUTE 'ALTER TABLE heads_of_claim ADD CONSTRAINT heads_of_claim_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_heads_of_claim_case ON heads_of_claim(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_heads_of_claim_status ON heads_of_claim(status)';
    END IF;

    -- 4. Create case deadlines table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_deadlines') THEN
        EXECUTE 'CREATE TABLE case_deadlines (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            task VARCHAR(512) NOT NULL,
            description TEXT,
            deadline_date TIMESTAMP WITH TIME ZONE,
            reminder_days INTEGER,
            is_completed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';
        EXECUTE 'COMMENT ON TABLE case_deadlines IS ''Important deadlines and tasks for a case''';
    END IF;

    -- Add FK and Indexes for case_deadlines
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_deadlines') THEN
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
             EXECUTE 'ALTER TABLE case_deadlines DROP CONSTRAINT IF EXISTS case_deadlines_case_id_fkey';
             EXECUTE 'ALTER TABLE case_deadlines ADD CONSTRAINT case_deadlines_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_deadlines_case ON case_deadlines(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_deadlines_date ON case_deadlines(deadline_date)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_deadlines_completed ON case_deadlines(is_completed)';
    END IF;

    -- 5. Allow stakeholders and keywords to be associated with either case or project
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stakeholders') THEN
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'stakeholders' AND column_name = 'case_id') THEN
             EXECUTE 'ALTER TABLE stakeholders ALTER COLUMN case_id DROP NOT NULL';
        END IF;
        EXECUTE 'ALTER TABLE stakeholders DROP CONSTRAINT IF EXISTS chk_stakeholders_case_or_project';
        EXECUTE 'ALTER TABLE stakeholders ADD CONSTRAINT chk_stakeholders_case_or_project CHECK (case_id IS NOT NULL OR project_id IS NOT NULL)';
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'keywords') THEN
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'keywords' AND column_name = 'case_id') THEN
             EXECUTE 'ALTER TABLE keywords ALTER COLUMN case_id DROP NOT NULL';
        END IF;
        EXECUTE 'ALTER TABLE keywords DROP CONSTRAINT IF EXISTS chk_keywords_case_or_project';
        EXECUTE 'ALTER TABLE keywords ADD CONSTRAINT chk_keywords_case_or_project CHECK (case_id IS NOT NULL OR project_id IS NOT NULL)';
    END IF;

END $$;
