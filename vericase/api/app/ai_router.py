"""
AI Adaptive Router - Dynamic model selection based on real-time performance.

This module provides intelligent routing of AI requests to the optimal model
based on:
- Real-time performance metrics from the ModelRegistry
- Task-type specific requirements
- Admin-configured overrides and pinning
- Latency thresholds and SLA requirements
- Cost optimization preferences

The router supports:
- Automatic model selection
- Latency-aware routing
- Fallback chains
- Admin pinning/overrides
- Geographic routing for Bedrock
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable
from enum import Enum

from sqlalchemy.orm import Session

from .ai_model_registry import get_registry, record_model_call, ModelRegistry
from .ai_settings import (
    get_ai_api_key,
    get_ai_model,
    is_bedrock_enabled,
    get_bedrock_region,
    AISettings,
)
from .ai_pricing import get_cost_tier
from .ai_runtime import complete_chat

logger = logging.getLogger(__name__)


class RoutingStrategy(str, Enum):
    """Available routing strategies."""

    PERFORMANCE = "performance"  # Best performing model based on metrics
    COST = "cost"  # Cheapest model that meets quality threshold
    LATENCY = "latency"  # Fastest responding model
    QUALITY = "quality"  # Highest quality output
    BALANCED = "balanced"  # Balance of all factors
    PINNED = "pinned"  # Use admin-pinned model only
    FALLBACK = "fallback"  # Use fallback chain order


@dataclass
class RoutingConfig:
    """Configuration for routing decisions."""

    strategy: RoutingStrategy = RoutingStrategy.BALANCED
    max_latency_ms: int = 5000  # Max acceptable latency
    min_quality_score: float = 0.6  # Min acceptable quality
    cost_weight: float = 0.2  # Weight for cost in balanced scoring
    latency_weight: float = 0.3  # Weight for latency
    quality_weight: float = 0.5  # Weight for quality
    prefer_bedrock: bool = True  # Prefer Bedrock for cost savings
    enable_fallback: bool = True  # Enable fallback on failure
    pinned_models: dict[str, tuple[str, str]] = field(
        default_factory=dict
    )  # task_type -> (provider, model)


@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    provider: str
    model_id: str
    strategy_used: RoutingStrategy
    reason: str
    confidence: float = 1.0  # How confident in this decision
    alternatives: list[tuple[str, str]] = field(
        default_factory=list
    )  # Fallback options
    expected_latency_ms: int = 0
    expected_quality: float = 0.5


class AdaptiveModelRouter:
    """
    Intelligent router for selecting the optimal AI model.

    Uses real-time performance data to make routing decisions,
    with support for admin overrides and fallback chains.

    Usage:
        router = AdaptiveModelRouter(db)

        # Get best model for a task
        decision = router.route("deep_analysis")
        print(f"Using {decision.provider}/{decision.model_id}")

        # Execute with automatic routing
        result = await router.execute(
            task_type="deep_analysis",
            prompt="Analyze this document",
            system_prompt="You are an analyst",
        )
    """

    # Default model preferences by task type
    TASK_DEFAULTS: dict[str, list[tuple[str, str]]] = {
        "quick_search": [
            ("bedrock", "amazon.nova-micro-v1:0"),
            ("bedrock", "amazon.nova-lite-v1:0"),
            ("gemini", "gemini-2.5-flash-lite"),
            ("openai", "gpt-5-mini"),
        ],
        "deep_analysis": [
            ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
            ("anthropic", "claude-sonnet-4-20250514"),
            ("openai", "gpt-5.2-thinking"),
        ],
        "synthesis": [
            ("openai", "gpt-5.2-instant"),
            ("anthropic", "claude-sonnet-4-20250514"),
            ("bedrock", "amazon.nova-pro-v1:0"),
        ],
        "validation": [
            ("anthropic", "claude-sonnet-4-20250514"),
            ("gemini", "gemini-2.5-flash-lite"),
            ("openai", "gpt-5.2-instant"),
        ],
        "causation_analysis": [
            ("anthropic", "claude-sonnet-4-20250514"),
            ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
            ("openai", "gpt-5.2-thinking"),
        ],
        "timeline": [
            ("bedrock", "amazon.nova-lite-v1:0"),
            ("openai", "gpt-5.2-instant"),
            ("gemini", "gemini-2.5-flash"),
        ],
        "default": [
            ("bedrock", "amazon.nova-pro-v1:0"),
            ("openai", "gpt-5.2-instant"),
            ("anthropic", "claude-sonnet-4-20250514"),
        ],
    }

    def __init__(
        self,
        db: Session,
        config: RoutingConfig | None = None,
        registry: ModelRegistry | None = None,
    ):
        self.db = db
        self.config = config or RoutingConfig()
        self.registry = registry or get_registry()

        # Load provider availability
        self.openai_key = get_ai_api_key("openai", db)
        self.anthropic_key = get_ai_api_key("anthropic", db)
        self.gemini_key = get_ai_api_key("gemini", db)
        self.xai_key = get_ai_api_key("xai", db) or get_ai_api_key("grok", db)
        self.perplexity_key = get_ai_api_key("perplexity", db)
        self.bedrock_enabled = is_bedrock_enabled(db)
        self.bedrock_region = get_bedrock_region(db)

        # Load admin overrides
        self._load_admin_overrides()

    def _load_admin_overrides(self) -> None:
        """Load admin-configured model overrides."""
        # These could come from database settings
        # For now, check for specific settings keys
        try:
            # Check for per-function pinned models
            for task_type in [
                "quick_search",
                "deep_analysis",
                "synthesis",
                "validation",
            ]:
                pinned = AISettings.get(f"ai_function_{task_type}_model", self.db)
                if pinned:
                    # Parse format: "provider:model_id"
                    if ":" in pinned:
                        provider, model_id = pinned.split(":", 1)
                        self.config.pinned_models[task_type] = (provider, model_id)
        except Exception as e:
            logger.warning(f"Failed to load admin overrides: {e}")

    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider is available."""
        if provider == "openai":
            return bool(self.openai_key)
        elif provider == "anthropic":
            return bool(self.anthropic_key)
        elif provider == "gemini":
            return bool(self.gemini_key)
        elif provider in {"xai", "grok"}:
            return bool(self.xai_key)
        elif provider == "perplexity":
            return bool(self.perplexity_key)
        elif provider == "bedrock":
            return self.bedrock_enabled
        return False

    def get_available_providers(self) -> list[str]:
        """Get list of available providers."""
        providers = []
        if self.openai_key:
            providers.append("openai")
        if self.anthropic_key:
            providers.append("anthropic")
        if self.gemini_key:
            providers.append("gemini")
        if self.xai_key:
            providers.append("xai")
        if self.perplexity_key:
            providers.append("perplexity")
        if self.bedrock_enabled:
            providers.append("bedrock")
        return providers

    def route(
        self,
        task_type: str,
        strategy: RoutingStrategy | None = None,
        context: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        """
        Make a routing decision for a task type.

        Args:
            task_type: Type of task (quick_search, deep_analysis, etc.)
            strategy: Override strategy (uses config default if None)
            context: Additional context for routing (e.g., priority, budget)

        Returns:
            RoutingDecision with selected model and alternatives
        """
        strategy = strategy or self.config.strategy
        context = context or {}

        # Check for pinned model first
        if task_type in self.config.pinned_models:
            provider, model_id = self.config.pinned_models[task_type]
            if self.is_provider_available(provider):
                return RoutingDecision(
                    provider=provider,
                    model_id=model_id,
                    strategy_used=RoutingStrategy.PINNED,
                    reason=f"Admin pinned model for {task_type}",
                    confidence=1.0,
                    alternatives=self._get_alternatives(
                        task_type, exclude=(provider, model_id)
                    ),
                )

        # Route based on strategy
        if strategy == RoutingStrategy.PERFORMANCE:
            return self._route_by_performance(task_type)
        elif strategy == RoutingStrategy.COST:
            return self._route_by_cost(task_type)
        elif strategy == RoutingStrategy.LATENCY:
            return self._route_by_latency(task_type)
        elif strategy == RoutingStrategy.QUALITY:
            return self._route_by_quality(task_type)
        elif strategy == RoutingStrategy.BALANCED:
            return self._route_balanced(task_type, context)
        elif strategy == RoutingStrategy.FALLBACK:
            return self._route_by_fallback(task_type)
        else:
            return self._route_balanced(task_type, context)

    def _route_by_performance(self, task_type: str) -> RoutingDecision:
        """Route to the best performing model based on registry data."""
        # Check registry for best model
        best = self.registry.get_best_model(
            task_type,
            available_providers=self.get_available_providers(),
        )

        if best:
            provider, model_id = best
            metrics = self.registry.get_model_metrics(provider, model_id)
            return RoutingDecision(
                provider=provider,
                model_id=model_id,
                strategy_used=RoutingStrategy.PERFORMANCE,
                reason=(
                    f"Best performing model (score: {metrics.overall_score:.2f})"
                    if metrics
                    else "Best performing"
                ),
                confidence=0.9 if metrics and metrics.total_calls > 10 else 0.5,
                alternatives=self._get_alternatives(task_type, exclude=best),
                expected_latency_ms=int(metrics.avg_latency_ms) if metrics else 0,
                expected_quality=metrics.avg_quality_score if metrics else 0.5,
            )

        # Fall back to defaults
        return self._route_by_fallback(task_type)

    def _route_by_cost(self, task_type: str) -> RoutingDecision:
        """Route to the cheapest model that meets quality threshold."""
        # Cost ordering (cheapest first)
        cost_order = [
            ("bedrock", "amazon.nova-micro-v1:0"),  # ~$0.035/1M
            ("bedrock", "amazon.nova-lite-v1:0"),  # ~$0.06/1M
            ("gemini", "gemini-2.5-flash-lite"),  # fast/budget
            ("bedrock", "amazon.nova-pro-v1:0"),  # ~$0.8/1M
            ("openai", "gpt-5-mini"),
            ("anthropic", "claude-4.5-haiku"),
            ("openai", "gpt-5.2-instant"),
            ("anthropic", "claude-sonnet-4.5"),
        ]

        for provider, model_id in cost_order:
            if not self.is_provider_available(provider):
                continue

            metrics = self.registry.get_model_metrics(provider, model_id)
            if metrics and metrics.avg_quality_score < self.config.min_quality_score:
                continue  # Skip if quality too low

            return RoutingDecision(
                provider=provider,
                model_id=model_id,
                strategy_used=RoutingStrategy.COST,
                reason="Cheapest available model meeting quality threshold",
                confidence=0.8,
                alternatives=self._get_alternatives(
                    task_type, exclude=(provider, model_id)
                ),
            )

        # Fall back to defaults
        return self._route_by_fallback(task_type)

    def _route_by_latency(self, task_type: str) -> RoutingDecision:
        """Route to the fastest responding model."""
        # Get all models with latency data
        rankings = self.registry.get_model_ranking(task_type, top_k=10)

        if rankings:
            # Sort by latency (ascending)
            ranked_by_latency = sorted(
                rankings, key=lambda x: x.get("avg_latency_ms", float("inf"))
            )

            for model_info in ranked_by_latency:
                provider = model_info["provider"]
                model_id = model_info["model_id"]

                if not self.is_provider_available(provider):
                    continue

                if model_info.get("avg_latency_ms", 0) > self.config.max_latency_ms:
                    continue

                return RoutingDecision(
                    provider=provider,
                    model_id=model_id,
                    strategy_used=RoutingStrategy.LATENCY,
                    reason=f"Fastest model ({model_info.get('avg_latency_ms', 0)}ms avg)",
                    confidence=0.85,
                    alternatives=self._get_alternatives(
                        task_type, exclude=(provider, model_id)
                    ),
                    expected_latency_ms=int(model_info.get("avg_latency_ms", 0)),
                )

        # Default to fast models
        fast_models = [
            ("bedrock", "amazon.nova-micro-v1:0"),
            ("bedrock", "amazon.nova-lite-v1:0"),
            ("gemini", "gemini-2.5-flash-lite"),
        ]

        for provider, model_id in fast_models:
            if self.is_provider_available(provider):
                return RoutingDecision(
                    provider=provider,
                    model_id=model_id,
                    strategy_used=RoutingStrategy.LATENCY,
                    reason="Default fast model",
                    confidence=0.6,
                    alternatives=self._get_alternatives(
                        task_type, exclude=(provider, model_id)
                    ),
                )

        return self._route_by_fallback(task_type)

    def _route_by_quality(self, task_type: str) -> RoutingDecision:
        """Route to the highest quality model."""
        # Quality ordering (highest quality first)
        quality_order = [
            ("anthropic", "claude-opus-4.5"),
            ("openai", "gpt-5.2-pro"),
            ("openai", "gpt-5.2-thinking"),
            ("anthropic", "claude-sonnet-4.5"),
            ("gemini", "gemini-2.5-pro"),
            ("bedrock", "anthropic.claude-sonnet-4-5-20250929-v1:0"),
            ("bedrock", "amazon.nova-pro-v1:0"),
        ]

        for provider, model_id in quality_order:
            if self.is_provider_available(provider):
                metrics = self.registry.get_model_metrics(provider, model_id)
                return RoutingDecision(
                    provider=provider,
                    model_id=model_id,
                    strategy_used=RoutingStrategy.QUALITY,
                    reason="Highest quality model available",
                    confidence=0.9,
                    alternatives=self._get_alternatives(
                        task_type, exclude=(provider, model_id)
                    ),
                    expected_quality=metrics.avg_quality_score if metrics else 0.85,
                )

        return self._route_by_fallback(task_type)

    def _route_balanced(
        self, task_type: str, context: dict[str, Any]
    ) -> RoutingDecision:
        """Route using balanced scoring of all factors."""
        # Get registry rankings
        rankings = self.registry.get_model_ranking(task_type, top_k=10)

        if rankings:
            # Score each model
            scored: list[tuple[float, dict[str, Any]]] = []
            for model_info in rankings:
                provider = model_info["provider"]
                if not self.is_provider_available(provider):
                    continue

                # Calculate balanced score
                quality_score = model_info.get("avg_quality", 0.5)
                latency_score = max(0, 1 - model_info.get("avg_latency_ms", 0) / 5000)
                reliability = model_info.get("reliability", 0.5)

                # Simple cost score (lower is better)
                cost_tier = self._get_cost_tier(provider, model_info["model_id"])
                cost_score = 1 - (cost_tier / 5)  # Normalize 0-5 tier to 0-1

                balanced = (
                    quality_score * self.config.quality_weight
                    + latency_score * self.config.latency_weight
                    + cost_score * self.config.cost_weight
                    + reliability * 0.1  # Small reliability bonus
                )

                scored.append((balanced, model_info))

            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                best_score, best_model = scored[0]

                return RoutingDecision(
                    provider=best_model["provider"],
                    model_id=best_model["model_id"],
                    strategy_used=RoutingStrategy.BALANCED,
                    reason=f"Best balanced score ({best_score:.2f})",
                    confidence=0.85,
                    alternatives=[
                        (m["provider"], m["model_id"]) for _, m in scored[1:4]
                    ],
                    expected_latency_ms=int(best_model.get("avg_latency_ms", 0)),
                    expected_quality=best_model.get("avg_quality", 0.5),
                )

        # Fall back to task defaults with Bedrock preference
        return self._route_by_fallback(task_type)

    def _route_by_fallback(self, task_type: str) -> RoutingDecision:
        """Route using predefined fallback order."""
        defaults = self._get_task_chain(task_type)

        for provider, model_id in defaults:
            if self.is_provider_available(provider):
                return RoutingDecision(
                    provider=provider,
                    model_id=model_id,
                    strategy_used=RoutingStrategy.FALLBACK,
                    reason="Fallback chain default",
                    confidence=0.7,
                    alternatives=self._get_alternatives(
                        task_type, exclude=(provider, model_id)
                    ),
                )

        # Last resort - any available provider
        for provider in ["bedrock", "openai", "anthropic", "gemini"]:
            if self.is_provider_available(provider):
                model_id = get_ai_model(provider, self.db)
                return RoutingDecision(
                    provider=provider,
                    model_id=model_id,
                    strategy_used=RoutingStrategy.FALLBACK,
                    reason="Last resort fallback",
                    confidence=0.5,
                    alternatives=[],
                )

        # No models available
        raise RuntimeError("No AI providers available for routing")

    def _get_alternatives(
        self,
        task_type: str,
        exclude: tuple[str, str] | None = None,
    ) -> list[tuple[str, str]]:
        """Get alternative models for fallback."""
        defaults = self._get_task_chain(task_type)
        alternatives = []

        for provider, model_id in defaults:
            if (provider, model_id) == exclude:
                continue
            if self.is_provider_available(provider):
                alternatives.append((provider, model_id))

        return alternatives[:3]  # Return top 3 alternatives

    def _get_cost_tier(self, provider: str, model_id: str) -> int:
        """Get cost tier (1=cheapest, 5=expensive)."""
        return get_cost_tier(model_id, default=3)

    def _get_task_chain(self, task_type: str) -> list[tuple[str, str]]:
        """Read task fallback chain from AISettings, with static defaults fallback."""
        try:
            config = AISettings.get_function_config(task_type, self.db)
            raw_chain = config.get("fallback_chain")
            if isinstance(raw_chain, list):
                parsed: list[tuple[str, str]] = []
                for item in raw_chain:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        parsed.append((str(item[0]), str(item[1])))
                if parsed:
                    return parsed
        except Exception as exc:
            logger.debug("Failed to load task chain for %s: %s", task_type, exc)

        return self.TASK_DEFAULTS.get(task_type, self.TASK_DEFAULTS["default"])

    async def execute(
        self,
        task_type: str,
        prompt: str,
        system_prompt: str = "",
        strategy: RoutingStrategy | None = None,
        call_fn: Callable[[str, str, str, str], Awaitable[str]] | None = None,
    ) -> tuple[str, RoutingDecision]:
        """
        Execute a prompt with automatic routing and fallback.

        Args:
            task_type: Type of task for routing
            prompt: The prompt to execute
            system_prompt: Optional system prompt
            strategy: Override routing strategy
            call_fn: Custom function(provider, model, prompt, system) -> response

        Returns:
            Tuple of (response, decision)
        """
        decision = self.route(task_type, strategy)

        # Try primary model
        start_time = time.time()

        try:
            if call_fn:
                response = await call_fn(
                    decision.provider,
                    decision.model_id,
                    prompt,
                    system_prompt,
                )
            else:
                response = await self._default_call(
                    decision.provider,
                    decision.model_id,
                    prompt,
                    system_prompt,
                )

            latency = int((time.time() - start_time) * 1000)

            # Record success
            record_model_call(
                provider=decision.provider,
                model_id=decision.model_id,
                task_type=task_type,
                latency_ms=latency,
                quality_score=0.8,  # Default quality
                success=True,
            )

            return response, decision

        except Exception as e:
            latency = int((time.time() - start_time) * 1000)

            # Record failure
            record_model_call(
                provider=decision.provider,
                model_id=decision.model_id,
                task_type=task_type,
                latency_ms=latency,
                quality_score=0,
                success=False,
                error=str(e),
            )

            # Try alternatives if fallback enabled
            if self.config.enable_fallback and decision.alternatives:
                for alt_provider, alt_model in decision.alternatives:
                    try:
                        start_time = time.time()

                        if call_fn:
                            response = await call_fn(
                                alt_provider,
                                alt_model,
                                prompt,
                                system_prompt,
                            )
                        else:
                            response = await self._default_call(
                                alt_provider,
                                alt_model,
                                prompt,
                                system_prompt,
                            )

                        latency = int((time.time() - start_time) * 1000)

                        # Record success
                        record_model_call(
                            provider=alt_provider,
                            model_id=alt_model,
                            task_type=task_type,
                            latency_ms=latency,
                            quality_score=0.75,
                            success=True,
                        )

                        # Update decision to reflect actual model used
                        decision.provider = alt_provider
                        decision.model_id = alt_model
                        decision.reason = (
                            f"Fallback after primary failure: {str(e)[:50]}"
                        )

                        return response, decision

                    except Exception as alt_e:
                        latency = int((time.time() - start_time) * 1000)
                        record_model_call(
                            provider=alt_provider,
                            model_id=alt_model,
                            task_type=task_type,
                            latency_ms=latency,
                            quality_score=0,
                            success=False,
                            error=str(alt_e),
                        )
                        continue

            # All options exhausted
            raise RuntimeError(f"All models failed for {task_type}: {str(e)}")

    async def _default_call(
        self,
        provider: str,
        model_id: str,
        prompt: str,
        system_prompt: str,
    ) -> str:
        """Default implementation for calling models."""
        api_key = None
        if provider == "openai":
            api_key = self.openai_key
        elif provider == "anthropic":
            api_key = self.anthropic_key
        elif provider == "gemini":
            api_key = self.gemini_key

        return await complete_chat(
            provider=provider,
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            db=self.db,
            api_key=api_key,
            bedrock_region=self.bedrock_region,
            max_tokens=4000,
            temperature=0.3,
        )


# Convenience function for quick routing
def get_router(db: Session) -> AdaptiveModelRouter:
    """Get an adaptive router instance."""
    return AdaptiveModelRouter(db)
