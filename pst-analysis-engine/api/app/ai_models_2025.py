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
            {
                "id": "gpt-5.1",
                "name": "GPT-5.1",
                "description": "Flagship general model with advanced reasoning",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "gpt-5",
                "name": "GPT-5",
                "description": "Previous flagship model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "gpt-5-mini",
                "name": "GPT-5 Mini",
                "description": "Compact GPT-5 variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-5-nano",
                "name": "GPT-5 Nano",
                "description": "Lightweight GPT-5 variant",
                "type": "mini",
                "capabilities": ["chat", "analysis"],
                "context_window": 64000,
                "cost_tier": "budget",
            },
            {
                "id": "gpt-5-pro",
                "name": "GPT-5 Pro",
                "description": "Premium high-performance GPT-5",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "code", "analysis", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "o3-deep-research",
                "name": "o3 Deep Research",
                "description": "Extended reasoning for deep research",
                "type": "reasoning",
                "capabilities": ["reasoning", "research", "analysis"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "o4-mini-deep-research",
                "name": "o4 Mini Deep Research",
                "description": "Fast deep research model",
                "type": "reasoning",
                "capabilities": ["reasoning", "research", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "o3-pro",
                "name": "o3 Pro",
                "description": "Premium reasoning model",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "problem_solving"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "o3",
                "name": "o3",
                "description": "Dedicated reasoning model",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "problem_solving"],
                "context_window": 128000,
                "cost_tier": "premium",
            },
            {
                "id": "o4-mini",
                "name": "o4 Mini",
                "description": "Fast reasoning model",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-4.1",
                "name": "GPT-4.1",
                "description": "Improved GPT-4 generation",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-4.1-mini",
                "name": "GPT-4.1 Mini",
                "description": "Fast GPT-4.1 variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
            {
                "id": "gpt-4.1-nano",
                "name": "GPT-4.1 Nano",
                "description": "Lightweight GPT-4.1 variant",
                "type": "mini",
                "capabilities": ["chat", "analysis"],
                "context_window": 64000,
                "cost_tier": "budget",
            },
            {
                "id": "gpt-4o",
                "name": "GPT-4o",
                "description": "Multimodal GPT-4 Turbo",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "code", "analysis", "multimodal"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
            {
                "id": "gpt-4o-mini",
                "name": "GPT-4o Mini",
                "description": "Fast multimodal model",
                "type": "fast",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
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
            {
                "id": "claude-sonnet-4-5-20250929",
                "name": "Claude 4.5 Sonnet",
                "description": "Main workhorse model with excellent balance",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "claude-haiku-4-5-20251001",
                "name": "Claude 4.5 Haiku",
                "description": "Fast, lightweight model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget",
            },
            {
                "id": "claude-opus-4-5-20251101",
                "name": "Claude 4.5 Opus",
                "description": "Highest-end Claude model with extended thinking",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "claude-opus-4-1-20250805",
                "name": "Claude 4.1 Opus",
                "description": "Previous flagship Claude model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
        ],
        "default": "claude-sonnet-4-5-20250929",
    },
    "gemini": {
        "provider_name": "Google Gemini",
        "icon": "fa-gem",
        "color": "#4285f4",
        "models": [
            {
                "id": "gemini-3-pro-preview",
                "name": "Gemini 3.0 Pro",
                "description": "New flagship multimodal model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "multimodal", "analysis", "code"],
                "context_window": 2000000,
                "cost_tier": "premium",
            },
            {
                "id": "gemini-2.5-pro",
                "name": "Gemini 2.5 Pro",
                "description": "Balanced multimodal model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "multimodal", "analysis", "code"],
                "context_window": 1000000,
                "cost_tier": "standard",
            },
            {
                "id": "gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "description": "Fast, low-latency variant",
                "type": "fast",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 1000000,
                "cost_tier": "standard",
            },
            {
                "id": "gemini-2.5-flash-lite",
                "name": "Gemini 2.5 Flash-Lite",
                "description": "Ultra-fast lightweight variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 500000,
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
            # Claude via Bedrock
            {
                "id": "anthropic.claude-sonnet-4-5-20250929-v1:0",
                "name": "Claude 4.5 Sonnet (Bedrock)",
                "description": "Claude Sonnet via AWS Bedrock",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            {
                "id": "anthropic.claude-haiku-4-5-20251001-v1:0",
                "name": "Claude 4.5 Haiku (Bedrock)",
                "description": "Claude Haiku via AWS Bedrock",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget",
            },
            {
                "id": "anthropic.claude-opus-4-5-20251101-v1:0",
                "name": "Claude 4.5 Opus (Bedrock)",
                "description": "Claude Opus via AWS Bedrock",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium",
            },
            {
                "id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "name": "Claude 3.5 Sonnet v2 (Bedrock)",
                "description": "Legacy Claude 3.5 Sonnet",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard",
            },
            # Amazon Nova
            {
                "id": "amazon.nova-2-pro-v1:0",
                "name": "Amazon Nova 2 Pro",
                "description": "Latest Nova flagship model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "multimodal"],
                "context_window": 300000,
                "cost_tier": "premium",
            },
            {
                "id": "amazon.nova-2-lite-v1:0",
                "name": "Amazon Nova 2 Lite",
                "description": "Fast Nova 2 variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 300000,
                "cost_tier": "standard",
            },
            {
                "id": "amazon.nova-pro-v1:0",
                "name": "Amazon Nova Pro",
                "description": "Balanced Nova model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "multimodal"],
                "context_window": 300000,
                "cost_tier": "standard",
            },
            {
                "id": "amazon.nova-lite-v1:0",
                "name": "Amazon Nova Lite",
                "description": "Fast Nova variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 300000,
                "cost_tier": "budget",
            },
            {
                "id": "amazon.nova-micro-v1:0",
                "name": "Amazon Nova Micro",
                "description": "Ultra-lightweight Nova",
                "type": "mini",
                "capabilities": ["chat"],
                "context_window": 128000,
                "cost_tier": "budget",
            },
            # Amazon Titan
            {
                "id": "amazon.titan-text-express-v1",
                "name": "Titan Text Express",
                "description": "Fast text generation",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 8000,
                "cost_tier": "budget",
            },
            {
                "id": "amazon.titan-embed-text-v2:0",
                "name": "Titan Embeddings v2",
                "description": "High-quality text embeddings",
                "type": "embedding",
                "capabilities": ["embedding"],
                "context_window": 8192,
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
                "name": "Mistral Large (24.07)",
                "description": "Mistral's flagship model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard",
            },
        ],
        "default": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    },
}

# Model categories for UI organization
MODEL_CATEGORIES = {
    "flagship": "🚀 Flagship Models",
    "workhorse": "⚡ Workhorse Models",
    "reasoning": "🧠 Reasoning Models",
    "fast": "💨 Fast Models",
    "coding": "💻 Coding Models",
    "mini": "📱 Mini Models",
    "embedding": "🔗 Embedding Models",
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
