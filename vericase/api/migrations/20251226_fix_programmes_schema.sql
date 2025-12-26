-- Migration: Align programmes table with ORM model fields
-- Date: 2025-12-26

DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'programmes') THEN
        -- Core metadata fields
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='programme_name') THEN
            EXECUTE 'ALTER TABLE programmes ADD COLUMN programme_name VARCHAR(255)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='project_id') THEN
            EXECUTE 'ALTER TABLE programmes ADD COLUMN project_id UUID';
        END IF;

        -- File storage fields
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='filename') THEN
            EXECUTE 'ALTER TABLE programmes ADD COLUMN filename VARCHAR(512)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='s3_bucket') THEN
            EXECUTE 'ALTER TABLE programmes ADD COLUMN s3_bucket VARCHAR(128)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='s3_key') THEN
            EXECUTE 'ALTER TABLE programmes ADD COLUMN s3_key VARCHAR(2048)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='file_format') THEN
            EXECUTE 'ALTER TABLE programmes ADD COLUMN file_format VARCHAR(50)';
        END IF;

        -- Uploader field (align with ORM name)
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by') THEN
            EXECUTE 'ALTER TABLE programmes ADD COLUMN uploaded_by UUID';
        END IF;

        -- Best-effort backfill from legacy column
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by_id') THEN
            EXECUTE 'UPDATE programmes SET uploaded_by = uploaded_by_id WHERE uploaded_by IS NULL';
        END IF;

        -- Foreign keys (best-effort, guarded)
        -- Note: PostgreSQL doesn't support IF NOT EXISTS for constraints, so we check first
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='project_id')
           AND EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name='projects')
           AND NOT EXISTS (SELECT FROM information_schema.table_constraints WHERE constraint_name='programmes_project_id_fkey') THEN
            EXECUTE 'ALTER TABLE programmes ADD CONSTRAINT programmes_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by')
           AND EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name='users')
           AND NOT EXISTS (SELECT FROM information_schema.table_constraints WHERE constraint_name='programmes_uploaded_by_fkey') THEN
            EXECUTE 'ALTER TABLE programmes ADD CONSTRAINT programmes_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES users(id)';
        END IF;
    END IF;
END $$;

-- Indexes for new columns
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'programmes') THEN
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='project_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_project_id ON programmes(project_id)';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='programmes' AND column_name='uploaded_by') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_uploaded_by ON programmes(uploaded_by)';
        END IF;
    END IF;
END $$;
