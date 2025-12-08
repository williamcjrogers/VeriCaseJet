-- Migration: Add extracted_metadata and metadata_extracted_at columns to evidence_items
-- Date: 2025-11-26
-- Description: Adds columns for storing comprehensive metadata extracted from files

-- Add extracted_metadata column (JSONB for flexible storage)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'evidence_items' AND column_name = 'extracted_metadata'
    ) THEN
        ALTER TABLE evidence_items 
        ADD COLUMN extracted_metadata JSONB;
        
        COMMENT ON COLUMN evidence_items.extracted_metadata IS 'Comprehensive metadata extracted from file (EXIF, PDF properties, Office metadata, etc.)';
    END IF;
END $$;

-- Add metadata_extracted_at column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'evidence_items' AND column_name = 'metadata_extracted_at'
    ) THEN
        ALTER TABLE evidence_items 
        ADD COLUMN metadata_extracted_at TIMESTAMP WITH TIME ZONE;
        
        COMMENT ON COLUMN evidence_items.metadata_extracted_at IS 'Timestamp when metadata was last extracted';
    END IF;
END $$;

-- Create index on extracted_metadata for efficient querying
CREATE INDEX IF NOT EXISTS idx_evidence_items_extracted_metadata 
ON evidence_items USING GIN (extracted_metadata);

-- Create index on metadata_extracted_at for efficient filtering
CREATE INDEX IF NOT EXISTS idx_evidence_items_metadata_extracted_at 
ON evidence_items (metadata_extracted_at) WHERE metadata_extracted_at IS NOT NULL;

-- Done
SELECT 'Migration 20251126_evidence_metadata_columns completed successfully' AS status;

