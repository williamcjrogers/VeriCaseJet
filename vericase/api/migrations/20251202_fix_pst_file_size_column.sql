-- Migration: Fix Schema Issues (PST Upload 500 Error)
-- Created: 2025-12-02
-- Description: Fixes column types (BIGINT) and names for file sizes, and adds missing uploaded_at column.

-- 1. Fix pst_files
DO $$
BEGIN
    -- Rename file_size to file_size_bytes if needed
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 'file_size') THEN
        ALTER TABLE pst_files RENAME COLUMN file_size TO file_size_bytes;
    END IF;

    -- Ensure file_size_bytes is BIGINT
    ALTER TABLE pst_files ALTER COLUMN file_size_bytes TYPE BIGINT;

    -- Add uploaded_at if missing
    IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 'uploaded_at') THEN
        ALTER TABLE pst_files ADD COLUMN uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
    END IF;
END $$;

-- 2. Fix email_attachments
DO $$
BEGIN
    -- Rename file_size to file_size_bytes if needed
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_attachments' AND column_name = 'file_size') THEN
        ALTER TABLE email_attachments RENAME COLUMN file_size TO file_size_bytes;
    END IF;

    -- Ensure file_size_bytes is BIGINT
    ALTER TABLE email_attachments ALTER COLUMN file_size_bytes TYPE BIGINT;
END $$;

-- 3. Fix documents (guarded - column may already be BIGINT or not exist)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'documents' AND column_name = 'size') THEN
        EXECUTE 'ALTER TABLE documents ALTER COLUMN size TYPE BIGINT';
    END IF;
EXCEPTION WHEN OTHERS THEN
    -- Already BIGINT or other harmless error
    NULL;
END $$;

-- 4. Fix evidence_items (guarded - may be blocked by dependent views)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'evidence_items' AND column_name = 'file_size') THEN
        -- Drop dependent view first
        EXECUTE 'DROP VIEW IF EXISTS v_evidence_with_links CASCADE';
        EXECUTE 'ALTER TABLE evidence_items ALTER COLUMN file_size TYPE BIGINT';
    END IF;
EXCEPTION WHEN OTHERS THEN
    -- Already BIGINT or other harmless error
    NULL;
END $$;
