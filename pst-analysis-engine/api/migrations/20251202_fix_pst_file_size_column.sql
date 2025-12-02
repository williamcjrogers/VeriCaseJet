-- Migration: Fix PST File Size Column
-- Created: 2025-12-02
-- Description: Renames file_size to file_size_bytes and changes type to BIGINT to match Python model

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'pst_files') THEN
        
        -- Check if file_size exists and file_size_bytes does not
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 'file_size') 
           AND NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 'file_size_bytes') THEN
            
            -- Rename column
            ALTER TABLE pst_files RENAME COLUMN file_size TO file_size_bytes;
            
            -- Change type to BIGINT
            ALTER TABLE pst_files ALTER COLUMN file_size_bytes TYPE BIGINT;
            
        ELSIF EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 'file_size_bytes') THEN
            -- Ensure it is BIGINT
            ALTER TABLE pst_files ALTER COLUMN file_size_bytes TYPE BIGINT;
        END IF;

    END IF;
END $$;
