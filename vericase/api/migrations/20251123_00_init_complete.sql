-- Consolidated Initial Schema for VeriCase
-- Matches models.py as of 2025-11-23

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- For text search

-- ========================================
-- Core Auth & User Management
-- ========================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'EDITOR',
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    display_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Enhanced security fields
    email_verified BOOLEAN DEFAULT FALSE,
    verification_token VARCHAR(255),
    reset_token VARCHAR(255),
    reset_token_expires TIMESTAMP WITH TIME ZONE,
    failed_login_attempts INTEGER DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    last_failed_attempt TIMESTAMP WITH TIME ZONE,
    password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);

CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_jti VARCHAR(255) NOT NULL UNIQUE,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_sessions_jti ON user_sessions(token_jti);

CREATE TABLE password_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE login_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    ip_address VARCHAR(45),
    user_agent TEXT,
    success BOOLEAN NOT NULL,
    failure_reason VARCHAR(100),
    attempted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_login_attempts_email ON login_attempts(email);

-- ========================================
-- Multi-Tenancy & Structure
-- ========================================

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE,
    subscription_tier VARCHAR(50) DEFAULT 'professional',
    storage_limit_gb INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT TRUE,
    logo_url VARCHAR(500),
    primary_color VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_companies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role VARCHAR(50) DEFAULT 'user',
    is_primary BOOLEAN DEFAULT FALSE,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- Case Management
-- ========================================

CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_number VARCHAR(100) UNIQUE NOT NULL,
    case_id_custom VARCHAR(100),
    name VARCHAR(500) NOT NULL,
    description TEXT,
    project_name VARCHAR(500),
    contract_type VARCHAR(100),
    dispute_type VARCHAR(100),
    status VARCHAR(50) DEFAULT 'active',
    case_status VARCHAR(50),
    resolution_route VARCHAR(100),
    claimant VARCHAR(255),
    defendant VARCHAR(255),
    client VARCHAR(255),
    legal_team JSON,
    heads_of_claim JSON,
    deadlines JSON,
    owner_id UUID NOT NULL REFERENCES users(id),
    company_id UUID NOT NULL REFERENCES companies(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_cases_case_number ON cases(case_number);
CREATE INDEX idx_cases_case_id_custom ON cases(case_id_custom);

CREATE TABLE case_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) DEFAULT 'viewer',
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    added_by_id UUID REFERENCES users(id)
);

-- ========================================
-- Projects (PST Analysis Container)
-- ========================================

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_name VARCHAR(255) NOT NULL,
    project_code VARCHAR(100) UNIQUE NOT NULL,
    start_date TIMESTAMP WITH TIME ZONE,
    completion_date TIMESTAMP WITH TIME ZONE,
    contract_type VARCHAR(100),
    analysis_type VARCHAR(50) DEFAULT 'project',
    project_aliases TEXT,
    site_address TEXT,
    include_domains TEXT,
    exclude_people TEXT,
    project_terms TEXT,
    exclude_keywords TEXT,
    metadata JSON DEFAULT '{}',
    owner_user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- PST & Email Forensics
-- ========================================

CREATE TABLE pst_files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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
    uploaded_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE email_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pst_file_id UUID NOT NULL REFERENCES pst_files(id) ON DELETE CASCADE,
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    
    -- Metadata
    message_id VARCHAR(512),
    in_reply_to VARCHAR(512),
    email_references TEXT,
    conversation_index VARCHAR(1024),
    thread_id VARCHAR(100),
    
    -- PST specific
    pst_message_offset INTEGER,
    pst_message_path TEXT,
    
    -- Content
    subject TEXT,
    sender_email VARCHAR(512),
    sender_name VARCHAR(512),
    recipients_to JSON,
    recipients_cc JSON,
    recipients_bcc JSON,
    date_sent TIMESTAMP WITH TIME ZONE,
    date_received TIMESTAMP WITH TIME ZONE,
    body_text TEXT,
    body_html TEXT,
    
    -- Flags & Status
    has_attachments BOOLEAN DEFAULT FALSE,
    is_read BOOLEAN DEFAULT FALSE,
    importance VARCHAR(20),
    
    -- Analysis
    matched_stakeholders JSONB,
    matched_keywords JSONB,
    
    -- Storage
    body_preview TEXT,
    body_full_s3_key VARCHAR(512),
    metadata JSON DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_email_message_id ON email_messages(message_id);
