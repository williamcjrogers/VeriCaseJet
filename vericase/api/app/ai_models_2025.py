"""
2025 AI Model Configurations for VeriCase
Consolidated to 4 providers: OpenAI, Anthropic, Gemini, Amazon Bedrock
"""

from typing import Any

# Latest AI Models - Updated December 2025
AI_MODELS_2025: dict[str, dict[str, Any]] = {
    "openai": {
        "provider_name": "OpenAI",
        "icon": "fa-brain",
        "color": "#10a37f",
        "models": [
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
        "default": "gpt-4o",
    },
    "anthropic": {
        "provider_name": "Anthropic",
        "icon": "fa-comment-dots",
        "color": "#d97706",
        "models": [
            # Claude 4 Series (Latest - actual API model IDs)
            {
                "id": "claude-opus-4-20250514",
                "name": "Claude Opus 4 (Flagship)",
                "description": "Highest-end Claude model with extended thinking",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "claude-sonnet-4-20250514",
                "name": "Claude Sonnet 4 (Workhorse)",
                "description": "Main workhorse model with excellent balance",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            # Claude 3.5 Series (actual API model IDs)
            {
                "id": "claude-3-5-sonnet-20241022",
                "name": "Claude 3.5 Sonnet (Oct 2024)",
                "description": "Claude 3.5 Sonnet - fast and capable",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "claude-3-5-haiku-20241022",
                "name": "Claude 3.5 Haiku (Fastest)",
                "description": "Claude 3.5 fast model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget",
            },
        ],
        "default": "claude-sonnet-4-20250514",
    },
    "gemini": {
        "provider_name": "Google Gemini",
        "icon": "fa-gem",
        "color": "#4285f4",
        "models": [
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
        "default": "gemini-2.0-flash",
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
        ],
        "default": "amazon.nova-pro-v1:0",
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
SUPPORTED_PROVIDERS = ["openai", "anthropic", "gemini", "bedrock"]


def get_all_models() -> list[dict[str, Any]]:
    """Get all available models across all providers"""
    all_models = []
    for provider, config in AI_MODELS_2025.items():
        for model in config["models"]:
            model_info = model.copy()
            model_info["provider"] = provider
            model_info["provider_name"] = config.get("provider_name", provider)
            all_models.append(model_info)
    return all_models


def get_models_by_provider(provider: str) -> list[dict[str, Any]]:
    """Get models for a specific provider"""
    return AI_MODELS_2025.get(provider, {}).get("models", [])


def get_default_model(provider: str) -> str | None:
    """Get default model for a provider"""
    return AI_MODELS_2025.get(provider, {}).get("default")


def get_provider_info(provider: str) -> dict[str, Any] | None:
    """Get provider metadata (name, icon, color)"""
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
    """Get all models that support a specific capability"""
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
    """Get all models optimized for reasoning"""
    return get_models_by_capability("reasoning")


def get_coding_models() -> list[dict[str, Any]]:
    """Get all models optimized for coding"""
    return get_models_by_capability("code")


def get_search_models() -> list[dict[str, Any]]:
    """Get all models optimized for search/retrieval"""
    return get_models_by_capability("search")


def get_embedding_models() -> list[dict[str, Any]]:
    """Get all embedding models"""
    return get_models_by_capability("embedding")


def get_models_by_type(model_type: str) -> list[dict[str, Any]]:
    """Get all models of a specific type (flagship, workhorse, fast, etc.)"""
    matching_models = []
    for provider, config in AI_MODELS_2025.items():
        for model in config["models"]:
            if model.get("type") == model_type:
                model_info = model.copy()
                model_info["provider"] = provider
                model_info["provider_name"] = config.get("provider_name", provider)
                matching_models.append(model_info)
    return matching_models


# ---------------------------------------------------------------------------
# Friendly-name resolution (compat layer)
# ---------------------------------------------------------------------------

def normalize_provider(provider: str) -> str:
    """Normalize provider keys to canonical names."""
    p = (provider or "").lower().strip()
    if p == "google":
        return "gemini"
    return p


# Backward-compatible friendly aliases used across the codebase.
FRIENDLY_MODEL_ALIASES: dict[str, tuple[str, str]] = {
    # Anthropic direct
    "claude-sonnet-4": ("anthropic", "claude-sonnet-4-20250514"),
    "claude-opus-4-extended": ("anthropic", "claude-opus-4-20250514"),
    "claude-haiku-4": ("anthropic", "claude-3-5-haiku-20241022"),
    # OpenAI
    "gpt-4o": ("openai", "gpt-4o"),
    "gpt-4o-mini": ("openai", "gpt-4o-mini"),
    "gpt-5": ("openai", "gpt-5.1"),
    "o1-reasoning": ("openai", "o1"),
    "o3-reasoning": ("openai", "o1"),
    # Gemini
    "gemini-2-flash": ("gemini", "gemini-2.0-flash"),
    "gemini-3-pro": ("gemini", "gemini-1.5-pro"),
    "gemini-2-5-pro": ("gemini", "gemini-1.5-pro"),
    # Bedrock
    "bedrock-nova-pro": ("bedrock", "amazon.nova-pro-v1:0"),
    "bedrock-nova-lite": ("bedrock", "amazon.nova-lite-v1:0"),
    "bedrock-nova-micro": ("bedrock", "amazon.nova-micro-v1:0"),
    "bedrock-claude-sonnet": ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
    "bedrock-claude-opus": ("bedrock", "anthropic.claude-opus-4-5-20251101-v1:0"),
}


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
