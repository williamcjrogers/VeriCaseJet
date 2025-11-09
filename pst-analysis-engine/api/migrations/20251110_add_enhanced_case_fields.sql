-- Migration: Add Enhanced Case Fields
-- Created: 2025-11-10
-- Description: Adds fields for enhanced case creation from the configuration wizard

-- Add resolution route and dispute party fields
ALTER TABLE cases 
ADD COLUMN IF NOT EXISTS resolution_route VARCHAR(100),
ADD COLUMN IF NOT EXISTS claimant VARCHAR(512),
ADD COLUMN IF NOT EXISTS defendant VARCHAR(512),
ADD COLUMN IF NOT EXISTS client VARCHAR(512);

-- Create legal team table for case team members
CREATE TABLE IF NOT EXISTS case_legal_team (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    role VARCHAR(255) NOT NULL,
    name VARCHAR(512) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_legal_team_case ON case_legal_team(case_id);

-- Create heads of claim table
CREATE TABLE IF NOT EXISTS heads_of_claim (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    head VARCHAR(512) NOT NULL,
    status VARCHAR(100) DEFAULT 'Discovery',
    actions TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_heads_of_claim_case ON heads_of_claim(case_id);
CREATE INDEX IF NOT EXISTS idx_heads_of_claim_status ON heads_of_claim(status);

-- Create case deadlines table
CREATE TABLE IF NOT EXISTS case_deadlines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    task VARCHAR(512) NOT NULL,
    description TEXT,
    deadline_date TIMESTAMP WITH TIME ZONE,
    reminder_days INTEGER,
    is_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_deadlines_case ON case_deadlines(case_id);
CREATE INDEX IF NOT EXISTS idx_case_deadlines_date ON case_deadlines(deadline_date);
CREATE INDEX IF NOT EXISTS idx_case_deadlines_completed ON case_deadlines(is_completed);

-- Allow stakeholders and keywords to be associated with either case or project
ALTER TABLE stakeholders 
ALTER COLUMN case_id DROP NOT NULL;

ALTER TABLE keywords 
ALTER COLUMN case_id DROP NOT NULL;

-- Add constraint to ensure either case_id or project_id is set
ALTER TABLE stakeholders
ADD CONSTRAINT chk_stakeholders_case_or_project 
CHECK (case_id IS NOT NULL OR project_id IS NOT NULL);

ALTER TABLE keywords
ADD CONSTRAINT chk_keywords_case_or_project 
CHECK (case_id IS NOT NULL OR project_id IS NOT NULL);

-- Comments for documentation
COMMENT ON COLUMN cases.resolution_route IS 'Type of resolution: adjudication, litigation, arbitration, mediation, settlement, TBC';
COMMENT ON COLUMN cases.claimant IS 'Name of the claimant party';
COMMENT ON COLUMN cases.defendant IS 'Name of the defendant party';
COMMENT ON COLUMN cases.client IS 'Top-level client party for whom we are acting';
COMMENT ON TABLE case_legal_team IS 'Legal team members assigned to a case';
COMMENT ON TABLE heads_of_claim IS 'Heads of claim for tracking case progress';
COMMENT ON TABLE case_deadlines IS 'Important deadlines and tasks for a case';