CREATE INDEX idx_email_sender ON email_messages(sender_email);
CREATE INDEX idx_email_date_sent ON email_messages(date_sent);
CREATE INDEX idx_email_thread_id ON email_messages(thread_id);
CREATE INDEX idx_email_case_id ON email_messages(case_id);
CREATE INDEX idx_email_project_id ON email_messages(project_id);

CREATE TABLE email_attachments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email_message_id UUID NOT NULL REFERENCES email_messages(id) ON DELETE CASCADE,
    filename VARCHAR(512) NOT NULL,
    content_type VARCHAR(128),
    file_size INTEGER,
    s3_bucket VARCHAR(128) NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    has_been_ocred BOOLEAN DEFAULT FALSE,
    extracted_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- Analysis & Aux Tables
-- ========================================

CREATE TABLE stakeholders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    role VARCHAR(255) NOT NULL,
    name VARCHAR(512) NOT NULL,
    email VARCHAR(512),
    organization VARCHAR(512),
    email_domain VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE keywords (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    keyword_name VARCHAR(255) NOT NULL,
    variations TEXT,
    is_regex BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE programmes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    programme_name VARCHAR(255) NOT NULL,
    programme_type VARCHAR(100) NOT NULL,
    programme_date TIMESTAMP WITH TIME ZONE,
    version_number VARCHAR(50),
    filename VARCHAR(512) NOT NULL,
    s3_bucket VARCHAR(128) NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    file_format VARCHAR(50),
    activities JSON,
    critical_path JSON,
    milestones JSON,
    project_start TIMESTAMP WITH TIME ZONE,
    project_finish TIMESTAMP WITH TIME ZONE,
    notes TEXT,
    uploaded_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_settings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key VARCHAR(128) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Basic Documents & Folders (Legacy support)
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename VARCHAR(512) NOT NULL,
    path VARCHAR(1024),
    content_type VARCHAR(128),
    size INTEGER,
    bucket VARCHAR(128) NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    status VARCHAR(50) DEFAULT 'NEW',
    title VARCHAR(512),
    metadata JSON,
    text_excerpt TEXT,
    owner_user_id UUID REFERENCES users(id),
    last_accessed_at TIMESTAMP WITH TIME ZONE,
    last_accessed_by UUID REFERENCES users(id),
    is_private BOOLEAN DEFAULT FALSE,
    workspace_type VARCHAR(20) DEFAULT 'shared',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE folders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path VARCHAR(1024) NOT NULL,
    name VARCHAR(255) NOT NULL,
    parent_path VARCHAR(1024),
    owner_user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE share_links (
    token VARCHAR(64) PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    password_hash VARCHAR(255)
);

CREATE TABLE user_invitations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    invited_by UUID NOT NULL REFERENCES users(id),
    role VARCHAR(50) DEFAULT 'VIEWER',
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_shares (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id),
    shared_by UUID NOT NULL REFERENCES users(id),
    shared_with UUID NOT NULL REFERENCES users(id),
    permission VARCHAR(20) DEFAULT 'view',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE folder_shares (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    folder_path VARCHAR(500) NOT NULL,
    owner_id UUID NOT NULL REFERENCES users(id),
    shared_by UUID NOT NULL REFERENCES users(id),
    shared_with UUID NOT NULL REFERENCES users(id),
    permission VARCHAR(20) DEFAULT 'view',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE favorites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    document_id UUID NOT NULL REFERENCES documents(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id),
    version_number INTEGER NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    filename VARCHAR(512) NOT NULL,
    size INTEGER,
    content_type VARCHAR(128),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    comment TEXT
);

CREATE TABLE claims (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id),
    claim_type VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    claimed_amount INTEGER,
    currency VARCHAR(10) DEFAULT 'GBP',
    claim_date TIMESTAMP WITH TIME ZONE,
    response_due_date TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) DEFAULT 'draft',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE issues (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    issue_type VARCHAR(100),
    status VARCHAR(50) DEFAULT 'open',
    relevant_contract_clauses JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id),
    document_id UUID NOT NULL REFERENCES documents(id),
    issue_id UUID REFERENCES issues(id),
    evidence_type VARCHAR(100),
    exhibit_number VARCHAR(50),
    date_of_evidence TIMESTAMP WITH TIME ZONE,
    
    -- Email metadata copy for search/filtering
    email_from VARCHAR(255),
    email_to VARCHAR(500),
    email_cc VARCHAR(500),
    email_subject VARCHAR(500),
    email_date TIMESTAMP WITH TIME ZONE,
    email_message_id VARCHAR(500),
    email_in_reply_to VARCHAR(500),
    email_thread_topic VARCHAR(500),
    email_conversation_index VARCHAR(500),
    thread_id VARCHAR(100),
    
    content TEXT,
    content_type VARCHAR(50),
    attachments JSONB,
    relevance_score INTEGER,
    notes TEXT,
    metadata JSON,
    
    as_planned_date TIMESTAMP WITHOUT TIME ZONE,
    as_planned_activity VARCHAR(500),
    as_built_date TIMESTAMP WITHOUT TIME ZONE,
    as_built_activity VARCHAR(500),
    delay_days INTEGER DEFAULT 0,
    is_critical_path BOOLEAN DEFAULT FALSE,
    
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    added_by_id UUID REFERENCES users(id)
);

