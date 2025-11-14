-- Add thread_id field to email_messages table for email threading (USP feature)
-- Migration: 20251114_add_thread_id_to_email_messages.sql
-- Date: 2025-11-14

-- Add thread_id column
ALTER TABLE email_messages 
ADD COLUMN IF NOT EXISTS thread_id VARCHAR(100);

-- Create index for thread_id (for fast thread queries)
CREATE INDEX IF NOT EXISTS idx_email_thread_id 
ON email_messages(thread_id) 
WHERE thread_id IS NOT NULL;

-- Create composite index for case + thread
CREATE INDEX IF NOT EXISTS idx_email_case_thread 
ON email_messages(case_id, thread_id) 
WHERE case_id IS NOT NULL AND thread_id IS NOT NULL;

-- Create composite index for project + thread
CREATE INDEX IF NOT EXISTS idx_email_project_thread 
ON email_messages(project_id, thread_id) 
WHERE project_id IS NOT NULL AND thread_id IS NOT NULL;

-- Add comment
COMMENT ON COLUMN email_messages.thread_id IS 'Computed thread ID for grouping related emails using Message-ID, In-Reply-To, References, and Conversation-Index';
