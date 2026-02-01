"""
Canonical AI Model Registry -- definitions, catalog, and runtime metrics.

This is the **single source of truth** for:
- Model catalog (AI_MODELS_2025) with provider metadata and per-model info
- Friendly-name alias resolution (FRIENDLY_MODEL_ALIASES, resolve_friendly_model)
- Task-complexity routing (AIModelService, ModelPriorityManager, TaskComplexity)
- Real-time performance tracking (ModelRegistry, ModelMetrics)

Other modules (ai_models.py, ai_models_2025.py) re-export from here so that
existing import paths remain valid.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypedDict, cast

from .ai_pricing import estimate_cost_usd
from .config import settings

logger = logging.getLogger(__name__)

# Try to import Redis for persistent metrics
try:
    from redis import Redis

    REDIS_AVAILABLE = True
except ImportError:
    Redis = None  # type: ignore
    REDIS_AVAILABLE = False


# ============================================================================
# Model Catalog (formerly in ai_models_2025.py)
# ============================================================================

# Latest AI Models - Updated December 2025
AI_MODELS_2025: dict[str, dict[str, Any]] = {
    "openai": {
        "provider_name": "OpenAI",
        "icon": "fa-brain",
        "color": "#10a37f",
        "models": [
            # GPT-5.2 Models (December 2025)
            {
                "id": "gpt-5.2-instant",
                "name": "GPT-5.2 Instant",
                "description": "Speed-optimized GPT-5.2 model",
                "type": "fast",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 400000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-5.2-thinking",
                "name": "GPT-5.2 Thinking",
                "description": "Reasoning-optimized GPT-5.2 model",
                "type": "reasoning",
                "capabilities": ["chat", "reasoning", "analysis", "code", "multimodal"],
                "context_window": 400000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-5.2-pro",
                "name": "GPT-5.2 Pro",
                "description": "Highest quality GPT-5.2 model for critical decisions",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "multimodal"],
                "context_window": 400000,
                "cost_tier": "premium",
            },
            # GPT-5 Models (August 2025)
            {
                "id": "gpt-5.1",
                "name": "GPT-5.1 Flagship",
                "description": "Unified GPT-5 flagship model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "multimodal"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-5-mini",
                "name": "GPT-5 Mini",
                "description": "Cost-optimized GPT-5 mini model",
                "type": "mini",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
            # GPT-4o Models (current flagship)
            {
                "id": "gpt-4o",
                "name": "GPT-4o (Flagship)",
                "description": "Multimodal GPT-4 Turbo - fastest and most capable",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "code", "analysis", "multimodal"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-4o-mini",
                "name": "GPT-4o Mini (Fast)",
                "description": "Fast multimodal model",
                "type": "fast",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
            # GPT-4 Turbo
            {
                "id": "gpt-4-turbo",
                "name": "GPT-4 Turbo",
                "description": "GPT-4 with 128K context",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            # OpenAI Reasoning Models (o1 series)
            {
                "id": "o1",
                "name": "o1 (Reasoning)",
                "description": "Advanced reasoning model for complex problems",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "problem_solving"],
                "context_window": 128000,
                "cost_tier": "premium",
            },
            {
                "id": "o1-mini",
                "name": "o1-mini (Fast Reasoning)",
                "description": "Fast reasoning model",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            # Embeddings
            {
                "id": "text-embedding-3-large",
                "name": "Embedding 3 Large",
                "description": "High-performance text embeddings",
                "type": "embedding",
                "capabilities": ["embedding"],
                "context_window": 8191,
                "cost_tier": "budget",
            },
            {
                "id": "text-embedding-3-small",
                "name": "Embedding 3 Small",
                "description": "Efficient text embeddings",
                "type": "embedding",
                "capabilities": ["embedding"],
                "context_window": 8191,
                "cost_tier": "budget",
            },
        ],
        # Default should favor a fast, general-purpose model.
        "default": "gpt-5.2-instant",
    },
    "anthropic": {
        "provider_name": "Anthropic",
        "icon": "fa-comment-dots",
        "color": "#d97706",
        "models": [
            # Claude 4.5 Series (December 2025 - Latest)
            {
                "id": "claude-opus-4.5-20251201",
                "name": "Claude Opus 4.5 (Latest Flagship)",
                "description": "Most advanced Claude model with extended reasoning",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "claude-sonnet-4.5-20251201",
                "name": "Claude Sonnet 4.5 (Latest Workhorse)",
                "description": "Latest balanced Claude model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "claude-haiku-4.5-20251201",
                "name": "Claude Haiku 4.5 (Latest Fast)",
                "description": "Fastest Claude 4.5 model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget",
            },
            # Claude 4 Series (May 2025)
            {
                "id": "claude-opus-4-20250514",
                "name": "Claude Opus 4",
                "description": "Claude 4 flagship with extended thinking",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "claude-sonnet-4-20250514",
                "name": "Claude Sonnet 4",
                "description": "Claude 4 workhorse model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            # Claude 3.5 Series (Oct 2024)
            {
                "id": "claude-3-5-sonnet-20241022",
                "name": "Claude 3.5 Sonnet",
                "description": "Claude 3.5 Sonnet",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "claude-3-5-haiku-20241022",
                "name": "Claude 3.5 Haiku",
                "description": "Claude 3.5 fast model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget",
            },
        ],
        # Default to latest Claude 4.5 Sonnet.
        "default": "claude-sonnet-4.5-20251201",
    },
    "gemini": {
        "provider_name": "Google Gemini",
        "icon": "fa-gem",
        "color": "#4285f4",
        "models": [
            # Gemini 3 / 2.5 Series (2025)
            {
                "id": "gemini-3-pro-preview",
                "name": "Gemini 3 Pro Preview",
                "description": "Most advanced Gemini model (preview)",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "multimodal", "code"],
                "context_window": 1048576,
                "cost_tier": "standard",
            },
            {
                "id": "gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "description": "Advanced reasoning Gemini 2.5 Pro model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "multimodal", "code"],
                "context_window": 1048576,
                "cost_tier": "standard",
            },
            {
                "id": "gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "description": "Balanced speed/capability Gemini 2.5 Flash model",
                "type": "fast",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 1048576,
                "cost_tier": "standard",
            },
            {
                "id": "gemini-2.5-flash-lite",
                "name": "Gemini 2.5 Flash Lite",
                "description": "Ultra-fast, cost-efficient Gemini 2.5 Flash Lite model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 1048576,
                "cost_tier": "budget",
            },
            # Gemini 2.0 Series (current)
            {
                "id": "gemini-2.0-flash",
                "name": "Gemini 2.0 Flash (Flagship)",
                "description": "Fast, low-latency flagship model",
                "type": "flagship",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 1000000,
                "cost_tier": "standard",
            },
            {
                "id": "gemini-2.0-flash-lite",
                "name": "Gemini 2.0 Flash Lite",
                "description": "Ultra-fast lightweight variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 500000,
                "cost_tier": "budget",
            },
            # Gemini 1.5 Series
            {
                "id": "gemini-1.5-pro",
                "name": "Gemini 1.5 Pro (Advanced)",
                "description": "Gemini 1.5 with 1M context",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "multimodal", "analysis", "code"],
                "context_window": 1000000,
                "cost_tier": "standard",
            },
            {
                "id": "gemini-1.5-flash",
                "name": "Gemini 1.5 Flash",
                "description": "Gemini 1.5 fast model",
                "type": "fast",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 1000000,
                "cost_tier": "budget",
            },
        ],
        "default": "gemini-2.5-flash",
    },
    "bedrock": {
        "provider_name": "Amazon Bedrock",
        "icon": "fa-aws",
        "color": "#ff9900",
        "models": [
            # Amazon Nova (newest Amazon models)
            {
                "id": "amazon.nova-pro-v1:0",
                "name": "Amazon Nova Pro",
                "description": "Amazon's flagship multimodal model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 300000,
                "cost_tier": "standard",
            },
            {
                "id": "amazon.nova-lite-v1:0",
                "name": "Amazon Nova Lite",
                "description": "Fast, cost-effective Amazon model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 300000,
                "cost_tier": "budget",
            },
            {
                "id": "amazon.nova-micro-v1:0",
                "name": "Amazon Nova Micro",
                "description": "Ultra-lightweight Amazon model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
            # Claude via Bedrock - 4.5 Series (latest)
            {
                "id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
                "name": "Claude Sonnet 4.5 (Bedrock)",
                "description": "Latest Claude Sonnet via AWS Bedrock",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "anthropic.claude-opus-4-5-20251101-v1:0",
                "name": "Claude Opus 4.5 (Bedrock)",
                "description": "Highest-end Claude Opus via AWS Bedrock",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "anthropic.claude-haiku-4-5-20251001-v1:0",
                "name": "Claude Haiku 4.5 (Bedrock)",
                "description": "Fast Claude Haiku via AWS Bedrock",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget",
            },
            # Claude via Bedrock - 3.5 Series
            {
                "id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "name": "Claude 3.5 Sonnet v2 (Bedrock)",
                "description": "Claude 3.5 Sonnet via AWS Bedrock",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "anthropic.claude-3-5-haiku-20241022-v1:0",
                "name": "Claude 3.5 Haiku (Bedrock)",
                "description": "Claude 3.5 Haiku via AWS Bedrock",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget",
            },
            # Meta Llama
            {
                "id": "meta.llama3-3-70b-instruct-v1:0",
                "name": "Llama 3.3 70B",
                "description": "Open-source large language model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            # Mistral
            {
                "id": "mistral.mistral-large-2407-v1:0",
                "name": "Mistral Large",
                "description": "Mistral's flagship model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            # Mistral
            {
                "id": "mistral.mistral-large-2402-v1:0",
                "name": "Mistral Large",
                "description": "Mistral's flagship model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            # Cohere
            {
                "id": "cohere.command-r-plus",
                "name": "Cohere Command R+",
                "description": "Cohere's flagship model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "cohere.command-r",
                "name": "Cohere Command R",
                "description": "Cohere's balanced model",
                "type": "workhorse",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "amazon.titan-text-express-v1",
                "name": "Amazon Titan Text Express v1",
                "description": "Cost-effective text generation model (confirmed correct ID)",
                "type": "workhorse",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
        ],
        "default": "amazon.nova-pro-v1:0",
    },
    "xai": {
        "provider_name": "xAI",
        "icon": "fa-bolt",
        "color": "#000000",
        "models": [
            {
                "id": "grok-4.1-fast",
                "name": "Grok 4.1 Fast",
                "description": "Agentic tool calling, 2M context",
                "type": "flagship",
                "capabilities": ["chat", "analysis", "reasoning", "code"],
                "context_window": 2000000,
                "cost_tier": "budget",
            },
            {
                "id": "grok-4.1-fast-reason",
                "name": "Grok 4.1 Fast Reason",
                "description": "Reasoning-optimized Grok 4.1 Fast",
                "type": "reasoning",
                "capabilities": ["chat", "analysis", "reasoning", "code"],
                "context_window": 2000000,
                "cost_tier": "budget",
            },
            {
                "id": "grok-4.1-fast-non-reason",
                "name": "Grok 4.1 Fast Non-Reason",
                "description": "Ultra-rapid Grok 4.1 Fast variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 2000000,
                "cost_tier": "budget",
            },
            {
                "id": "grok-4",
                "name": "Grok 4",
                "description": "Standard Grok 4 model",
                "type": "workhorse",
                "capabilities": ["chat", "analysis", "reasoning"],
                "context_window": 256000,
                "cost_tier": "standard",
            },
            {
                "id": "grok-4-heavy",
                "name": "Grok 4 Heavy",
                "description": "Premium Grok 4 Heavy model",
                "type": "flagship",
                "capabilities": ["chat", "analysis", "reasoning"],
                "context_window": 256000,
                "cost_tier": "premium",
            },
            {
                "id": "grok-3",
                "name": "Grok 3",
                "description": "Mid-tier Grok model",
                "type": "workhorse",
                "capabilities": ["chat", "analysis", "reasoning"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "grok-3-mini",
                "name": "Grok 3 Mini",
                "description": "Budget-friendly Grok mini model",
                "type": "mini",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
            {
                "id": "grok-2-image-1212",
                "name": "Grok 2 Image",
                "description": "Text-to-image generation model",
                "type": "workhorse",
                "capabilities": ["image"],
                "context_window": 0,
                "cost_tier": "standard",
            },
        ],
        "default": "grok-3-mini",
    },
    "perplexity": {
        "provider_name": "Perplexity",
        "icon": "fa-search",
        "color": "#222222",
        "models": [
            {
                "id": "sonar",
                "name": "Sonar",
                "description": "Fast real-time search model",
                "type": "fast",
                "capabilities": ["chat", "search", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "sonar-pro",
                "name": "Sonar Pro",
                "description": "Deep multi-search analysis model",
                "type": "workhorse",
                "capabilities": ["chat", "search", "analysis"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "sonar-reasoning",
                "name": "Sonar Reasoning",
                "description": "Chain-of-thought search model",
                "type": "reasoning",
                "capabilities": ["chat", "search", "analysis", "reasoning"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "sonar-reasoning-pro",
                "name": "Sonar Reasoning Pro",
                "description": "Reasoning-optimized Sonar Pro model",
                "type": "reasoning",
                "capabilities": ["chat", "search", "analysis", "reasoning"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "sonar-deep-research",
                "name": "Sonar Deep Research",
                "description": "Multi-step deep research workflows",
                "type": "reasoning",
                "capabilities": ["chat", "search", "analysis", "reasoning", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
        ],
        "default": "sonar-pro",
    },
}

# Model categories for UI organization
MODEL_CATEGORIES = {
    "flagship": "Flagship Models",
    "workhorse": "Workhorse Models",
    "reasoning": "Reasoning Models",
    "fast": "Fast Models",
    "coding": "Coding Models",
    "mini": "Mini Models",
    "embedding": "Embedding Models",
}

# Cost tiers
COST_TIERS = {
    "budget": {"label": "Budget", "color": "green"},
    "standard": {"label": "Standard", "color": "blue"},
    "premium": {"label": "Premium", "color": "orange"},
}

# Supported providers (for validation)
SUPPORTED_PROVIDERS = ["openai", "anthropic", "gemini", "bedrock", "xai", "perplexity"]

# Backward-compatible friendly aliases used across the codebase.
FRIENDLY_MODEL_ALIASES: dict[str, tuple[str, str]] = {
    # Anthropic direct - Claude 4.5 (December 2025 latest)
    "claude-opus-4.5": ("anthropic", "claude-opus-4.5-20251201"),
    "claude-sonnet-4.5": ("anthropic", "claude-sonnet-4.5-20251201"),
    "claude-haiku-4.5": ("anthropic", "claude-haiku-4.5-20251201"),
    # Claude 4 (May 2025)
    "claude-sonnet-4": ("anthropic", "claude-sonnet-4-20250514"),
    "claude-opus-4": ("anthropic", "claude-opus-4-20250514"),
    "claude-opus-4-extended": ("anthropic", "claude-opus-4-20250514"),
    # Claude 3.5 (Oct 2024)
    "claude-haiku-4": ("anthropic", "claude-3-5-haiku-20241022"),
    "claude-4.5-haiku": ("anthropic", "claude-haiku-4.5-20251201"),
    "claude-3.5-sonnet": ("anthropic", "claude-3-5-sonnet-20241022"),
    "claude-3.5-haiku": ("anthropic", "claude-3-5-haiku-20241022"),
    # OpenAI
    "gpt-4o": ("openai", "gpt-4o"),
    "gpt-4o-mini": ("openai", "gpt-4o-mini"),
    "gpt-5.2-instant": ("openai", "gpt-5.2-instant"),
    "gpt-5.2-thinking": ("openai", "gpt-5.2-thinking"),
    "gpt-5.2-pro": ("openai", "gpt-5.2-pro"),
    "gpt-5": ("openai", "gpt-5.1"),
    "gpt-5-mini": ("openai", "gpt-5-mini"),
    "o1-reasoning": ("openai", "o1"),
    "o3-reasoning": ("openai", "o1"),
    # Gemini
    "gemini-2-flash": ("gemini", "gemini-2.0-flash"),
    # Legacy friendly names: map to the current stable Pro tier.
    # (Historically these pointed at older 1.5 models and drifted over time.)
    "gemini-3-pro": ("gemini", "gemini-2.5-pro"),
    "gemini-2-5-pro": ("gemini", "gemini-2.5-pro"),
    "gemini-3-pro-preview": ("gemini", "gemini-3-pro-preview"),
    "gemini-2.5-pro": ("gemini", "gemini-2.5-pro"),
    "gemini-2.5-flash": ("gemini", "gemini-2.5-flash"),
    "gemini-2.5-flash-lite": ("gemini", "gemini-2.5-flash-lite"),
    # Bedrock
    "bedrock-nova-pro": ("bedrock", "amazon.nova-pro-v1:0"),
    "bedrock-nova-lite": ("bedrock", "amazon.nova-lite-v1:0"),
    "bedrock-nova-micro": ("bedrock", "amazon.nova-micro-v1:0"),
    "bedrock-claude-sonnet": ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
    "bedrock-claude-opus": ("bedrock", "anthropic.claude-opus-4-5-20251101-v1:0"),
    "bedrock-claude-haiku": ("bedrock", "anthropic.claude-haiku-4-5-20251001-v1:0"),
    # xAI Grok
    "grok-4.1-fast": ("xai", "grok-4.1-fast"),
    "grok-4.1-fast-reason": ("xai", "grok-4.1-fast-reason"),
    "grok-4.1-fast-non-reason": ("xai", "grok-4.1-fast-non-reason"),
    "grok-4": ("xai", "grok-4"),
    "grok-4-heavy": ("xai", "grok-4-heavy"),
    "grok-3": ("xai", "grok-3"),
    "grok-3-mini": ("xai", "grok-3-mini"),
    "grok-2-image-1212": ("xai", "grok-2-image-1212"),
    # Perplexity Sonar
    "sonar": ("perplexity", "sonar"),
    "sonar-pro": ("perplexity", "sonar-pro"),
    "sonar-reasoning": ("perplexity", "sonar-reasoning"),
    "sonar-reasoning-pro": ("perplexity", "sonar-reasoning-pro"),
    "sonar-deep-research": ("perplexity", "sonar-deep-research"),
}


# ---------------------------------------------------------------------------
# Catalog helper functions (formerly in ai_models_2025.py)
# ---------------------------------------------------------------------------


def get_all_models() -> list[dict[str, Any]]:
    """Get all available models across all providers."""
    all_models = []
    for provider, config in AI_MODELS_2025.items():
        for model in config["models"]:
            model_info = model.copy()
            model_info["provider"] = provider
            model_info["provider_name"] = config.get("provider_name", provider)
            all_models.append(model_info)
    return all_models


def get_models_by_provider(provider: str) -> list[dict[str, Any]]:
    """Get models for a specific provider."""
    return AI_MODELS_2025.get(provider, {}).get("models", [])


def get_default_model(provider: str) -> str | None:
    """Get default model for a provider."""
    return AI_MODELS_2025.get(provider, {}).get("default")


def get_provider_info(provider: str) -> dict[str, Any] | None:
    """Get provider metadata (name, icon, color)."""
    config = AI_MODELS_2025.get(provider)
    if not config:
        return None
    return {
        "id": provider,
        "name": config.get("provider_name", provider),
        "icon": config.get("icon", "fa-robot"),
        "color": config.get("color", "#666666"),
        "default_model": config.get("default"),
        "model_count": len(config.get("models", [])),
    }


def get_models_by_capability(capability: str) -> list[dict[str, Any]]:
    """Get all models that support a specific capability."""
    matching_models = []
    for provider, config in AI_MODELS_2025.items():
        for model in config["models"]:
            if capability in model.get("capabilities", []):
                model_info = model.copy()
                model_info["provider"] = provider
                model_info["provider_name"] = config.get("provider_name", provider)
                matching_models.append(model_info)
    return matching_models


def get_reasoning_models() -> list[dict[str, Any]]:
    """Get all models optimized for reasoning."""
    return get_models_by_capability("reasoning")


def get_coding_models() -> list[dict[str, Any]]:
    """Get all models optimized for coding."""
    return get_models_by_capability("code")


def get_search_models() -> list[dict[str, Any]]:
    """Get all models optimized for search/retrieval."""
    return get_models_by_capability("search")


def get_embedding_models() -> list[dict[str, Any]]:
    """Get all embedding models."""
    return get_models_by_capability("embedding")


def get_models_by_type(model_type: str) -> list[dict[str, Any]]:
    """Get all models of a specific type (flagship, workhorse, fast, etc.)."""
    matching_models = []
    for provider, config in AI_MODELS_2025.items():
        for model in config["models"]:
            if model.get("type") == model_type:
                model_info = model.copy()
                model_info["provider"] = provider
                model_info["provider_name"] = config.get("provider_name", provider)
                matching_models.append(model_info)
    return matching_models


def normalize_provider(provider: str) -> str:
    """Normalize provider keys to canonical names."""
    p = (provider or "").lower().strip()
    if p == "google":
        return "gemini"
    return p


def resolve_friendly_model(friendly_name: str) -> dict[str, str] | None:
    """
    Resolve a friendly/alias model name to canonical provider + model ID.

    Accepts:
      - friendly aliases (claude-sonnet-4, bedrock-nova-pro, gemini-2-flash, ...)
      - raw provider:model_id strings
      - raw model IDs present in AI_MODELS_2025
    """
    if not friendly_name:
        return None

    name = friendly_name.strip()

    if ":" in name:
        maybe_provider, maybe_id = name.split(":", 1)
        provider_norm = normalize_provider(maybe_provider)
        if provider_norm in SUPPORTED_PROVIDERS:
            return {"provider": provider_norm, "model": maybe_id}

    alias = FRIENDLY_MODEL_ALIASES.get(name)
    if alias:
        provider, model_id = alias
        return {"provider": provider, "model": model_id}

    # If it's already a known model ID, infer provider from catalog.
    for provider, config in AI_MODELS_2025.items():
        for model in config.get("models", []):
            if model.get("id") == name:
                return {"provider": provider, "model": name}

    return None


# ============================================================================
# Task-complexity routing (formerly in ai_models.py)
# ============================================================================


class TaskComplexity(Enum):
    BASIC = "basic"
    MODERATE = "moderate"
    DEEP_RESEARCH = "deep_research"


def log_model_selection(task: str, selected_model: str, reason: str) -> None:
    """
    Lightweight hook so every selection can be traced in logs without exposing secrets.
    """
    logger.info("Model Selection: %s -> %s (%s)", task, selected_model, reason)


class ModelPriorityManager:
    """
    Defines global ordering so fallbacks are deterministic across the platform.
    Consolidated across supported providers.
    """

    BASIC_ORDER = [
        # Fast/cheap defaults (2025 catalog)
        "gemini-2.5-flash-lite",
        "gpt-5.2-instant",
        "claude-haiku-4",
        "bedrock-nova-lite",
    ]

    MODERATE_ORDER = [
        "claude-sonnet-4",
        "gpt-5.2-instant",
        "gemini-2.5-flash",
        "bedrock-nova-pro",
    ]

    DEEP_RESEARCH_ORDER = [
        "gpt-5.2-thinking",
        "claude-opus-4-extended",
        "gemini-2.5-pro",
        "bedrock-claude-opus",
    ]

    ORDER_BY_COMPLEXITY: dict[TaskComplexity, list[str]] = {
        TaskComplexity.BASIC: BASIC_ORDER,
        TaskComplexity.MODERATE: MODERATE_ORDER,
        TaskComplexity.DEEP_RESEARCH: DEEP_RESEARCH_ORDER,
    }

    @classmethod
    def get_model_order(cls, task: str, complexity: TaskComplexity) -> list[str]:
        return cls.ORDER_BY_COMPLEXITY.get(complexity, cls.BASIC_ORDER)


class ModelConfig(TypedDict, total=False):
    primary: str
    fallbacks: list[str]
    features: list[str]


class AIModelService:
    """
    Provides centralized selection and metadata for all AI tasks.

    Model identifiers here are *friendly* and resolved via
    ``resolve_friendly_model``.
    """

    MODELS: dict[TaskComplexity, ModelConfig] = {
        TaskComplexity.BASIC: {
            "primary": "gemini-2.5-flash-lite",
            "fallbacks": ["gpt-5.2-instant", "claude-haiku-4", "bedrock-nova-lite"],
            "features": ["fast", "structured", "conversational"],
        },
        TaskComplexity.MODERATE: {
            "primary": "claude-sonnet-4",
            "fallbacks": ["gpt-5.2-instant", "gemini-2.5-flash", "bedrock-nova-pro"],
            "features": ["analysis", "extraction", "structured"],
        },
        TaskComplexity.DEEP_RESEARCH: {
            "primary": "gpt-5.2-thinking",
            "fallbacks": [
                "claude-opus-4-extended",
                "gemini-2.5-pro",
                "bedrock-claude-opus",
            ],
            "features": [
                "comprehensive",
                "analytical",
                "extended_context",
                "reasoning",
            ],
        },
    }

    MODEL_API_MAP: dict[str, dict[str, str]] = {
        # Friendly name -> provider + actual model identifier
        # ============ ANTHROPIC (Claude) - Direct API ============
        "claude-sonnet-4": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
        },
        "claude-opus-4-extended": {
            "provider": "anthropic",
            "model": "claude-opus-4-20250514",
        },
        "claude-haiku-4": {
            "provider": "anthropic",
            "model": "claude-3-5-haiku-20241022",
        },
        "claude-haiku-4.5": {
            "provider": "anthropic",
            "model": "claude-3-5-haiku-20241022",
        },
        "claude-opus-4.5": {
            "provider": "anthropic",
            "model": "claude-opus-4-20250514",
        },
        "claude-sonnet-4.5": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
        },
        # ============ OPENAI (GPT) ============
        "gpt-4o": {
            "provider": "openai",
            "model": "gpt-4o",
        },
        "gpt-4o-mini": {
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
        "o1-reasoning": {
            "provider": "openai",
            "model": "o1",
        },
        "o3-reasoning": {
            "provider": "openai",
            "model": "o1",
        },
        "gpt-5": {
            "provider": "openai",
            "model": "gpt-5.1",  # GPT-5.1 flagship
        },
        "gpt-5.2-instant": {
            "provider": "openai",
            "model": "gpt-5.2-instant",
        },
        "gpt-5.2-thinking": {
            "provider": "openai",
            "model": "gpt-5.2-thinking",
        },
        "gpt-5.2-pro": {
            "provider": "openai",
            "model": "gpt-5.2-pro",
        },
        "gpt-5-mini": {
            "provider": "openai",
            "model": "gpt-5-mini",
        },
        # ============ GOOGLE (Gemini) ============
        "gemini-2-flash": {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
        },
        "gemini-3-pro": {
            "provider": "gemini",
            "model": "gemini-2.5-pro",
        },
        "gemini-2-5-pro": {
            "provider": "gemini",
            "model": "gemini-2.5-pro",
        },
        "gemini-3-pro-preview": {
            "provider": "gemini",
            "model": "gemini-3-pro-preview",
        },
        "gemini-2.5-pro": {
            "provider": "gemini",
            "model": "gemini-2.5-pro",
        },
        "gemini-2.5-flash": {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
        },
        "gemini-2.5-flash-lite": {
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
        },
        # ============ AMAZON BEDROCK ============
        "bedrock-claude-opus": {
            "provider": "bedrock",
            "model": "anthropic.claude-opus-4-5-20251101-v1:0",
        },
        "bedrock-claude-sonnet": {
            "provider": "bedrock",
            "model": "anthropic.claude-sonnet-4-5-20250929-v1:0",
        },
        "bedrock-nova-pro": {
            "provider": "bedrock",
            "model": "amazon.nova-pro-v1:0",
        },
        "bedrock-nova-lite": {
            "provider": "bedrock",
            "model": "amazon.nova-lite-v1:0",
        },
        "bedrock-nova-micro": {
            "provider": "bedrock",
            "model": "amazon.nova-micro-v1:0",
        },
        "bedrock-llama-70b": {
            "provider": "bedrock",
            "model": "meta.llama3-70b-instruct-v1:0",
        },
        "bedrock-mistral-large": {
            "provider": "bedrock",
            "model": "mistral.mistral-large-2407-v1:0",
        },
        # ============ xAI (Grok) ============
        "grok-4.1-fast": {"provider": "xai", "model": "grok-4.1-fast"},
        "grok-4.1-fast-reason": {"provider": "xai", "model": "grok-4.1-fast-reason"},
        "grok-4.1-fast-non-reason": {
            "provider": "xai",
            "model": "grok-4.1-fast-non-reason",
        },
        "grok-4": {"provider": "xai", "model": "grok-4"},
        "grok-4-heavy": {"provider": "xai", "model": "grok-4-heavy"},
        "grok-3": {"provider": "xai", "model": "grok-3"},
        "grok-3-mini": {"provider": "xai", "model": "grok-3-mini"},
        "grok-2-image-1212": {"provider": "xai", "model": "grok-2-image-1212"},
        # ============ PERPLEXITY (Sonar) ============
        "sonar": {"provider": "perplexity", "model": "sonar"},
        "sonar-pro": {"provider": "perplexity", "model": "sonar-pro"},
        "sonar-reasoning": {"provider": "perplexity", "model": "sonar-reasoning"},
        "sonar-reasoning-pro": {
            "provider": "perplexity",
            "model": "sonar-reasoning-pro",
        },
        "sonar-deep-research": {
            "provider": "perplexity",
            "model": "sonar-deep-research",
        },
    }

    MODEL_LABELS: dict[str, str] = {
        # Anthropic
        "claude-sonnet-4": "Claude Sonnet 4",
        "claude-opus-4-extended": "Claude Opus 4 (Extended)",
        "claude-haiku-4": "Claude Haiku (Legacy)",
        "claude-haiku-4.5": "Claude 4.5 Haiku",
        "claude-opus-4.5": "Claude 4.5 Opus",
        "claude-sonnet-4.5": "Claude 4.5 Sonnet",
        # OpenAI
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o Mini",
        "o1-reasoning": "OpenAI o1 (Reasoning)",
        "o3-reasoning": "OpenAI o3 (Reasoning)",
        "gpt-5": "GPT-5.1 Flagship",
        "gpt-5.2-instant": "GPT-5.2 Instant",
        "gpt-5.2-thinking": "GPT-5.2 Thinking",
        "gpt-5.2-pro": "GPT-5.2 Pro",
        "gpt-5-mini": "GPT-5 Mini",
        # Gemini
        "gemini-2-flash": "Gemini 2.0 Flash",
        "gemini-3-pro": "Gemini Pro (Legacy)",
        "gemini-2-5-pro": "Gemini 2.5 Pro",
        "gemini-3-pro-preview": "Gemini 3 Pro Preview",
        "gemini-2.5-pro": "Gemini 2.5 Pro",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
        # Bedrock
        "bedrock-claude-opus": "Claude Opus 4.5 (Bedrock)",
        "bedrock-claude-sonnet": "Claude Sonnet 4.5 (Bedrock)",
        "bedrock-nova-pro": "Amazon Nova Pro",
        "bedrock-nova-lite": "Amazon Nova Lite",
        "bedrock-nova-micro": "Amazon Nova Micro",
        "bedrock-llama-70b": "Llama 3.3 70B (Bedrock)",
        "bedrock-mistral-large": "Mistral Large (Bedrock)",
        # xAI Grok
        "grok-4.1-fast": "Grok 4.1 Fast",
        "grok-4.1-fast-reason": "Grok 4.1 Fast Reason",
        "grok-4.1-fast-non-reason": "Grok 4.1 Fast Non-Reason",
        "grok-4": "Grok 4",
        "grok-4-heavy": "Grok 4 Heavy",
        "grok-3": "Grok 3",
        "grok-3-mini": "Grok 3 Mini",
        "grok-2-image-1212": "Grok 2 Image",
        # Perplexity Sonar
        "sonar": "Sonar",
        "sonar-pro": "Sonar Pro",
        "sonar-reasoning": "Sonar Reasoning",
        "sonar-reasoning-pro": "Sonar Reasoning Pro",
        "sonar-deep-research": "Sonar Deep Research",
    }

    @classmethod
    def select_model(
        cls, task_type: str, complexity: TaskComplexity | str
    ) -> ModelConfig:
        resolved_complexity = cls._ensure_complexity(complexity)
        base_config = cls.MODELS.get(
            resolved_complexity, cls.MODELS[TaskComplexity.BASIC]
        )
        model_config = cls._copy_model_config(base_config)

        preferences = getattr(settings, "AI_MODEL_PREFERENCES", {}) or {}
        override_key = f"{task_type}:{resolved_complexity.value}"
        preferred_model = preferences.get(override_key)
        if preferred_model:
            model_config["primary"] = preferred_model

        return model_config

    @classmethod
    def build_priority_queue(
        cls,
        task_type: str,
        complexity: TaskComplexity | str,
        model_config: ModelConfig,
    ) -> list[str]:
        resolved_complexity = cls._ensure_complexity(complexity)
        baseline = ModelPriorityManager.get_model_order(task_type, resolved_complexity)
        candidate_list: list[str] = []
        for candidate in [
            model_config.get("primary"),
            *model_config.get("fallbacks", []),
            *baseline,
        ]:
            if isinstance(candidate, str) and candidate not in candidate_list:
                candidate_list.append(candidate)
        return candidate_list

    @classmethod
    def resolve_model(cls, friendly_name: str) -> dict[str, str] | None:
        return resolve_friendly_model(friendly_name) or cls.MODEL_API_MAP.get(
            friendly_name
        )

    @classmethod
    def display_name(cls, friendly_name: str) -> str:
        return cls.MODEL_LABELS.get(friendly_name, friendly_name)

    @staticmethod
    def _copy_model_config(config: ModelConfig) -> ModelConfig:
        copied: ModelConfig = cast(ModelConfig, dict(config))
        if "fallbacks" in config:
            copied["fallbacks"] = list(config["fallbacks"])
        if "features" in config:
            copied["features"] = list(config["features"])
        return copied

    @staticmethod
    def _ensure_complexity(value: TaskComplexity | str) -> TaskComplexity:
        if isinstance(value, TaskComplexity):
            return value
        if not isinstance(value, str):
            return TaskComplexity.BASIC
        try:
            return TaskComplexity(value.lower().strip())
        except ValueError:
            return TaskComplexity.BASIC


# ============================================================================
# Runtime performance tracking (original ai_model_registry content)
# ============================================================================


@dataclass
class ModelMetrics:
    """Performance metrics for a single model."""

    provider: str
    model_id: str

    # Rolling averages (last N calls)
    avg_latency_ms: float = 0.0
    avg_tokens_used: int = 0
    avg_quality_score: float = 0.0

    # Counts
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0

    # Recent performance (for real-time decisions)
    recent_latencies: list[int] = field(default_factory=list)
    recent_quality_scores: list[float] = field(default_factory=list)
    recent_errors: list[str] = field(default_factory=list)

    # Cost tracking
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Timestamps
    last_used: datetime | None = None
    last_success: datetime | None = None
    last_failure: datetime | None = None

    # Computed scores
    reliability_score: float = 1.0  # success_rate * 0.5 + (1 - error_rate) * 0.5
    overall_score: float = 0.5  # Weighted combination for routing

    def update_from_call(
        self,
        latency_ms: int,
        tokens_used: int,
        quality_score: float,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Update metrics after a model call."""
        self.total_calls += 1
        self.last_used = datetime.now(timezone.utc)

        if success:
            self.successful_calls += 1
            self.last_success = datetime.now(timezone.utc)

            # Update rolling metrics (keep last 100)
            self.recent_latencies.append(latency_ms)
            if len(self.recent_latencies) > 100:
                self.recent_latencies.pop(0)

            self.recent_quality_scores.append(quality_score)
            if len(self.recent_quality_scores) > 100:
                self.recent_quality_scores.pop(0)

            # Update averages
            self.avg_latency_ms = sum(self.recent_latencies) / len(
                self.recent_latencies
            )
            self.avg_quality_score = sum(self.recent_quality_scores) / len(
                self.recent_quality_scores
            )
            self.avg_tokens_used = (
                self.avg_tokens_used * (self.successful_calls - 1) + tokens_used
            ) // self.successful_calls

            # Update token tracking
            self.total_tokens += tokens_used
            self.estimated_cost_usd = self._estimate_cost()

        else:
            self.failed_calls += 1
            self.last_failure = datetime.now(timezone.utc)
            if error:
                self.recent_errors.append(error)
                if len(self.recent_errors) > 20:
                    self.recent_errors.pop(0)

        # Recalculate scores
        self._recalculate_scores()

    def _recalculate_scores(self) -> None:
        """Recalculate reliability and overall scores."""
        if self.total_calls == 0:
            self.reliability_score = 1.0
            self.overall_score = 0.5
            return

        success_rate = self.successful_calls / self.total_calls

        # Reliability: weighted by recency (recent failures hurt more)
        recent_success = (
            len([e for e in self.recent_errors if not e])
            if self.recent_errors
            else self.successful_calls
        )
        recent_total = (
            len(self.recent_errors) if self.recent_errors else self.total_calls
        )
        recent_rate = recent_success / max(recent_total, 1)

        self.reliability_score = success_rate * 0.6 + recent_rate * 0.4

        # Overall score: balance of quality, speed, and reliability
        # Normalize latency (lower is better, target 2000ms)
        latency_score = (
            max(0, 1 - (self.avg_latency_ms / 5000)) if self.avg_latency_ms > 0 else 0.5
        )

        # Quality score is already 0-1
        quality = self.avg_quality_score if self.avg_quality_score > 0 else 0.5

        # Weighted combination
        self.overall_score = (
            quality * 0.40  # Quality matters most
            + latency_score * 0.30  # Speed is important
            + self.reliability_score * 0.30  # Reliability is crucial
        )

    def _estimate_cost(self) -> float:
        """Estimate cost in USD based on token usage and model pricing."""
        return estimate_cost_usd(
            model_id=self.model_id,
            tokens_total=self.total_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_tokens_used": self.avg_tokens_used,
            "avg_quality_score": self.avg_quality_score,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "reliability_score": self.reliability_score,
            "overall_score": self.overall_score,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "last_used": self.last_used.isoformat() if self.last_used else None,
        }


