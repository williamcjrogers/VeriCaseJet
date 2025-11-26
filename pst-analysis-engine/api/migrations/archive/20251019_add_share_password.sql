--noinspection SqlResolveForFile @ table/"share_links"

DO $$
BEGIN
    -- Safe migration: Add password_hash to share_links only if table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'share_links') THEN
        -- Use dynamic SQL to avoid static analysis errors if table is missing
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'share_links' AND column_name = 'password_hash') THEN
            EXECUTE 'ALTER TABLE share_links ADD COLUMN password_hash VARCHAR(255)';
        END IF;
    END IF;
END $$;
