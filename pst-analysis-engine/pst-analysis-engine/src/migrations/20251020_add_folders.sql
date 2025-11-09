-- Add folders table to track empty folders
-- Virtual folders are derived from document paths, but we need to track empty ones

CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    path VARCHAR(1024) NOT NULL,
    name VARCHAR(255) NOT NULL,
    parent_path VARCHAR(1024),
    owner_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(owner_user_id, path)
);

CREATE INDEX idx_folders_owner ON folders(owner_user_id);
CREATE INDEX idx_folders_path ON folders(path);
CREATE INDEX idx_folders_parent_path ON folders(parent_path);
