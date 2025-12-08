-- Migration: Contentious Matters and Heads of Claim Module
-- Date: 2025-11-26
-- Description: Creates tables for tracking contentious matters, heads of claim,
--              linking them to correspondence/evidence, and comment history

-- ============================================================================
-- Contentious Matters
-- Groups of evidence/correspondence related to a dispute
-- ============================================================================
CREATE TABLE IF NOT EXISTS contentious_matters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active', -- active, resolved, pending, closed
    priority VARCHAR(20) DEFAULT 'normal', -- low, normal, high, critical
    estimated_value DECIMAL(15,2),
    currency VARCHAR(10) DEFAULT 'GBP',
    date_identified DATE,
    resolution_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    
    -- At least one of project_id or case_id should be set
    CONSTRAINT chk_matter_owner CHECK (project_id IS NOT NULL OR case_id IS NOT NULL)
);

-- Indexes for contentious_matters
CREATE INDEX IF NOT EXISTS idx_contentious_matters_project ON contentious_matters(project_id);
CREATE INDEX IF NOT EXISTS idx_contentious_matters_case ON contentious_matters(case_id);
CREATE INDEX IF NOT EXISTS idx_contentious_matters_status ON contentious_matters(status);
CREATE INDEX IF NOT EXISTS idx_contentious_matters_created ON contentious_matters(created_at);

-- ============================================================================
-- Heads of Claim
-- Legal categorization of claims, can be linked to a contentious matter
-- ============================================================================
CREATE TABLE IF NOT EXISTS heads_of_claim (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    contentious_matter_id UUID REFERENCES contentious_matters(id) ON DELETE SET NULL,
    reference_number VARCHAR(100), -- e.g., "HOC-001", "EOT-001"
    name VARCHAR(500) NOT NULL,
    description TEXT,
    claim_type VARCHAR(100), -- delay, defects, variation, loss_expense, extension_of_time
    claimed_amount DECIMAL(15,2),
    awarded_amount DECIMAL(15,2),
    currency VARCHAR(10) DEFAULT 'GBP',
    status VARCHAR(50) DEFAULT 'draft', -- draft, submitted, under_review, accepted, rejected, settled, withdrawn
    submission_date DATE,
    response_due_date DATE,
    determination_date DATE,
    supporting_contract_clause TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    
    CONSTRAINT chk_claim_owner CHECK (project_id IS NOT NULL OR case_id IS NOT NULL)
);

-- Indexes for heads_of_claim
CREATE INDEX IF NOT EXISTS idx_heads_of_claim_project ON heads_of_claim(project_id);
CREATE INDEX IF NOT EXISTS idx_heads_of_claim_case ON heads_of_claim(case_id);
CREATE INDEX IF NOT EXISTS idx_heads_of_claim_matter ON heads_of_claim(contentious_matter_id);
CREATE INDEX IF NOT EXISTS idx_heads_of_claim_status ON heads_of_claim(status);
CREATE INDEX IF NOT EXISTS idx_heads_of_claim_type ON heads_of_claim(claim_type);
CREATE INDEX IF NOT EXISTS idx_heads_of_claim_ref ON heads_of_claim(reference_number);

-- ============================================================================
-- Item Claim Links
-- Links correspondence and evidence items to contentious matters or heads of claim
-- ============================================================================
CREATE TABLE IF NOT EXISTS item_claim_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_type VARCHAR(50) NOT NULL, -- 'correspondence' or 'evidence'
    item_id UUID NOT NULL, -- References email_messages.id or evidence_items.id
    contentious_matter_id UUID REFERENCES contentious_matters(id) ON DELETE CASCADE,
    head_of_claim_id UUID REFERENCES heads_of_claim(id) ON DELETE CASCADE,
    link_type VARCHAR(50) DEFAULT 'supporting', -- supporting, contradicting, neutral, key
    relevance_score INTEGER CHECK (relevance_score >= 0 AND relevance_score <= 100),
    notes TEXT,
    status VARCHAR(50) DEFAULT 'active', -- active, removed, superseded
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    
    -- Ensure at least one of contentious_matter_id or head_of_claim_id is set
    CONSTRAINT chk_link_target CHECK (
        contentious_matter_id IS NOT NULL OR head_of_claim_id IS NOT NULL
    ),
    
    -- Prevent duplicate links
    CONSTRAINT uq_item_claim_link UNIQUE (item_type, item_id, contentious_matter_id, head_of_claim_id)
);

