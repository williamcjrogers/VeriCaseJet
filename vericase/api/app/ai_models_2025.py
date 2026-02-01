"""Thin re-export shim -- canonical definitions live in ai_model_registry.

All symbols that were historically imported from this module are re-exported
here so that existing ``from .ai_models_2025 import ...`` statements keep working.
"""

from .ai_model_registry import (  # noqa: F401
    AI_MODELS_2025,
    COST_TIERS,
    FRIENDLY_MODEL_ALIASES,
    MODEL_CATEGORIES,
    SUPPORTED_PROVIDERS,
    get_all_models,
    get_coding_models,
    get_default_model,
    get_embedding_models,
    get_models_by_capability,
    get_models_by_provider,
    get_models_by_type,
    get_provider_info,
    get_reasoning_models,
    get_search_models,
    normalize_provider,
    resolve_friendly_model,
)
