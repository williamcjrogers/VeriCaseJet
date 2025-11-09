ALTER TABLE share_links
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);
