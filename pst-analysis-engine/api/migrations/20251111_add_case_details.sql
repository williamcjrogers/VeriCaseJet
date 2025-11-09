-- Add extended case metadata fields for wizard workflow
ALTER TABLE cases
    ADD COLUMN IF NOT EXISTS case_id_custom VARCHAR(100),
    ADD COLUMN IF NOT EXISTS case_status VARCHAR(50),
    ADD COLUMN IF NOT EXISTS resolution_route VARCHAR(100),
    ADD COLUMN IF NOT EXISTS claimant VARCHAR(255),
    ADD COLUMN IF NOT EXISTS defendant VARCHAR(255),
    ADD COLUMN IF NOT EXISTS client VARCHAR(255),
    ADD COLUMN IF NOT EXISTS legal_team JSONB,
    ADD COLUMN IF NOT EXISTS heads_of_claim JSONB,
    ADD COLUMN IF NOT EXISTS deadlines JSONB;

CREATE INDEX IF NOT EXISTS idx_cases_case_id_custom ON cases(case_id_custom);

