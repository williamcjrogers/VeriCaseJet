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
        "sonnet-4.5",
        "chatgpt-5",
        "gemini-2.5-flash",
        "perplexity-local",
    ]

    MODERATE_ORDER = [
        "chatgpt-5",
        "sonnet-4.5",
        "gemini-2.5-flash",
        "perplexity-local",
    ]

    DEEP_RESEARCH_ORDER = [
        "chatgpt-5-pro-deep-research",
        "sonnet-4.5-extended",
        "gemini-2.5-pro-deep-think",
        "grok-4-heavy",
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
            "primary": "sonnet-4.5",
            "fallbacks": ["chatgpt-5", "gemini-2.5-flash", "perplexity-local"],
            "features": ["fast", "structured", "conversational"],
        },
        TaskComplexity.MODERATE: {
            "primary": "chatgpt-5",
            "fallbacks": ["sonnet-4.5", "gemini-2.5-flash", "perplexity-local"],
            "features": ["analysis", "extraction", "structured"],
        },
        TaskComplexity.DEEP_RESEARCH: {
            "primary": "chatgpt-5-pro-deep-research",
            "fallbacks": [
                "sonnet-4.5-extended",
                "gemini-2.5-pro-deep-think",
                "grok-4-heavy",
            ],
            "features": ["comprehensive", "analytical", "extended_context"],
        },
    }

    MODEL_API_MAP: dict[str, dict[str, str]] = {
        # Friendly name -> provider + actual model identifier
        "sonnet-4.5": {
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
        },
        "sonnet-4.5-extended": {
            "provider": "anthropic",
            "model": "claude-3-opus-20240229",
        },
        "chatgpt-5": {
            "provider": "openai",
            "model": "gpt-4-turbo",
        },
        "chatgpt-5-pro-deep-research": {
            "provider": "openai",
            "model": "o1-preview",
        },
        "gemini-2.5-flash": {
            "provider": "google",
            "model": "gemini-2.0-flash",
        },
        "gemini-2.5-pro-deep-think": {
            "provider": "google",
            "model": "gemini-2.0-flash-thinking-exp-01-21",
        },
        "grok-4-heavy": {
            "provider": "grok",
            "model": "grok-2-1212",
        },
        "perplexity-local": {
            "provider": "perplexity",
            "model": "pplx-7b-chat",
        },
    }

    MODEL_LABELS: dict[str, str] = {
        "sonnet-4.5": "Sonnet 4.5",
        "sonnet-4.5-extended": "Sonnet 4.5 Extended Thinking",
        "chatgpt-5": "ChatGPT 5",
        "chatgpt-5-pro-deep-research": "ChatGPT 5 Pro Deep Research",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-2.5-pro-deep-think": "Gemini 2.5 Pro Deep Think",
        "grok-4-heavy": "Grok 4 Heavy",
        "perplexity-local": "Perplexity Local Mode",
    }

    @classmethod
    def select_model(cls, task_type: str, complexity: TaskComplexity | str) -> ModelConfig:
        resolved_complexity = cls._ensure_complexity(complexity)
        base_config = cls.MODELS.get(resolved_complexity, cls.MODELS[TaskComplexity.BASIC])
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
        "model": "pplx-7b-chat",
        "messages": [
            {
                "role": "system",
                "content": "You are Perplexity operating in offline mode. Use ONLY the supplied context.",
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nPrompt:\n{prompt}",
            },
        ],
        # Never hit the public web unless explicitly enabled
        "search_web": bool(getattr(settings, "AI_WEB_ACCESS_ENABLED", False)),
        "search_recency": "off",
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

