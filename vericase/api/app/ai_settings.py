from __future__ import annotations

"""
AI Settings Manager - Loads AI configuration from database with fallback to environment variables
Supports: OpenAI, Anthropic, Gemini, Amazon Bedrock, xAI, and Perplexity providers
"""
import json
import logging
from typing import Any
from sqlalchemy.orm import Session

from .models import AppSetting

logger = logging.getLogger(__name__)


# Supported providers
SUPPORTED_PROVIDERS = ["openai", "anthropic", "gemini", "bedrock", "xai", "perplexity"]


class AISettings:
    """
    Manages AI provider settings, loading from database with env var fallbacks.
    Settings are cached but can be refreshed on demand.

    Supported Providers:
    - OpenAI (direct API)
    - Anthropic (direct API)
    - Gemini (direct API)
    - Amazon Bedrock (IAM-based)
    """

    _cache: dict[str, str] = {}
    _cache_valid: bool = False

    # Default models for each provider
    # Use actual API model IDs, not display names
    DEFAULT_MODELS: dict[str, str] = {
        # Updated defaults (align with ai_models_2025 catalog)
        "openai": "gpt-5.2-instant",
        "anthropic": "claude-sonnet-4.5",
        "gemini": "gemini-2.5-flash",
        "bedrock": "amazon.nova-pro-v1:0",  # Amazon Nova Pro (cost-effective)
        "xai": "grok-4.1-fast",
        "perplexity": "sonar-pro",
    }

    # ==========================================================================
    # AI TOOL REGISTRY - Comprehensive Configuration for All AI Features
    # ==========================================================================
    # Each tool has: enabled status, provider/model, fallback chain, parameters
    # Admin can override any setting via database (ai_tool_{tool_name})
    # ==========================================================================

    DEFAULT_TOOL_CONFIGS: dict[str, dict[str, Any]] = {
        # ------------------------------------------------------------------
        # BASIC AI CHAT - Simple query/response for email evidence
        # ------------------------------------------------------------------
        "basic_chat": {
            "enabled": True,
            "display_name": "AI Chat Assistant",
            "description": "Basic AI chat for querying email evidence and documents",
            "category": "assistant",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "max_tokens": 4000,
            "temperature": 0.3,
            "max_duration_seconds": 60,
            "fallback_chain": [
                ("bedrock", "amazon.nova-lite-v1:0"),
                ("openai", "gpt-5.2-instant"),
                ("gemini", "gemini-2.5-flash"),
            ],
            "features": {
                "streaming": True,
                "context_window": 32000,
                "web_search": False,
            },
        },
        # ------------------------------------------------------------------
        # VERICASE ANALYSIS - Flagship multi-agent legal research platform
        # ------------------------------------------------------------------
        "vericase_analysis": {
            "enabled": True,
            "display_name": "VeriCase Analysis",
            "description": "Flagship multi-agent legal research with DAG planning, "
            "semantic search, timeline & delay analysis",
            "category": "flagship",
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "max_tokens": 8000,
            "temperature": 0.2,
            "max_duration_seconds": 600,
            "fallback_chain": [
                ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
                ("anthropic", "claude-sonnet-4.5"),
                ("openai", "gpt-5.2-thinking"),
            ],
            "agents": {
                "planner": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4.5",
                    "description": "Creates DAG research strategy",
                },
                "searcher": {
                    "provider": "bedrock",
                    "model": "amazon.nova-micro-v1:0",
                    "description": "Fast semantic search with 4-vector retrieval",
                },
                "researcher": {
                    "provider": "openai",
                    "model": "gpt-5.2-thinking",
                    "description": "Deep evidence investigation",
                },
                "synthesizer": {
                    "provider": "openai",
                    "model": "gpt-5.2-instant",
                    "description": "Report synthesis and thematic analysis",
                },
                "validator": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4.5",
                    "description": "Quality assurance and hallucination detection",
                },
            },
            "features": {
                "multi_vector_search": True,
                "cross_encoder_reranking": True,
                "mmr_diversity": True,
                "timeline_analysis": True,
                "delay_analysis": True,
                "parallel_execution": True,
            },
        },
        # ------------------------------------------------------------------
        # DEEP RESEARCH - DAG-structured multi-agent investigation (legacy)
        # ------------------------------------------------------------------
        "deep_research": {
            "enabled": True,
            "display_name": "Deep Research",
            "description": "Multi-agent investigation with DAG planning (original name for VeriCase)",
            "category": "research",
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "max_tokens": 8000,
            "temperature": 0.2,
            "max_duration_seconds": 600,
            "fallback_chain": [
                ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
                ("anthropic", "claude-sonnet-4.5"),
                ("openai", "gpt-5.2-thinking"),
            ],
            "agents": {
                "planner": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4.5",
                },
                "researcher": {"provider": "openai", "model": "gpt-5.2-thinking"},
                "synthesizer": {"provider": "openai", "model": "gpt-5.2-instant"},
                "validator": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4.5",
                },
            },
            "features": {
                "dag_planning": True,
                "parallel_execution": True,
                "validation": True,
            },
        },
        # ------------------------------------------------------------------
        # AI REFINEMENT - Intelligent evidence filtering with questions
        # ------------------------------------------------------------------
        "ai_refinement": {
            "enabled": True,
            "display_name": "AI Refinement Wizard",
            "description": "Multi-stage evidence refinement with intelligent questioning",
            "category": "refinement",
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "max_tokens": 4000,
            "temperature": 0.2,
            "max_duration_seconds": 300,
            "fallback_chain": [
                ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
                ("anthropic", "claude-sonnet-4.5"),
                ("openai", "gpt-5.2-instant"),
                ("gemini", "gemini-2.5-flash-lite"),
            ],
            "stages": [
                "initial_analysis",
                "project_cross_reference",
                "spam_detection",
                "people_validation",
                "topic_filtering",
                "domain_questions",
                "final_review",
            ],
            "features": {
                "spam_detection": True,
                "duplicate_detection": True,
                "project_cross_reference": True,
                "progressive_questions": True,
            },
        },
        # ------------------------------------------------------------------
        # CHRONOLOGY BUILDER - Timeline generation from evidence
        # ------------------------------------------------------------------
        "chronology_builder": {
            "enabled": True,
            "display_name": "Chronology Builder",
            "description": "AI-powered timeline generation from emails and documents",
            "category": "timeline",
            "provider": "openai",
            "model": "gpt-5.2-thinking",
            "max_tokens": 8000,
            "temperature": 0.1,
            "max_duration_seconds": 300,
            "fallback_chain": [
                ("bedrock", "amazon.nova-pro-v1:0"),
                ("openai", "gpt-5.2-thinking"),
                ("anthropic", "claude-sonnet-4.5"),
            ],
            "features": {
                "event_extraction": True,
                "date_normalization": True,
                "significance_scoring": True,
                "milestone_detection": True,
            },
        },
        # ------------------------------------------------------------------
        # DELAY ANALYSIS - Causation analysis for construction disputes
        # ------------------------------------------------------------------
        "delay_analysis": {
            "enabled": True,
            "display_name": "Delay Analysis",
            "description": "AI-powered delay causation and entitlement analysis",
            "category": "analysis",
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "max_tokens": 8000,
            "temperature": 0.1,
            "max_duration_seconds": 300,
            "fallback_chain": [
                ("anthropic", "claude-sonnet-4.5"),
                ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
                ("openai", "gpt-5.2-thinking"),
            ],
            "agents": {
                "causation_analyzer": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4.5",
                    "description": "Cause-effect reasoning for delays",
                },
                "impact_quantifier": {
                    "provider": "openai",
                    "model": "gpt-5.2-thinking",
                    "description": "Numerical impact calculations",
                },
                "narrative_generator": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4.5",
                    "description": "Claims narrative generation",
                },
            },
            "features": {
                "causation_chains": True,
                "concurrent_delay_detection": True,
                "entitlement_calculation": True,
                "claims_narrative": True,
            },
        },
        # ------------------------------------------------------------------
        # NATURAL LANGUAGE QUERY - AI-powered email search
        # ------------------------------------------------------------------
        "natural_language_query": {
            "enabled": True,
            "display_name": "Natural Language Search",
            "description": "Search emails using natural language queries",
            "category": "search",
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
            "max_tokens": 2000,
            "temperature": 0.1,
            "max_duration_seconds": 30,
            "fallback_chain": [
                ("bedrock", "amazon.nova-micro-v1:0"),
                ("gemini", "gemini-2.5-flash-lite"),
                ("openai", "gpt-5-mini"),
            ],
            "features": {
                "query_expansion": True,
                "semantic_search": True,
                "filter_generation": True,
            },
        },
        # ------------------------------------------------------------------
        # AUTO CLASSIFICATION - Document categorization
        # ------------------------------------------------------------------
        "auto_classification": {
            "enabled": True,
            "display_name": "Auto Classification",
            "description": "Automatic document and email categorization",
            "category": "classification",
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
            "max_tokens": 1000,
            "temperature": 0.0,
            "max_duration_seconds": 30,
            "fallback_chain": [
                ("bedrock", "amazon.nova-micro-v1:0"),
                ("gemini", "gemini-2.5-flash-lite"),
                ("openai", "gpt-5-mini"),
            ],
            "features": {
                "category_prediction": True,
                "confidence_scores": True,
                "batch_processing": True,
            },
        },
        # ------------------------------------------------------------------
        # DATASET INSIGHTS - AI analysis of email datasets
        # ------------------------------------------------------------------
        "dataset_insights": {
            "enabled": True,
            "display_name": "Dataset Insights",
            "description": "AI-powered analysis of email dataset patterns",
            "category": "analysis",
            "provider": "openai",
            "model": "gpt-5.2-thinking",
            "max_tokens": 4000,
            "temperature": 0.2,
            "max_duration_seconds": 120,
            "fallback_chain": [
                ("openai", "gpt-5.2-thinking"),
                ("anthropic", "claude-sonnet-4.5"),
                ("bedrock", "amazon.nova-pro-v1:0"),
            ],
            "features": {
                "pattern_detection": True,
                "key_player_identification": True,
                "topic_clustering": True,
                "timeline_overview": True,
            },
        },
        # ------------------------------------------------------------------
        # EVIDENCE SUMMARY - Quick document summarization
        # ------------------------------------------------------------------
        "evidence_summary": {
            "enabled": True,
            "display_name": "Evidence Summary",
            "description": "Quick AI summaries of evidence items",
            "category": "summary",
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
            "max_tokens": 2000,
            "temperature": 0.1,
            "max_duration_seconds": 60,
            "fallback_chain": [
                ("bedrock", "amazon.nova-lite-v1:0"),
                ("gemini", "gemini-2.5-flash-lite"),
                ("openai", "gpt-5-mini"),
            ],
            "features": {
                "key_points": True,
                "entity_extraction": True,
                "sentiment_analysis": False,
            },
        },
        # ------------------------------------------------------------------
        # MULTI-MODEL ORCHESTRATION - Cross-model collaboration
        # ------------------------------------------------------------------
        "multi_model_orchestration": {
            "enabled": True,
            "display_name": "Multi-Model Orchestration",
            "description": "Execute tasks across multiple AI models with voting/consensus",
            "category": "orchestration",
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "max_tokens": 4000,
            "temperature": 0.2,
            "max_duration_seconds": 300,
            "models": [
                ("anthropic", "claude-sonnet-4.5"),
                ("openai", "gpt-5.2-instant"),
                ("gemini", "gemini-2.5-flash"),
            ],
            "selection_methods": [
                "first_success",
                "fastest",
                "quality_score",
                "voting",
            ],
            "collaboration_patterns": [
                "draft_refine",
                "generate_validate",
                "parallel_compete",
            ],
        },
    }

    # Default function configurations (cost-aware defaults)
    # Maps internal function names to their configurations
    DEFAULT_FUNCTION_CONFIGS: dict[str, dict[str, Any]] = {
        "quick_search": {
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
            "thinking_enabled": False,
            "max_duration_seconds": 30,
            "fallback_chain": [
                ("bedrock", "amazon.nova-micro-v1:0"),
                ("bedrock", "amazon.nova-lite-v1:0"),
                ("gemini", "gemini-2.5-flash-lite"),
                ("openai", "gpt-5-mini"),
            ],
        },
        "deep_analysis": {
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "thinking_enabled": True,
            "thinking_budget_tokens": 5000,
            "max_duration_seconds": 300,
            "orchestration": {
                "enabled": False,
                "mode": "parallel",
                "models": [],
            },
            "fallback_chain": [
                ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
                ("anthropic", "claude-sonnet-4.5"),
                ("openai", "gpt-5.2-thinking"),
            ],
        },
        "synthesis": {
            "provider": "openai",
            "model": "gpt-5.2-instant",
            "max_duration_seconds": 180,
            "fallback_chain": [
                ("openai", "gpt-5.2-instant"),
                ("anthropic", "claude-sonnet-4.5"),
                ("bedrock", "amazon.nova-pro-v1:0"),
            ],
        },
        "validation": {
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "max_duration_seconds": 120,
            "fallback_chain": [
                ("anthropic", "claude-sonnet-4.5"),
                ("gemini", "gemini-2.5-flash-lite"),
                ("openai", "gpt-5.2-instant"),
            ],
        },
        "causation_analysis": {
            "provider": "anthropic",
            "model": "claude-sonnet-4.5",
            "max_duration_seconds": 180,
            "description": "Delay causation analysis - Claude excels at analytical reasoning",
            "fallback_chain": [
                ("anthropic", "claude-sonnet-4.5"),
                ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
                ("openai", "gpt-5.2-thinking"),
            ],
        },
        "timeline": {
            "provider": "bedrock",
            "model": "amazon.nova-lite-v1:0",
            "max_duration_seconds": 120,
            "description": "Timeline generation - cost-effective for structured output",
            "fallback_chain": [
                ("bedrock", "amazon.nova-lite-v1:0"),
                ("openai", "gpt-5.2-instant"),
                ("gemini", "gemini-2.5-flash"),
            ],
        },
        "reranking": {
            "provider": "bedrock",
            "model": "amazon.nova-micro-v1:0",
            "max_duration_seconds": 30,
            "description": "Fast reranking for search results",
            "fallback_chain": [
                ("bedrock", "amazon.nova-micro-v1:0"),
                ("gemini", "gemini-2.5-flash-lite"),
            ],
        },
    }

    # Orchestration settings per agent role
    DEFAULT_AGENT_CONFIGS: dict[str, dict[str, Any]] = {
        "planner": {
            "primary_provider": "anthropic",
            "primary_model": "claude-sonnet-4.5",
            "description": "Research planning - Claude for long-context planning",
        },
        "researcher": {
            "primary_provider": "openai",
            "primary_model": "gpt-5.2-thinking",
            "description": "Evidence investigation - GPT-4 for comprehension",
        },
        "synthesizer": {
            "primary_provider": "openai",
            "primary_model": "gpt-5.2-instant",
            "description": "Report synthesis - GPT-4 for coherent writing",
        },
        "validator": {
            "primary_provider": "anthropic",
            "primary_model": "claude-sonnet-4.5",
            "description": "Validation - Claude for analytical checking",
        },
        "reranker": {
            "primary_provider": "bedrock",
            "primary_model": "amazon.nova-micro-v1:0",
            "description": "Reranking - fast and cost-effective",
        },
    }

    # Bedrock model mapping for Claude routing
    CLAUDE_TO_BEDROCK_MAP: dict[str, str] = {
        # Claude 4.5 series
        "claude-4.5-opus": "anthropic.claude-4.5-opus-v1:0",
        "claude-4.5-sonnet": "anthropic.claude-4.5-sonnet-v1:0",
        "claude-4.5-haiku": "anthropic.claude-haiku-4-5-20251001-v1:0",
        # Common direct Anthropic IDs used in configuration/UI
        "claude-opus-4.5": "anthropic.claude-opus-4-5-20251101-v1:0",
        "claude-sonnet-4.5": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        # Claude 4.1 series
        "claude-4.1-opus": "anthropic.claude-4.1-opus-v1:0",
        "claude-4.1-sonnet": "anthropic.claude-4.1-sonnet-v1:0",
        # Claude 4.0 series
        "claude-4-opus": "anthropic.claude-4-opus-v1:0",
        "claude-4-sonnet": "anthropic.claude-4-sonnet-v1:0",
        "claude-4-haiku": "anthropic.claude-4-haiku-v1:0",
        # Claude 3.5 series
        "claude-3.5-sonnet": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "claude-3-5-sonnet-20241022": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "claude-3.5-haiku": "anthropic.claude-3-5-haiku-20240620-v1:0",
    }

    @classmethod
    def refresh_cache(cls, db: Session) -> None:
        """Reload all AI settings from database"""
        cls._cache = {}

        try:
            ai_settings = (
                db.query(AppSetting)
                .filter(
                    AppSetting.key.like("openai_%")
                    | AppSetting.key.like("anthropic_%")
                    | AppSetting.key.like("gemini_%")
                    | AppSetting.key.like("bedrock_%")
                    | AppSetting.key.like("ai_%")
                )
                .all()
            )

            for setting in ai_settings:
                cls._cache[setting.key] = setting.value

            cls._cache_valid = True
            logger.debug(f"AI settings cache refreshed with {len(cls._cache)} settings")

        except Exception as e:
            logger.warning(f"Failed to load AI settings from database: {e}")
            cls._cache_valid = False

    @classmethod
    def get(
        cls, key: str, db: Session | None = None, default: str | None = None
    ) -> str | None:
        """
        Get an AI setting value.
        Priority: Database > Environment Variable > Default
        """
        # Try cache first
        if cls._cache_valid and key in cls._cache:
            return cls._cache[key]

        # Try database if session provided
        if db is not None:
            try:
                setting = db.query(AppSetting).filter(AppSetting.key == key).first()
                if setting and setting.value:
                    cls._cache[key] = setting.value
                    return setting.value
            except Exception as e:
                logger.debug(f"Failed to get setting {key} from DB: {e}")

        # Try environment variable (map key to env var name)
        env_map = {
            "openai_api_key": "OPENAI_API_KEY",
            "anthropic_api_key": "CLAUDE_API_KEY",
            "gemini_api_key": "GEMINI_API_KEY",
            "xai_api_key": "XAI_API_KEY",
            "grok_api_key": "GROK_API_KEY",
            "perplexity_api_key": "PERPLEXITY_API_KEY",
            "bedrock_enabled": "BEDROCK_ENABLED",
            "bedrock_region": "BEDROCK_REGION",
            "bedrock_route_claude": "BEDROCK_ROUTE_CLAUDE",
            "ai_fallback_enabled": "AI_FALLBACK_ENABLED",
            "ai_fallback_log_attempts": "AI_FALLBACK_LOG_ATTEMPTS",
            "ai_routing_strategy": "AI_ROUTING_STRATEGY",
            "ai_prefer_bedrock": "AI_PREFER_BEDROCK",
            "ai_enable_multi_model": "AI_ENABLE_MULTI_MODEL",
            "ai_enable_validation": "AI_ENABLE_VALIDATION",
        }

        env_var = env_map.get(key)
        if env_var:
            # Use os.getenv directly - config_production.py loads secrets into os.environ
            # at startup, but env_settings Pydantic object was created before that
            import os

            env_value = os.getenv(env_var)
            # Backward/forward compatibility for Anthropic key naming.
            if env_value is None and key == "anthropic_api_key":
                env_value = os.getenv("ANTHROPIC_API_KEY")
            if env_value is not None:
                return env_value

        return default

    @classmethod
    def get_api_key(cls, provider: str, db: Session | None = None) -> str | None:
        """Get API key for a specific provider"""
        key = f"{provider}_api_key"
        return cls.get(key, db)

    @classmethod
    def get_model(cls, provider: str, db: Session | None = None) -> str:
        """Get selected model for a specific provider"""
        key = f"{provider}_model"
        return cls.get(key, db) or cls.DEFAULT_MODELS.get(provider, "")

    @classmethod
    def get_default_provider(cls, db: Session | None = None) -> str:
        """Get the default AI provider"""
        return cls.get("ai_default_provider", db) or "gemini"

    @classmethod
    def is_web_search_enabled(cls, db: Session | None = None) -> bool:
        """Check if web search is enabled for AI queries"""
        value = cls.get("ai_web_search_enabled", db)
        return value == "true" if value else False

    @classmethod
    def get_all_configured_providers(
        cls, db: Session | None = None
    ) -> dict[str, dict[str, str | bool]]:
        """Get status of all AI providers"""
        # Check Bedrock availability
        bedrock_enabled = cls.get("bedrock_enabled", db) == "true"
        bedrock_region = cls.get("bedrock_region", db) or "us-east-1"

        providers = {
            "openai": {
                "name": "OpenAI (GPT)",
                "available": bool(cls.get_api_key("openai", db)),
                "model": cls.get_model("openai", db),
                "task": "Chronology & Event Analysis",
            },
            "anthropic": {
                "name": "Anthropic (Claude)",
                "available": bool(cls.get_api_key("anthropic", db)),
                "model": cls.get_model("anthropic", db),
                "task": "Narrative Construction",
            },
            "gemini": {
                "name": "Google (Gemini)",
                "available": bool(cls.get_api_key("gemini", db)),
                "model": cls.get_model("gemini", db),
                "task": "Pattern Recognition",
            },
            "bedrock": {
                "name": "Amazon Bedrock",
                "available": bedrock_enabled,
                "model": cls.get_model("bedrock", db),
                "region": bedrock_region,
                "task": "Enterprise AI (Claude, Nova, Titan, Llama)",
            },
            "xai": {
                "name": "xAI (Grok)",
                "available": bool(cls.get_api_key("xai", db)),
                "model": cls.get_model("xai", db) or "grok-3-latest",
                "task": "Real-time Analysis & Reasoning",
            },
            "perplexity": {
                "name": "Perplexity (Sonar)",
                "available": bool(cls.get_api_key("perplexity", db)),
                "model": cls.get_model("perplexity", db) or "sonar-pro",
                "task": "Research & Web Search",
            },
        }
        return providers

    @classmethod
    def get_function_config(
        cls, function_name: str, db: Session | None = None
    ) -> dict[str, Any]:
        """
        Get configuration for a specific AI function (quick_search, deep_analysis)

        Args:
            function_name: Name of the function (quick_search, deep_analysis)
            db: Database session

        Returns:
            Function configuration dict
        """
        key = f"ai_function_{function_name}"

        # Build defaults first (always return at least the current default schema)
        defaults = cls.DEFAULT_FUNCTION_CONFIGS.get(
            function_name, cls.DEFAULT_FUNCTION_CONFIGS["quick_search"]
        ).copy()

        # Try to get from database/cache
        config_json = cls.get(key, db)
        if config_json:
            try:
                saved = json.loads(config_json)
                if isinstance(saved, dict):
                    # Merge with defaults to ensure new fields (e.g., fallback_chain)
                    # are present even if an older DB entry predates them.
                    if isinstance(defaults.get("orchestration"), dict) and isinstance(
                        saved.get("orchestration"), dict
                    ):
                        merged_orchestration = defaults["orchestration"].copy()
                        merged_orchestration.update(saved["orchestration"])
                        saved["orchestration"] = merged_orchestration

                    defaults.update(saved)
                    return defaults
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON for {key}, using defaults")

        return defaults

    @classmethod
    def set_function_config(
        cls, function_name: str, config: dict[str, Any], db: Session
    ) -> bool:
        """
        Save configuration for a specific AI function

        Args:
            function_name: Name of the function
            config: Configuration dict
            db: Database session

        Returns:
            True if saved successfully
        """
        key = f"ai_function_{function_name}"
        try:
            config_json = json.dumps(config)

            # Update or create setting
            setting = db.query(AppSetting).filter(AppSetting.key == key).first()
            if setting:
                setting.value = config_json
            else:
                setting = AppSetting(key=key, value=config_json)
                db.add(setting)

            db.commit()

            # Update cache
            cls._cache[key] = config_json
            return True

        except Exception as e:
            logger.error(f"Failed to save function config {function_name}: {e}")
            db.rollback()
            return False

    @classmethod
    def get_agent_config(
        cls, agent_name: str, db: Session | None = None
    ) -> dict[str, Any]:
        """
        Get configuration for a specific agent (planner, researcher, etc.)

        Args:
            agent_name: Name of the agent (planner, researcher, synthesizer, validator, reranker)
            db: Database session

        Returns:
            Agent configuration dict
        """
        key = f"ai_agent_{agent_name}"

        # Try to get from database/cache
        config_json = cls.get(key, db)
        if config_json:
            try:
                return json.loads(config_json)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON for {key}, using defaults")

        # Return default config
        return cls.DEFAULT_AGENT_CONFIGS.get(
            agent_name, cls.DEFAULT_AGENT_CONFIGS.get("researcher", {})
        )

    @classmethod
    def set_agent_config(
        cls, agent_name: str, config: dict[str, Any], db: Session
    ) -> bool:
        """
        Save configuration for a specific agent

        Args:
            agent_name: Name of the agent
            config: Configuration dict
            db: Database session

        Returns:
            True if saved successfully
        """
        key = f"ai_agent_{agent_name}"
        try:
            config_json = json.dumps(config)

            setting = db.query(AppSetting).filter(AppSetting.key == key).first()
            if setting:
                setting.value = config_json
            else:
                setting = AppSetting(key=key, value=config_json)
                db.add(setting)

            db.commit()
            cls._cache[key] = config_json
            return True

        except Exception as e:
            logger.error(f"Failed to save agent config {agent_name}: {e}")
            db.rollback()
            return False

    # ==========================================================================
    # AI TOOL CONFIGURATION METHODS
    # ==========================================================================

    @classmethod
    def get_tool_config(
        cls, tool_name: str, db: Session | None = None
    ) -> dict[str, Any]:
        """
        Get configuration for a specific AI tool.

        Args:
            tool_name: Name of the tool (e.g., 'vericase_analysis', 'ai_refinement')
            db: Database session

        Returns:
            Tool configuration dict including provider, model, features, etc.
        """
        key = f"ai_tool_{tool_name}"

        # Try to get from database/cache (admin overrides)
        config_json = cls.get(key, db)
        if config_json:
            try:
                # Merge with defaults to ensure all fields present
                defaults = cls.DEFAULT_TOOL_CONFIGS.get(tool_name, {}).copy()
                saved = json.loads(config_json)
                defaults.update(saved)
                return defaults
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON for {key}, using defaults")

        # Return default config
        return cls.DEFAULT_TOOL_CONFIGS.get(tool_name, {})

    @classmethod
    def set_tool_config(
        cls, tool_name: str, config: dict[str, Any], db: Session
    ) -> bool:
        """
        Save configuration for a specific AI tool.

        Args:
            tool_name: Name of the tool
            config: Configuration dict
            db: Database session

        Returns:
            True if saved successfully
        """
        key = f"ai_tool_{tool_name}"
        try:
            config_json = json.dumps(config)

            setting = db.query(AppSetting).filter(AppSetting.key == key).first()
            if setting:
                setting.value = config_json
            else:
                setting = AppSetting(key=key, value=config_json)
                db.add(setting)

            db.commit()
            cls._cache[key] = config_json
            return True

        except Exception as e:
            logger.error(f"Failed to save tool config {tool_name}: {e}")
            db.rollback()
            return False

    @classmethod
    def is_tool_enabled(cls, tool_name: str, db: Session | None = None) -> bool:
        """
        Check if a specific AI tool is enabled.

        Args:
            tool_name: Name of the tool
            db: Database session

        Returns:
            True if tool is enabled
        """
        config = cls.get_tool_config(tool_name, db)
        return config.get("enabled", True)

    @classmethod
    def get_tool_provider_model(
        cls, tool_name: str, db: Session | None = None
    ) -> tuple[str, str]:
        """
        Get the provider and model for a specific AI tool.

        Args:
            tool_name: Name of the tool
            db: Database session

        Returns:
            Tuple of (provider, model)
        """
        config = cls.get_tool_config(tool_name, db)
        provider = config.get("provider", "gemini")
        model = config.get("model", cls.DEFAULT_MODELS.get(provider, ""))
        return provider, model

    @classmethod
    def get_tool_fallback_chain(
        cls, tool_name: str, db: Session | None = None
    ) -> list[tuple[str, str]]:
        """
        Get the fallback chain for a specific AI tool.

        Args:
            tool_name: Name of the tool
            db: Database session

        Returns:
            List of (provider, model) tuples
        """
        config = cls.get_tool_config(tool_name, db)
        fallback_chain = config.get("fallback_chain", [])
        return [(str(p), str(m)) for p, m in fallback_chain]

    @classmethod
    def get_tool_agent_config(
        cls, tool_name: str, agent_name: str, db: Session | None = None
    ) -> dict[str, Any]:
        """
        Get configuration for a specific agent within a tool.

        Args:
            tool_name: Name of the tool (e.g., 'vericase_analysis')
            agent_name: Name of the agent (e.g., 'planner', 'researcher')
            db: Database session

        Returns:
            Agent configuration dict
        """
        config = cls.get_tool_config(tool_name, db)
        agents = config.get("agents", {})
        return agents.get(agent_name, {})

    @classmethod
    def get_all_tool_configs(
        cls, db: Session | None = None
    ) -> dict[str, dict[str, Any]]:
        """
        Get configurations for all AI tools.

        Args:
            db: Database session

        Returns:
            Dict of tool_name -> configuration
        """
        result = {}
        for tool_name in cls.DEFAULT_TOOL_CONFIGS:
            result[tool_name] = cls.get_tool_config(tool_name, db)
        return result

    @classmethod
    def get_enabled_tools(cls, db: Session | None = None) -> list[dict[str, Any]]:
        """
        Get list of all enabled AI tools with their configurations.

        Args:
            db: Database session

        Returns:
            List of enabled tool configurations
        """
        enabled = []
        for tool_name, config in cls.get_all_tool_configs(db).items():
            if config.get("enabled", True):
                tool_info = {
                    "name": tool_name,
                    "display_name": config.get("display_name", tool_name),
                    "description": config.get("description", ""),
                    "category": config.get("category", "general"),
                    "provider": config.get("provider"),
                    "model": config.get("model"),
                }
                enabled.append(tool_info)
        return enabled

    @classmethod
    def get_orchestration_settings(cls, db: Session | None = None) -> dict[str, Any]:
        """
        Get global orchestration settings

        Returns:
            Orchestration configuration including:
            - routing_strategy: performance|cost|latency|balanced
            - max_latency_ms: Maximum acceptable latency
            - min_quality_score: Minimum quality threshold
            - prefer_bedrock: Whether to prefer Bedrock models
            - enable_validation: Whether to run validation phase
            - enable_multi_model: Whether to enable multi-model execution
        """
        key = "ai_orchestration_settings"
        config_json = cls.get(key, db)

        defaults = {
            "routing_strategy": "balanced",
            "max_latency_ms": 5000,
            "min_quality_score": 0.6,
            "prefer_bedrock": True,
            "enable_validation": True,
            "enable_multi_model": False,
            "cost_budget_per_session": None,  # No limit by default
            "latency_weight": 0.3,
            "quality_weight": 0.5,
            "cost_weight": 0.2,
        }

        if config_json:
            try:
                saved = json.loads(config_json)
                defaults.update(saved)
            except json.JSONDecodeError:
                pass

        return defaults

    @classmethod
    def set_orchestration_settings(cls, settings: dict[str, Any], db: Session) -> bool:
        """Save global orchestration settings"""
        key = "ai_orchestration_settings"
        try:
            config_json = json.dumps(settings)

            setting = db.query(AppSetting).filter(AppSetting.key == key).first()
            if setting:
                setting.value = config_json
            else:
                setting = AppSetting(key=key, value=config_json)
                db.add(setting)

            db.commit()
            cls._cache[key] = config_json
            return True

        except Exception as e:
            logger.error(f"Failed to save orchestration settings: {e}")
            db.rollback()
            return False

    @classmethod
    def get_pinned_model(
        cls, function_name: str, db: Session | None = None
    ) -> tuple[str, str] | None:
        """
        Get admin-pinned model for a function if set

        Returns:
            Tuple of (provider, model_id) or None if not pinned
        """
        key = f"ai_pinned_model_{function_name}"
        value = cls.get(key, db)

        if value and ":" in value:
            provider, model_id = value.split(":", 1)
            return (provider, model_id)

        return None

    @classmethod
    def set_pinned_model(
        cls, function_name: str, provider: str, model_id: str, db: Session
    ) -> bool:
        """Pin a specific model for a function"""
        key = f"ai_pinned_model_{function_name}"
        value = f"{provider}:{model_id}"

        try:
            setting = db.query(AppSetting).filter(AppSetting.key == key).first()
            if setting:
                setting.value = value
            else:
                setting = AppSetting(key=key, value=value)
                db.add(setting)

            db.commit()
            cls._cache[key] = value
            return True

        except Exception as e:
            logger.error(f"Failed to pin model for {function_name}: {e}")
            db.rollback()
            return False

    @classmethod
    def clear_pinned_model(cls, function_name: str, db: Session) -> bool:
        """Remove pinned model for a function"""
        key = f"ai_pinned_model_{function_name}"

        try:
            setting = db.query(AppSetting).filter(AppSetting.key == key).first()
            if setting:
                db.delete(setting)
                db.commit()

            if key in cls._cache:
                del cls._cache[key]

            return True

        except Exception as e:
            logger.error(f"Failed to clear pinned model for {function_name}: {e}")
            db.rollback()
            return False

    @classmethod
    def is_bedrock_enabled(cls, db: Session | None = None) -> bool:
        """Check if Amazon Bedrock is enabled"""
        return cls.get("bedrock_enabled", db) == "true"

    @classmethod
    def get_bedrock_region(cls, db: Session | None = None) -> str:
        """Get configured Bedrock region"""
        return cls.get("bedrock_region", db) or "us-east-1"

    @classmethod
    def is_bedrock_route_claude(cls, db: Session | None = None) -> bool:
        """Check if Claude requests should be routed through Bedrock"""
        return cls.get("bedrock_route_claude", db) == "true"

    @classmethod
    def is_fallback_enabled(cls, db: Session | None = None) -> bool:
        """Check if AI fallback is enabled"""
        value = cls.get("ai_fallback_enabled", db)
        # Default to True if not set
        return value != "false"

    @classmethod
    def is_fallback_logging_enabled(cls, db: Session | None = None) -> bool:
        """Check if fallback logging is enabled"""
        value = cls.get("ai_fallback_log_attempts", db)
        # Default to True if not set
        return value != "false"

    @classmethod
    def get_effective_provider(
        cls,
        requested_provider: str,
        model: str,
        db: Session | None = None,
    ) -> tuple[str, str]:
        """
        Get the effective provider and model after applying routing rules.

        If bedrock_route_claude is enabled and the requested provider is Anthropic,
        the request will be routed through Bedrock instead.

        Args:
            requested_provider: The originally requested provider
            model: The originally requested model
            db: Database session

        Returns:
            Tuple of (effective_provider, effective_model)
        """
        # Check if Bedrock routing is enabled for Claude
        if cls.is_bedrock_route_claude(db) and requested_provider == "anthropic":
            # Check if Bedrock is actually available
            if cls.is_bedrock_enabled(db):
                # Try to map the model to Bedrock equivalent
                bedrock_model = cls.CLAUDE_TO_BEDROCK_MAP.get(model)
                if bedrock_model:
                    logger.debug(
                        f"Routing {requested_provider}/{model} -> bedrock/{bedrock_model}"
                    )
                    return "bedrock", bedrock_model
                else:
                    logger.warning(
                        f"No Bedrock mapping for model {model}, using direct Anthropic API"
                    )

        return requested_provider, model


