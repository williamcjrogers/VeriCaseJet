-- Migration: Add indexes to programmes table for performance optimization
-- Date: 2024-11-09
-- Description: Adds indexes on case_id and project_id columns to speed up common lookups

-- Create index on case_id for faster case-based queries
CREATE INDEX IF NOT EXISTS idx_programmes_case_id ON programmes(case_id);

-- Create index on project_id for faster project-based queries
CREATE INDEX IF NOT EXISTS idx_programmes_project_id ON programmes(project_id);

-- Create index on uploaded_by for faster user-based queries
CREATE INDEX IF NOT EXISTS idx_programmes_uploaded_by ON programmes(uploaded_by);

-- Verify indexes were created (uncomment to run)
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'programmes';
