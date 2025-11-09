-- Additional performance indexes for email_messages table with project support
-- Created: 2025-11-09
-- Description: Adds optimized indexes for project-based queries on email_messages

-- Add composite indexes for project-based queries (matching case-based indexes)
CREATE INDEX IF NOT EXISTS idx_email_project_date ON email_messages(project_id, date_sent);
CREATE INDEX IF NOT EXISTS idx_email_project_has_attachments ON email_messages(project_id, has_attachments);
CREATE INDEX IF NOT EXISTS idx_email_project_conversation ON email_messages(project_id, conversation_index);
CREATE INDEX IF NOT EXISTS idx_email_project_sender ON email_messages(project_id, sender_email);

-- Ensure basic project index exists
CREATE INDEX IF NOT EXISTS idx_email_messages_project_id ON email_messages(project_id);

-- Analyze table to update query planner statistics
ANALYZE email_messages;