-- Indexes for item_claim_links
CREATE INDEX IF NOT EXISTS idx_item_claim_links_item ON item_claim_links(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_item_claim_links_matter ON item_claim_links(contentious_matter_id);
CREATE INDEX IF NOT EXISTS idx_item_claim_links_claim ON item_claim_links(head_of_claim_id);
CREATE INDEX IF NOT EXISTS idx_item_claim_links_type ON item_claim_links(link_type);

-- ============================================================================
-- Item Comments
-- Comment history on linked items
-- ============================================================================
CREATE TABLE IF NOT EXISTS item_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_claim_link_id UUID REFERENCES item_claim_links(id) ON DELETE CASCADE,
    -- Allow direct comments on items without link
    item_type VARCHAR(50), -- 'correspondence', 'evidence', 'matter', 'claim'
    item_id UUID,
    parent_comment_id UUID REFERENCES item_comments(id) ON DELETE CASCADE, -- For threaded comments
    content TEXT NOT NULL,
    is_edited BOOLEAN DEFAULT FALSE,
    edited_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    
    -- Either link_id or (item_type + item_id) should be set
    CONSTRAINT chk_comment_target CHECK (
        item_claim_link_id IS NOT NULL OR (item_type IS NOT NULL AND item_id IS NOT NULL)
    )
);

-- Indexes for item_comments
CREATE INDEX IF NOT EXISTS idx_item_comments_link ON item_comments(item_claim_link_id);
CREATE INDEX IF NOT EXISTS idx_item_comments_item ON item_comments(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_item_comments_parent ON item_comments(parent_comment_id);
CREATE INDEX IF NOT EXISTS idx_item_comments_created ON item_comments(created_at);

-- ============================================================================
-- Helper Views
-- ============================================================================

-- View to get all linked items for a contentious matter
CREATE OR REPLACE VIEW v_matter_items AS
SELECT 
    cm.id as matter_id,
    cm.name as matter_name,
    icl.item_type,
    icl.item_id,
    icl.link_type,
    icl.relevance_score,
    icl.notes,
    icl.created_at as linked_at,
    u.email as linked_by
FROM contentious_matters cm
JOIN item_claim_links icl ON cm.id = icl.contentious_matter_id
LEFT JOIN users u ON icl.created_by = u.id
WHERE icl.status = 'active';

-- View to get all linked items for a head of claim
CREATE OR REPLACE VIEW v_claim_items AS
SELECT 
    hoc.id as claim_id,
    hoc.name as claim_name,
    hoc.reference_number,
    icl.item_type,
    icl.item_id,
    icl.link_type,
    icl.relevance_score,
    icl.notes,
    icl.created_at as linked_at,
    u.email as linked_by
FROM heads_of_claim hoc
JOIN item_claim_links icl ON hoc.id = icl.head_of_claim_id
LEFT JOIN users u ON icl.created_by = u.id
WHERE icl.status = 'active';

-- ============================================================================
-- Triggers for updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_contentious_matters_updated_at ON contentious_matters;
CREATE TRIGGER update_contentious_matters_updated_at
    BEFORE UPDATE ON contentious_matters
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_heads_of_claim_updated_at ON heads_of_claim;
CREATE TRIGGER update_heads_of_claim_updated_at
    BEFORE UPDATE ON heads_of_claim
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_item_claim_links_updated_at ON item_claim_links;
CREATE TRIGGER update_item_claim_links_updated_at
    BEFORE UPDATE ON item_claim_links
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Grant permissions (adjust as needed for your setup)
-- ============================================================================
-- GRANT ALL ON contentious_matters TO vericase;
-- GRANT ALL ON heads_of_claim TO vericase;
-- GRANT ALL ON item_claim_links TO vericase;
-- GRANT ALL ON item_comments TO vericase;
-- GRANT ALL ON v_matter_items TO vericase;
-- GRANT ALL ON v_claim_items TO vericase;

COMMENT ON TABLE contentious_matters IS 'Groups of disputed items - the overarching dispute categories';
COMMENT ON TABLE heads_of_claim IS 'Specific legal claims, can be nested under contentious matters';
COMMENT ON TABLE item_claim_links IS 'Links correspondence and evidence to matters and claims';
COMMENT ON TABLE item_comments IS 'Comment history on linked items for audit trail';

