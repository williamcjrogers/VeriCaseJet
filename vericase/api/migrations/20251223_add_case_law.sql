-- Migration: Add case_law table
-- Created: 2025-12-23
-- Description:
--   * Adds case_law table for Case Law Intelligence Layer

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'case_law'
    ) THEN
        EXECUTE $SQL$
            CREATE TABLE case_law (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                neutral_citation VARCHAR(255) NOT NULL UNIQUE,
                case_name VARCHAR(500) NOT NULL,
                court VARCHAR(255),
                judgment_date TIMESTAMP,
                judge VARCHAR(255),
                s3_bucket VARCHAR(128) NOT NULL,
                s3_key_raw VARCHAR(2048) NOT NULL,
                s3_key_curated VARCHAR(2048),
                summary TEXT,
                full_text_preview TEXT,
                embedding_status VARCHAR(50) DEFAULT 'pending',
                extraction_status VARCHAR(50) DEFAULT 'pending',
                kb_ingestion_job_id VARCHAR(100),
                extracted_analysis JSONB,
                meta JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )
        $SQL$;
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_case_law_embedding_status'
    ) THEN
        EXECUTE 'CREATE INDEX idx_case_law_embedding_status ON case_law (embedding_status)';
    END IF;

    IF NOT EXISTS (
        SELECT FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'idx_case_law_extraction_status'
    ) THEN
        EXECUTE 'CREATE INDEX idx_case_law_extraction_status ON case_law (extraction_status)';
    END IF;
END
$$;
