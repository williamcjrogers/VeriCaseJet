-- Performance optimization indexes for VeriCase Analysis
-- Created: 2024-11-10

-- Case table indexes
CREATE INDEX IF NOT EXISTS idx_case_owner ON cases(owner_id);
CREATE INDEX IF NOT EXISTS idx_case_company ON cases(company_id);
CREATE INDEX IF NOT EXISTS idx_case_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_case_created_at ON cases(created_at);
CREATE INDEX IF NOT EXISTS idx_case_status_owner ON cases(status, owner_id);

-- Project table indexes  
CREATE INDEX IF NOT EXISTS idx_project_owner ON projects(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_project_code ON projects(project_code);
CREATE INDEX IF NOT EXISTS idx_project_analysis_type ON projects(analysis_type);
CREATE INDEX IF NOT EXISTS idx_project_created_at ON projects(created_at);

-- PSTFile table indexes
CREATE INDEX IF NOT EXISTS idx_pst_case ON pst_files(case_id);
CREATE INDEX IF NOT EXISTS idx_pst_project ON pst_files(project_id);
CREATE INDEX IF NOT EXISTS idx_pst_status ON pst_files(processing_status);
CREATE INDEX IF NOT EXISTS idx_pst_uploaded_by ON pst_files(uploaded_by);
CREATE INDEX IF NOT EXISTS idx_pst_case_status ON pst_files(case_id, processing_status);

-- EmailMessage table indexes (some already exist, adding missing ones)
CREATE INDEX IF NOT EXISTS idx_email_pst_file ON email_messages(pst_file_id);
CREATE INDEX IF NOT EXISTS idx_email_in_reply_to ON email_messages(in_reply_to);
CREATE INDEX IF NOT EXISTS idx_email_date_sent_desc ON email_messages(date_sent DESC);
CREATE INDEX IF NOT EXISTS idx_email_case_sender ON email_messages(case_id, sender_email);
CREATE INDEX IF NOT EXISTS idx_email_conversation ON email_messages(conversation_index);
CREATE INDEX IF NOT EXISTS idx_email_received ON email_messages(date_received);

-- EmailAttachment table indexes
CREATE INDEX IF NOT EXISTS idx_attachment_email ON email_attachments(email_message_id);
CREATE INDEX IF NOT EXISTS idx_attachment_ocr_status ON email_attachments(has_been_ocred);

-- Stakeholder table indexes
CREATE INDEX IF NOT EXISTS idx_stakeholder_case ON stakeholders(case_id);
CREATE INDEX IF NOT EXISTS idx_stakeholder_project ON stakeholders(project_id);
CREATE INDEX IF NOT EXISTS idx_stakeholder_email ON stakeholders(email);
CREATE INDEX IF NOT EXISTS idx_stakeholder_domain ON stakeholders(email_domain);
CREATE INDEX IF NOT EXISTS idx_stakeholder_case_email ON stakeholders(case_id, email);

-- Keyword table indexes
CREATE INDEX IF NOT EXISTS idx_keyword_case ON keywords(case_id);
CREATE INDEX IF NOT EXISTS idx_keyword_project ON keywords(project_id);
CREATE INDEX IF NOT EXISTS idx_keyword_name ON keywords(keyword_name);
CREATE INDEX IF NOT EXISTS idx_keyword_case_name ON keywords(case_id, keyword_name);

-- Document table indexes
CREATE INDEX IF NOT EXISTS idx_document_owner ON documents(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_document_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_document_workspace ON documents(workspace_type);
CREATE INDEX IF NOT EXISTS idx_document_accessed ON documents(last_accessed_at);

-- Folder table indexes
CREATE INDEX IF NOT EXISTS idx_folder_owner ON folders(owner_id);
CREATE INDEX IF NOT EXISTS idx_folder_is_root ON folders(is_root);

-- Programme table indexes
CREATE INDEX IF NOT EXISTS idx_programme_case ON programmes(case_id);
CREATE INDEX IF NOT EXISTS idx_programme_project ON programmes(project_id);
CREATE INDEX IF NOT EXISTS idx_programme_type ON programmes(programme_type);

-- Evidence table indexes
CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type);
CREATE INDEX IF NOT EXISTS idx_evidence_created_at ON evidence(created_at);

-- Issue table indexes
CREATE INDEX IF NOT EXISTS idx_issue_case ON issues(case_id);
CREATE INDEX IF NOT EXISTS idx_issue_status ON issues(status);
CREATE INDEX IF NOT EXISTS idx_issue_priority ON issues(priority);
CREATE INDEX IF NOT EXISTS idx_issue_raised_date ON issues(raised_date);

-- Claim table indexes
CREATE INDEX IF NOT EXISTS idx_claim_case ON claims(case_id);
CREATE INDEX IF NOT EXISTS idx_claim_type ON claims(claim_type);
CREATE INDEX IF NOT EXISTS idx_claim_status ON claims(status);

-- CaseUser table indexes
CREATE INDEX IF NOT EXISTS idx_case_user_case ON case_users(case_id);
CREATE INDEX IF NOT EXISTS idx_case_user_user ON case_users(user_id);
CREATE INDEX IF NOT EXISTS idx_case_user_role ON case_users(role);

-- DocVersion table indexes
CREATE INDEX IF NOT EXISTS idx_docversion_document ON doc_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_docversion_version ON doc_versions(version_number);
CREATE INDEX IF NOT EXISTS idx_docversion_created ON doc_versions(created_at);

-- SharedLink table indexes
CREATE INDEX IF NOT EXISTS idx_sharedlink_document ON shared_links(document_id);
CREATE INDEX IF NOT EXISTS idx_sharedlink_token ON shared_links(token);
CREATE INDEX IF NOT EXISTS idx_sharedlink_expires ON shared_links(expires_at);

-- Analyze tables to update statistics after creating indexes
ANALYZE cases;
ANALYZE projects;
ANALYZE pst_files;
ANALYZE email_messages;
ANALYZE email_attachments;
ANALYZE stakeholders;
ANALYZE keywords;
ANALYZE documents;
ANALYZE programmes;
ANALYZE evidence;
ANALYZE issues;
ANALYZE claims;
