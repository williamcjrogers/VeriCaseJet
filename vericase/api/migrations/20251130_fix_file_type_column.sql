-- Migration: Increase file_type and mime_type column sizes for flexibility
-- Date: 2025-11-30
-- Issue: PST files with unusual filenames were causing truncation errors

-- Increase file_type from VARCHAR(50) to VARCHAR(255)
ALTER TABLE evidence_items 
ALTER COLUMN file_type TYPE VARCHAR(255);

-- Increase mime_type from VARCHAR(128) to VARCHAR(255) for edge cases
ALTER TABLE evidence_items 
ALTER COLUMN mime_type TYPE VARCHAR(255);

-- Also update any other tables that might have similar constraints
-- (documents table if it exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'documents' AND column_name = 'content_type') THEN
        ALTER TABLE documents ALTER COLUMN content_type TYPE VARCHAR(255);
    END IF;
END $$;

-- Add comment explaining the change
COMMENT ON COLUMN evidence_items.file_type IS 'File extension or type identifier (increased to 255 for flexibility)';
COMMENT ON COLUMN evidence_items.mime_type IS 'MIME type of the file (increased to 255 for edge cases)';

