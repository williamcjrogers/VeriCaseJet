-- Active: 1763739336777@@localhost@55432
-- Fix user_role enum - Step 2: Update existing data to uppercase
-- Date: 2025-11-13
-- Description: Safely updates existing users to new uppercase roles using dynamic SQL

DO $$
BEGIN
    -- Only run updates if users table exists
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
        
        -- 1. admin -> ADMIN
        -- We cast to text for the comparison to match legacy values safely
        EXECUTE 'UPDATE users SET role = ''ADMIN'' WHERE role::text = ''admin''';
        
        -- 2. user -> EDITOR (Standard user role)
        EXECUTE 'UPDATE users SET role = ''EDITOR'' WHERE role::text = ''user''';
        
        -- 3. analyst -> EDITOR (Standard user role)
        EXECUTE 'UPDATE users SET role = ''EDITOR'' WHERE role::text = ''analyst''';
        
        -- 4. viewer -> VIEWER
        EXECUTE 'UPDATE users SET role = ''VIEWER'' WHERE role::text = ''viewer''';
        
    END IF;
END $$;

-- Note: Once this is verified and running for a while, a future migration (step 3)
-- could remove the lowercase enum values ('admin', 'user', etc) using a new type swap
-- but Postgres doesn't support removing enum values easily without type recreation.
