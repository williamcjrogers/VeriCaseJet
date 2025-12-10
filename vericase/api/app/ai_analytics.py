"""
AI Analytics Dashboard - API endpoints for monitoring AI orchestration performance.

This module provides dashboard-ready endpoints for:
- Model health monitoring
- Function performance metrics
- Cost breakdown analysis
- Quality metrics tracking
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .ai_metrics import get_collector, AggregatedMetrics
from .ai_model_registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["AI Analytics"])


# ============================================================================
# Response Models
# ============================================================================

class ModelHealthResponse(BaseModel):
    """Health status for a single model."""
    provider: str
    model_id: str
    status: str  # healthy, degraded, unhealthy
    avg_latency_ms: float
    p95_latency_ms: float
    error_rate: float
    total_calls: int
    last_error: str | None = None
    last_error_time: str | None = None


class ProviderHealthResponse(BaseModel):
    """Health status for a provider."""
    provider: str
    status: str
    models: list[ModelHealthResponse]
    total_calls: int
    avg_latency_ms: float
    error_rate: float


class SystemHealthResponse(BaseModel):
    """Overall system health."""
    status: str
    providers: list[ProviderHealthResponse]
    total_calls_last_hour: int
    avg_latency_ms: float
    error_rate: float
    timestamp: str


class FunctionMetricsResponse(BaseModel):
    """Metrics for a specific function/task type."""
    function_name: str
    total_calls: int
    avg_completion_time_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    avg_sources_analyzed: float
    success_rate: float
    avg_quality_score: float
    preferred_model: str | None = None
    calls_by_model: dict[str, int] = {}


class CostBreakdownResponse(BaseModel):
    """Cost breakdown analysis."""
    period: str
    total_cost_usd: float
    by_provider: dict[str, float]
    by_function: dict[str, float]
    by_model: dict[str, float]
    by_agent: dict[str, float]
    tokens_used: int
    avg_cost_per_call: float
    projected_monthly_cost: float


class QualityMetricsResponse(BaseModel):
    """Quality metrics summary."""
    period: str
    validation_pass_rate: float
    avg_quality_score: float
    user_corrections: int
    citation_accuracy: float
    coherence_score: float
    by_function: dict[str, float]
    by_model: dict[str, float]
    quality_trend: list[dict[str, Any]]


class PerformanceTrendResponse(BaseModel):
    """Performance trends over time."""
    period: str
    data_points: list[dict[str, Any]]
    summary: dict[str, Any]


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health() -> SystemHealthResponse:
    """
    Get overall system health status.

    Returns health status for all AI providers and models,
    including latency, error rates, and call counts.
    """
    registry = get_registry()
    collector = get_collector()

    # Get metrics from last hour
    aggregated = collector.get_aggregated_metrics(period_type="hour")

    # Build provider health
    providers: list[ProviderHealthResponse] = []
    provider_models: dict[str, list[ModelHealthResponse]] = {}

    # Get health from registry
    health_data = registry.get_health_status()

    for model_key, model_health in health_data.get("models", {}).items():
        parts = model_key.split(":", 1)
        if len(parts) == 2:
            provider, model_id = parts
        else:
            provider = "unknown"
            model_id = model_key

        if provider not in provider_models:
            provider_models[provider] = []

        provider_models[provider].append(ModelHealthResponse(
            provider=provider,
            model_id=model_id,
            status=model_health.get("status", "unknown"),
            avg_latency_ms=model_health.get("avg_latency", 0),
            p95_latency_ms=model_health.get("p95_latency", 0),
            error_rate=model_health.get("error_rate", 0),
            total_calls=model_health.get("total_calls", 0),
            last_error=model_health.get("last_error"),
            last_error_time=model_health.get("last_error_time"),
        ))

    for provider, models in provider_models.items():
        total_calls = sum(m.total_calls for m in models)
        avg_latency = (
            sum(m.avg_latency_ms * m.total_calls for m in models) / total_calls
            if total_calls > 0 else 0
        )
        error_rate = (
            sum(m.error_rate * m.total_calls for m in models) / total_calls
            if total_calls > 0 else 0
        )

        # Determine provider status
        if any(m.status == "unhealthy" for m in models):
            status = "degraded"
        elif all(m.status == "healthy" for m in models):
            status = "healthy"
        else:
            status = "degraded"

        providers.append(ProviderHealthResponse(
            provider=provider,
            status=status,
            models=models,
            total_calls=total_calls,
            avg_latency_ms=avg_latency,
            error_rate=error_rate,
        ))

    # Determine overall status
    if not providers:
        overall_status = "unknown"
    elif any(p.status == "unhealthy" for p in providers):
        overall_status = "degraded"
    elif all(p.status == "healthy" for p in providers):
        overall_status = "healthy"
    else:
        overall_status = "degraded"

    return SystemHealthResponse(
        status=overall_status,
        providers=providers,
        total_calls_last_hour=aggregated.total_calls,
        avg_latency_ms=aggregated.avg_latency_ms,
        error_rate=(
            aggregated.failed_calls / aggregated.total_calls
            if aggregated.total_calls > 0 else 0
        ),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/health/provider/{provider}")
async def get_provider_health(provider: str) -> ProviderHealthResponse:
    """Get health status for a specific provider."""
    system_health = await get_system_health()

    for p in system_health.providers:
        if p.provider == provider:
            return p

    raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")


@router.get("/functions", response_model=list[FunctionMetricsResponse])
async def get_function_metrics(
    period_hours: int = Query(default=24, ge=1, le=168),
) -> list[FunctionMetricsResponse]:
    """
    Get performance metrics for all AI functions.

    Args:
        period_hours: Time period to analyze (1-168 hours, default 24)
    """
    collector = get_collector()
    registry = get_registry()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=period_hours)

    # Get recent metrics
    metrics = collector.get_recent_metrics(limit=1000)
    relevant = [m for m in metrics if start_time <= m.timestamp <= end_time]

    # Group by task type
    by_function: dict[str, list] = {}
    for m in relevant:
        if m.task_type not in by_function:
            by_function[m.task_type] = []
        by_function[m.task_type].append(m)

    results: list[FunctionMetricsResponse] = []

    for func_name, func_metrics in by_function.items():
        latencies = sorted([m.latency_ms for m in func_metrics])
        total = len(func_metrics)

        # Model breakdown
        calls_by_model: dict[str, int] = {}
        for m in func_metrics:
            calls_by_model[m.model_id] = calls_by_model.get(m.model_id, 0) + 1

        # Get preferred model from registry
        best_model = registry.get_best_model(func_name)

        results.append(FunctionMetricsResponse(
            function_name=func_name,
            total_calls=total,
            avg_completion_time_ms=sum(latencies) / total if total > 0 else 0,
            p50_latency_ms=latencies[total // 2] if total > 0 else 0,
            p95_latency_ms=latencies[int(total * 0.95)] if total > 0 else 0,
            avg_sources_analyzed=0,  # Would need to track this in metrics
            success_rate=sum(1 for m in func_metrics if m.success) / total if total > 0 else 0,
            avg_quality_score=sum(m.quality_score for m in func_metrics) / total if total > 0 else 0,
            preferred_model=best_model,
            calls_by_model=calls_by_model,
        ))

    return results


@router.get("/functions/{function_name}", response_model=FunctionMetricsResponse)
async def get_function_metrics_detail(
    function_name: str,
    period_hours: int = Query(default=24, ge=1, le=168),
) -> FunctionMetricsResponse:
    """Get detailed metrics for a specific function."""
    all_functions = await get_function_metrics(period_hours=period_hours)

    for func in all_functions:
        if func.function_name == function_name:
            return func

    raise HTTPException(status_code=404, detail=f"Function '{function_name}' not found")


@router.get("/costs", response_model=CostBreakdownResponse)
async def get_cost_breakdown(
    period_hours: int = Query(default=24, ge=1, le=720),
) -> CostBreakdownResponse:
    """
    Get cost breakdown analysis.

    Args:
        period_hours: Time period to analyze (1-720 hours, default 24)
    """
    collector = get_collector()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=period_hours)

    # Get recent metrics
    metrics = collector.get_recent_metrics(limit=1000)
    relevant = [m for m in metrics if start_time <= m.timestamp <= end_time]

    if not relevant:
        return CostBreakdownResponse(
            period=f"last_{period_hours}_hours",
            total_cost_usd=0,
            by_provider={},
            by_function={},
            by_model={},
            by_agent={},
            tokens_used=0,
            avg_cost_per_call=0,
            projected_monthly_cost=0,
        )

    total_cost = sum(m.estimated_cost_usd for m in relevant)
    total_tokens = sum(m.tokens_total for m in relevant)

    by_provider: dict[str, float] = {}
    by_function: dict[str, float] = {}
    by_model: dict[str, float] = {}
    by_agent: dict[str, float] = {}

    for m in relevant:
        by_provider[m.provider] = by_provider.get(m.provider, 0) + m.estimated_cost_usd
        by_function[m.task_type] = by_function.get(m.task_type, 0) + m.estimated_cost_usd
        by_model[m.model_id] = by_model.get(m.model_id, 0) + m.estimated_cost_usd
        if m.agent_name:
            by_agent[m.agent_name] = by_agent.get(m.agent_name, 0) + m.estimated_cost_usd

    # Calculate projected monthly cost
    hours_elapsed = (end_time - start_time).total_seconds() / 3600
    hourly_rate = total_cost / hours_elapsed if hours_elapsed > 0 else 0
    projected_monthly = hourly_rate * 24 * 30

    return CostBreakdownResponse(
        period=f"last_{period_hours}_hours",
        total_cost_usd=round(total_cost, 4),
        by_provider={k: round(v, 4) for k, v in by_provider.items()},
        by_function={k: round(v, 4) for k, v in by_function.items()},
        by_model={k: round(v, 4) for k, v in by_model.items()},
        by_agent={k: round(v, 4) for k, v in by_agent.items()},
        tokens_used=total_tokens,
        avg_cost_per_call=round(total_cost / len(relevant), 6),
        projected_monthly_cost=round(projected_monthly, 2),
    )


@router.get("/quality", response_model=QualityMetricsResponse)
async def get_quality_metrics(
    period_hours: int = Query(default=24, ge=1, le=168),
) -> QualityMetricsResponse:
    """
    Get quality metrics summary.

    Args:
        period_hours: Time period to analyze (1-168 hours, default 24)
    """
    collector = get_collector()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=period_hours)

    # Get recent metrics
    metrics = collector.get_recent_metrics(limit=1000)
    relevant = [m for m in metrics if start_time <= m.timestamp <= end_time]

    if not relevant:
        return QualityMetricsResponse(
            period=f"last_{period_hours}_hours",
            validation_pass_rate=0,
            avg_quality_score=0,
            user_corrections=0,
            citation_accuracy=0,
            coherence_score=0,
            by_function={},
            by_model={},
            quality_trend=[],
        )

    validation_passed = sum(1 for m in relevant if m.validation_passed)
    total = len(relevant)

    # Quality by function
    by_function: dict[str, list[float]] = {}
    by_model: dict[str, list[float]] = {}

    for m in relevant:
        if m.task_type not in by_function:
            by_function[m.task_type] = []
        by_function[m.task_type].append(m.quality_score)

        if m.model_id not in by_model:
            by_model[m.model_id] = []
        by_model[m.model_id].append(m.quality_score)

    # Calculate hourly trend
    quality_trend: list[dict[str, Any]] = []
    hours = min(period_hours, 24)  # Max 24 data points

    for i in range(hours):
        hour_start = end_time - timedelta(hours=i+1)
        hour_end = end_time - timedelta(hours=i)
        hour_metrics = [m for m in relevant if hour_start <= m.timestamp <= hour_end]

        if hour_metrics:
            quality_trend.append({
                "hour": hour_start.isoformat(),
                "avg_quality": sum(m.quality_score for m in hour_metrics) / len(hour_metrics),
                "calls": len(hour_metrics),
                "pass_rate": sum(1 for m in hour_metrics if m.validation_passed) / len(hour_metrics),
            })

    quality_trend.reverse()  # Oldest first

    return QualityMetricsResponse(
        period=f"last_{period_hours}_hours",
        validation_pass_rate=validation_passed / total,
        avg_quality_score=sum(m.quality_score for m in relevant) / total,
        user_corrections=0,  # Would need separate tracking
        citation_accuracy=0,  # Would need separate tracking
        coherence_score=0,  # Would need separate tracking
        by_function={k: sum(v) / len(v) for k, v in by_function.items()},
        by_model={k: sum(v) / len(v) for k, v in by_model.items()},
        quality_trend=quality_trend,
    )


@router.get("/trends/latency", response_model=PerformanceTrendResponse)
async def get_latency_trends(
    period_hours: int = Query(default=24, ge=1, le=168),
    granularity: str = Query(default="hour", pattern="^(minute|hour|day)$"),
) -> PerformanceTrendResponse:
    """
    Get latency trends over time.

    Args:
        period_hours: Time period to analyze
        granularity: minute, hour, or day
    """
    collector = get_collector()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=period_hours)

    metrics = collector.get_recent_metrics(limit=1000)
    relevant = [m for m in metrics if start_time <= m.timestamp <= end_time]

    # Determine bucket size
    if granularity == "minute":
        bucket_delta = timedelta(minutes=1)
        num_buckets = min(period_hours * 60, 60)
    elif granularity == "hour":
        bucket_delta = timedelta(hours=1)
        num_buckets = min(period_hours, 24)
    else:
        bucket_delta = timedelta(days=1)
        num_buckets = min(period_hours // 24, 7)

    data_points: list[dict[str, Any]] = []

    for i in range(num_buckets):
        bucket_start = end_time - bucket_delta * (i + 1)
        bucket_end = end_time - bucket_delta * i
        bucket_metrics = [m for m in relevant if bucket_start <= m.timestamp <= bucket_end]

        if bucket_metrics:
            latencies = [m.latency_ms for m in bucket_metrics]
            latencies.sort()

            data_points.append({
                "timestamp": bucket_start.isoformat(),
                "avg_latency_ms": sum(latencies) / len(latencies),
                "p50_latency_ms": latencies[len(latencies) // 2],
                "p95_latency_ms": latencies[int(len(latencies) * 0.95)],
                "max_latency_ms": max(latencies),
                "call_count": len(bucket_metrics),
            })

    data_points.reverse()

    # Summary statistics
    if relevant:
        all_latencies = sorted([m.latency_ms for m in relevant])
        summary = {
            "total_calls": len(relevant),
            "avg_latency_ms": sum(all_latencies) / len(all_latencies),
            "p50_latency_ms": all_latencies[len(all_latencies) // 2],
            "p95_latency_ms": all_latencies[int(len(all_latencies) * 0.95)],
            "max_latency_ms": max(all_latencies),
            "min_latency_ms": min(all_latencies),
        }
    else:
        summary = {}

    return PerformanceTrendResponse(
        period=f"last_{period_hours}_hours",
        data_points=data_points,
        summary=summary,
    )


@router.get("/trends/throughput", response_model=PerformanceTrendResponse)
async def get_throughput_trends(
    period_hours: int = Query(default=24, ge=1, le=168),
) -> PerformanceTrendResponse:
    """Get throughput (calls per hour) trends."""
    collector = get_collector()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=period_hours)

    metrics = collector.get_recent_metrics(limit=1000)
    relevant = [m for m in metrics if start_time <= m.timestamp <= end_time]

    # Hourly buckets
    num_hours = min(period_hours, 24)
    data_points: list[dict[str, Any]] = []

    for i in range(num_hours):
        hour_start = end_time - timedelta(hours=i+1)
        hour_end = end_time - timedelta(hours=i)
        hour_metrics = [m for m in relevant if hour_start <= m.timestamp <= hour_end]

        data_points.append({
            "timestamp": hour_start.isoformat(),
            "calls": len(hour_metrics),
            "successful": sum(1 for m in hour_metrics if m.success),
            "failed": sum(1 for m in hour_metrics if not m.success),
            "tokens_used": sum(m.tokens_total for m in hour_metrics),
        })

    data_points.reverse()

    return PerformanceTrendResponse(
        period=f"last_{period_hours}_hours",
        data_points=data_points,
        summary={
            "total_calls": len(relevant),
            "avg_calls_per_hour": len(relevant) / period_hours if period_hours > 0 else 0,
            "peak_hour_calls": max(dp["calls"] for dp in data_points) if data_points else 0,
        },
    )


@router.get("/model-ranking/{task_type}")
async def get_model_ranking(task_type: str) -> dict[str, Any]:
    """
    Get model rankings for a specific task type.

    Returns models sorted by performance score.
    """
    registry = get_registry()
    ranking = registry.get_model_ranking(task_type)

    return {
        "task_type": task_type,
        "rankings": ranking,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/summary")
async def get_analytics_summary() -> dict[str, Any]:
    """
    Get a comprehensive analytics summary.

    Combines key metrics from all categories for dashboard overview.
    """
    collector = get_collector()
    registry = get_registry()

    # Get aggregated data
    hour_metrics = collector.get_aggregated_metrics(period_type="hour")
    day_metrics = collector.get_aggregated_metrics(period_type="day")
    quick_stats = collector.get_quick_stats()
    health = registry.get_health_status()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_hour": {
            "total_calls": hour_metrics.total_calls,
            "success_rate": (
                hour_metrics.successful_calls / hour_metrics.total_calls
                if hour_metrics.total_calls > 0 else 1.0
            ),
            "avg_latency_ms": hour_metrics.avg_latency_ms,
            "total_cost_usd": hour_metrics.total_cost_usd,
        },
        "last_24_hours": {
            "total_calls": day_metrics.total_calls,
            "success_rate": (
                day_metrics.successful_calls / day_metrics.total_calls
                if day_metrics.total_calls > 0 else 1.0
            ),
            "avg_latency_ms": day_metrics.avg_latency_ms,
            "total_cost_usd": day_metrics.total_cost_usd,
            "by_provider": day_metrics.by_provider,
            "by_function": day_metrics.by_task_type,
        },
        "totals": quick_stats,
        "health": health,
    }


@router.post("/reset-counters")
async def reset_counters() -> dict[str, str]:
    """Reset in-memory counters (for testing/admin use)."""
    collector = get_collector()
    collector.reset_counters()
    return {"status": "counters_reset"}
