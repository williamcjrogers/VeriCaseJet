-- EMERGENCY FIX: User Role Enum Issue
-- Run this IMMEDIATELY in your AWS RDS database to fix the application
-- 
-- HOW TO RUN:
-- 1. Connect to your AWS RDS PostgreSQL database
-- 2. Run SECTION 1 below and COMMIT
-- 3. Then run SECTION 2 and COMMIT
--
-- DO NOT RUN BOTH SECTIONS IN THE SAME TRANSACTION!
-- PostgreSQL requires enum values to be committed before they can be used.

-- ============================================================
-- SECTION 1: Add Uppercase Enum Values
-- Run this first, then COMMIT before running Section 2
-- ============================================================

ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'ADMIN';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'EDITOR';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'VIEWER';

-- ** STOP HERE - COMMIT THE TRANSACTION **
-- In DataGrip: Ctrl+Alt+Y
-- In PyCharm Database Console: Commit button
-- In psql: Type "COMMIT;"
-- In AWS Query Editor: Execute, then start new query


-- ============================================================
-- SECTION 2: Update Existing User Data
-- Run this AFTER Section 1 is committed
-- ============================================================

-- Update any existing users from lowercase to uppercase
UPDATE users SET role = 'ADMIN'::user_role WHERE role = 'admin'::user_role;
UPDATE users SET role = 'EDITOR'::user_role WHERE role = 'editor'::user_role;
UPDATE users SET role = 'VIEWER'::user_role WHERE role = 'viewer'::user_role;

-- Verify the fix worked:
SELECT email, role FROM users;

-- Expected result: All roles should be in UPPERCASE (ADMIN, EDITOR, VIEWER)

-- ============================================================
-- DONE! Your database is now fixed.
-- Restart your application and it should work.
-- ============================================================
