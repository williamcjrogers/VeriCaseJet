-- Migration: Enhanced Document Management Features
-- Date: 2025-10-23
-- Description: Adds favorites, versioning, and access tracking

-- Favorites table for starring files
CREATE TABLE IF NOT EXISTS favorites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, document_id)
);

CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_document ON favorites(document_id);

-- Document versions table for version history
CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    filename VARCHAR(512) NOT NULL,
    size INTEGER,
    content_type VARCHAR(128),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    comment TEXT,
    UNIQUE(document_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_versions_created ON document_versions(created_at DESC);

-- Add tracking columns to documents table
ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_accessed_by UUID REFERENCES users(id);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_private BOOLEAN DEFAULT false;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS workspace_type VARCHAR(20) DEFAULT 'shared';

-- Add index for workspace filtering
CREATE INDEX IF NOT EXISTS idx_documents_workspace ON documents(workspace_type);
CREATE INDEX IF NOT EXISTS idx_documents_private ON documents(is_private);
CREATE INDEX IF NOT EXISTS idx_documents_last_accessed ON documents(last_accessed_at DESC);

-- Function to auto-create default folders for new users
CREATE OR REPLACE FUNCTION create_default_user_folders()
RETURNS TRIGGER AS $$
BEGIN
    -- Create private folders
    INSERT INTO folders (path, name, parent_path, owner_user_id)
    VALUES 
        ('private/' || NEW.id::text, NEW.email, NULL, NEW.id),
        ('private/' || NEW.id::text || '/Documents', 'Documents', 'private/' || NEW.id::text, NEW.id),
        ('private/' || NEW.id::text || '/Projects', 'Projects', 'private/' || NEW.id::text, NEW.id),
        ('private/' || NEW.id::text || '/Archive', 'Archive', 'private/' || NEW.id::text, NEW.id)
    ON CONFLICT DO NOTHING;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to create folders on user creation
DROP TRIGGER IF EXISTS trigger_create_user_folders ON users;
CREATE TRIGGER trigger_create_user_folders
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION create_default_user_folders();

-- Create shared workspace folders (run once)
DO $$
DECLARE
    admin_user_id UUID;
BEGIN
    -- Get first admin user or create system user
    SELECT id INTO admin_user_id FROM users WHERE role = 'admin' LIMIT 1;
    
    IF admin_user_id IS NULL THEN
        -- Create system user for shared folders if no admin exists
        INSERT INTO users (email, password_hash, role, display_name)
        VALUES ('system@vericase.local', 'none', 'admin', 'System')
        RETURNING id INTO admin_user_id;
    END IF;
    
    -- Create shared workspace folders
    INSERT INTO folders (path, name, parent_path, owner_user_id)
    VALUES 
        ('shared', 'Shared Workspace', NULL, admin_user_id),
        ('shared/General', 'General', 'shared', admin_user_id),
        ('shared/Legal', 'Legal', 'shared', admin_user_id),
        ('shared/HR', 'Human Resources', 'shared', admin_user_id),
        ('shared/Finance', 'Finance', 'shared', admin_user_id),
        ('shared/Projects', 'Projects', 'shared', admin_user_id)
    ON CONFLICT DO NOTHING;
END $$;

-- Add comments for documentation
COMMENT ON TABLE favorites IS 'Stores user favorites/starred documents';
COMMENT ON TABLE document_versions IS 'Stores version history for documents';
COMMENT ON COLUMN documents.workspace_type IS 'Type of workspace: private or shared';
COMMENT ON COLUMN documents.is_private IS 'Whether document is in private folder';