@dataclass
class TaskTypeMetrics:
    """Metrics for a specific task type across all models."""

    task_type: str
    model_rankings: dict[str, float] = field(default_factory=dict)  # model_key -> score
    best_model: str | None = None
    avg_completion_time_ms: int = 0
    total_tasks: int = 0

    def update_ranking(self, model_key: str, score: float) -> None:
        """Update model ranking for this task type."""
        # Exponential moving average
        if model_key in self.model_rankings:
            self.model_rankings[model_key] = (
                self.model_rankings[model_key] * 0.7 + score * 0.3
            )
        else:
            self.model_rankings[model_key] = score

        # Update best model
        if self.model_rankings:
            self.best_model = max(self.model_rankings, key=self.model_rankings.get)


class ModelRegistry:
    """
    Central registry for AI model performance tracking.

    Provides:
    - Real-time metrics per model
    - Task-type specific rankings
    - Model selection recommendations
    - Redis-backed persistence (optional)

    Usage:
        registry = ModelRegistry()

        # Record a call
        registry.record_call(
            provider="openai",
            model_id="gpt-4o",
            task_type="deep_analysis",
            latency_ms=1500,
            tokens_used=2000,
            quality_score=0.85,
            success=True,
        )

        # Get best model for task
        best = registry.get_best_model("deep_analysis")

        # Get all metrics
        metrics = registry.get_model_metrics("openai", "gpt-4o")
    """

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url
        self._redis: Redis | None = None

        # In-memory storage
        self._model_metrics: dict[str, ModelMetrics] = (
            {}
        )  # provider:model_id -> metrics
        self._task_metrics: dict[str, TaskTypeMetrics] = {}  # task_type -> metrics

        # Initialize Redis if available
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection if available."""
        if not REDIS_AVAILABLE or not self.redis_url:
            return

        try:
            self._redis = Redis.from_url(self.redis_url)
            self._redis.ping()
            logger.info("ModelRegistry: Redis connected for persistent metrics")
        except Exception as e:
            logger.warning(f"ModelRegistry: Redis unavailable: {e}")
            self._redis = None

    def _get_model_key(self, provider: str, model_id: str) -> str:
        """Get unique key for a model."""
        return f"{provider}:{model_id}"

    def record_call(
        self,
        provider: str,
        model_id: str,
        task_type: str,
        latency_ms: int,
        tokens_used: int = 0,
        quality_score: float = 0.5,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """
        Record a model call and update metrics.

        Args:
            provider: AI provider (openai, anthropic, gemini, bedrock)
            model_id: Model identifier
            task_type: Type of task (quick_search, deep_analysis, etc.)
            latency_ms: Response time in milliseconds
            tokens_used: Total tokens used
            quality_score: Quality score 0-1 (from validation or heuristics)
            success: Whether the call succeeded
            error: Error message if failed
        """
        model_key = self._get_model_key(provider, model_id)

        # Get or create model metrics
        if model_key not in self._model_metrics:
            self._model_metrics[model_key] = ModelMetrics(
                provider=provider,
                model_id=model_id,
            )

        # Update model metrics
        self._model_metrics[model_key].update_from_call(
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            quality_score=quality_score,
            success=success,
            error=error,
        )

        # Update task type metrics
        if task_type not in self._task_metrics:
            self._task_metrics[task_type] = TaskTypeMetrics(task_type=task_type)

        if success:
            self._task_metrics[task_type].total_tasks += 1
            self._task_metrics[task_type].update_ranking(
                model_key,
                self._model_metrics[model_key].overall_score,
            )

        # Persist to Redis if available
        self._persist_metrics(model_key)

    def _persist_metrics(self, model_key: str) -> None:
        """Persist metrics to Redis."""
        if not self._redis:
            return

        try:
            metrics = self._model_metrics.get(model_key)
            if metrics:
                self._redis.hset(
                    "ai_model_metrics",
                    model_key,
                    json.dumps(metrics.to_dict()),
                )
                self._redis.expire("ai_model_metrics", 86400)  # 24 hour TTL
        except Exception as e:
            logger.warning(f"Failed to persist metrics to Redis: {e}")

    def get_model_metrics(self, provider: str, model_id: str) -> ModelMetrics | None:
        """Get metrics for a specific model."""
        model_key = self._get_model_key(provider, model_id)
        return self._model_metrics.get(model_key)

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """Get all model metrics as dictionaries."""
        return {key: metrics.to_dict() for key, metrics in self._model_metrics.items()}

    def get_best_model(
        self,
        task_type: str,
        available_providers: list[str] | None = None,
    ) -> tuple[str, str] | None:
        """
        Get the best model for a task type based on performance.

        Args:
            task_type: Type of task
            available_providers: Optional list of available providers to filter

        Returns:
            Tuple of (provider, model_id) or None
        """
        task_metrics = self._task_metrics.get(task_type)
        if not task_metrics or not task_metrics.model_rankings:
            return None

        # Sort by score descending
        ranked = sorted(
            task_metrics.model_rankings.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        for model_key, score in ranked:
            provider, model_id = model_key.split(":", 1)
            if available_providers is None or provider in available_providers:
                return (provider, model_id)

        return None

    def get_model_ranking(
        self,
        task_type: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Get ranked list of models for a task type.

        Returns list of {provider, model_id, score, metrics} dicts.
        """
        task_metrics = self._task_metrics.get(task_type)
        if not task_metrics or not task_metrics.model_rankings:
            return []

        ranked = sorted(
            task_metrics.model_rankings.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        results = []
        for model_key, score in ranked:
            provider, model_id = model_key.split(":", 1)
            metrics = self._model_metrics.get(model_key)
            results.append(
                {
                    "provider": provider,
                    "model_id": model_id,
                    "score": score,
                    "avg_latency_ms": metrics.avg_latency_ms if metrics else 0,
                    "avg_quality": metrics.avg_quality_score if metrics else 0,
                    "reliability": metrics.reliability_score if metrics else 0,
                }
            )

        return results

    def get_health_status(self) -> dict[str, Any]:
        """Get overall health status of all models."""
        status = {
            "total_models": len(self._model_metrics),
            "healthy_models": 0,
            "degraded_models": 0,
            "unhealthy_models": 0,
            "models": [],
        }

        for model_key, metrics in self._model_metrics.items():
            model_status = {
                "model_key": model_key,
                "reliability": metrics.reliability_score,
                "avg_latency_ms": metrics.avg_latency_ms,
                "recent_errors": len(metrics.recent_errors),
            }

            if metrics.reliability_score >= 0.9 and metrics.avg_latency_ms < 3000:
                model_status["status"] = "healthy"
                status["healthy_models"] += 1
            elif metrics.reliability_score >= 0.7:
                model_status["status"] = "degraded"
                status["degraded_models"] += 1
            else:
                model_status["status"] = "unhealthy"
                status["unhealthy_models"] += 1

            status["models"].append(model_status)

        return status

    def reset_metrics(
        self, provider: str | None = None, model_id: str | None = None
    ) -> None:
        """Reset metrics for a specific model or all models."""
        if provider and model_id:
            model_key = self._get_model_key(provider, model_id)
            if model_key in self._model_metrics:
                del self._model_metrics[model_key]
        else:
            self._model_metrics.clear()
            self._task_metrics.clear()


# Global registry instance
_registry: ModelRegistry | None = None


def get_registry(redis_url: str | None = None) -> ModelRegistry:
    """Get or create the global model registry."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry(redis_url=redis_url)
    return _registry


def record_model_call(
    provider: str,
    model_id: str,
    task_type: str,
    latency_ms: int,
    tokens_used: int = 0,
    quality_score: float = 0.5,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Convenience function to record a model call."""
    registry = get_registry()
    registry.record_call(
        provider=provider,
        model_id=model_id,
        task_type=task_type,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        quality_score=quality_score,
        success=success,
        error=error,
    )