# Convenience functions for direct import
def get_ai_api_key(provider: str, db: Session | None = None) -> str | None:
    return AISettings.get_api_key(provider, db)


def get_ai_model(provider: str, db: Session | None = None) -> str:
    return AISettings.get_model(provider, db)


def get_ai_providers_status(
    db: Session | None = None,
) -> dict[str, dict[str, str | bool]]:
    return AISettings.get_all_configured_providers(db)


def get_function_config(
    function_name: str, db: Session | None = None
) -> dict[str, Any]:
    """Get configuration for an AI function (quick_search, deep_analysis)"""
    return AISettings.get_function_config(function_name, db)


def is_bedrock_enabled(db: Session | None = None) -> bool:
    """Check if Amazon Bedrock is enabled"""
    return AISettings.is_bedrock_enabled(db)


def get_bedrock_region(db: Session | None = None) -> str:
    """Get configured Bedrock region"""
    return AISettings.get_bedrock_region(db)


def is_bedrock_route_claude(db: Session | None = None) -> bool:
    """Check if Claude requests should be routed through Bedrock"""
    return AISettings.is_bedrock_route_claude(db)


def is_fallback_enabled(db: Session | None = None) -> bool:
    """Check if AI fallback is enabled"""
    return AISettings.is_fallback_enabled(db)


