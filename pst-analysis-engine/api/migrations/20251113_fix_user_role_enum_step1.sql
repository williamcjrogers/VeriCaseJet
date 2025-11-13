-- Fix user_role enum case mismatch - Step 1: Add uppercase values
-- Date: 2025-11-13
-- Description: Add uppercase enum values (ADMIN, EDITOR, VIEWER)
-- Note: PostgreSQL requires enum values to be added and committed before they can be used
--       This is why we split into two migration files

-- Add uppercase values to enum
-- These will be committed when this migration file completes
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'ADMIN';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'EDITOR';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'VIEWER';

-- Note: DO NOT use these new values yet - that happens in step 2
-- The transaction must complete and commit before the new values can be used
