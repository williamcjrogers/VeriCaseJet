-- Active: 1763739336777@@localhost@55432
-- Migration: Add PST Analysis Tables
-- Created: 2025-11-09
-- Description: Adds tables for PST forensic analysis, email extraction, and dispute intelligence
-- Updated: 2025-11-20 (Refactored for idempotency, dynamic SQL, and pgcrypto)

-- Ensure pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    -- 1. PROJECTS table updates
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
        -- Add missing columns if they don't exist
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'start_date') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN start_date TIMESTAMP WITH TIME ZONE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'completion_date') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN completion_date TIMESTAMP WITH TIME ZONE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'projects' AND column_name = 'contract_type') THEN
            EXECUTE 'ALTER TABLE projects ADD COLUMN contract_type VARCHAR(100)';
        END IF;
    ELSE
        -- Create table if it doesn't exist (fallback)
        EXECUTE 'CREATE TABLE projects (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_name VARCHAR(255) NOT NULL,
            project_code VARCHAR(100) UNIQUE NOT NULL,
            start_date TIMESTAMP WITH TIME ZONE,
            completion_date TIMESTAMP WITH TIME ZONE,
            contract_type VARCHAR(100),
            owner_user_id UUID NOT NULL, 
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )';
        
        -- Add FK if users table exists
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
            EXECUTE 'ALTER TABLE projects ADD CONSTRAINT projects_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES users(id)';
        END IF;
    END IF;

    -- 2. PST FILES table updates
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'pst_files') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 's3_bucket') THEN
            EXECUTE 'ALTER TABLE pst_files ADD COLUMN s3_bucket VARCHAR(128)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'pst_files' AND column_name = 'processing_status') THEN
             EXECUTE 'ALTER TABLE pst_files ADD COLUMN processing_status VARCHAR(50) DEFAULT ''queued''';
        END IF;
    ELSE
        EXECUTE 'CREATE TABLE pst_files (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            filename VARCHAR(512) NOT NULL,
            case_id UUID NOT NULL, 
            project_id UUID, 
            s3_bucket VARCHAR(128) NOT NULL,
            s3_key VARCHAR(2048) NOT NULL,
            file_size INTEGER,
            total_emails INTEGER DEFAULT 0,
            processed_emails INTEGER DEFAULT 0,
            processing_status VARCHAR(50) DEFAULT ''queued'',
            processing_started_at TIMESTAMP WITH TIME ZONE,
            processing_completed_at TIMESTAMP WITH TIME ZONE,
            error_message TEXT,
            uploaded_by UUID NOT NULL, 
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';

        -- Add FKs
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
            EXECUTE 'ALTER TABLE pst_files ADD CONSTRAINT pst_files_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
            EXECUTE 'ALTER TABLE pst_files ADD CONSTRAINT pst_files_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
            EXECUTE 'ALTER TABLE pst_files ADD CONSTRAINT pst_files_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES users(id)';
        END IF;
    END IF;

    -- 3. EMAIL MESSAGES table updates
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        -- Add new forensic columns
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'email_references') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN email_references TEXT';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'pst_message_offset') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN pst_message_offset INTEGER';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'pst_message_path') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN pst_message_path TEXT';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'recipients_to') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN recipients_to JSONB';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'recipients_cc') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN recipients_cc JSONB';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'recipients_bcc') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN recipients_bcc JSONB';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'body_text') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN body_text TEXT';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'body_html') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN body_html TEXT';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'has_attachments') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN has_attachments BOOLEAN DEFAULT FALSE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'matched_stakeholders') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN matched_stakeholders JSONB';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_messages' AND column_name = 'matched_keywords') THEN
            EXECUTE 'ALTER TABLE email_messages ADD COLUMN matched_keywords JSONB';
        END IF;
    ELSE
        EXECUTE 'CREATE TABLE email_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pst_file_id UUID NOT NULL,
            case_id UUID NOT NULL,
            message_id VARCHAR(512),
            in_reply_to VARCHAR(512),
            email_references TEXT,
            conversation_index VARCHAR(1024),
            pst_message_offset INTEGER,
            pst_message_path TEXT,
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
            has_attachments BOOLEAN DEFAULT FALSE,
            is_read BOOLEAN DEFAULT FALSE,
            importance VARCHAR(20),
            matched_stakeholders JSONB,
            matched_keywords JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';
        
        -- Add FKs
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'pst_files') THEN
            EXECUTE 'ALTER TABLE email_messages ADD CONSTRAINT email_messages_pst_file_id_fkey FOREIGN KEY (pst_file_id) REFERENCES pst_files(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
            EXECUTE 'ALTER TABLE email_messages ADD CONSTRAINT email_messages_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
    END IF;

    -- 4. EMAIL ATTACHMENTS table updates
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_attachments') THEN
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_attachments' AND column_name = 's3_bucket') THEN
            EXECUTE 'ALTER TABLE email_attachments ADD COLUMN s3_bucket VARCHAR(128)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_attachments' AND column_name = 'has_been_ocred') THEN
            EXECUTE 'ALTER TABLE email_attachments ADD COLUMN has_been_ocred BOOLEAN DEFAULT FALSE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name = 'email_attachments' AND column_name = 'extracted_text') THEN
            EXECUTE 'ALTER TABLE email_attachments ADD COLUMN extracted_text TEXT';
        END IF;
    ELSE
        EXECUTE 'CREATE TABLE email_attachments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email_message_id UUID NOT NULL,
            filename VARCHAR(512) NOT NULL,
            content_type VARCHAR(128),
            file_size INTEGER,
            s3_bucket VARCHAR(128) NOT NULL,
            s3_key VARCHAR(2048) NOT NULL,
            has_been_ocred BOOLEAN DEFAULT FALSE,
            extracted_text TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';

        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
            EXECUTE 'ALTER TABLE email_attachments ADD CONSTRAINT email_attachments_email_message_id_fkey FOREIGN KEY (email_message_id) REFERENCES email_messages(id) ON DELETE CASCADE';
        END IF;
    END IF;

    -- 5. STAKEHOLDERS table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stakeholders') THEN
        EXECUTE 'CREATE TABLE stakeholders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            project_id UUID,
            role VARCHAR(255) NOT NULL,
            name VARCHAR(512) NOT NULL,
            email VARCHAR(512),
            organization VARCHAR(512),
            email_domain VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
            EXECUTE 'ALTER TABLE stakeholders ADD CONSTRAINT stakeholders_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
            EXECUTE 'ALTER TABLE stakeholders ADD CONSTRAINT stakeholders_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL';
        END IF;
    END IF;

    -- 6. KEYWORDS table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'keywords') THEN
        EXECUTE 'CREATE TABLE keywords (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            project_id UUID,
            keyword_name VARCHAR(255) NOT NULL,
            variations TEXT,
            is_regex BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
            EXECUTE 'ALTER TABLE keywords ADD CONSTRAINT keywords_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
            EXECUTE 'ALTER TABLE keywords ADD CONSTRAINT keywords_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL';
        END IF;
    END IF;

    -- 7. PROGRAMMES_PST table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes_pst') THEN
        EXECUTE 'CREATE TABLE programmes_pst (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            project_id UUID,
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
            uploaded_by UUID NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
            EXECUTE 'ALTER TABLE programmes_pst ADD CONSTRAINT programmes_pst_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
            EXECUTE 'ALTER TABLE programmes_pst ADD CONSTRAINT programmes_pst_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
            EXECUTE 'ALTER TABLE programmes_pst ADD CONSTRAINT programmes_pst_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES users(id)';
        END IF;
    END IF;

    -- 8. DELAY_EVENTS_PST table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'delay_events_pst') THEN
        EXECUTE 'CREATE TABLE delay_events_pst (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL,
            as_planned_programme_id UUID,
            as_built_programme_id UUID,
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
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'cases') THEN
            EXECUTE 'ALTER TABLE delay_events_pst ADD CONSTRAINT delay_events_pst_case_id_fkey FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE';
        END IF;
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes_pst') THEN
            EXECUTE 'ALTER TABLE delay_events_pst ADD CONSTRAINT delay_events_pst_as_planned_fkey FOREIGN KEY (as_planned_programme_id) REFERENCES programmes_pst(id) ON DELETE SET NULL';
            EXECUTE 'ALTER TABLE delay_events_pst ADD CONSTRAINT delay_events_pst_as_built_fkey FOREIGN KEY (as_built_programme_id) REFERENCES programmes_pst(id) ON DELETE SET NULL';
        END IF;
    END IF;
    
