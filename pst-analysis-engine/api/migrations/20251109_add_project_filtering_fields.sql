-- Add filtering fields for retrospective analysis
ALTER TABLE projects 
ADD COLUMN IF NOT EXISTS analysis_type VARCHAR(50) DEFAULT 'project',
ADD COLUMN IF NOT EXISTS project_aliases TEXT,
ADD COLUMN IF NOT EXISTS site_address TEXT,
ADD COLUMN IF NOT EXISTS include_domains TEXT,
ADD COLUMN IF NOT EXISTS exclude_people TEXT,
ADD COLUMN IF NOT EXISTS project_terms TEXT,
ADD COLUMN IF NOT EXISTS exclude_keywords TEXT;

-- Add comments to explain the fields
COMMENT ON COLUMN projects.analysis_type IS 'Type of analysis: retrospective or project';
COMMENT ON COLUMN projects.project_aliases IS 'Comma-separated alternative project names';
COMMENT ON COLUMN projects.site_address IS 'Project site address/location';
COMMENT ON COLUMN projects.include_domains IS 'Comma-separated email domains to include';
COMMENT ON COLUMN projects.exclude_people IS 'Comma-separated names/emails to exclude';
COMMENT ON COLUMN projects.project_terms IS 'Project-specific terms and abbreviations';
COMMENT ON COLUMN projects.exclude_keywords IS 'Keywords that indicate other projects';
