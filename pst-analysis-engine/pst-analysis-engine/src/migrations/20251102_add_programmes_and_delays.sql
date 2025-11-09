CREATE TABLE IF NOT EXISTS programmes (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    programme_type VARCHAR(50) NOT NULL, -- as_planned, as_built, interim
    programme_date TIMESTAMPTZ,
    version_number VARCHAR(100),
    activities JSONB, -- Activity schedule data
    critical_path JSONB, -- Critical activities
    milestones JSONB, -- Milestone events
    project_start TIMESTAMPTZ,
    project_finish TIMESTAMPTZ,
    data_date TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    uploaded_by_id UUID REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_programmes_case ON programmes(case_id);
CREATE INDEX IF NOT EXISTS idx_programmes_type ON programmes(programme_type);
CREATE INDEX IF NOT EXISTS idx_programmes_document ON programmes(document_id);


CREATE TABLE IF NOT EXISTS delay_events (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    as_planned_programme_id UUID REFERENCES programmes(id) ON DELETE SET NULL,
    as_built_programme_id UUID REFERENCES programmes(id) ON DELETE SET NULL,
    activity_id VARCHAR(100), -- Activity ID from programme
    activity_name VARCHAR(500),
    planned_start TIMESTAMPTZ,
    planned_finish TIMESTAMPTZ,
    actual_start TIMESTAMPTZ,
    actual_finish TIMESTAMPTZ,
    delay_days INTEGER NOT NULL DEFAULT 0,
    delay_type VARCHAR(50), -- critical, non_critical, concurrent
    is_on_critical_path BOOLEAN DEFAULT FALSE,
    delay_cause VARCHAR(100), -- employer, contractor, neutral, force_majeure
    description TEXT,
    linked_correspondence_ids JSONB, -- Array of evidence IDs
    linked_issue_id UUID REFERENCES issues(id) ON DELETE SET NULL,
    eot_entitlement_days INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by_id UUID REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_delay_events_case ON delay_events(case_id);
CREATE INDEX IF NOT EXISTS idx_delay_events_planned_prog ON delay_events(as_planned_programme_id);
CREATE INDEX IF NOT EXISTS idx_delay_events_built_prog ON delay_events(as_built_programme_id);
CREATE INDEX IF NOT EXISTS idx_delay_events_critical ON delay_events(is_on_critical_path);
CREATE INDEX IF NOT EXISTS idx_delay_events_cause ON delay_events(delay_cause);


-- Add programme columns to Evidence table for linking correspondence to programme analysis
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS as_planned_date TIMESTAMP;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS as_planned_activity VARCHAR(500);
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS as_built_date TIMESTAMP;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS as_built_activity VARCHAR(500);
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS delay_days INTEGER DEFAULT 0;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS is_critical_path BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_evidence_as_planned ON evidence(as_planned_date);
CREATE INDEX IF NOT EXISTS idx_evidence_as_built ON evidence(as_built_date);