def is_fallback_logging_enabled(db: Session | None = None) -> bool:
    """Check if fallback logging is enabled"""
    return AISettings.is_fallback_logging_enabled(db)


def get_effective_provider(
    requested_provider: str,
    model: str,
    db: Session | None = None,
) -> tuple[str, str]:
    """Get effective provider after applying routing rules (Bedrock-first, etc.)"""
    return AISettings.get_effective_provider(requested_provider, model, db)


def get_agent_config(agent_name: str, db: Session | None = None) -> dict[str, Any]:
    """Get configuration for an AI agent (planner, researcher, etc.)"""
    return AISettings.get_agent_config(agent_name, db)


def get_orchestration_settings(db: Session | None = None) -> dict[str, Any]:
    """Get global orchestration settings"""
    return AISettings.get_orchestration_settings(db)


# =============================================================================
# AI TOOL CONFIGURATION CONVENIENCE FUNCTIONS
# =============================================================================


def get_tool_config(tool_name: str, db: Session | None = None) -> dict[str, Any]:
    """Get configuration for an AI tool (vericase_analysis, ai_refinement, etc.)"""
    return AISettings.get_tool_config(tool_name, db)


def is_tool_enabled(tool_name: str, db: Session | None = None) -> bool:
    """Check if a specific AI tool is enabled"""
    return AISettings.is_tool_enabled(tool_name, db)


def get_tool_provider_model(
    tool_name: str, db: Session | None = None
) -> tuple[str, str]:
    """Get the provider and model for a specific AI tool"""
    return AISettings.get_tool_provider_model(tool_name, db)


def get_tool_fallback_chain(
    tool_name: str, db: Session | None = None
) -> list[tuple[str, str]]:
    """Get the fallback chain for a specific AI tool"""
    return AISettings.get_tool_fallback_chain(tool_name, db)


def get_tool_agent_config(
    tool_name: str, agent_name: str, db: Session | None = None
) -> dict[str, Any]:
    """Get configuration for a specific agent within a tool"""
    return AISettings.get_tool_agent_config(tool_name, agent_name, db)


def get_all_tool_configs(db: Session | None = None) -> dict[str, dict[str, Any]]:
    """Get configurations for all AI tools"""
    return AISettings.get_all_tool_configs(db)


def get_enabled_tools(db: Session | None = None) -> list[dict[str, Any]]:
    """Get list of all enabled AI tools with their configurations"""
    return AISettings.get_enabled_tools(db)


def get_pinned_model(
    function_name: str, db: Session | None = None
) -> tuple[str, str] | None:
    """Get admin-pinned model for a function"""
    return AISettings.get_pinned_model(function_name, db)
