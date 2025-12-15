from __future__ import annotations

"""
AI Settings Manager - Loads AI configuration from database with fallback to environment variables
Supports: OpenAI, Anthropic, Gemini, Amazon Bedrock, xAI, and Perplexity providers
"""
import json
import logging
from typing import Any
from sqlalchemy.orm import Session

from .config import settings as env_settings
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
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-20250514",  # Correct Anthropic Claude Sonnet 4 model ID
        "gemini": "gemini-2.0-flash",
        "bedrock": "amazon.nova-pro-v1:0",  # Amazon Nova Pro (cost-effective)
        "xai": "grok-4.1-fast",
        "perplexity": "sonar",
    }

    # Default function configurations (cost-aware defaults)
    DEFAULT_FUNCTION_CONFIGS: dict[str, dict[str, Any]] = {
        "quick_search": {
            "provider": "gemini",
            "model": "gemini-2.0-flash",  # Budget tier
            "thinking_enabled": False,
            "max_duration_seconds": 30,
            "fallback_chain": [
                ("bedrock", "amazon.nova-micro-v1:0"),
                ("bedrock", "amazon.nova-lite-v1:0"),
                ("gemini", "gemini-2.0-flash"),
            ],
        },
        "deep_analysis": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",  # Correct Anthropic model ID
            "thinking_enabled": True,
            "thinking_budget_tokens": 5000,  # Reduced for cost efficiency
            "max_duration_seconds": 300,
            "orchestration": {
                "enabled": False,
                "mode": "parallel",
                "models": [],
            },
            "fallback_chain": [
                ("bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
                ("anthropic", "claude-sonnet-4-20250514"),
                ("openai", "gpt-4o"),
            ],
        },
        "synthesis": {
            "provider": "openai",
            "model": "gpt-4o",
            "max_duration_seconds": 180,
            "fallback_chain": [
                ("openai", "gpt-4o"),
                ("anthropic", "claude-sonnet-4-20250514"),
                ("bedrock", "amazon.nova-pro-v1:0"),
            ],
        },
        "validation": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "max_duration_seconds": 120,
            "fallback_chain": [
                ("anthropic", "claude-sonnet-4-20250514"),
                ("gemini", "gemini-2.0-flash"),
                ("openai", "gpt-4o"),
            ],
        },
        "causation_analysis": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "max_duration_seconds": 180,
            "description": "Delay causation analysis - Claude excels at analytical reasoning",
            "fallback_chain": [
                ("anthropic", "claude-sonnet-4-20250514"),
                ("bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
                ("openai", "gpt-4o"),
            ],
        },
        "timeline": {
            "provider": "bedrock",
            "model": "amazon.nova-lite-v1:0",
            "max_duration_seconds": 120,
            "description": "Timeline generation - cost-effective for structured output",
            "fallback_chain": [
                ("bedrock", "amazon.nova-lite-v1:0"),
                ("openai", "gpt-4o"),
                ("gemini", "gemini-2.0-flash"),
            ],
        },
        "reranking": {
            "provider": "bedrock",
            "model": "amazon.nova-micro-v1:0",
            "max_duration_seconds": 30,
            "description": "Fast reranking for search results",
            "fallback_chain": [
                ("bedrock", "amazon.nova-micro-v1:0"),
                ("gemini", "gemini-2.0-flash"),
            ],
        },
    }

    # Orchestration settings per agent role
    DEFAULT_AGENT_CONFIGS: dict[str, dict[str, Any]] = {
        "planner": {
            "primary_provider": "anthropic",
            "primary_model": "claude-sonnet-4-20250514",
            "description": "Research planning - Claude for long-context planning",
        },
        "researcher": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "description": "Evidence investigation - GPT-4 for comprehension",
        },
        "synthesizer": {
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "description": "Report synthesis - GPT-4 for coherent writing",
        },
        "validator": {
            "primary_provider": "anthropic",
            "primary_model": "claude-sonnet-4-20250514",
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
            env_value_raw: object | None = getattr(env_settings, env_var, None)
            if env_value_raw is not None:
                return str(env_value_raw)

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

        # Try to get from database/cache
        config_json = cls.get(key, db)
        if config_json:
            try:
                return json.loads(config_json)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON for {key}, using defaults")

        # Return default config
        return cls.DEFAULT_FUNCTION_CONFIGS.get(
            function_name, cls.DEFAULT_FUNCTION_CONFIGS["quick_search"]
        )

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
    def set_orchestration_settings(
        cls, settings: dict[str, Any], db: Session
    ) -> bool:
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


def get_function_config(function_name: str, db: Session | None = None) -> dict[str, Any]:
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


def get_pinned_model(function_name: str, db: Session | None = None) -> tuple[str, str] | None:
    """Get admin-pinned model for a function"""
    return AISettings.get_pinned_model(function_name, db)
