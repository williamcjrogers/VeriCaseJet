-- User Management Migration
-- Date: 2025-10-22
-- Description: Add user roles, invitations, and document sharing tables
-- SQL Dialect: PostgreSQL
-- Note: IDE warnings about unresolved tables/columns are false positives
--       Tables are created in 20240101_initial_schema.sql

--noinspection SqlResolveForFile @ routine/"gen_random_uuid"
--noinspection SqlResolveForFile @ table/"users"
--noinspection SqlResolveForFile @ table/"documents"
--noinspection SqlResolveForFile @ column/"id"
--noinspection SqlResolveForFile @ column/"role"
--noinspection SqlResolveForFile @ column/"created_at"

-- Ensure pgcrypto for gen_random_uuid
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create user role enum safely
DO $$ 
BEGIN
    -- Create type if not exists
    IF NOT EXISTS (SELECT 1 as alias FROM pg_type WHERE typname = 'user_role') THEN
        EXECUTE 'CREATE TYPE user_role AS ENUM (''admin'', ''editor'', ''viewer'')';
    ELSE
        -- If type exists, ensure 'editor' value exists (it might be missing in older schemas)
        BEGIN
            EXECUTE 'ALTER TYPE user_role ADD VALUE IF NOT EXISTS ''editor''';
        EXCEPTION WHEN duplicate_object THEN NULL; END;
        
        BEGIN
            EXECUTE 'ALTER TYPE user_role ADD VALUE IF NOT EXISTS ''viewer''';
        EXCEPTION WHEN duplicate_object THEN NULL; END;
        
        BEGIN
            EXECUTE 'ALTER TYPE user_role ADD VALUE IF NOT EXISTS ''admin''';
        EXCEPTION WHEN duplicate_object THEN NULL; END;
    END IF;
END $$;

-- Add role and management columns to users table safely
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='role') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN role user_role DEFAULT ''editor''';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='is_active') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT true';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='last_login_at') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='display_name') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN display_name VARCHAR(255)';
        END IF;
    END IF;
END $$;

-- Create user invitations table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'user_invitations') THEN
        EXECUTE 'CREATE TABLE user_invitations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) NOT NULL,
            invited_by UUID NOT NULL, 
            role user_role NOT NULL DEFAULT ''viewer'',
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            accepted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE user_invitations ADD CONSTRAINT user_invitations_invited_by_fkey 
             FOREIGN KEY (invited_by) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
    END IF;
END $$;

-- Indexes for user_invitations
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'user_invitations') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_invitations_token ON user_invitations(token)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_invitations_email ON user_invitations(email)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_invitations_expires ON user_invitations(expires_at)';
    END IF;
END $$;

-- Create document shares table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'document_shares') THEN
        EXECUTE 'CREATE TABLE document_shares (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL,
            shared_by UUID NOT NULL,
            shared_with UUID NOT NULL,
            permission VARCHAR(20) NOT NULL DEFAULT ''view'' CHECK (permission IN (''view'', ''edit'')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, shared_with)
        )';
        
        -- Add FKs safely
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
             EXECUTE 'ALTER TABLE document_shares ADD CONSTRAINT document_shares_document_id_fkey 
             FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE document_shares ADD CONSTRAINT document_shares_shared_by_fkey 
             FOREIGN KEY (shared_by) REFERENCES users(id) ON DELETE CASCADE';
             EXECUTE 'ALTER TABLE document_shares ADD CONSTRAINT document_shares_shared_with_fkey 
             FOREIGN KEY (shared_with) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
    END IF;
END $$;

-- Indexes for document_shares
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'document_shares') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_shares_document ON document_shares(document_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_shares_shared_with ON document_shares(shared_with)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_shares_shared_by ON document_shares(shared_by)';
    END IF;
END $$;

-- Create folder shares table
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'folder_shares') THEN
        EXECUTE 'CREATE TABLE folder_shares (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            folder_path VARCHAR(500) NOT NULL,
            owner_id UUID NOT NULL,
            shared_by UUID NOT NULL,
            shared_with UUID NOT NULL,
            permission VARCHAR(20) NOT NULL DEFAULT ''view'' CHECK (permission IN (''view'', ''edit'')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(folder_path, owner_id, shared_with)
        )';

        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE folder_shares ADD CONSTRAINT folder_shares_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE';
             EXECUTE 'ALTER TABLE folder_shares ADD CONSTRAINT folder_shares_shared_by_fkey FOREIGN KEY (shared_by) REFERENCES users(id) ON DELETE CASCADE';
             EXECUTE 'ALTER TABLE folder_shares ADD CONSTRAINT folder_shares_shared_with_fkey FOREIGN KEY (shared_with) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
    END IF;
END $$;

-- Indexes for folder_shares
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'folder_shares') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folder_shares_path ON folder_shares(folder_path, owner_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folder_shares_shared_with ON folder_shares(shared_with)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folder_shares_shared_by ON folder_shares(shared_by)';
    END IF;
END $$;

-- Set first user as admin (safely)
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') AND
       EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='role') THEN
        EXECUTE 'UPDATE users SET role = ''admin'' WHERE id = (SELECT id FROM users ORDER BY created_at LIMIT 1)';
    END IF;
END $$;

-- Add comments
DO $$ BEGIN
    EXECUTE 'COMMENT ON TABLE user_invitations IS ''Stores user invitation tokens for onboarding new users''';
    EXECUTE 'COMMENT ON TABLE document_shares IS ''Stores document-level sharing permissions between users''';
    EXECUTE 'COMMENT ON TABLE folder_shares IS ''Stores folder-level sharing permissions between users''';
    IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='role') THEN
        EXECUTE 'COMMENT ON COLUMN users.role IS ''User role: admin (full access), editor (can create/edit), viewer (read-only)''';
    END IF;
END $$;
