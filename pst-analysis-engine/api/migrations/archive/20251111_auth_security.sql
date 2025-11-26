-- Active: 1763739336777@@localhost@55432
-- Enhanced Authentication Security Migration
-- Adds security fields to users table and creates session tracking tables
-- Refactored for idempotency and static analysis safety

-- Ensure pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    -- 1. Add security fields to users table
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
        
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='email_verified') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='verification_token') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN verification_token VARCHAR(255)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='reset_token') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN reset_token VARCHAR(255)';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='reset_token_expires') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN reset_token_expires TIMESTAMP WITH TIME ZONE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='failed_login_attempts') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='locked_until') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN locked_until TIMESTAMP WITH TIME ZONE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='last_failed_attempt') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN last_failed_attempt TIMESTAMP WITH TIME ZONE';
        END IF;
        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_name='users' AND column_name='password_changed_at') THEN
            EXECUTE 'ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP';
        END IF;

        -- Create indexes for token lookups (Dynamic SQL)
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_users_verification_token ON users(verification_token) WHERE verification_token IS NOT NULL';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users(reset_token) WHERE reset_token IS NOT NULL';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_users_email_verified ON users(email_verified)';

        -- Add comments
        EXECUTE 'COMMENT ON COLUMN users.email_verified IS ''Whether the user has verified their email address''';
        EXECUTE 'COMMENT ON COLUMN users.verification_token IS ''Token for email verification''';
        EXECUTE 'COMMENT ON COLUMN users.reset_token IS ''Token for password reset''';
        EXECUTE 'COMMENT ON COLUMN users.reset_token_expires IS ''Expiration time for password reset token''';
        EXECUTE 'COMMENT ON COLUMN users.failed_login_attempts IS ''Number of consecutive failed login attempts''';
        EXECUTE 'COMMENT ON COLUMN users.locked_until IS ''Account locked until this timestamp due to failed attempts''';
        EXECUTE 'COMMENT ON COLUMN users.last_failed_attempt IS ''Timestamp of last failed login attempt''';
        EXECUTE 'COMMENT ON COLUMN users.password_changed_at IS ''Last time the password was changed''';

    END IF;

    -- 2. Create sessions table for tracking active sessions
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'user_sessions') THEN
        EXECUTE 'CREATE TABLE user_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL, -- FK added later
            token_jti VARCHAR(255) NOT NULL UNIQUE,
            ip_address INET,
            user_agent TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            revoked_at TIMESTAMP WITH TIME ZONE,
            last_activity TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE user_sessions ADD CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
    END IF;

    -- Create indexes for session queries
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'user_sessions') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sessions_jti ON user_sessions(token_jti)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions(expires_at)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON user_sessions(revoked_at) WHERE revoked_at IS NOT NULL';
        EXECUTE 'COMMENT ON TABLE user_sessions IS ''Active JWT sessions for users''';
    END IF;

    -- 3. Create password history table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'password_history') THEN
        EXECUTE 'CREATE TABLE password_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL, -- FK added later
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE password_history ADD CONSTRAINT password_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'password_history') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_password_history_user ON password_history(user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_password_history_created ON password_history(created_at)';
        EXECUTE 'COMMENT ON TABLE password_history IS ''Password history to prevent reuse''';
    END IF;

    -- 4. Create login attempts table
    IF NOT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'login_attempts') THEN
        EXECUTE 'CREATE TABLE login_attempts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) NOT NULL,
            user_id UUID, -- Nullable FK
            ip_address INET,
            user_agent TEXT,
            success BOOLEAN NOT NULL,
            failure_reason VARCHAR(100),
            attempted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )';
        
        IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'users') THEN
             EXECUTE 'ALTER TABLE login_attempts ADD CONSTRAINT login_attempts_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE';
        END IF;
    END IF;

    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'login_attempts') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_login_attempts_email ON login_attempts(email)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_login_attempts_user ON login_attempts(user_id)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_login_attempts_time ON login_attempts(attempted_at)';
        EXECUTE 'COMMENT ON TABLE login_attempts IS ''Audit trail of login attempts''';
    END IF;

END $$;
