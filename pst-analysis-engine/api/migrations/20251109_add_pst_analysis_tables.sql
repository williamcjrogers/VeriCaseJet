-- Migration: Add PST Analysis Tables
-- Created: 2025-11-09
-- Description: Adds tables for PST forensic analysis, email extraction, and dispute intelligence

-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_name VARCHAR(255) NOT NULL,
    project_code VARCHAR(100) UNIQUE NOT NULL,
    start_date TIMESTAMP WITH TIME ZONE,
    completion_date TIMESTAMP WITH TIME ZONE,
    contract_type VARCHAR(100),
    owner_user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_projects_code ON projects(project_code);

-- PST Files table
CREATE TABLE IF NOT EXISTS pst_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(512) NOT NULL,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    s3_bucket VARCHAR(128) NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    file_size INTEGER,
    total_emails INTEGER DEFAULT 0,
    processed_emails INTEGER DEFAULT 0,
    processing_status VARCHAR(50) DEFAULT 'queued',
    processing_started_at TIMESTAMP WITH TIME ZONE,
    processing_completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pst_files_case ON pst_files(case_id);
CREATE INDEX IF NOT EXISTS idx_pst_files_project ON pst_files(project_id);
CREATE INDEX IF NOT EXISTS idx_pst_files_status ON pst_files(processing_status);

-- Email Messages table
CREATE TABLE IF NOT EXISTS email_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pst_file_id UUID NOT NULL REFERENCES pst_files(id) ON DELETE CASCADE,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    
    -- Email metadata for threading
    message_id VARCHAR(512),
    in_reply_to VARCHAR(512),
    email_references TEXT,  -- renamed from 'references' (reserved keyword)
    conversation_index VARCHAR(1024),
    
    -- PST forensic data
    pst_message_offset INTEGER,
    pst_message_path TEXT,
    
    -- Email content
    subject TEXT,
    sender_email VARCHAR(512),
    sender_name VARCHAR(512),
    recipients_to JSONB,
    recipients_cc JSONB,
    recipients_bcc JSONB,
    date_sent TIMESTAMP WITH TIME ZONE,
    date_received TIMESTAMP WITH TIME ZONE,
    body_text TEXT,
    body_html TEXT,
    
    -- Flags
    has_attachments BOOLEAN DEFAULT FALSE,
    is_read BOOLEAN DEFAULT FALSE,
    importance VARCHAR(20),
    
    -- Auto-tagging results
    matched_stakeholders JSONB,
    matched_keywords JSONB,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_messages_pst_file ON email_messages(pst_file_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_case ON email_messages(case_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_message_id ON email_messages(message_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_sender ON email_messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_email_messages_date ON email_messages(date_sent);
CREATE INDEX IF NOT EXISTS idx_email_messages_attachments ON email_messages(has_attachments) WHERE has_attachments = TRUE;

-- Email Attachments table
CREATE TABLE IF NOT EXISTS email_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_message_id UUID NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
    filename VARCHAR(512) NOT NULL,
    content_type VARCHAR(128),
    file_size INTEGER,
    s3_bucket VARCHAR(128) NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    has_been_ocred BOOLEAN DEFAULT FALSE,
    extracted_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_attachments_message ON email_attachments(email_message_id);
CREATE INDEX IF NOT EXISTS idx_email_attachments_ocr ON email_attachments(has_been_ocred) WHERE has_been_ocred = FALSE;

-- Stakeholders table
CREATE TABLE IF NOT EXISTS stakeholders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    role VARCHAR(255) NOT NULL,
    name VARCHAR(512) NOT NULL,
    email VARCHAR(512),
    organization VARCHAR(512),
    email_domain VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stakeholders_case ON stakeholders(case_id);
CREATE INDEX IF NOT EXISTS idx_stakeholders_project ON stakeholders(project_id);
CREATE INDEX IF NOT EXISTS idx_stakeholders_email ON stakeholders(email);
CREATE INDEX IF NOT EXISTS idx_stakeholders_domain ON stakeholders(email_domain);

-- Keywords table
CREATE TABLE IF NOT EXISTS keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    keyword_name VARCHAR(255) NOT NULL,
    variations TEXT,
    is_regex BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_keywords_case ON keywords(case_id);
CREATE INDEX IF NOT EXISTS idx_keywords_project ON keywords(project_id);

-- Programmes table (updated to align with PST analysis)
CREATE TABLE IF NOT EXISTS programmes_pst (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    programme_name VARCHAR(255) NOT NULL,
    programme_type VARCHAR(100) NOT NULL,
    programme_date TIMESTAMP WITH TIME ZONE,
    version_number VARCHAR(50),
    filename VARCHAR(512) NOT NULL,
    s3_bucket VARCHAR(128) NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    file_format VARCHAR(50),
    activities JSONB,
    critical_path JSONB,
    milestones JSONB,
    project_start TIMESTAMP WITH TIME ZONE,
    project_finish TIMESTAMP WITH TIME ZONE,
    notes TEXT,
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_programmes_pst_case ON programmes_pst(case_id);
CREATE INDEX IF NOT EXISTS idx_programmes_pst_project ON programmes_pst(project_id);
CREATE INDEX IF NOT EXISTS idx_programmes_pst_type ON programmes_pst(programme_type);

-- Delay Events table (updated to align with PST analysis)
CREATE TABLE IF NOT EXISTS delay_events_pst (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    as_planned_programme_id UUID REFERENCES programmes_pst(id) ON DELETE SET NULL,
    as_built_programme_id UUID REFERENCES programmes_pst(id) ON DELETE SET NULL,
    activity_id VARCHAR(255),
    activity_name VARCHAR(512),
    planned_start TIMESTAMP WITH TIME ZONE,
    actual_start TIMESTAMP WITH TIME ZONE,
    planned_finish TIMESTAMP WITH TIME ZONE,
    actual_finish TIMESTAMP WITH TIME ZONE,
    delay_days INTEGER,
    is_on_critical_path BOOLEAN DEFAULT FALSE,
    delay_cause TEXT,
    responsibility VARCHAR(255),
    notes TEXT,
    linked_correspondence_ids JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_delay_events_pst_case ON delay_events_pst(case_id);
CREATE INDEX IF NOT EXISTS idx_delay_events_pst_critical ON delay_events_pst(is_on_critical_path) WHERE is_on_critical_path = TRUE;

-- Comments for documentation
COMMENT ON TABLE projects IS 'Construction/engineering project management';
COMMENT ON TABLE pst_files IS 'Uploaded PST files for email forensics';
COMMENT ON TABLE email_messages IS 'Extracted email messages with forensic metadata';
COMMENT ON TABLE email_attachments IS 'Email attachments extracted from PST files';
COMMENT ON TABLE stakeholders IS 'Project/case stakeholders for auto-tagging';
COMMENT ON TABLE keywords IS 'Keywords for email auto-tagging';
COMMENT ON TABLE programmes_pst IS 'Construction programmes (Asta, MS Project)';
COMMENT ON TABLE delay_events_pst IS 'Delay events from programme variance analysis';

