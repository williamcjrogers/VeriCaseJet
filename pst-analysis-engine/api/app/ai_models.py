"""
Centralized AI model selection, priorities, and helper utilities.
Ensures we consistently choose the right model for each task without web search.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, TypedDict, cast

import aiohttp

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
    """

    BASIC_ORDER = [
        "claude-sonnet-4",
        "gpt-4o",
        "gemini-2-flash",
        "perplexity-sonar",
    ]

    MODERATE_ORDER = [
        "gpt-4o",
        "claude-sonnet-4",
        "gemini-2-flash",
        "grok-3",
    ]

    DEEP_RESEARCH_ORDER = [
        "gpt-5.1-reasoning",
        "claude-opus-4-extended",
        "gemini-3-pro",
        "grok-4-thinking",
        "sonar-pro",
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
    """

    MODELS: dict[TaskComplexity, ModelConfig] = {
        TaskComplexity.BASIC: {
            "primary": "claude-sonnet-4",
            "fallbacks": ["gpt-4o", "gemini-2-flash", "perplexity-sonar"],
            "features": ["fast", "structured", "conversational"],
        },
        TaskComplexity.MODERATE: {
            "primary": "gpt-5.1",
            "fallbacks": ["claude-sonnet-4", "gemini-3-pro", "grok-3"],
            "features": ["analysis", "extraction", "structured"],
        },
        TaskComplexity.DEEP_RESEARCH: {
            "primary": "gpt-5.1-reasoning",
            "fallbacks": [
                "claude-opus-4-extended",
                "gemini-3-pro",
                "grok-4-thinking",
                "sonar-pro",
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
        # ============ ANTHROPIC (Claude) ============
        "claude-sonnet-4": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
        },
        "claude-opus-4-extended": {
            "provider": "anthropic",
            "model": "claude-opus-4-5-20251101",  # Latest Opus 4.5 with extended thinking
        },
        # ============ OPENAI (GPT) ============
        "gpt-4o": {
            "provider": "openai",
            "model": "gpt-4o",
        },
        "gpt-5.1": {
            "provider": "openai",
            "model": "gpt-5.1-2025-11-13",  # Latest flagship
        },
        "gpt-5.1-reasoning": {
            "provider": "openai",
            "model": "gpt-5.1-2025-11-13",  # With effort: "high" for deep reasoning
            "reasoning_effort": "high",
        },
        # ============ GOOGLE (Gemini) ============
        "gemini-2-flash": {
            "provider": "google",
            "model": "gemini-2.0-flash",
        },
        "gemini-3-pro": {
            "provider": "google",
            "model": "gemini-3.0-pro",  # Flagship multimodal, 1M+ context
        },
        # ============ XAI (Grok) ============
        "grok-3": {
            "provider": "xai",
            "model": "grok-3",
        },
        "grok-4-thinking": {
            "provider": "xai",
            "model": "grok-4-1-fast-reasoning",  # Exposes chain-of-thought
        },
        # ============ PERPLEXITY ============
        "perplexity-sonar": {
            "provider": "perplexity",
            "model": "sonar",
        },
        "sonar-pro": {
            "provider": "perplexity",
            "model": "sonar-pro",  # Deep research, 200k context, 2x citations
        },
    }

    MODEL_LABELS: dict[str, str] = {
        "claude-sonnet-4": "Claude Sonnet 4",
        "claude-opus-4-extended": "Claude Opus 4.5 Extended Thinking",
        "gpt-4o": "GPT-4o",
        "gpt-5.1": "GPT-5.1 Flagship",
        "gpt-5.1-reasoning": "GPT-5.1 Deep Reasoning",
        "gemini-2-flash": "Gemini 2.0 Flash",
        "gemini-3-pro": "Gemini 3.0 Pro",
        "grok-3": "Grok 3",
        "grok-4-thinking": "Grok 4.1 Thinking",
        "perplexity-sonar": "Perplexity Sonar",
        "sonar-pro": "Perplexity Sonar Pro (Deep Research)",
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


async def query_perplexity_local(prompt: str, context: str) -> str | None:
    """
    Query Perplexity with web search disabled so we only rely on provided evidence.
    """
    api_key = getattr(settings, "PERPLEXITY_API_KEY", None)
    if not api_key:
        return None

    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": "sonar-pro",  # Deep research model with 200k context
        "messages": [
            {
                "role": "system",
                "content": "You are Perplexity Sonar Pro. Analyze the supplied context thoroughly and provide comprehensive insights.",
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nPrompt:\n{prompt}",
            },
        ],
        # Control web search based on settings
        "search_web": bool(getattr(settings, "AI_WEB_ACCESS_ENABLED", False)),
        "temperature": 0.2,
        "top_p": 0.9,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()
                choices_raw = data.get("choices")
                if not isinstance(choices_raw, list) or not choices_raw:
                    return None
                first_choice_raw = cast(object, choices_raw[0])
                if not isinstance(first_choice_raw, dict):
                    return None
                first_choice = cast(dict[str, object], first_choice_raw)
                message_raw = first_choice.get("message")
                if not isinstance(message_raw, dict):
                    return None
                message = cast(dict[str, object], message_raw)
                content = message.get("content")
                if isinstance(content, str):
                    return content
                return None
    except Exception as exc:
        logger.warning("Perplexity offline query failed: %s", exc)
        return None
