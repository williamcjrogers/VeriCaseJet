"""
AI Model Registry - Real-time performance tracking and model selection.

This module maintains rolling performance metrics for each AI model,
enabling dynamic model selection based on:
- Latency (response time)
- Quality scores (from validation)
- Error rates
- Cost (token usage)

The registry supports the adaptive routing strategy where the best
model for each task is selected based on live performance data.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any
from collections import deque

logger = logging.getLogger(__name__)

# Try to import Redis for persistent metrics
try:
    from redis import Redis
    REDIS_AVAILABLE = True
except ImportError:
    Redis = None  # type: ignore
    REDIS_AVAILABLE = False


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
            self.avg_latency_ms = sum(self.recent_latencies) / len(self.recent_latencies)
            self.avg_quality_score = sum(self.recent_quality_scores) / len(self.recent_quality_scores)
            self.avg_tokens_used = (self.avg_tokens_used * (self.successful_calls - 1) + tokens_used) // self.successful_calls

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
        recent_success = len([e for e in self.recent_errors if not e]) if self.recent_errors else self.successful_calls
        recent_total = len(self.recent_errors) if self.recent_errors else self.total_calls
        recent_rate = recent_success / max(recent_total, 1)

        self.reliability_score = success_rate * 0.6 + recent_rate * 0.4

        # Overall score: balance of quality, speed, and reliability
        # Normalize latency (lower is better, target 2000ms)
        latency_score = max(0, 1 - (self.avg_latency_ms / 5000)) if self.avg_latency_ms > 0 else 0.5

        # Quality score is already 0-1
        quality = self.avg_quality_score if self.avg_quality_score > 0 else 0.5

        # Weighted combination
        self.overall_score = (
            quality * 0.40 +          # Quality matters most
            latency_score * 0.30 +    # Speed is important
            self.reliability_score * 0.30  # Reliability is crucial
        )

    def _estimate_cost(self) -> float:
        """Estimate cost in USD based on token usage and model pricing."""
        # Approximate pricing per 1M tokens (input + output averaged)
        pricing = {
            "gpt-4o": 5.0,
            "gpt-4o-mini": 0.15,
            "gpt-4": 30.0,
            "gpt-3.5-turbo": 0.5,
            "claude-sonnet-4-20250514": 3.0,
            "claude-opus-4-20250514": 15.0,
            "claude-3-5-haiku-20241022": 0.25,
            "gemini-2.0-flash": 0.35,
            "gemini-1.5-pro": 1.25,
            "amazon.nova-pro-v1:0": 0.8,
            "amazon.nova-lite-v1:0": 0.06,
            "amazon.nova-micro-v1:0": 0.035,
        }

        rate = pricing.get(self.model_id, 1.0)  # Default $1 per 1M tokens
        return (self.total_tokens / 1_000_000) * rate

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
            self.model_rankings[model_key] = self.model_rankings[model_key] * 0.7 + score * 0.3
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
        self._model_metrics: dict[str, ModelMetrics] = {}  # provider:model_id -> metrics
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
        return {
            key: metrics.to_dict()
            for key, metrics in self._model_metrics.items()
        }

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
            results.append({
                "provider": provider,
                "model_id": model_id,
                "score": score,
                "avg_latency_ms": metrics.avg_latency_ms if metrics else 0,
                "avg_quality": metrics.avg_quality_score if metrics else 0,
                "reliability": metrics.reliability_score if metrics else 0,
            })

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

    def reset_metrics(self, provider: str | None = None, model_id: str | None = None) -> None:
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
