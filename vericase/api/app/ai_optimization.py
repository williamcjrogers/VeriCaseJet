"""AI Optimization Tracking System

Tracks all AI API calls with detailed metrics for optimization analysis:
- Models used
- Response times
- Token usage
- Costs
- Success/failure rates
- Quality assessments

This module provides both the database model and API endpoints for logging
and analyzing AI performance across all providers.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, UserRole
from .security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/ai-optimization", tags=["ai-optimization"])


# =============================================================================
# Pydantic Models
# =============================================================================


class AIEventLog(BaseModel):
    """Request to log an AI event"""

    provider: str  # openai, anthropic, gemini, bedrock, xai, perplexity
    model_id: str
    function_name: str | None = None  # e.g., "quick_search", "deep_analysis"
    task_type: str | None = None  # e.g., "search", "analysis", "generation"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    response_time_ms: int  # milliseconds
    cost_usd: float | None = None
    success: bool
    error_message: str | None = None
    quality_score: float | None = None  # 0.0-1.0
    metadata: dict[str, Any] | None = None


class AIEventResponse(BaseModel):
    """AI event record"""

    id: str
    provider: str
    model_id: str
    function_name: str | None
    task_type: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    response_time_ms: int
    cost_usd: float | None
    success: bool
    error_message: str | None
    quality_score: float | None
    metadata: dict[str, Any] | None
    created_at: datetime
    user_id: str | None


class AIOptimizationStats(BaseModel):
    """Aggregated statistics for AI optimization"""

    total_events: int
    total_cost_usd: float
    average_response_time_ms: float
    success_rate: float
    events_by_provider: dict[str, int]
    events_by_model: dict[str, int]
    cost_by_provider: dict[str, float]
    average_quality_score: float | None
    total_tokens: int


class AIEventListResponse(BaseModel):
    """Paginated list of AI events"""

    total: int
    events: list[AIEventResponse]
    stats: AIOptimizationStats


# =============================================================================
# Helper Functions
# =============================================================================


def _require_admin(user: User = Depends(current_user)) -> User:
    """Ensure user is an admin"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


AdminDep = Depends(_require_admin)


