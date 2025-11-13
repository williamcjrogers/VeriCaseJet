-- Fix user_role enum case mismatch - Step 2: Update existing data
-- Date: 2025-11-13
-- Description: Update existing users to use uppercase enum values
-- Prerequisites: Step 1 must be completed and committed first

-- Update existing user records from lowercase to uppercase
-- Only update records that actually have lowercase values
UPDATE users SET role = 'ADMIN'::user_role WHERE role = 'admin'::user_role;
UPDATE users SET role = 'EDITOR'::user_role WHERE role = 'editor'::user_role;
UPDATE users SET role = 'VIEWER'::user_role WHERE role = 'viewer'::user_role;

-- The old lowercase values can remain in the enum for backward compatibility
-- or be removed in a future migration once we're certain no legacy data exists
