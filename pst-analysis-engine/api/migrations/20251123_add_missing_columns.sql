-- Add missing columns to companies table
ALTER TABLE companies ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(50) DEFAULT 'professional';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS storage_limit_gb INTEGER DEFAULT 100;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS primary_color VARCHAR(20);

-- Add missing columns to cases table
ALTER TABLE cases ADD COLUMN IF NOT EXISTS case_id_custom VARCHAR(100);
ALTER TABLE cases ADD COLUMN IF NOT EXISTS project_name VARCHAR(500);
ALTER TABLE cases ADD COLUMN IF NOT EXISTS dispute_type VARCHAR(100);
ALTER TABLE cases ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'active';
ALTER TABLE cases ADD COLUMN IF NOT EXISTS case_status VARCHAR(50);
ALTER TABLE cases ADD COLUMN IF NOT EXISTS legal_team JSON;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS heads_of_claim JSON;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS deadlines JSON;
ALTER TABLE cases ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP WITH TIME ZONE;

-- Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_cases_case_id_custom ON cases(case_id_custom);

