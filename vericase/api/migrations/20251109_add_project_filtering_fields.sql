-- Active: 1763739336777@@localhost@55432
-- Add filtering fields for retrospective analysis
-- Migration: 20251109_add_project_filtering_fields.sql

DO $$
BEGIN
    -- Ensure projects table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
        
        -- Add columns safely
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'analysis_type') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN analysis_type VARCHAR(50) DEFAULT ''project''';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'project_aliases') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN project_aliases TEXT';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'site_address') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN site_address TEXT';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'include_domains') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN include_domains TEXT';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'exclude_people') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN exclude_people TEXT';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'project_terms') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN project_terms TEXT';
        END IF;

        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'exclude_keywords') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN exclude_keywords TEXT';
        END IF;

        -- Add comments
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'analysis_type') THEN
            EXECUTE 'COMMENT ON COLUMN projects.analysis_type IS ''Type of analysis: retrospective or project''';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'project_aliases') THEN
            EXECUTE 'COMMENT ON COLUMN projects.project_aliases IS ''Comma-separated alternative project names''';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'site_address') THEN
            EXECUTE 'COMMENT ON COLUMN projects.site_address IS ''Project site address/location''';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'include_domains') THEN
            EXECUTE 'COMMENT ON COLUMN projects.include_domains IS ''Comma-separated email domains to include''';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'exclude_people') THEN
            EXECUTE 'COMMENT ON COLUMN projects.exclude_people IS ''Comma-separated names/emails to exclude''';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'project_terms') THEN
            EXECUTE 'COMMENT ON COLUMN projects.project_terms IS ''Project-specific terms and abbreviations''';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'exclude_keywords') THEN
            EXECUTE 'COMMENT ON COLUMN projects.exclude_keywords IS ''Keywords that indicate other projects''';
        END IF;

    END IF;
END $$;
