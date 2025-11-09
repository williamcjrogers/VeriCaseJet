-- Add metadata JSON columns for storing refinement and other flexible data

-- Add metadata to projects table
ALTER TABLE projects 
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Add metadata to email_messages table
ALTER TABLE email_messages 
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Add indexes for JSON queries
CREATE INDEX IF NOT EXISTS idx_project_metadata ON projects USING gin (metadata);
CREATE INDEX IF NOT EXISTS idx_email_metadata ON email_messages USING gin (metadata);

-- Comments
COMMENT ON COLUMN projects.metadata IS 'JSON storage for flexible project data including refinement filters';
COMMENT ON COLUMN email_messages.metadata IS 'JSON storage for flexible email data including refinement exclusions';
