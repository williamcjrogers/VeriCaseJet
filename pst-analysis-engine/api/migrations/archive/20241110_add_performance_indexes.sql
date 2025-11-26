-- Performance optimization indexes for VeriCase Analysis
-- Created: 2024-11-10

-- Performance optimization indexes for VeriCase Analysis
-- Created: 2024-11-10
-- Updated to be idempotent and schema-aware

DO $$
BEGIN
    -- Case table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_owner ON cases(owner_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_company ON cases(company_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_status ON cases(status)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_created_at ON cases(created_at)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_status_owner ON cases(status, owner_id)';
    END IF;

    -- Project table indexes  
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_owner ON projects(owner_user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_code ON projects(project_code)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_analysis_type ON projects(analysis_type)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_project_created_at ON projects(created_at)';
    END IF;

    -- PSTFile table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'pst_files') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_case ON pst_files(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_project ON pst_files(project_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_status ON pst_files(processing_status)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_uploaded_by ON pst_files(uploaded_by)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_case_status ON pst_files(case_id, processing_status)';
    END IF;

    -- EmailMessage table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_pst_file ON email_messages(pst_file_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_in_reply_to ON email_messages(in_reply_to)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_date_sent_desc ON email_messages(date_sent DESC)';
        
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='case_id') AND
           EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='sender_email') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_case_sender ON email_messages(case_id, sender_email)';
        END IF;
        
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='conversation_index') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_conversation ON email_messages(conversation_index)';
        END IF;
        
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_messages' AND column_name='date_received') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_received ON email_messages(date_received)';
        END IF;
    END IF;

    -- EmailAttachment table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_attachments') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_attachment_email ON email_attachments(email_message_id)';
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='email_attachments' AND column_name='has_been_ocred') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_attachment_ocr_status ON email_attachments(has_been_ocred)';
        END IF;
    END IF;

    -- Stakeholder table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stakeholders') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholder_case ON stakeholders(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholder_project ON stakeholders(project_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholder_email ON stakeholders(email)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholder_domain ON stakeholders(email_domain)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholder_case_email ON stakeholders(case_id, email)';
    END IF;

    -- Keyword table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'keywords') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_keyword_case ON keywords(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_keyword_project ON keywords(project_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_keyword_name ON keywords(keyword_name)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_keyword_case_name ON keywords(case_id, keyword_name)';
    END IF;

    -- Document table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'documents') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_document_owner ON documents(owner_user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_document_status ON documents(status)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_document_workspace ON documents(workspace_type)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_document_accessed ON documents(last_accessed_at)';
    END IF;

    -- Folder table indexes (2025+ feature)
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'folders') THEN
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='folders' AND column_name='owner_user_id') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folder_owner ON folders(owner_user_id)';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='folders' AND column_name='is_root') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_folder_is_root ON folders(is_root)';
        END IF;
    END IF;

    -- Programme table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programme_case ON programmes(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programme_project ON programmes(project_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programme_type ON programmes(programme_type)';
    END IF;

    -- Evidence table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'evidence') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type)';
        -- Handle column name change (created_at vs added_at)
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='created_at') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_evidence_created_at ON evidence(created_at)';
        ELSIF EXISTS (SELECT FROM information_schema.columns WHERE table_name='evidence' AND column_name='added_at') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_evidence_added_at ON evidence(added_at)';
        END IF;
    END IF;

    -- Issue table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'issues') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_issue_case ON issues(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_issue_status ON issues(status)';
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='issues' AND column_name='priority') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_issue_priority ON issues(priority)';
        END IF;
        IF EXISTS (SELECT FROM information_schema.columns WHERE table_name='issues' AND column_name='raised_date') THEN
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_issue_raised_date ON issues(raised_date)';
        END IF;
    END IF;

    -- Claim table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'claims') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_claim_case ON claims(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_claim_type ON claims(claim_type)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_claim_status ON claims(status)';
    END IF;

    -- CaseUser table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_users') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_user_case ON case_users(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_user_user ON case_users(user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_case_user_role ON case_users(role)';
    END IF;

    -- DocVersion table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'doc_versions') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_docversion_document ON doc_versions(document_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_docversion_version ON doc_versions(version_number)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_docversion_created ON doc_versions(created_at)';
    END IF;

    -- SharedLink table indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'shared_links') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sharedlink_document ON shared_links(document_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sharedlink_token ON shared_links(token)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sharedlink_expires ON shared_links(expires_at)';
    END IF;

END $$;

-- Analyze tables to update statistics after creating indexes (if they exist)
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='cases') THEN ANALYZE cases; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='projects') THEN ANALYZE projects; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='pst_files') THEN ANALYZE pst_files; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='email_messages') THEN ANALYZE email_messages; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='email_attachments') THEN ANALYZE email_attachments; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='stakeholders') THEN ANALYZE stakeholders; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='keywords') THEN ANALYZE keywords; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='documents') THEN ANALYZE documents; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='programmes') THEN ANALYZE programmes; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='evidence') THEN ANALYZE evidence; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='issues') THEN ANALYZE issues; END IF; END $$;
DO $$ BEGIN IF EXISTS (SELECT FROM pg_tables WHERE tablename='claims') THEN ANALYZE claims; END IF; END $$;

