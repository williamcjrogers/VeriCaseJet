-- Active: 1763739336777@@localhost@55432
-- Migration: Enhanced Document Management Features
-- Date: 2025-10-23
-- Description: Adds favorites, versioning, and access tracking
-- SQL Dialect: PostgreSQL
-- Note: IDE warnings about unresolved tables are false positives

--noinspection SqlResolveForFile @ routine/"gen_random_uuid"
--noinspection SqlResolveForFile @ table/"users"
--noinspection SqlResolveForFile @ table/"documents"
--noinspection SqlResolveForFile @ table/"folders"
--noinspection SqlResolveForFile @ column/"id"
--noinspection SqlResolveForFile @ column/"role"
--noinspection SqlResolveForFile @ column/"email"
--noinspection SqlResolveForFile @ column/"password_hash"
--noinspection SqlResolveForFile @ column/"display_name"
--noinspection SqlResolveForFile @ column/"workspace_type"
--noinspection SqlResolveForFile @ column/"is_private"
--noinspection SqlResolveForFile @ column/"last_accessed_at"
--noinspection SqlResolveForFile @ column/"path"
--noinspection SqlResolveForFile @ column/"name"
--noinspection SqlResolveForFile @ column/"parent_path"
--noinspection SqlResolveForFile @ column/"owner_user_id"
--noinspection SqlInsertValuesForFile

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Favorites table for starring files
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'favorites') THEN
        EXECUTE 'CREATE TABLE favorites (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            document_id UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE(user_id, document_id)
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
            EXECUTE 'ALTER TABLE favorites ADD CONSTRAINT favorites_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
            EXECUTE 'ALTER TABLE favorites ADD CONSTRAINT favorites_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE';
        END IF;
    END IF;
END $$;

-- Favorites indexes
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'favorites') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_favorites_document ON favorites(document_id)';
    END IF;
END $$;

-- Document versions table for version history
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'document_versions') THEN
        EXECUTE 'CREATE TABLE document_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL,
            version_number INTEGER NOT NULL,
            s3_key VARCHAR(2048) NOT NULL,
            filename VARCHAR(512) NOT NULL,
            size INTEGER,
            content_type VARCHAR(128),
            created_by UUID,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            comment TEXT,
            UNIQUE(document_id, version_number)
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
            EXECUTE 'ALTER TABLE document_versions ADD CONSTRAINT document_versions_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
            EXECUTE 'ALTER TABLE document_versions ADD CONSTRAINT document_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id)';
        END IF;
    END IF;
END $$;

-- Versions indexes
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'document_versions') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_versions_created ON document_versions(created_at DESC)';
    END IF;
END $$;

-- Add tracking columns to documents table
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='documents' AND column_name='last_accessed_at') THEN
            EXECUTE 'ALTER TABLE documents ADD COLUMN last_accessed_at TIMESTAMP WITH TIME ZONE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='documents' AND column_name='last_accessed_by') THEN
            EXECUTE 'ALTER TABLE documents ADD COLUMN last_accessed_by UUID REFERENCES users(id)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='documents' AND column_name='is_private') THEN
            EXECUTE 'ALTER TABLE documents ADD COLUMN is_private BOOLEAN DEFAULT false';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='documents' AND column_name='workspace_type') THEN
            EXECUTE 'ALTER TABLE documents ADD COLUMN workspace_type VARCHAR(20) DEFAULT ''shared''';
        END IF;
    END IF;
END $$;

-- Add index for workspace filtering
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_type)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_documents_private ON documents(is_private)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_documents_last_accessed ON documents(last_accessed_at DESC)';
    END IF;
END $$;

