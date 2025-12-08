-- Performance indexes for email correspondence
-- These indexes dramatically improve query performance for the server-side row model

-- Index for project-based queries with date ordering (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_email_project_date 
ON email_messages(project_id, date_sent DESC);

-- Index for case-based queries with date ordering
CREATE INDEX IF NOT EXISTS idx_email_case_date 
ON email_messages(case_id, date_sent DESC);

-- Index for sender lookups (filtering by sender)
CREATE INDEX IF NOT EXISTS idx_email_sender 
ON email_messages(sender_email);

-- Index for subject text search (using trigram for ILIKE)
-- Note: Requires pg_trgm extension
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_email_subject_trgm 
ON email_messages USING gin(subject gin_trgm_ops);

-- Index for body text search (using trigram for ILIKE)
CREATE INDEX IF NOT EXISTS idx_email_body_trgm 
ON email_messages USING gin(body_text gin_trgm_ops);

-- Index for attachment filtering
CREATE INDEX IF NOT EXISTS idx_email_has_attachments 
ON email_messages(has_attachments) WHERE has_attachments = true;

-- Composite index for common filter combinations
CREATE INDEX IF NOT EXISTS idx_email_project_sender_date
ON email_messages(project_id, sender_email, date_sent DESC);

-- Index for linked activity queries
CREATE INDEX IF NOT EXISTS idx_email_linked_activity
ON email_messages(linked_activity_id) WHERE linked_activity_id IS NOT NULL;

-- Analyze the table to update statistics
ANALYZE email_messages;

