-- Add project_id to email_messages table to support PST files linked to projects
ALTER TABLE email_messages 
ADD COLUMN project_id UUID REFERENCES projects(id);

-- Make case_id nullable since we can have either case_id OR project_id
ALTER TABLE email_messages 
ALTER COLUMN case_id DROP NOT NULL;

-- Add check constraint to ensure we have either case_id or project_id
ALTER TABLE email_messages 
ADD CONSTRAINT check_case_or_project CHECK (
    (case_id IS NOT NULL AND project_id IS NULL) OR 
    (case_id IS NULL AND project_id IS NOT NULL)
);

-- Add index on project_id for performance
CREATE INDEX idx_email_messages_project_id ON email_messages(project_id);

-- Update existing emails to link to projects through their PST files
UPDATE email_messages em
SET project_id = pf.project_id
FROM pst_files pf
WHERE em.pst_file_id = pf.id
AND pf.project_id IS NOT NULL
AND em.project_id IS NULL;
