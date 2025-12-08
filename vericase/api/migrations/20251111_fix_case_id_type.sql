-- Active: 1763739336777@@localhost@55432
-- Fix cases table to use UUID instead of integer for ID
-- Refactored for static analysis safety and idempotency

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Drop FKs and Recreate cases table
DO $$
BEGIN
    -- Drop evidence FK if table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evidence') THEN
        ALTER TABLE evidence DROP CONSTRAINT IF EXISTS evidence_case_id_fkey;
    END IF;

    -- Drop issues FK if table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'issues') THEN
        ALTER TABLE issues DROP CONSTRAINT IF EXISTS issues_case_id_fkey;
    END IF;

    -- Drop jobs FK if table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'jobs') THEN
        ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_case_id_fkey;
    END IF;

    -- Drop and recreate cases table
    -- We use dynamic SQL to prevent IDEs from getting confused by the DROP/CREATE cycle
    EXECUTE 'DROP TABLE IF EXISTS cases CASCADE';
    
    EXECUTE 'CREATE TABLE cases (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        case_number VARCHAR(100) UNIQUE NOT NULL,
        name VARCHAR(500) NOT NULL,
        description TEXT,
        contract_type VARCHAR(50),
        programme_type VARCHAR(50),
        owner_id UUID NOT NULL,
        company_id UUID,
        resolution_route VARCHAR(50),
        claimant VARCHAR(255),
        defendant VARCHAR(255),
        client VARCHAR(255),
        config_json JSON,
        is_configured BOOLEAN DEFAULT false,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )';

    -- Add FKs for cases
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
        EXECUTE 'ALTER TABLE cases ADD CONSTRAINT cases_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id)';
    END IF;
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'companies') THEN
        EXECUTE 'ALTER TABLE cases ADD CONSTRAINT cases_company_id_fkey FOREIGN KEY (company_id) REFERENCES companies(id)';
    END IF;

    -- Create indexes
    EXECUTE 'CREATE INDEX idx_cases_case_number ON cases(case_number)';
    EXECUTE 'CREATE INDEX idx_cases_owner ON cases(owner_id)';
    EXECUTE 'CREATE INDEX idx_cases_company ON cases(company_id)';
END $$;

-- 3. Legal Team
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_legal_team') THEN
        EXECUTE 'CREATE TABLE case_legal_team (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID,
            role VARCHAR(100),
            name VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )';
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
        EXECUTE 'ALTER TABLE case_legal_team DROP CONSTRAINT IF EXISTS case_legal_team_case_id_fkey';
        EXECUTE 'ALTER TABLE case_legal_team ADD CONSTRAINT case_legal_team_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
    END IF;
END $$;

-- 4. Heads of Claim
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'heads_of_claim') THEN
        EXECUTE 'CREATE TABLE heads_of_claim (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID,
            claim_type VARCHAR(50),
            description TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )';
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
         EXECUTE 'ALTER TABLE heads_of_claim DROP CONSTRAINT IF EXISTS heads_of_claim_case_id_fkey';
         EXECUTE 'ALTER TABLE heads_of_claim ADD CONSTRAINT heads_of_claim_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
    END IF;
END $$;

-- 5. Case Deadlines
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_deadlines') THEN
        EXECUTE 'CREATE TABLE case_deadlines (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID,
            "deadline_type" VARCHAR(100),
            deadline_date TIMESTAMP WITH TIME ZONE,
            description TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )';
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
         EXECUTE 'ALTER TABLE case_deadlines DROP CONSTRAINT IF EXISTS case_deadlines_case_id_fkey';
         EXECUTE 'ALTER TABLE case_deadlines ADD CONSTRAINT case_deadlines_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
    END IF;
END $$;

-- 6. Issues
DO $$
BEGIN
    EXECUTE 'DROP TABLE IF EXISTS issues CASCADE';
    EXECUTE 'CREATE TABLE issues (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        case_id UUID,
        title VARCHAR(500) NOT NULL,
        description TEXT,
        issue_type VARCHAR(50),
        raised_by VARCHAR(255),
        raised_date TIMESTAMP WITH TIME ZONE,
        response_due TIMESTAMP WITH TIME ZONE,
        status VARCHAR(50) DEFAULT ''open'',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    )';

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
         EXECUTE 'ALTER TABLE issues ADD CONSTRAINT issues_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id)';
    END IF;
END $$;

-- 7. Evidence
DO $$
BEGIN
    EXECUTE 'DROP TABLE IF EXISTS evidence CASCADE';
    EXECUTE 'CREATE TABLE evidence (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        case_id UUID,
        document_id UUID,
        issue_id UUID,
        description TEXT,
        relevance_score FLOAT DEFAULT 0.0,
        added_by UUID,
        added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        notice_type VARCHAR(100),
        notice_date TIMESTAMP WITH TIME ZONE,
        sender VARCHAR(255),
        recipient VARCHAR(255),
        delay_days INTEGER,
        cost_impact NUMERIC(15, 2),
        currency VARCHAR(10) DEFAULT ''GBP'',
        metadata JSON
    )';

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
         EXECUTE 'ALTER TABLE evidence ADD CONSTRAINT evidence_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id)';
    END IF;
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
         EXECUTE 'ALTER TABLE evidence ADD CONSTRAINT evidence_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id)';
    END IF;
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'issues') THEN
         EXECUTE 'ALTER TABLE evidence ADD CONSTRAINT evidence_issue_id_fkey FOREIGN KEY (issue_id) REFERENCES issues(id)';
    END IF;
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
         EXECUTE 'ALTER TABLE evidence ADD CONSTRAINT evidence_added_by_fkey FOREIGN KEY (added_by) REFERENCES users(id)';
    END IF;
END $$;

-- 8. Claims
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'claims') THEN
        EXECUTE 'CREATE TABLE claims (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID,
            claim_type VARCHAR(50) NOT NULL,
            title VARCHAR(500) NOT NULL,
            description TEXT,
            claimed_amount INTEGER,
            currency VARCHAR(10),
            claim_date TIMESTAMP WITH TIME ZONE,
            response_due_date TIMESTAMP WITH TIME ZONE,
            status VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )';
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
         EXECUTE 'ALTER TABLE claims DROP CONSTRAINT IF EXISTS claims_case_id_fkey';
         EXECUTE 'ALTER TABLE claims ADD CONSTRAINT claims_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id)';
    END IF;
    
    EXECUTE 'COMMENT ON TABLE cases IS ''Legal cases with enhanced construction dispute fields''';
END $$;
