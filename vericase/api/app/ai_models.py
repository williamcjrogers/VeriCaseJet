"""Thin re-export shim -- canonical definitions live in ai_model_registry.

All symbols that were historically imported from this module are re-exported
here so that existing ``from .ai_models import ...`` statements keep working.
"""

from .ai_model_registry import (  # noqa: F401
    AIModelService,
    ModelConfig,
    ModelPriorityManager,
    TaskComplexity,
    log_model_selection,
)
