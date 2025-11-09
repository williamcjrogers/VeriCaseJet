-- User Management Migration
-- Date: 2025-10-22
-- Description: Add user roles, invitations, and document sharing tables

-- Create user role enum
CREATE TYPE user_role AS ENUM ('admin', 'editor', 'viewer');

-- Add role and management columns to users table
ALTER TABLE users 
    ADD COLUMN IF NOT EXISTS role user_role DEFAULT 'editor',
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS display_name VARCHAR(255);

-- Create user invitations table
CREATE TABLE IF NOT EXISTS user_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    invited_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role user_role NOT NULL DEFAULT 'viewer',
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    accepted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_invitations_token ON user_invitations(token);
CREATE INDEX IF NOT EXISTS idx_invitations_email ON user_invitations(email);
CREATE INDEX IF NOT EXISTS idx_invitations_expires ON user_invitations(expires_at);

-- Create document shares table (for sharing with specific users)
CREATE TABLE IF NOT EXISTS document_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    shared_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shared_with UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission VARCHAR(20) NOT NULL DEFAULT 'view' CHECK (permission IN ('view', 'edit')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, shared_with)
);

CREATE INDEX IF NOT EXISTS idx_shares_document ON document_shares(document_id);
CREATE INDEX IF NOT EXISTS idx_shares_shared_with ON document_shares(shared_with);
CREATE INDEX IF NOT EXISTS idx_shares_shared_by ON document_shares(shared_by);

-- Create folder shares table (for sharing entire folders)
CREATE TABLE IF NOT EXISTS folder_shares (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    folder_path VARCHAR(500) NOT NULL,
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shared_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shared_with UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission VARCHAR(20) NOT NULL DEFAULT 'view' CHECK (permission IN ('view', 'edit')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(folder_path, owner_id, shared_with)
);

CREATE INDEX IF NOT EXISTS idx_folder_shares_path ON folder_shares(folder_path, owner_id);
CREATE INDEX IF NOT EXISTS idx_folder_shares_shared_with ON folder_shares(shared_with);
CREATE INDEX IF NOT EXISTS idx_folder_shares_shared_by ON folder_shares(shared_by);

-- Set first user as admin (if exists)
UPDATE users 
SET role = 'admin' 
WHERE id = (SELECT id FROM users ORDER BY created_at LIMIT 1);

-- Add comments
COMMENT ON TABLE user_invitations IS 'Stores user invitation tokens for onboarding new users';
COMMENT ON TABLE document_shares IS 'Stores document-level sharing permissions between users';
COMMENT ON TABLE folder_shares IS 'Stores folder-level sharing permissions between users';
COMMENT ON COLUMN users.role IS 'User role: admin (full access), editor (can create/edit), viewer (read-only)';
COMMENT ON COLUMN users.is_active IS 'Whether the user account is active';
COMMENT ON COLUMN users.display_name IS 'User display name for UI';