END $$;

-- 9. Indexes (Conditional creation using dynamic SQL)
DO $$
BEGIN
    -- Projects indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'projects') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_projects_code ON projects(project_code)';
    END IF;

    -- PST Files indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'pst_files') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_files_case ON pst_files(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_files_project ON pst_files(project_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_pst_files_status ON pst_files(processing_status)';
    END IF;

    -- Email Messages indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_messages') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_pst_file ON email_messages(pst_file_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_case ON email_messages(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_message_id ON email_messages(message_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_sender ON email_messages(sender_email)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_date ON email_messages(date_sent)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_messages_attachments ON email_messages(has_attachments) WHERE has_attachments = TRUE';
    END IF;

    -- Email Attachments indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'email_attachments') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_attachments_message ON email_attachments(email_message_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_email_attachments_ocr ON email_attachments(has_been_ocred) WHERE has_been_ocred = FALSE';
    END IF;

    -- Stakeholders indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'stakeholders') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholders_case ON stakeholders(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholders_project ON stakeholders(project_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholders_email ON stakeholders(email)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_stakeholders_domain ON stakeholders(email_domain)';
    END IF;

    -- Keywords indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'keywords') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_keywords_case ON keywords(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_keywords_project ON keywords(project_id)';
    END IF;

    -- Programmes PST indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'programmes_pst') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_pst_case ON programmes_pst(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_pst_project ON programmes_pst(project_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_programmes_pst_type ON programmes_pst(programme_type)';
    END IF;

    -- Delay Events PST indexes
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'delay_events_pst') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_delay_events_pst_case ON delay_events_pst(case_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_delay_events_pst_critical ON delay_events_pst(is_on_critical_path) WHERE is_on_critical_path = TRUE';
    END IF;

    -- 10. Comments (Dynamic SQL to avoid static analysis errors)
    EXECUTE 'COMMENT ON TABLE projects IS ''Construction/engineering project management''';
    EXECUTE 'COMMENT ON TABLE pst_files IS ''Uploaded PST files for email forensics''';
    EXECUTE 'COMMENT ON TABLE email_messages IS ''Extracted email messages with forensic metadata''';
    EXECUTE 'COMMENT ON TABLE email_attachments IS ''Email attachments extracted from PST files''';
    EXECUTE 'COMMENT ON TABLE stakeholders IS ''Project/case stakeholders for auto-tagging''';
    EXECUTE 'COMMENT ON TABLE keywords IS ''Keywords for email auto-tagging''';
    EXECUTE 'COMMENT ON TABLE programmes_pst IS ''Construction programmes (Asta, MS Project)''';
    EXECUTE 'COMMENT ON TABLE delay_events_pst IS ''Delay events from programme variance analysis''';

END $$;