def log_ai_event(
    db: Session,
    provider: str,
    model_id: str,
    response_time_ms: int,
    success: bool,
    *,
    user_id: uuid.UUID | None = None,
    function_name: str | None = None,
    task_type: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_usd: float | None = None,
    error_message: str | None = None,
    quality_score: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log an AI event to the database for optimization tracking.

    This function should be called after every AI API call to track
    performance, costs, and quality metrics.

    Args:
        db: Database session
        provider: AI provider name (openai, anthropic, etc.)
        model_id: Model identifier
        response_time_ms: Response time in milliseconds
        success: Whether the call succeeded
        user_id: Optional user ID who triggered the call
        function_name: Optional function/tool name
        task_type: Optional task type (search, analysis, etc.)
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        total_tokens: Total tokens used
        cost_usd: Estimated cost in USD
        error_message: Error message if failed
        quality_score: Quality assessment (0.0-1.0)
        metadata: Additional metadata
    """
    try:
        from .models import AIOptimizationEvent

        event = AIOptimizationEvent(
            provider=provider,
            model_id=model_id,
            function_name=function_name,
            task_type=task_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            response_time_ms=response_time_ms,
            cost_usd=cost_usd,
            success=success,
            error_message=error_message,
            quality_score=quality_score,
            meta=metadata,
            user_id=user_id,
        )
        db.add(event)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log AI event: {e}")
        db.rollback()


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/events", status_code=201)
def create_ai_event(
    event: AIEventLog = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Log an AI event (for internal use by AI runtime).

    This endpoint is called automatically by the AI runtime to track
    all AI API calls.
    """
    log_ai_event(
        db=db,
        provider=event.provider,
        model_id=event.model_id,
        response_time_ms=event.response_time_ms,
        success=event.success,
        user_id=user.id,
        function_name=event.function_name,
        task_type=event.task_type,
        prompt_tokens=event.prompt_tokens,
        completion_tokens=event.completion_tokens,
        total_tokens=event.total_tokens,
        cost_usd=event.cost_usd,
        error_message=event.error_message,
        quality_score=event.quality_score,
        metadata=event.metadata,
    )
    return {"status": "logged"}


@router.get("/events", response_model=AIEventListResponse)
def get_ai_events(
    db: Session = Depends(get_db),
    admin: User = AdminDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    provider: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    function_name: str | None = Query(default=None),
    success_only: bool = Query(default=False),
) -> AIEventListResponse:
    """Get AI events with optional filtering (admin only).

    Returns paginated list of AI events along with aggregated statistics.
    """
    from .models import AIOptimizationEvent

    # Build query
    query = db.query(AIOptimizationEvent)

    if provider:
        query = query.filter(AIOptimizationEvent.provider == provider)
    if model_id:
        query = query.filter(AIOptimizationEvent.model_id == model_id)
    if function_name:
        query = query.filter(AIOptimizationEvent.function_name == function_name)
    if success_only:
        query = query.filter(AIOptimizationEvent.success == True)

    # Get total count
    total = query.count()

    # Get paginated events
    events = (
        query.order_by(desc(AIOptimizationEvent.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Calculate statistics
    stats_query = db.query(AIOptimizationEvent)
    if provider:
        stats_query = stats_query.filter(AIOptimizationEvent.provider == provider)
    if model_id:
        stats_query = stats_query.filter(AIOptimizationEvent.model_id == model_id)

    all_events = stats_query.all()

    total_cost = sum(e.cost_usd for e in all_events if e.cost_usd is not None)
    avg_response_time = (
        sum(e.response_time_ms for e in all_events) / len(all_events)
        if all_events
        else 0
    )
    success_rate = (
        sum(1 for e in all_events if e.success) / len(all_events) if all_events else 0
    )
    total_tokens_used = sum(
        e.total_tokens for e in all_events if e.total_tokens is not None
    )

    # Group by provider
    events_by_provider: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}
    for event in all_events:
        events_by_provider[event.provider] = (
            events_by_provider.get(event.provider, 0) + 1
        )
        if event.cost_usd:
            cost_by_provider[event.provider] = (
                cost_by_provider.get(event.provider, 0.0) + event.cost_usd
            )

    # Group by model
    events_by_model: dict[str, int] = {}
    for event in all_events:
        events_by_model[event.model_id] = events_by_model.get(event.model_id, 0) + 1

    # Average quality score
    quality_scores = [
        e.quality_score for e in all_events if e.quality_score is not None
    ]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else None

    stats = AIOptimizationStats(
        total_events=len(all_events),
        total_cost_usd=total_cost,
        average_response_time_ms=avg_response_time,
        success_rate=success_rate,
        events_by_provider=events_by_provider,
        events_by_model=events_by_model,
        cost_by_provider=cost_by_provider,
        average_quality_score=avg_quality,
        total_tokens=total_tokens_used,
    )

    # Convert events to response model
    event_responses = [
        AIEventResponse(
            id=str(e.id),
            provider=e.provider,
            model_id=e.model_id,
            function_name=e.function_name,
            task_type=e.task_type,
            prompt_tokens=e.prompt_tokens,
            completion_tokens=e.completion_tokens,
            total_tokens=e.total_tokens,
            response_time_ms=e.response_time_ms,
            cost_usd=e.cost_usd,
            success=e.success,
            error_message=e.error_message,
            quality_score=e.quality_score,
            metadata=e.meta,
            created_at=e.created_at or datetime.now(timezone.utc),
            user_id=str(e.user_id) if e.user_id else None,
        )
        for e in events
    ]

    return AIEventListResponse(total=total, events=event_responses, stats=stats)


@router.get("/stats", response_model=AIOptimizationStats)
def get_ai_stats(
    db: Session = Depends(get_db),
    admin: User = AdminDep,
    provider: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> AIOptimizationStats:
    """Get aggregated AI optimization statistics (admin only).

    Returns statistics for the specified time period.
    """
    from .models import AIOptimizationEvent
    from datetime import timedelta

    # Filter by date range
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = db.query(AIOptimizationEvent).filter(
        AIOptimizationEvent.created_at >= since
    )

    if provider:
        query = query.filter(AIOptimizationEvent.provider == provider)

    all_events = query.all()

    if not all_events:
        return AIOptimizationStats(
            total_events=0,
            total_cost_usd=0.0,
            average_response_time_ms=0.0,
            success_rate=0.0,
            events_by_provider={},
            events_by_model={},
            cost_by_provider={},
            average_quality_score=None,
            total_tokens=0,
        )

    total_cost = sum(e.cost_usd for e in all_events if e.cost_usd is not None)
    avg_response_time = sum(e.response_time_ms for e in all_events) / len(all_events)
    success_rate = sum(1 for e in all_events if e.success) / len(all_events)
    total_tokens_used = sum(
        e.total_tokens for e in all_events if e.total_tokens is not None
    )

    # Group by provider
    events_by_provider: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}
    for event in all_events:
        events_by_provider[event.provider] = (
            events_by_provider.get(event.provider, 0) + 1
        )
        if event.cost_usd:
            cost_by_provider[event.provider] = (
                cost_by_provider.get(event.provider, 0.0) + event.cost_usd
            )

    # Group by model
    events_by_model: dict[str, int] = {}
    for event in all_events:
        events_by_model[event.model_id] = events_by_model.get(event.model_id, 0) + 1

    # Average quality score
    quality_scores = [
        e.quality_score for e in all_events if e.quality_score is not None
    ]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else None

    return AIOptimizationStats(
        total_events=len(all_events),
        total_cost_usd=total_cost,
        average_response_time_ms=avg_response_time,
        success_rate=success_rate,
        events_by_provider=events_by_provider,
        events_by_model=events_by_model,
        cost_by_provider=cost_by_provider,
        average_quality_score=avg_quality,
        total_tokens=total_tokens_used,
    )


@router.delete("/events")
def delete_ai_events(
    db: Session = Depends(get_db),
    admin: User = AdminDep,
    older_than_days: int = Query(default=90, ge=1),
) -> dict[str, Any]:
    """Delete old AI events (admin only).

    Useful for cleaning up old data and managing database size.
    """
    from .models import AIOptimizationEvent
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    deleted = (
        db.query(AIOptimizationEvent)
        .filter(AIOptimizationEvent.created_at < cutoff)
        .delete()
    )
    db.commit()

    return {"deleted": deleted, "older_than_days": older_than_days}
