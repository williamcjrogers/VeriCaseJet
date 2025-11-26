-- Active: 1763739336777@@localhost@55432
-- Allow project-only keywords without associated case
-- Refactored for safety and idempotency

DO $$
BEGIN
    -- Relax constraint on stakeholders table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stakeholders') THEN
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'stakeholders' AND column_name = 'case_id') THEN
             EXECUTE 'ALTER TABLE stakeholders ALTER COLUMN case_id DROP NOT NULL';
        END IF;
    END IF;

    -- Relax constraint on keywords table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'keywords') THEN
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'keywords' AND column_name = 'case_id') THEN
             EXECUTE 'ALTER TABLE keywords ALTER COLUMN case_id DROP NOT NULL';
        END IF;
    END IF;
END $$;
