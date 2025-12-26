-- AI Optimization Tracking Table
-- Records all AI API calls for performance analysis and optimization

-- Ensure pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS ai_optimization_events (
	id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

	-- Provider and model info
	provider VARCHAR(50) NOT NULL,  -- openai, anthropic, gemini, bedrock, xai, perplexity
	model_id VARCHAR(255) NOT NULL,

	-- Function/task context
	function_name VARCHAR(100),  -- e.g., "quick_search", "deep_analysis"
	task_type VARCHAR(50),  -- e.g., "search", "analysis", "generation"

	-- Token usage
	prompt_tokens INTEGER,
	completion_tokens INTEGER,
	total_tokens INTEGER,

	-- Performance metrics
	response_time_ms INTEGER NOT NULL,
	cost_usd NUMERIC(10, 6),  -- Cost in USD

	-- Status
	success BOOLEAN NOT NULL DEFAULT TRUE,
	error_message TEXT,

	-- Quality assessment
	quality_score NUMERIC(3, 2),  -- 0.00-1.00

	-- Additional metadata (JSONB for flexibility)
	metadata JSONB,

	-- User tracking
	user_id UUID REFERENCES users(id) ON DELETE SET NULL,

	-- Timestamps
	created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_created_at ON ai_optimization_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_provider ON ai_optimization_events(provider);
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_model ON ai_optimization_events(model_id);
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_function ON ai_optimization_events(function_name);
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_success ON ai_optimization_events(success);
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_user ON ai_optimization_events(user_id);

-- Composite index for common filtering
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_provider_model ON ai_optimization_events(provider, model_id);
CREATE INDEX IF NOT EXISTS idx_ai_opt_events_provider_created ON ai_optimization_events(provider, created_at DESC);

COMMENT ON TABLE ai_optimization_events IS 'Tracks all AI API calls for performance analysis and cost optimization';
COMMENT ON COLUMN ai_optimization_events.provider IS 'AI provider name (openai, anthropic, gemini, bedrock, xai, perplexity)';
COMMENT ON COLUMN ai_optimization_events.model_id IS 'Specific model identifier used for the API call';
COMMENT ON COLUMN ai_optimization_events.function_name IS 'VeriCase function or tool that triggered the AI call';
COMMENT ON COLUMN ai_optimization_events.task_type IS 'Type of task (search, analysis, generation, etc.)';
COMMENT ON COLUMN ai_optimization_events.response_time_ms IS 'API response time in milliseconds';
COMMENT ON COLUMN ai_optimization_events.cost_usd IS 'Estimated cost in USD based on token usage and provider pricing';
COMMENT ON COLUMN ai_optimization_events.quality_score IS 'Quality assessment score (0.0-1.0) if available';