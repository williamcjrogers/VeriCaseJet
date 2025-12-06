"""
Centralized AI model selection, priorities, and helper utilities.
Supports: OpenAI, Anthropic, Gemini, and Amazon Bedrock providers.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TypedDict

from .config import settings

logger = logging.getLogger(__name__)


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
    Consolidated to 4 providers: OpenAI, Anthropic, Gemini, Bedrock
    """

    BASIC_ORDER = [
        "claude-sonnet-4",
        "gpt-4o",
        "gemini-2-flash",
        "bedrock-nova-lite",
    ]

    MODERATE_ORDER = [
        "gpt-4o",
        "claude-sonnet-4",
        "gemini-3-pro",
        "bedrock-nova-pro",
    ]

    DEEP_RESEARCH_ORDER = [
        "o1-reasoning",
        "claude-opus-4-extended",
        "gemini-3-pro",
        "bedrock-claude-opus",
    ]

    @staticmethod
    def get_model_order(task: str, complexity: TaskComplexity) -> list[str]:
        if complexity == TaskComplexity.DEEP_RESEARCH:
            return ModelPriorityManager.DEEP_RESEARCH_ORDER
        if complexity == TaskComplexity.MODERATE:
            return ModelPriorityManager.MODERATE_ORDER
        return ModelPriorityManager.BASIC_ORDER


class ModelConfig(TypedDict, total=False):
    primary: str
    fallbacks: list[str]
    features: list[str]


class AIModelService:
    """
    Provides centralized selection and metadata for all AI tasks.
    Supports 4 providers: OpenAI, Anthropic, Gemini, Amazon Bedrock
    """

    MODELS: dict[TaskComplexity, ModelConfig] = {
        TaskComplexity.BASIC: {
            "primary": "claude-sonnet-4",
            "fallbacks": ["gpt-4o", "gemini-2-flash", "bedrock-nova-lite"],
            "features": ["fast", "structured", "conversational"],
        },
        TaskComplexity.MODERATE: {
            "primary": "gpt-4o",
            "fallbacks": ["claude-sonnet-4", "gemini-3-pro", "bedrock-nova-pro"],
            "features": ["analysis", "extraction", "structured"],
        },
        TaskComplexity.DEEP_RESEARCH: {
            "primary": "o1-reasoning",
            "fallbacks": [
                "claude-opus-4-extended",
                "gemini-3-pro",
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
            "model": "claude-sonnet-4-5-20250929",
        },
        "claude-opus-4-extended": {
            "provider": "anthropic",
            "model": "claude-opus-4-5-20251101",  # Opus 4.5 with extended thinking
        },
        "claude-haiku-4": {
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
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
            "model": "o1",  # OpenAI o1 reasoning model
        },
        "o3-reasoning": {
            "provider": "openai",
            "model": "o3",  # OpenAI o3 reasoning model
        },
        "gpt-5": {
            "provider": "openai",
            "model": "gpt-5.1",  # GPT-5.1 flagship
        },
        # ============ GOOGLE (Gemini) ============
        "gemini-2-flash": {
            "provider": "google",
            "model": "gemini-2.5-flash",
        },
        "gemini-3-pro": {
            "provider": "google",
            "model": "gemini-3-pro-preview",  # Flagship multimodal, 1M+ context
        },
        "gemini-2-5-pro": {
            "provider": "google",
            "model": "gemini-2.5-pro",
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
            "model": "meta.llama3-3-70b-instruct-v1:0",
        },
        "bedrock-mistral-large": {
            "provider": "bedrock",
            "model": "mistral.mistral-large-2407-v1:0",
        },
    }

    MODEL_LABELS: dict[str, str] = {
        # Anthropic
        "claude-sonnet-4": "Claude 4.5 Sonnet",
        "claude-opus-4-extended": "Claude 4.5 Opus (Extended Thinking)",
        "claude-haiku-4": "Claude 4.5 Haiku",
        # OpenAI
        "gpt-4o": "GPT-4o",
        "gpt-4o-mini": "GPT-4o Mini",
        "o1-reasoning": "OpenAI o1 (Reasoning)",
        "o3-reasoning": "OpenAI o3 (Reasoning)",
        "gpt-5": "GPT-5.1 Flagship",
        # Gemini
        "gemini-2-flash": "Gemini 2.5 Flash",
        "gemini-3-pro": "Gemini 3.0 Pro",
        "gemini-2-5-pro": "Gemini 2.5 Pro",
        # Bedrock
        "bedrock-claude-opus": "Claude Opus 4.5 (Bedrock)",
        "bedrock-claude-sonnet": "Claude Sonnet 4.5 (Bedrock)",
        "bedrock-nova-pro": "Amazon Nova Pro",
        "bedrock-nova-lite": "Amazon Nova Lite",
        "bedrock-nova-micro": "Amazon Nova Micro",
        "bedrock-llama-70b": "Llama 3.3 70B (Bedrock)",
        "bedrock-mistral-large": "Mistral Large (Bedrock)",
    }

    @classmethod
    def select_model(
        cls, task_type: str, complexity: TaskComplexity | str
    ) -> ModelConfig:
        resolved_complexity = cls._ensure_complexity(complexity)
        base_config = cls.MODELS.get(
            resolved_complexity, cls.MODELS[TaskComplexity.BASIC]
        )
        model_config: ModelConfig = {**base_config}

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
        return cls.MODEL_API_MAP.get(friendly_name)

    @classmethod
    def display_name(cls, friendly_name: str) -> str:
        return cls.MODEL_LABELS.get(friendly_name, friendly_name)

    @staticmethod
    def _ensure_complexity(value: TaskComplexity | str) -> TaskComplexity:
        if isinstance(value, TaskComplexity):
            return value
        try:
            return TaskComplexity(value.lower())
        except Exception:
            return TaskComplexity.BASIC
