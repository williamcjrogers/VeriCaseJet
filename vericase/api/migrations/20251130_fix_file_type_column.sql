-- Migration: Increase file_type and mime_type column sizes for flexibility
-- Date: 2025-11-30
-- Issue: PST files with unusual filenames were causing truncation errors

-- NOTE:
-- `evidence_items` is referenced by `v_evidence_with_links` (SELECT ei.*).
-- PostgreSQL blocks ALTER COLUMN TYPE while a dependent view exists.
-- Drop + recreate the view around the type changes (migration is idempotent).

DROP VIEW IF EXISTS v_evidence_with_links;

-- Increase file_type from VARCHAR(50) to VARCHAR(255)
ALTER TABLE evidence_items
ALTER COLUMN file_type TYPE VARCHAR(255);

-- Increase mime_type from VARCHAR(128) to VARCHAR(255) for edge cases
ALTER TABLE evidence_items
ALTER COLUMN mime_type TYPE VARCHAR(255);

-- Recreate view (keep definition consistent with 20251125_evidence_repository.sql)
CREATE OR REPLACE VIEW v_evidence_with_links AS
SELECT
    ei.*,
    COALESCE(link_counts.correspondence_count, 0) as correspondence_count,
    COALESCE(link_counts.verified_link_count, 0) as verified_link_count,
    COALESCE(rel_counts.relation_count, 0) as relation_count
FROM evidence_items ei
LEFT JOIN (
    SELECT
        evidence_item_id,
        COUNT(*) as correspondence_count,
        COUNT(*) FILTER (WHERE is_verified) as verified_link_count
    FROM evidence_correspondence_links
    GROUP BY evidence_item_id
) link_counts ON ei.id = link_counts.evidence_item_id
LEFT JOIN (
    SELECT
        source_evidence_id as evidence_id,
        COUNT(*) as relation_count
    FROM evidence_relations
    GROUP BY source_evidence_id
) rel_counts ON ei.id = rel_counts.evidence_id;

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

