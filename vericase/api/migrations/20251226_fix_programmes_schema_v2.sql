-- Migration: Align programmes table with ORM model fields (safe retries)
-- Date: 2025-12-26

-- Core metadata fields
ALTER TABLE programmes ADD COLUMN IF NOT EXISTS programme_name VARCHAR(255);
ALTER TABLE programmes ADD COLUMN IF NOT EXISTS project_id UUID;

-- File storage fields
ALTER TABLE programmes ADD COLUMN IF NOT EXISTS filename VARCHAR(512);
ALTER TABLE programmes ADD COLUMN IF NOT EXISTS s3_bucket VARCHAR(128);
ALTER TABLE programmes ADD COLUMN IF NOT EXISTS s3_key VARCHAR(2048);
ALTER TABLE programmes ADD COLUMN IF NOT EXISTS file_format VARCHAR(50);

-- Uploader field (align with ORM name)
ALTER TABLE programmes ADD COLUMN IF NOT EXISTS uploaded_by UUID;

-- Best-effort backfill from legacy column
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by_id') THEN
        EXECUTE 'UPDATE programmes SET uploaded_by = uploaded_by_id WHERE uploaded_by IS NULL';
    END IF;
END $$;

-- Foreign keys (guarded)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='project_id')
       AND EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name='projects')
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'programmes_project_id_fkey') THEN
        EXECUTE 'ALTER TABLE programmes ADD CONSTRAINT programmes_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL';
    END IF;

    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by')
       AND EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name='users')
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'programmes_uploaded_by_fkey') THEN
        EXECUTE 'ALTER TABLE programmes ADD CONSTRAINT programmes_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES users(id)';
    END IF;
END $$;

-- Indexes for new columns
CREATE INDEX IF NOT EXISTS idx_programmes_project_id ON programmes(project_id);
CREATE INDEX IF NOT EXISTS idx_programmes_uploaded_by ON programmes(uploaded_by);
