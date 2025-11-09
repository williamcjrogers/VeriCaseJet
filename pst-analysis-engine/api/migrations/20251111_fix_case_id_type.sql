-- Fix cases table to use UUID instead of integer for ID
-- This is a breaking change but necessary for consistency with the rest of the schema

-- First, drop all foreign key constraints referencing cases.id
ALTER TABLE evidence DROP CONSTRAINT IF EXISTS evidence_case_id_fkey;
ALTER TABLE issues DROP CONSTRAINT IF EXISTS issues_case_id_fkey;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_case_id_fkey;

-- Drop the existing cases table (WARNING: This will delete all existing case data!)
DROP TABLE IF EXISTS cases CASCADE;

-- Recreate cases table with UUID primary key and all new fields
CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    description TEXT,
    contract_type VARCHAR(50),
    programme_type VARCHAR(50),
    owner_id UUID REFERENCES users(id) NOT NULL,
    company_id UUID REFERENCES companies(id),
    resolution_route VARCHAR(50),
    claimant VARCHAR(255),
    defendant VARCHAR(255),
    client VARCHAR(255),
    config_json JSON,
    is_configured BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX idx_cases_case_number ON cases(case_number);
CREATE INDEX idx_cases_owner ON cases(owner_id);
CREATE INDEX idx_cases_company ON cases(company_id);

-- Create legal team table
CREATE TABLE IF NOT EXISTS case_legal_team (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    role VARCHAR(100),
    name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create heads of claim table
CREATE TABLE IF NOT EXISTS heads_of_claim (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    claim_type VARCHAR(50),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create case deadlines table
CREATE TABLE IF NOT EXISTS case_deadlines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
    deadline_type VARCHAR(100),
    deadline_date TIMESTAMP WITH TIME ZONE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Recreate issues table with UUID case_id reference
DROP TABLE IF EXISTS issues CASCADE;
CREATE TABLE issues (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    issue_type VARCHAR(50),
    raised_by VARCHAR(255),
    raised_date TIMESTAMP WITH TIME ZONE,
    response_due TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) DEFAULT 'open',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Recreate evidence table with UUID case_id reference
DROP TABLE IF EXISTS evidence CASCADE;
CREATE TABLE evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    document_id UUID REFERENCES documents(id),
    issue_id UUID REFERENCES issues(id),
    description TEXT,
    relevance_score FLOAT DEFAULT 0.0,
    added_by UUID REFERENCES users(id),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    notice_type VARCHAR(100),
    notice_date TIMESTAMP WITH TIME ZONE,
    sender VARCHAR(255),
    recipient VARCHAR(255),
    delay_days INTEGER,
    cost_impact NUMERIC(15, 2),
    currency VARCHAR(10) DEFAULT 'GBP',
    metadata JSON
);

-- Create claims table (new)
CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES cases(id),
    claim_type VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    claimed_amount INTEGER,
    currency VARCHAR(10),
    claim_date TIMESTAMP WITH TIME ZONE,
    response_due_date TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add comment
COMMENT ON TABLE cases IS 'Legal cases with enhanced construction dispute fields';
