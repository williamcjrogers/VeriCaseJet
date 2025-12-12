"""
AI Metrics Collection - Structured logging and metrics for AI operations.

This module provides comprehensive metrics collection for all AI model calls:
- Latency tracking
- Token usage and cost estimation
- Quality scores
- Error rates and types
- Per-provider/model breakdowns

Metrics are stored in Redis (if available) for time-series analysis
and can be exported to external monitoring systems.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any
from collections import defaultdict

from .ai_pricing import TOKEN_PRICING_PER_1M, estimate_cost_usd

logger = logging.getLogger(__name__)

# Try to import Redis
try:
    from redis import Redis
    REDIS_AVAILABLE = True
except ImportError:
    Redis = None  # type: ignore
    REDIS_AVAILABLE = False


@dataclass
class AICallMetric:
    """Metrics for a single AI call."""
    timestamp: datetime
    provider: str
    model_id: str
    task_type: str
    function_name: str
    agent_name: str | None = None

    # Performance
    latency_ms: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0

    # Quality
    quality_score: float = 0.0
    validation_passed: bool = True

    # Status
    success: bool = True
    error_type: str | None = None
    error_message: str | None = None

    # Cost (estimated)
    estimated_cost_usd: float = 0.0

    # Context
    session_id: str | None = None
    user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "provider": self.provider,
            "model_id": self.model_id,
            "task_type": self.task_type,
            "function_name": self.function_name,
            "agent_name": self.agent_name,
            "latency_ms": self.latency_ms,
            "tokens_prompt": self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "tokens_total": self.tokens_total,
            "quality_score": self.quality_score,
            "validation_passed": self.validation_passed,
            "success": self.success,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "estimated_cost_usd": self.estimated_cost_usd,
            "session_id": self.session_id,
            "user_id": self.user_id,
        }


@dataclass
class AggregatedMetrics:
    """Aggregated metrics for a time period."""
    period_start: datetime
    period_end: datetime
    period_type: str  # minute, hour, day

    # Totals
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0

    # Latency
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    max_latency_ms: float = 0.0

    # Tokens
    total_tokens: int = 0
    avg_tokens_per_call: float = 0.0

    # Quality
    avg_quality_score: float = 0.0
    validation_pass_rate: float = 0.0

    # Cost
    total_cost_usd: float = 0.0

    # Breakdowns
    by_provider: dict[str, int] = field(default_factory=dict)
    by_model: dict[str, int] = field(default_factory=dict)
    by_task_type: dict[str, int] = field(default_factory=dict)
    by_error_type: dict[str, int] = field(default_factory=dict)


class MetricsCollector:
    """
    Collects and stores AI operation metrics.

    Provides:
    - Real-time metric logging
    - Time-series storage in Redis
    - Aggregation for dashboards
    - Export capabilities
    """

    # Token pricing per 1M tokens (approximate) - shared source of truth
    TOKEN_PRICING = TOKEN_PRICING_PER_1M

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url
        self._redis: Redis | None = None
        self._init_redis()

        # In-memory buffer for recent metrics
        self._recent_metrics: list[AICallMetric] = []
        self._max_buffer_size = 1000

        # Counters for quick stats
        self._call_counts: dict[str, int] = defaultdict(int)
        self._error_counts: dict[str, int] = defaultdict(int)
        self._latency_sums: dict[str, float] = defaultdict(float)

    def _init_redis(self) -> None:
        """Initialize Redis connection."""
        if not REDIS_AVAILABLE or not self.redis_url:
            return

        try:
            self._redis = Redis.from_url(self.redis_url)
            self._redis.ping()
            logger.info("MetricsCollector: Redis connected")
        except Exception as e:
            logger.warning(f"MetricsCollector: Redis unavailable: {e}")
            self._redis = None

    def record(
        self,
        provider: str,
        model_id: str,
        task_type: str,
        function_name: str,
        latency_ms: int,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        quality_score: float = 0.0,
        success: bool = True,
        error_type: str | None = None,
        error_message: str | None = None,
        agent_name: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> AICallMetric:
        """
        Record metrics for an AI call.

        Args:
            provider: AI provider (openai, anthropic, etc.)
            model_id: Model identifier
            task_type: Type of task
            function_name: Name of the function
            latency_ms: Response time in milliseconds
            tokens_prompt: Input tokens used
            tokens_completion: Output tokens generated
            quality_score: Quality score 0-1
            success: Whether call succeeded
            error_type: Error category if failed
            error_message: Error details if failed
            agent_name: Agent that made the call
            session_id: Session identifier
            user_id: User identifier

        Returns:
            The recorded metric
        """
        tokens_total = tokens_prompt + tokens_completion
        estimated_cost = self._estimate_cost(model_id, tokens_prompt, tokens_completion)

        metric = AICallMetric(
            timestamp=datetime.now(timezone.utc),
            provider=provider,
            model_id=model_id,
            task_type=task_type,
            function_name=function_name,
            agent_name=agent_name,
            latency_ms=latency_ms,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            tokens_total=tokens_total,
            quality_score=quality_score,
            validation_passed=success,
            success=success,
            error_type=error_type,
            error_message=error_message,
            estimated_cost_usd=estimated_cost,
            session_id=session_id,
            user_id=user_id,
        )

        # Store in buffer
        self._recent_metrics.append(metric)
        if len(self._recent_metrics) > self._max_buffer_size:
            self._recent_metrics.pop(0)

        # Update counters
        model_key = f"{provider}:{model_id}"
        self._call_counts[model_key] += 1
        self._latency_sums[model_key] += latency_ms
        if not success:
            self._error_counts[model_key] += 1

        # Persist to Redis
        self._persist_metric(metric)

        # Log for monitoring
        if success:
            logger.debug(
                f"AI call: {provider}/{model_id} - {latency_ms}ms, "
                f"{tokens_total} tokens, ${estimated_cost:.4f}"
            )
        else:
            logger.warning(
                f"AI call failed: {provider}/{model_id} - {error_type}: {error_message}"
            )

        return metric

    def _estimate_cost(
        self,
        model_id: str,
        tokens_prompt: int,
        tokens_completion: int,
    ) -> float:
        """Estimate cost in USD based on token usage."""
        return estimate_cost_usd(
            model_id=model_id,
            tokens_total=tokens_prompt + tokens_completion,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
        )

    def _persist_metric(self, metric: AICallMetric) -> None:
        """Persist metric to Redis."""
        if not self._redis:
            return

        try:
            # Store in time-series list
            key = f"ai_metrics:{metric.timestamp.strftime('%Y-%m-%d-%H')}"
            self._redis.rpush(key, json.dumps(metric.to_dict()))
            self._redis.expire(key, 86400 * 7)  # 7 day retention

            # Update aggregates
            hour_key = f"ai_metrics_agg:{metric.timestamp.strftime('%Y-%m-%d-%H')}"
            self._redis.hincrby(hour_key, "total_calls", 1)
            self._redis.hincrby(hour_key, f"calls_{metric.provider}", 1)
            self._redis.hincrby(hour_key, f"calls_{metric.model_id}", 1)
            self._redis.hincrby(hour_key, "total_latency", metric.latency_ms)
            self._redis.hincrby(hour_key, "total_tokens", metric.tokens_total)
            if not metric.success:
                self._redis.hincrby(hour_key, "failed_calls", 1)
            self._redis.expire(hour_key, 86400 * 7)

        except Exception as e:
            logger.warning(f"Failed to persist metric to Redis: {e}")

    def get_recent_metrics(
        self,
        limit: int = 100,
        provider: str | None = None,
        task_type: str | None = None,
    ) -> list[AICallMetric]:
        """Get recent metrics from buffer."""
        metrics = self._recent_metrics[-limit:]

        if provider:
            metrics = [m for m in metrics if m.provider == provider]
        if task_type:
            metrics = [m for m in metrics if m.task_type == task_type]

        return list(reversed(metrics))

    def get_aggregated_metrics(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        period_type: str = "hour",
    ) -> AggregatedMetrics:
        """
        Get aggregated metrics for a time period.

        Args:
            start_time: Start of period (default: last hour)
            end_time: End of period (default: now)
            period_type: minute, hour, or day

        Returns:
            Aggregated metrics
        """
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            if period_type == "minute":
                start_time = end_time - timedelta(minutes=1)
            elif period_type == "hour":
                start_time = end_time - timedelta(hours=1)
            else:
                start_time = end_time - timedelta(days=1)

        # Filter metrics
        relevant = [
            m for m in self._recent_metrics
            if start_time <= m.timestamp <= end_time
        ]

        if not relevant:
            return AggregatedMetrics(
                period_start=start_time,
                period_end=end_time,
                period_type=period_type,
            )

        # Calculate aggregates
        latencies = [m.latency_ms for m in relevant]
        latencies.sort()

        total_calls = len(relevant)
        successful = sum(1 for m in relevant if m.success)

        by_provider: dict[str, int] = defaultdict(int)
        by_model: dict[str, int] = defaultdict(int)
        by_task: dict[str, int] = defaultdict(int)
        by_error: dict[str, int] = defaultdict(int)

        for m in relevant:
            by_provider[m.provider] += 1
            by_model[m.model_id] += 1
            by_task[m.task_type] += 1
            if m.error_type:
                by_error[m.error_type] += 1

        return AggregatedMetrics(
            period_start=start_time,
            period_end=end_time,
            period_type=period_type,
            total_calls=total_calls,
            successful_calls=successful,
            failed_calls=total_calls - successful,
            avg_latency_ms=sum(latencies) / len(latencies),
            p50_latency_ms=latencies[len(latencies) // 2],
            p95_latency_ms=latencies[int(len(latencies) * 0.95)],
            p99_latency_ms=latencies[int(len(latencies) * 0.99)] if len(latencies) >= 100 else latencies[-1],
            max_latency_ms=max(latencies),
            total_tokens=sum(m.tokens_total for m in relevant),
            avg_tokens_per_call=sum(m.tokens_total for m in relevant) / total_calls,
            avg_quality_score=sum(m.quality_score for m in relevant) / total_calls,
            validation_pass_rate=sum(1 for m in relevant if m.validation_passed) / total_calls,
            total_cost_usd=sum(m.estimated_cost_usd for m in relevant),
            by_provider=dict(by_provider),
            by_model=dict(by_model),
            by_task_type=dict(by_task),
            by_error_type=dict(by_error),
        )

    def get_quick_stats(self) -> dict[str, Any]:
        """Get quick statistics from counters."""
        total_calls = sum(self._call_counts.values())
        total_errors = sum(self._error_counts.values())

        return {
            "total_calls": total_calls,
            "total_errors": total_errors,
            "error_rate": total_errors / total_calls if total_calls > 0 else 0,
            "calls_by_model": dict(self._call_counts),
            "errors_by_model": dict(self._error_counts),
            "avg_latency_by_model": {
                k: self._latency_sums[k] / self._call_counts[k]
                for k in self._call_counts
                if self._call_counts[k] > 0
            },
        }

    def reset_counters(self) -> None:
        """Reset in-memory counters."""
        self._call_counts.clear()
        self._error_counts.clear()
        self._latency_sums.clear()


# Global collector instance
_collector: MetricsCollector | None = None


def get_collector(redis_url: str | None = None) -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _collector
    if _collector is None:
        _collector = MetricsCollector(redis_url=redis_url)
    return _collector


def record_ai_call(
    provider: str,
    model_id: str,
    task_type: str,
    function_name: str,
    latency_ms: int,
    **kwargs: Any,
) -> AICallMetric:
    """Convenience function to record an AI call."""
    collector = get_collector()
    return collector.record(
        provider=provider,
        model_id=model_id,
        task_type=task_type,
        function_name=function_name,
        latency_ms=latency_ms,
        **kwargs,
    )
