-- Migration: Add meta column to evidence_items for spam classification cascade
-- Date: 2025-12-15
-- Purpose: Enable spam/refinement state inheritance from parent emails

DO $$
BEGIN
    -- Add meta JSONB column if it doesn't exist
    IF NOT EXISTS (
        SELECT FROM information_schema.columns 
        WHERE table_name = 'evidence_items' AND column_name = 'meta'
    ) THEN
        ALTER TABLE evidence_items ADD COLUMN meta JSONB DEFAULT '{}';
        COMMENT ON COLUMN evidence_items.meta IS 'Metadata for spam classification, refinement state, inherited from parent email';
    END IF;
END $$;

-- Create GIN index on meta->spam for efficient filtering
CREATE INDEX IF NOT EXISTS idx_evidence_items_meta_spam 
ON evidence_items USING GIN ((meta->'spam'));

-- Create index for is_hidden lookups
CREATE INDEX IF NOT EXISTS idx_evidence_items_meta_spam_hidden 
ON evidence_items ((meta->'spam'->>'is_hidden')) 
WHERE meta->'spam'->>'is_hidden' IS NOT NULL;

SELECT 'Migration 20251215_evidence_meta_column completed successfully' AS status;
