-- Active: 1763739336777@@localhost@55432
-- Fix user_role enum case mismatch - Step 1: Add uppercase values
-- Date: 2025-11-13
-- Description: Add uppercase enum values (ADMIN, EDITOR, VIEWER)
-- Note: PostgreSQL requires enum values to be added and committed before they can be used
--       This is why we split into two migration files

-- 1) Ensure the enum type exists (idempotent)
DO $$
BEGIN
    BEGIN
        -- Attempt to create the type with legacy lowercase values
        EXECUTE 'CREATE TYPE user_role AS ENUM (''admin'', ''user'', ''analyst'', ''viewer'')';
    EXCEPTION
        WHEN duplicate_object THEN
            -- Type already exists; ignore
            NULL;
    END;
END $$;

-- 2) Add uppercase values using dynamic SQL and exception-safe guards
-- This avoids direct references to system catalogs for better tool compatibility
DO $$
BEGIN
    BEGIN
        EXECUTE 'ALTER TYPE user_role ADD VALUE IF NOT EXISTS ''ADMIN''';
    EXCEPTION WHEN undefined_object THEN
        -- Type does not exist yet (e.g., first run in a clean DB); ignore since step 1 above creates it
        NULL;
    END;

    BEGIN
        EXECUTE 'ALTER TYPE user_role ADD VALUE IF NOT EXISTS ''EDITOR''';
    EXCEPTION WHEN undefined_object THEN
        NULL;
    END;

    BEGIN
        EXECUTE 'ALTER TYPE user_role ADD VALUE IF NOT EXISTS ''VIEWER''';
    EXCEPTION WHEN undefined_object THEN
        NULL;
    END;
END $$;

-- Note: DO NOT switch existing rows to these new values here.
-- If needed, perform data updates in a separate migration (step 2) after this commits.
