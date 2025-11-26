-- Active: 1763739336777@@localhost@55432
-- Add programmes and delays tables
-- Date: 2025-11-02

--noinspection SqlResolveForFile @ routine/"gen_random_uuid"
--noinspection SqlResolveForFile @ table/"cases"
--noinspection SqlResolveForFile @ table/"documents"
--noinspection SqlResolveForFile @ table/"users"
--noinspection SqlResolveForFile @ table/"issues"
--noinspection SqlResolveForFile @ table/"evidence"
--noinspection SqlResolveForFile @ column/"id"
--noinspection SqlResolveForFile @ column/"as_planned_date"
--noinspection SqlResolveForFile @ column/"as_built_date"

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Programmes table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes') THEN
        EXECUTE 'CREATE TABLE programmes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            document_id UUID,
            programme_type VARCHAR(50) NOT NULL, 
            programme_date TIMESTAMPTZ,
            version_number VARCHAR(100),
            activities JSONB, 
            critical_path JSONB, 
            milestones JSONB, 
            project_start TIMESTAMPTZ,
            project_finish TIMESTAMPTZ,
            data_date TIMESTAMPTZ,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            uploaded_by_id UUID
        )';

        -- Add FKs safely
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
             EXECUTE 'ALTER TABLE programmes ADD CONSTRAINT programmes_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
             EXECUTE 'ALTER TABLE programmes ADD CONSTRAINT programmes_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE programmes ADD CONSTRAINT programmes_uploaded_by_id_fkey FOREIGN KEY (uploaded_by_id) REFERENCES users(id)';
        END IF;
    END IF;
END $$;

-- Indexes for programmes (dynamic SQL to avoid static analysis errors)
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_case ON programmes(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_type ON programmes(programme_type)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_document ON programmes(document_id)';
    END IF;
END $$;


-- Delay events table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'delay_events') THEN
        EXECUTE 'CREATE TABLE delay_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            as_planned_programme_id UUID,
            as_built_programme_id UUID,
            activity_id VARCHAR(100), 
            activity_name VARCHAR(500),
            planned_start TIMESTAMPTZ,
            planned_finish TIMESTAMPTZ,
            actual_start TIMESTAMPTZ,
            actual_finish TIMESTAMPTZ,
            delay_days INTEGER NOT NULL DEFAULT 0,
            delay_type VARCHAR(50), 
            is_on_critical_path BOOLEAN DEFAULT FALSE,
            delay_cause VARCHAR(100), 
            description TEXT,
            linked_correspondence_ids JSONB, 
            linked_issue_id UUID,
            eot_entitlement_days INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            created_by_id UUID
        )';

        -- Add FKs safely
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
             EXECUTE 'ALTER TABLE delay_events ADD CONSTRAINT delay_events_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes') THEN
             EXECUTE 'ALTER TABLE delay_events ADD CONSTRAINT delay_events_as_planned_fkey FOREIGN KEY (as_planned_programme_id) REFERENCES programmes(id) ON DELETE SET NULL';
             EXECUTE 'ALTER TABLE delay_events ADD CONSTRAINT delay_events_as_built_fkey FOREIGN KEY (as_built_programme_id) REFERENCES programmes(id) ON DELETE SET NULL';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'issues') THEN
             EXECUTE 'ALTER TABLE delay_events ADD CONSTRAINT delay_events_linked_issue_fkey FOREIGN KEY (linked_issue_id) REFERENCES issues(id) ON DELETE SET NULL';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE delay_events ADD CONSTRAINT delay_events_created_by_fkey FOREIGN KEY (created_by_id) REFERENCES users(id)';
        END IF;
    END IF;
END $$;

-- Indexes for delay_events
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'delay_events') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_delay_events_case ON delay_events(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_delay_events_planned_prog ON delay_events(as_planned_programme_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_delay_events_built_prog ON delay_events(as_built_programme_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_delay_events_critical ON delay_events(is_on_critical_path)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_delay_events_cause ON delay_events(delay_cause)';
    END IF;
END $$;


-- Add programme columns to Evidence table for linking correspondence to programme analysis
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evidence') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='metadata') THEN
            EXECUTE 'ALTER TABLE evidence ADD COLUMN metadata JSONB';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='as_planned_date') THEN
            EXECUTE 'ALTER TABLE evidence ADD COLUMN as_planned_date TIMESTAMP';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='as_planned_activity') THEN
            EXECUTE 'ALTER TABLE evidence ADD COLUMN as_planned_activity VARCHAR(500)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='as_built_date') THEN
            EXECUTE 'ALTER TABLE evidence ADD COLUMN as_built_date TIMESTAMP';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='as_built_activity') THEN
            EXECUTE 'ALTER TABLE evidence ADD COLUMN as_built_activity VARCHAR(500)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='delay_days') THEN
            EXECUTE 'ALTER TABLE evidence ADD COLUMN delay_days INTEGER DEFAULT 0';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='is_critical_path') THEN
            EXECUTE 'ALTER TABLE evidence ADD COLUMN is_critical_path BOOLEAN DEFAULT FALSE';
        END IF;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evidence') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_evidence_as_planned ON evidence(as_planned_date)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_evidence_as_built ON evidence(as_built_date)';
    END IF;
END $$;
