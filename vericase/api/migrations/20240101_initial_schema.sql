-- Initial database schema
-- This establishes the base tables and types for the PST Analysis Engine

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create ENUM types
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'user', 'analyst', 'viewer');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE case_status AS ENUM ('active', 'pending', 'closed', 'archived');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE processing_status AS ENUM ('pending', 'processing', 'completed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    role user_role DEFAULT 'user',
    company_id UUID REFERENCES companies(id),
    email_verified BOOLEAN DEFAULT FALSE,
    verification_token VARCHAR(255),
    verification_token_expires TIMESTAMP,
    reset_token VARCHAR(255),
    reset_token_expires TIMESTAMP,
    last_login TIMESTAMP,
    failed_login_attempts INTEGER DEFAULT 0,
    account_locked_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code VARCHAR(100) UNIQUE NOT NULL,
    project_name VARCHAR(255) NOT NULL,
    description TEXT,
    owner_user_id UUID REFERENCES users(id),
    company_id UUID REFERENCES companies(id),
    analysis_type VARCHAR(50),
    status VARCHAR(50) DEFAULT 'active',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cases table
CREATE TABLE IF NOT EXISTS cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id_custom VARCHAR(100) UNIQUE,
    case_name VARCHAR(255) NOT NULL,
    description TEXT,
    owner_id UUID REFERENCES users(id),
    company_id UUID REFERENCES companies(id),
    project_id UUID REFERENCES projects(id),
    status case_status DEFAULT 'active',
    case_type VARCHAR(100),
    case_value DECIMAL(15,2),
    jurisdiction VARCHAR(100),
    court_reference VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- PST files table
CREATE TABLE IF NOT EXISTS pst_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    project_id UUID REFERENCES projects(id),
    filename VARCHAR(500) NOT NULL,
    s3_key VARCHAR(1000) NOT NULL,
    file_size_bytes BIGINT,
    processing_status processing_status DEFAULT 'pending',
    uploaded_by UUID REFERENCES users(id),
    total_emails INTEGER DEFAULT 0,
    processed_emails INTEGER DEFAULT 0,
    error_message TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_started_at TIMESTAMP,
    processing_completed_at TIMESTAMP
);

-- Email messages table
CREATE TABLE IF NOT EXISTS email_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pst_file_id UUID REFERENCES pst_files(id) ON DELETE CASCADE,
    case_id UUID REFERENCES cases(id),
    project_id UUID REFERENCES projects(id),
    message_id VARCHAR(500),
    conversation_id VARCHAR(255),
    conversation_index VARCHAR(500),
    thread_id VARCHAR(255),
    in_reply_to VARCHAR(500),
    subject TEXT,
    sender_name VARCHAR(255),
    sender_email VARCHAR(255),
    recipients_to TEXT[],
    recipients_cc TEXT[],
    recipients_bcc TEXT[],
    date_sent TIMESTAMP,
    date_received TIMESTAMP,
    body_text TEXT,
    body_html TEXT,
    has_attachments BOOLEAN DEFAULT FALSE,
    attachment_count INTEGER DEFAULT 0,
    importance VARCHAR(20),
    message_class VARCHAR(100),
    matched_stakeholders TEXT[],
    matched_keywords TEXT[],
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Email attachments table
CREATE TABLE IF NOT EXISTS email_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_message_id UUID REFERENCES email_messages(id) ON DELETE CASCADE,
    filename VARCHAR(500),
    content_type VARCHAR(100),
    file_size_bytes INTEGER,
    s3_key VARCHAR(1000),
    has_been_ocred BOOLEAN DEFAULT FALSE,
    ocr_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Stakeholders table
CREATE TABLE IF NOT EXISTS stakeholders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    project_id UUID REFERENCES projects(id),
    name VARCHAR(255),
    email VARCHAR(255),
    email_domain VARCHAR(255),
    role VARCHAR(100),
    organization VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Keywords table
CREATE TABLE IF NOT EXISTS keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    project_id UUID REFERENCES projects(id),
    keyword_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    is_regex BOOLEAN DEFAULT FALSE,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    content TEXT,
    owner_user_id UUID REFERENCES users(id),
    case_id UUID REFERENCES cases(id),
    project_id UUID REFERENCES projects(id),
    workspace_type VARCHAR(50) DEFAULT 'private',
    is_private BOOLEAN DEFAULT TRUE,
    status VARCHAR(50) DEFAULT 'draft',
    last_accessed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Folders table
CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    path TEXT NOT NULL UNIQUE,
    parent_path TEXT,
    owner_id UUID REFERENCES users(id),
    owner_user_id UUID REFERENCES users(id),
    is_root BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Document versions table
