-- Allow project-only keywords without associated case
ALTER TABLE stakeholders
    ALTER COLUMN case_id DROP NOT NULL;

ALTER TABLE keywords
    ALTER COLUMN case_id DROP NOT NULL;

