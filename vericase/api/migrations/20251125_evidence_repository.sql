-- Evidence Repository Schema
-- Creates a case-independent evidence management system with intelligent linking
-- Migration: 20251125_evidence_repository.sql

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

-- Evidence type classification
DO $$ BEGIN
    CREATE TYPE evidence_type AS ENUM (
        'contract', 'variation', 'drawing', 'specification', 'programme',
        'invoice', 'payment_certificate', 'meeting_minutes', 'site_instruction',
        'rfi', 'notice', 'letter', 'email', 'photo', 'expert_report',
        'claim', 'eot_notice', 'delay_notice', 'progress_report',
        'quality_record', 'other'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Document category (construction-specific)
DO $$ BEGIN
    CREATE TYPE document_category AS ENUM (
        'jct_relevant_event', 'jct_extension_time', 'jct_loss_expense',
        'nec_compensation_event', 'nec_early_warning',
        'fidic_claim', 'fidic_variation',
        'contemporaneous', 'retrospective', 'witness_statement',
        'technical', 'financial', 'legal', 'correspondence', 'other'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Evidence source type
DO $$ BEGIN
    CREATE TYPE evidence_source_type AS ENUM (
        'pst_attachment', 'direct_upload', 'bulk_import', 
        'email_export', 'scan', 'api', 'migration'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Link type for correspondence
DO $$ BEGIN
    CREATE TYPE correspondence_link_type AS ENUM (
        'attachment', 'mentioned', 'related', 'same_thread', 
        'reply_to', 'forwards', 'references'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Relation type between evidence items
DO $$ BEGIN
    CREATE TYPE evidence_relation_type AS ENUM (
        'supersedes', 'references', 'responds_to', 'amends', 
        'duplicate', 'version_of', 'related', 'contradicts'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Processing status
DO $$ BEGIN
    CREATE TYPE evidence_processing_status AS ENUM (
        'pending', 'processing', 'ready', 'failed', 'archived'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- EVIDENCE SOURCES TABLE
-- Track provenance of evidence (PST files, bulk imports, etc.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source identification
    source_type VARCHAR(50) NOT NULL,
    source_name VARCHAR(500) NOT NULL,
    source_path TEXT,
    source_description TEXT,
    
    -- For PST files (optional link)
    pst_file_id UUID REFERENCES pst_files(id) ON DELETE SET NULL,
    
    -- Original file storage (for imports/uploads)
    original_s3_bucket VARCHAR(128),
    original_s3_key VARCHAR(2048),
    original_hash VARCHAR(128),
    original_size BIGINT,
    
    -- Processing statistics
    total_items INTEGER DEFAULT 0,
    processed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    duplicate_items INTEGER DEFAULT 0,
    
    -- Processing status
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Optional associations (evidence can exist without case/project)
    case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    
    -- Audit
    uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_evidence_sources_status ON evidence_sources(status);
CREATE INDEX IF NOT EXISTS idx_evidence_sources_type ON evidence_sources(source_type);
CREATE INDEX IF NOT EXISTS idx_evidence_sources_case ON evidence_sources(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_sources_project ON evidence_sources(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_sources_pst ON evidence_sources(pst_file_id);

-- ============================================================================
-- EVIDENCE COLLECTIONS TABLE
-- Virtual folders for organizing evidence
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Collection info
    name VARCHAR(255) NOT NULL,
    description TEXT,
    collection_type VARCHAR(50) DEFAULT 'manual', -- manual, smart, auto_date, auto_type, auto_party
    
    -- Smart collection rules (JSON filter criteria)
    filter_rules JSONB DEFAULT '{}',
    
    -- Hierarchy support
    parent_id UUID REFERENCES evidence_collections(id) ON DELETE CASCADE,
    path TEXT, -- Materialized path for efficient tree queries (e.g., "/root/contracts/2024")
    depth INTEGER DEFAULT 0,
    
    -- Optional associations
    case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    
    -- Display settings
    color VARCHAR(20),
    icon VARCHAR(50),
    sort_order INTEGER DEFAULT 0,
    is_system BOOLEAN DEFAULT FALSE, -- System collections can't be deleted
    
    -- Statistics (denormalized for performance)
    item_count INTEGER DEFAULT 0,
    
    -- Audit
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_evidence_collections_parent ON evidence_collections(parent_id);
CREATE INDEX IF NOT EXISTS idx_evidence_collections_path ON evidence_collections(path);
CREATE INDEX IF NOT EXISTS idx_evidence_collections_case ON evidence_collections(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_collections_project ON evidence_collections(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_collections_type ON evidence_collections(collection_type);

-- ============================================================================
-- EVIDENCE ITEMS TABLE
-- Core evidence repository - NOT case-dependent
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Core file metadata
    filename VARCHAR(512) NOT NULL,
    original_path TEXT,                    -- Original file location/source path
    file_type VARCHAR(50),                 -- Extension: pdf, docx, dwg, xlsx, etc.
    mime_type VARCHAR(128),
    file_size BIGINT,
    file_hash VARCHAR(128) NOT NULL,       -- SHA-256 for deduplication
    
    -- Storage
    s3_bucket VARCHAR(128) NOT NULL,
    s3_key VARCHAR(2048) NOT NULL,
    thumbnail_s3_key VARCHAR(2048),        -- Optional thumbnail for preview
    
    -- Classification
    evidence_type VARCHAR(100),            -- From evidence_type enum
    document_category VARCHAR(100),        -- From document_category enum
    
    -- Auto-extracted metadata
    document_date DATE,                    -- Extracted date from document content
    document_date_confidence DECIMAL(3,2), -- How confident in extracted date
    title VARCHAR(500),
    author VARCHAR(255),
    description TEXT,
    page_count INTEGER,
    
    -- Full-text content (for search)
    extracted_text TEXT,
    text_language VARCHAR(10) DEFAULT 'en',
    
    -- Entity extraction (auto-populated by AI/NLP)
    extracted_parties JSONB DEFAULT '[]',      -- [{name, role, confidence}]
    extracted_dates JSONB DEFAULT '[]',        -- [{date, context, confidence}]
    extracted_amounts JSONB DEFAULT '[]',      -- [{amount, currency, context}]
    extracted_references JSONB DEFAULT '[]',   -- [{ref, type, context}] - e.g., DRG-001, VI-123
    extracted_locations JSONB DEFAULT '[]',    -- [{location, type}]
    
    -- Auto-tagging
    auto_tags JSONB DEFAULT '[]',              -- AI-generated tags with confidence
    manual_tags JSONB DEFAULT '[]',            -- User-added tags
    keywords_matched JSONB DEFAULT '[]',       -- Matched from project/case keywords
    stakeholders_matched JSONB DEFAULT '[]',   -- Matched stakeholders
    
    -- Classification confidence
    classification_confidence DECIMAL(3,2),
    classification_method VARCHAR(50),         -- 'ai', 'rule', 'manual'
    
    -- Processing status
    processing_status VARCHAR(50) DEFAULT 'pending',
    processing_error TEXT,
    ocr_completed BOOLEAN DEFAULT FALSE,
    ai_analyzed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP WITH TIME ZONE,
    
    -- Provenance (forensic chain)
    source_type VARCHAR(50),                   -- From evidence_source_type enum
    source_id UUID REFERENCES evidence_sources(id) ON DELETE SET NULL,
    source_path TEXT,                          -- Path within source (e.g., PST folder path)
    source_email_id UUID REFERENCES email_messages(id) ON DELETE SET NULL, -- If from email attachment
    
    -- Optional associations (NULL = unassigned)
    case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    collection_id UUID REFERENCES evidence_collections(id) ON DELETE SET NULL,
    
    -- Flags
    is_duplicate BOOLEAN DEFAULT FALSE,
    duplicate_of_id UUID REFERENCES evidence_items(id) ON DELETE SET NULL,
    is_privileged BOOLEAN DEFAULT FALSE,       -- Legal privilege marker
    is_confidential BOOLEAN DEFAULT FALSE,
    is_starred BOOLEAN DEFAULT FALSE,
    is_reviewed BOOLEAN DEFAULT FALSE,
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    
    -- User notes
    notes TEXT,
    
    -- Audit
    uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Core indexes
CREATE INDEX IF NOT EXISTS idx_evidence_items_hash ON evidence_items(file_hash);
CREATE INDEX IF NOT EXISTS idx_evidence_items_type ON evidence_items(evidence_type);
CREATE INDEX IF NOT EXISTS idx_evidence_items_category ON evidence_items(document_category);
CREATE INDEX IF NOT EXISTS idx_evidence_items_date ON evidence_items(document_date);
CREATE INDEX IF NOT EXISTS idx_evidence_items_status ON evidence_items(processing_status);

-- Association indexes
CREATE INDEX IF NOT EXISTS idx_evidence_items_case ON evidence_items(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_project ON evidence_items(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_collection ON evidence_items(collection_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_source ON evidence_items(source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_source_email ON evidence_items(source_email_id);

-- Tag indexes (GIN for JSONB array contains queries)
CREATE INDEX IF NOT EXISTS idx_evidence_items_auto_tags ON evidence_items USING gin(auto_tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_evidence_items_manual_tags ON evidence_items USING gin(manual_tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_evidence_items_keywords ON evidence_items USING gin(keywords_matched jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_evidence_items_stakeholders ON evidence_items USING gin(stakeholders_matched jsonb_path_ops);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_evidence_items_text_search ON evidence_items 
    USING gin(to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(filename, '') || ' ' || COALESCE(extracted_text, '')));

-- Filename search (trigram for fuzzy matching)
CREATE INDEX IF NOT EXISTS idx_evidence_items_filename_trgm ON evidence_items USING gin(filename gin_trgm_ops);

-- Unassigned evidence (useful query)
CREATE INDEX IF NOT EXISTS idx_evidence_items_unassigned ON evidence_items(created_at) 
    WHERE case_id IS NULL AND project_id IS NULL;

-- ============================================================================
-- EVIDENCE CORRESPONDENCE LINKS TABLE
-- Links evidence items to emails/correspondence
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_correspondence_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Evidence item
    evidence_item_id UUID NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
    
    -- Link type and confidence
    link_type VARCHAR(50) NOT NULL,        -- From correspondence_link_type enum
    link_confidence DECIMAL(3,2),          -- 0.00-1.00, for auto-detected links
    link_method VARCHAR(50),               -- 'attachment', 'filename_match', 'reference_match', 'date_proximity', 'manual'
    
    -- Target: Email message (primary)
    email_message_id UUID REFERENCES email_messages(id) ON DELETE CASCADE,
    
    -- OR: External correspondence reference (for non-email correspondence)
    correspondence_type VARCHAR(50),       -- 'letter', 'fax', 'meeting_minutes', etc.
    correspondence_reference VARCHAR(500), -- External reference number
    correspondence_date DATE,
    correspondence_from VARCHAR(255),
    correspondence_to VARCHAR(255),
    correspondence_subject TEXT,
    
    -- Context of the link
    context_snippet TEXT,                  -- Relevant text showing the link
    page_reference VARCHAR(50),            -- Page number in document if applicable
    
    -- Classification
    is_auto_linked BOOLEAN DEFAULT FALSE,
    is_verified BOOLEAN DEFAULT FALSE,     -- User has confirmed this link
    
    -- Audit
    linked_by UUID REFERENCES users(id) ON DELETE SET NULL,
    verified_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    verified_at TIMESTAMP WITH TIME ZONE,
    
    -- Prevent duplicate links
    CONSTRAINT uq_evidence_email_link UNIQUE(evidence_item_id, email_message_id) 
);

CREATE INDEX IF NOT EXISTS idx_ecl_evidence ON evidence_correspondence_links(evidence_item_id);
CREATE INDEX IF NOT EXISTS idx_ecl_email ON evidence_correspondence_links(email_message_id);
CREATE INDEX IF NOT EXISTS idx_ecl_type ON evidence_correspondence_links(link_type);
CREATE INDEX IF NOT EXISTS idx_ecl_auto ON evidence_correspondence_links(is_auto_linked);
CREATE INDEX IF NOT EXISTS idx_ecl_verified ON evidence_correspondence_links(is_verified);
CREATE INDEX IF NOT EXISTS idx_ecl_correspondence_date ON evidence_correspondence_links(correspondence_date);

-- ============================================================================
-- EVIDENCE RELATIONS TABLE
-- Relationships between evidence items
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source and target evidence
    source_evidence_id UUID NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
    target_evidence_id UUID NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
    
    -- Relation details
    relation_type VARCHAR(50) NOT NULL,    -- From evidence_relation_type enum
    relation_direction VARCHAR(20) DEFAULT 'unidirectional', -- 'unidirectional' or 'bidirectional'
    
    -- Context
    description TEXT,
    confidence DECIMAL(3,2),               -- For auto-detected relations
    detection_method VARCHAR(50),          -- 'hash_match', 'content_similarity', 'reference_match', 'manual'
    
    -- Flags
    is_auto_detected BOOLEAN DEFAULT FALSE,
    is_verified BOOLEAN DEFAULT FALSE,
    
    -- Audit
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    verified_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    verified_at TIMESTAMP WITH TIME ZONE,
    
    -- Constraints
    CONSTRAINT chk_no_self_link CHECK (source_evidence_id != target_evidence_id),
    CONSTRAINT uq_evidence_relation UNIQUE(source_evidence_id, target_evidence_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_evidence_relations_source ON evidence_relations(source_evidence_id);
CREATE INDEX IF NOT EXISTS idx_evidence_relations_target ON evidence_relations(target_evidence_id);
CREATE INDEX IF NOT EXISTS idx_evidence_relations_type ON evidence_relations(relation_type);

-- ============================================================================
-- EVIDENCE COLLECTION ITEMS (Junction Table)
-- Many-to-many: evidence items can be in multiple collections
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_collection_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES evidence_collections(id) ON DELETE CASCADE,
    evidence_item_id UUID NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
    
    -- Order within collection
    sort_order INTEGER DEFAULT 0,
    
    -- How added
    added_method VARCHAR(50) DEFAULT 'manual', -- 'manual', 'auto_filter', 'bulk'
    
    -- Audit
    added_by UUID REFERENCES users(id) ON DELETE SET NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT uq_collection_evidence UNIQUE(collection_id, evidence_item_id)
);

CREATE INDEX IF NOT EXISTS idx_eci_collection ON evidence_collection_items(collection_id);
CREATE INDEX IF NOT EXISTS idx_eci_evidence ON evidence_collection_items(evidence_item_id);

-- ============================================================================
-- EVIDENCE ACTIVITY LOG
-- Audit trail for evidence access and modifications
-- ============================================================================

CREATE TABLE IF NOT EXISTS evidence_activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Target
    evidence_item_id UUID REFERENCES evidence_items(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES evidence_collections(id) ON DELETE CASCADE,
    
    -- Action
    action VARCHAR(50) NOT NULL,           -- 'view', 'download', 'update', 'tag', 'link', 'assign', 'delete'
    action_details JSONB,                  -- Additional context
    
    -- Actor
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    
    -- Timestamp
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_evidence_activity_item ON evidence_activity_log(evidence_item_id);
CREATE INDEX IF NOT EXISTS idx_evidence_activity_collection ON evidence_activity_log(collection_id);
CREATE INDEX IF NOT EXISTS idx_evidence_activity_user ON evidence_activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_evidence_activity_action ON evidence_activity_log(action);
CREATE INDEX IF NOT EXISTS idx_evidence_activity_time ON evidence_activity_log(created_at);

-- ============================================================================
-- FUNCTIONS AND TRIGGERS
-- ============================================================================

-- Function to update collection item counts
CREATE OR REPLACE FUNCTION update_collection_item_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE evidence_collections 
        SET item_count = item_count + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.collection_id;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE evidence_collections 
        SET item_count = GREATEST(0, item_count - 1), updated_at = CURRENT_TIMESTAMP
        WHERE id = OLD.collection_id;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Trigger for collection item count
DROP TRIGGER IF EXISTS trg_update_collection_count ON evidence_collection_items;
CREATE TRIGGER trg_update_collection_count
AFTER INSERT OR DELETE ON evidence_collection_items
FOR EACH ROW EXECUTE FUNCTION update_collection_item_count();

-- Function to update source item counts
CREATE OR REPLACE FUNCTION update_source_item_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.source_id IS NOT NULL THEN
        UPDATE evidence_sources 
        SET processed_items = processed_items + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.source_id;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' AND OLD.source_id IS NOT NULL THEN
        UPDATE evidence_sources 
        SET processed_items = GREATEST(0, processed_items - 1), updated_at = CURRENT_TIMESTAMP
        WHERE id = OLD.source_id;
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for source item count
DROP TRIGGER IF EXISTS trg_update_source_count ON evidence_items;
CREATE TRIGGER trg_update_source_count
AFTER INSERT OR DELETE ON evidence_items
FOR EACH ROW EXECUTE FUNCTION update_source_item_count();

-- Function to set updated_at timestamp
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for updated_at
DROP TRIGGER IF EXISTS trg_evidence_items_updated ON evidence_items;
CREATE TRIGGER trg_evidence_items_updated
BEFORE UPDATE ON evidence_items
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_evidence_collections_updated ON evidence_collections;
CREATE TRIGGER trg_evidence_collections_updated
BEFORE UPDATE ON evidence_collections
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_evidence_sources_updated ON evidence_sources;
CREATE TRIGGER trg_evidence_sources_updated
BEFORE UPDATE ON evidence_sources
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- DEFAULT COLLECTIONS (System Collections)
-- ============================================================================

-- Insert default system collections if they don't exist
INSERT INTO evidence_collections (id, name, description, collection_type, is_system, icon, sort_order)
VALUES 
    ('00000000-0000-0000-0001-000000000001', 'All Evidence', 'All evidence items in the repository', 'smart', TRUE, 'folder', 0),
    ('00000000-0000-0000-0001-000000000002', 'Unassigned', 'Evidence not assigned to any case or project', 'smart', TRUE, 'inbox', 1),
    ('00000000-0000-0000-0001-000000000003', 'Recent Uploads', 'Recently uploaded evidence', 'smart', TRUE, 'clock', 2),
    ('00000000-0000-0000-0001-000000000004', 'Contracts', 'Contract documents', 'smart', TRUE, 'file-contract', 10),
    ('00000000-0000-0000-0001-000000000005', 'Drawings', 'Technical drawings and plans', 'smart', TRUE, 'drafting-compass', 11),
    ('00000000-0000-0000-0001-000000000006', 'Correspondence', 'Letters and formal correspondence', 'smart', TRUE, 'envelope', 12),
    ('00000000-0000-0000-0001-000000000007', 'Invoices & Payments', 'Financial documents', 'smart', TRUE, 'file-invoice-dollar', 13),
    ('00000000-0000-0000-0001-000000000008', 'Meeting Minutes', 'Meeting records and minutes', 'smart', TRUE, 'users', 14),
    ('00000000-0000-0000-0001-000000000009', 'Photos', 'Photographs and images', 'smart', TRUE, 'image', 15),
    ('00000000-0000-0000-0001-000000000010', 'Starred', 'Starred important items', 'smart', TRUE, 'star', 3)
ON CONFLICT (id) DO NOTHING;

-- Set filter rules for smart collections
UPDATE evidence_collections SET filter_rules = '{"all": true}' WHERE id = '00000000-0000-0000-0001-000000000001';
UPDATE evidence_collections SET filter_rules = '{"case_id": null, "project_id": null}' WHERE id = '00000000-0000-0000-0001-000000000002';
UPDATE evidence_collections SET filter_rules = '{"created_within_days": 7}' WHERE id = '00000000-0000-0000-0001-000000000003';
UPDATE evidence_collections SET filter_rules = '{"evidence_type": ["contract", "variation"]}' WHERE id = '00000000-0000-0000-0001-000000000004';
UPDATE evidence_collections SET filter_rules = '{"evidence_type": ["drawing", "specification"]}' WHERE id = '00000000-0000-0000-0001-000000000005';
UPDATE evidence_collections SET filter_rules = '{"evidence_type": ["letter", "notice", "email"]}' WHERE id = '00000000-0000-0000-0001-000000000006';
UPDATE evidence_collections SET filter_rules = '{"evidence_type": ["invoice", "payment_certificate"]}' WHERE id = '00000000-0000-0000-0001-000000000007';
UPDATE evidence_collections SET filter_rules = '{"evidence_type": ["meeting_minutes"]}' WHERE id = '00000000-0000-0000-0001-000000000008';
UPDATE evidence_collections SET filter_rules = '{"evidence_type": ["photo"]}' WHERE id = '00000000-0000-0000-0001-000000000009';
UPDATE evidence_collections SET filter_rules = '{"is_starred": true}' WHERE id = '00000000-0000-0000-0001-000000000010';

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- View: Evidence with correspondence count
CREATE OR REPLACE VIEW v_evidence_with_links AS
SELECT 
    ei.*,
    COALESCE(link_counts.correspondence_count, 0) as correspondence_count,
    COALESCE(link_counts.verified_link_count, 0) as verified_link_count,
    COALESCE(rel_counts.relation_count, 0) as relation_count
FROM evidence_items ei
LEFT JOIN (
    SELECT 
        evidence_item_id,
        COUNT(*) as correspondence_count,
        COUNT(*) FILTER (WHERE is_verified) as verified_link_count
    FROM evidence_correspondence_links
    GROUP BY evidence_item_id
) link_counts ON ei.id = link_counts.evidence_item_id
LEFT JOIN (
    SELECT 
        source_evidence_id as evidence_id,
        COUNT(*) as relation_count
    FROM evidence_relations
    GROUP BY source_evidence_id
) rel_counts ON ei.id = rel_counts.evidence_id;

-- View: Collection tree with item counts
CREATE OR REPLACE VIEW v_collection_tree AS
WITH RECURSIVE collection_tree AS (
    -- Root collections
    SELECT 
        id, name, description, collection_type, parent_id, path,
        depth, item_count, is_system, icon, color, sort_order,
        ARRAY[id] as ancestors
    FROM evidence_collections
    WHERE parent_id IS NULL
    
    UNION ALL
    
    -- Child collections
    SELECT 
        c.id, c.name, c.description, c.collection_type, c.parent_id, c.path,
        c.depth, c.item_count, c.is_system, c.icon, c.color, c.sort_order,
        ct.ancestors || c.id
    FROM evidence_collections c
    INNER JOIN collection_tree ct ON c.parent_id = ct.id
)
SELECT * FROM collection_tree
ORDER BY sort_order, name;

COMMENT ON TABLE evidence_items IS 'Core evidence repository - case/project independent';
COMMENT ON TABLE evidence_collections IS 'Virtual folders for organizing evidence';
COMMENT ON TABLE evidence_sources IS 'Provenance tracking for evidence origins';
COMMENT ON TABLE evidence_correspondence_links IS 'Links between evidence and emails/correspondence';
COMMENT ON TABLE evidence_relations IS 'Inter-document relationships';