CREATE TABLE IF NOT EXISTS doc_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Programmes table
CREATE TABLE IF NOT EXISTS programmes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    project_id UUID REFERENCES projects(id),
    programme_name VARCHAR(255) NOT NULL,
    programme_type VARCHAR(100),
    file_s3_key VARCHAR(1000),
    uploaded_by UUID REFERENCES users(id),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Evidence table
CREATE TABLE IF NOT EXISTS evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    evidence_type VARCHAR(100),
    description TEXT,
    s3_key VARCHAR(1000),
    as_planned_date DATE,
    as_built_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Issues table
CREATE TABLE IF NOT EXISTS issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    issue_id UUID REFERENCES issues(id),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(50),
    priority VARCHAR(50),
    raised_by UUID REFERENCES users(id),
    raised_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Claims table
CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    claim_type VARCHAR(100),
    amount DECIMAL(15,2),
    status VARCHAR(50),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Case users junction table
CREATE TABLE IF NOT EXISTS case_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, user_id)
);

-- Share links table
CREATE TABLE IF NOT EXISTS share_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    created_by UUID REFERENCES users(id),
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Shared links table (alternative naming)
CREATE TABLE IF NOT EXISTS shared_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    token VARCHAR(255) UNIQUE NOT NULL,
    created_by UUID REFERENCES users(id),
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type VARCHAR(100) NOT NULL,
    status processing_status DEFAULT 'pending',
    user_id UUID REFERENCES users(id),
    company_id UUID REFERENCES companies(id),
    payload JSONB,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- Favorites table
CREATE TABLE IF NOT EXISTS favorites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, document_id)
);

-- Audit logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id UUID,
    details JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(500) UNIQUE NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_company_id ON users(company_id);
CREATE INDEX IF NOT EXISTS idx_projects_owner_user_id ON projects(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_projects_company_id ON projects(company_id);
CREATE INDEX IF NOT EXISTS idx_cases_owner_id ON cases(owner_id);
CREATE INDEX IF NOT EXISTS idx_cases_company_id ON cases(company_id);
CREATE INDEX IF NOT EXISTS idx_cases_project_id ON cases(project_id);
CREATE INDEX IF NOT EXISTS idx_pst_files_case_id ON pst_files(case_id);
CREATE INDEX IF NOT EXISTS idx_pst_files_project_id ON pst_files(project_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_pst_file_id ON email_messages(pst_file_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_case_id ON email_messages(case_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_project_id ON email_messages(project_id);
CREATE INDEX IF NOT EXISTS idx_email_messages_sender_email ON email_messages(sender_email);
CREATE INDEX IF NOT EXISTS idx_email_messages_date_sent ON email_messages(date_sent);
CREATE INDEX IF NOT EXISTS idx_email_attachments_email_message_id ON email_attachments(email_message_id);
CREATE INDEX IF NOT EXISTS idx_stakeholders_case_id ON stakeholders(case_id);
CREATE INDEX IF NOT EXISTS idx_stakeholders_project_id ON stakeholders(project_id);
CREATE INDEX IF NOT EXISTS idx_stakeholders_email ON stakeholders(email);
CREATE INDEX IF NOT EXISTS idx_keywords_case_id ON keywords(case_id);
CREATE INDEX IF NOT EXISTS idx_keywords_project_id ON keywords(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_owner_user_id ON documents(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_documents_case_id ON documents(case_id);
CREATE INDEX IF NOT EXISTS idx_documents_project_id ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_folders_owner_id ON folders(owner_id);
CREATE INDEX IF NOT EXISTS idx_folders_parent_path ON folders(parent_path);
CREATE INDEX IF NOT EXISTS idx_programmes_case_id ON programmes(case_id);
CREATE INDEX IF NOT EXISTS idx_programmes_project_id ON programmes(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_case_id ON evidence(case_id);
CREATE INDEX IF NOT EXISTS idx_issues_case_id ON issues(case_id);
CREATE INDEX IF NOT EXISTS idx_claims_case_id ON claims(case_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_type_id ON audit_logs(resource_type, resource_id);

-- Text search indexes
CREATE INDEX IF NOT EXISTS idx_email_messages_subject_trgm ON email_messages USING gin(subject gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_email_messages_body_text_trgm ON email_messages USING gin(body_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_stakeholders_name_trgm ON stakeholders USING gin(name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_documents_title_trgm ON documents USING gin(title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_documents_content_trgm ON documents USING gin(content gin_trgm_ops);
