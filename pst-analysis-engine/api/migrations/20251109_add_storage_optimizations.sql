-- Add storage optimization columns and indexes to email_messages table

-- Add columns for optimized storage
ALTER TABLE email_messages 
ADD COLUMN IF NOT EXISTS body_preview TEXT,
ADD COLUMN IF NOT EXISTS body_full_s3_key VARCHAR(512);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_email_case_date ON email_messages (case_id, date_sent);
CREATE INDEX IF NOT EXISTS idx_email_stakeholders ON email_messages USING gin (matched_stakeholders);
CREATE INDEX IF NOT EXISTS idx_email_keywords ON email_messages USING gin (matched_keywords);
CREATE INDEX IF NOT EXISTS idx_email_has_attachments ON email_messages (case_id, has_attachments);
CREATE INDEX IF NOT EXISTS idx_email_conversation ON email_messages (case_id, conversation_index);

-- Add comment explaining the storage optimization
COMMENT ON COLUMN email_messages.body_preview IS 'First 10KB of email body for quick display';
COMMENT ON COLUMN email_messages.body_full_s3_key IS 'S3 key for full email body if larger than 10KB';
