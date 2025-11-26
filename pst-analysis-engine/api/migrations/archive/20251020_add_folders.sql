-- Add folders table to track empty folders
-- Virtual folders are derived from document paths, but we need to track empty ones
-- SQL Dialect: PostgreSQL
-- Updated: 2025-11-20 (Refactored for idempotency, dynamic SQL, and pgcrypto)
-- Note: gen_random_uuid() requires pgcrypto extension

--noinspection SqlResolveForFile @ routine/"gen_random_uuid"
--noinspection SqlResolveForFile @ table/"users"
--noinspection SqlResolveForFile @ column/"id"
--noinspection SqlResolveForFile @ table/"pg_tables"

-- Ensure pgcrypto is available for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$

BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'folders') THEN
        -- Create table without FK first to avoid static analysis issues
        EXECUTE 'CREATE TABLE folders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            path VARCHAR(1024) NOT NULL,
            name VARCHAR(255) NOT NULL,
            parent_path VARCHAR(1024),
            owner_user_id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE,
            UNIQUE(owner_user_id, path)
        )';

        -- Add FK safely if users table exists
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
            EXECUTE 'ALTER TABLE folders ADD CONSTRAINT folders_owner_user_id_fkey 
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
    END IF;
END $$;

-- Indexes
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'folders') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folders_owner ON folders(owner_user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folders_path ON folders(path)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folders_parent_path ON folders(parent_path)';
    END IF;
END $$;