CREATE TABLE chronology_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id),
    claim_id UUID REFERENCES claims(id),
    event_date TIMESTAMP WITH TIME ZONE NOT NULL,
    event_type VARCHAR(100),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    evidence_ids JSON,
    parties_involved JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE rebuttals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    issue_id UUID NOT NULL REFERENCES issues(id),
    title VARCHAR(500) NOT NULL,
    argument TEXT NOT NULL,
    counter_argument TEXT,
    supporting_evidence_ids JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE contract_clauses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id),
    document_id UUID NOT NULL REFERENCES documents(id),
    clause_id VARCHAR(50) NOT NULL,
    clause_text TEXT NOT NULL,
    clause_title VARCHAR(500),
    parent_clause_id VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE search_queries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    company_id UUID REFERENCES companies(id),
    case_id UUID REFERENCES cases(id),
    query_text VARCHAR(1000) NOT NULL,
    query_type VARCHAR(50),
    filters_applied JSON,
    results_count INTEGER,
    execution_time_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE delay_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID NOT NULL REFERENCES cases(id),
    as_planned_programme_id UUID REFERENCES programmes(id),
    as_built_programme_id UUID REFERENCES programmes(id),
    activity_id VARCHAR(100),
    activity_name VARCHAR(500),
    planned_start TIMESTAMP WITH TIME ZONE,
    actual_start TIMESTAMP WITH TIME ZONE,
    planned_finish TIMESTAMP WITH TIME ZONE,
    actual_finish TIMESTAMP WITH TIME ZONE,
    delay_days INTEGER,
    delay_type VARCHAR(50),
    is_on_critical_path BOOLEAN DEFAULT FALSE,
    delay_cause VARCHAR(100),
    description TEXT,
    linked_correspondence_ids JSON,
    linked_issue_id UUID REFERENCES issues(id),
    eot_entitlement_days INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by_id UUID REFERENCES users(id)
);