-- Function to auto-create default folders for new users
-- Only create if folders and users tables exist
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'folders') AND
       EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
       
        EXECUTE 'CREATE OR REPLACE FUNCTION create_default_user_folders()
        RETURNS TRIGGER AS $FUNC$
        BEGIN
            -- Create private folders
            INSERT INTO folders (id, path, name, parent_path, owner_user_id)
            VALUES 
                (gen_random_uuid(), ''private/'' || NEW.id::text, NEW.email, NULL, NEW.id),
                (gen_random_uuid(), ''private/'' || NEW.id::text || ''/Documents'', ''Documents'', ''private/'' || NEW.id::text, NEW.id),
                (gen_random_uuid(), ''private/'' || NEW.id::text || ''/Projects'', ''Projects'', ''private/'' || NEW.id::text, NEW.id),
                (gen_random_uuid(), ''private/'' || NEW.id::text || ''/Archive'', ''Archive'', ''private/'' || NEW.id::text, NEW.id)
            ON CONFLICT DO NOTHING;
            
            RETURN NEW;
        END;
        $FUNC$ LANGUAGE plpgsql';

        -- Trigger to create folders on user creation
        EXECUTE 'DROP TRIGGER IF EXISTS trigger_create_user_folders ON users';
        EXECUTE 'CREATE TRIGGER trigger_create_user_folders
            AFTER INSERT ON users
            FOR EACH ROW
            EXECUTE FUNCTION create_default_user_folders()';
    END IF;
END $$;


-- Create shared workspace folders (run once)
DO $$
DECLARE
    admin_user_id UUID;
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'folders') AND
       EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
       
        -- Get first admin user or create system user
        -- Handle both 'admin' and 'ADMIN' roles safely
        BEGIN
            EXECUTE 'SELECT id FROM users WHERE role::text IN (''admin'', ''ADMIN'') LIMIT 1' INTO admin_user_id;
        EXCEPTION WHEN OTHERS THEN
            -- Fallback if role column issue
            NULL;
        END;
        
        IF admin_user_id IS NULL THEN
            -- Create system user for shared folders if no admin exists
            -- Assume users table structure is valid
            BEGIN
                EXECUTE 'INSERT INTO users (id, email, password_hash, role, display_name, email_verified, failed_login_attempts)
                VALUES (gen_random_uuid(), ''system@vericase.local'', ''none'', ''admin'', ''System'', true, 0)
                RETURNING id' INTO admin_user_id;
            EXCEPTION WHEN OTHERS THEN
                -- Failed to create system user, possibly due to constraints or missing columns
                NULL;
            END;
        END IF;
        
        IF admin_user_id IS NOT NULL THEN
            -- Create shared workspace folders
            -- We need to pass admin_user_id into the dynamic SQL.
            -- Format string or use logical check.
            -- It is easier to execute INSERT with parameter using EXECUTE ... USING
            EXECUTE 'INSERT INTO folders (id, path, name, parent_path, owner_user_id)
            VALUES 
                (gen_random_uuid(), ''shared'', ''Shared Workspace'', NULL, $1),
                (gen_random_uuid(), ''shared/General'', ''General'', ''shared'', $1),
                (gen_random_uuid(), ''shared/Legal'', ''Legal'', ''shared'', $1),
                (gen_random_uuid(), ''shared/HR'', ''Human Resources'', ''shared'', $1),
                (gen_random_uuid(), ''shared/Finance'', ''Finance'', ''shared'', $1),
                (gen_random_uuid(), ''shared/Projects'', ''Projects'', ''shared'', $1)
            ON CONFLICT DO NOTHING' USING admin_user_id;
        END IF;
    END IF;
END $$;

-- Add comments for documentation
DO $$
BEGIN
    EXECUTE 'COMMENT ON TABLE favorites IS ''Stores user favorites/starred documents''';
    EXECUTE 'COMMENT ON TABLE document_versions IS ''Stores version history for documents''';
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='documents' AND column_name='workspace_type') THEN
        EXECUTE 'COMMENT ON COLUMN documents.workspace_type IS ''Type of workspace: private or shared''';
    END IF;
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='documents' AND column_name='is_private') THEN
        EXECUTE 'COMMENT ON COLUMN documents.is_private IS ''Whether document is in private folder''';
    END IF;
END $$;
