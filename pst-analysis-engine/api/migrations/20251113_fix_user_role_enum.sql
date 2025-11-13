-- Fix user_role enum case mismatch
-- Date: 2025-11-13
-- Description: Update user_role enum to accept uppercase values

-- Add uppercase values to enum
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'ADMIN';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'MANAGER';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'USER';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'VIEWER';

-- Update existing users to use uppercase (if any exist with lowercase)
UPDATE users SET role = 'ADMIN' WHERE role = 'admin';
UPDATE users SET role = 'VIEWER' WHERE role = 'viewer';
UPDATE users SET role = 'USER' WHERE role = 'editor';
