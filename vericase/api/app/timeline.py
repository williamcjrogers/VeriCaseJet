"""
Project Timeline API
Unified timeline with two views: Event Timeline (visual) + Project Chronology (tabular)

Single data layer serving both views with shared filters and data normalization.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    Case,
    ChronologyItem,
    DelayEvent,
    EmailMessage,
    EvidenceItem,
    Programme,
    Project,
    User,
)
from .security import get_current_user

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/timeline", tags=["timeline"])


def _normalize_datetime(dt: datetime) -> datetime:
    """Normalize datetime to UTC for safe comparison (handles tz-aware vs naive)."""
    if dt.tzinfo is None:
        # Assume naive datetimes are UTC
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =============================================================================
# Enums and DTOs
# =============================================================================


class TimelineEventType(str, PyEnum):
    """Types of events that can appear on the timeline"""

    ACTIVITY = "activity"  # Programme activity (span)
    MILESTONE = "milestone"  # Programme milestone (point)
    DELAY = "delay"  # Delay event (point or span)
    EMAIL = "email"  # Correspondence (point)
    DOCUMENT = "document"  # Document/evidence (point)
    CHRONOLOGY = "chronology"  # Manual chronology item (point)
    MANUAL = "manual"  # User-created event (point)


class TimelineEventSource(str, PyEnum):
    """Source tables for timeline events"""

    PROGRAMME = "programme"
    DELAY_EVENT = "delay_event"
    EMAIL_MESSAGE = "email_message"
    EVIDENCE_ITEM = "evidence_item"
    CHRONOLOGY_ITEM = "chronology_item"
    MANUAL = "manual"


class TimelineEvent(BaseModel):
    """Unified timeline event - single shape for all sources"""

    id: str
    case_id: str | None = None
    project_id: str | None = None

    # Event classification
    event_type: TimelineEventType
    source_table: TimelineEventSource
    source_id: str

    # Content
    title: str
    summary: str | None = None
    description: str | None = None

    # Temporal - start_date required, end_date optional (point vs span)
    start_date: datetime
    end_date: datetime | None = None

    # Flags and metadata
    is_critical: bool = False
    is_pinned: bool = False
    delay_days: int | None = None
    tags: list[str] = Field(default_factory=list)

    # Linked entities for drill-down
    linked_activity_id: str | None = None
    linked_activity_name: str | None = None
    linked_programme_id: str | None = None

    # Relationship data
    related_ids: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class TimelineStats(BaseModel):
    """Aggregated statistics for timeline"""

    total_events: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_month: list[dict[str, Any]] = Field(default_factory=list)
    critical_events: int = 0
    total_delay_days: int = 0
    date_range: dict[str, datetime | None] = Field(default_factory=dict)


class TimelineResponse(BaseModel):
    """Response wrapper for timeline queries"""

    events: list[TimelineEvent]
    total: int
    has_more: bool = False
    cursor: str | None = None
    stats: TimelineStats | None = None


class TimelineFilters(BaseModel):
    """Filter parameters for timeline queries"""

    types: list[TimelineEventType] | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    critical_only: bool = False
    search: str | None = None
    tags: list[str] | None = None
    limit: int = 500
    cursor: str | None = None


class ManualEventCreate(BaseModel):
    """Schema for creating manual timeline events"""

    title: str
    summary: str | None = None
    description: str | None = None
    start_date: datetime
    end_date: datetime | None = None
    event_type: TimelineEventType = TimelineEventType.MANUAL
    is_critical: bool = False
    is_pinned: bool = False
    tags: list[str] = Field(default_factory=list)


class ManualEventUpdate(BaseModel):
    """Schema for updating manual timeline events"""

    title: str | None = None
    summary: str | None = None
    description: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_critical: bool | None = None
    is_pinned: bool | None = None
    tags: list[str] | None = None


# =============================================================================
# Adapter Functions - Convert source data to unified TimelineEvent
# =============================================================================


def _adapt_programme_activities(
    programme: Programme,
    case_id: str | None,
    project_id: str | None,
) -> list[TimelineEvent]:
    """Convert Programme activities and milestones to timeline events"""
    events: list[TimelineEvent] = []

    if not programme.activities:
        return events

    critical_ids = set(programme.critical_path or [])

    for activity in programme.activities:
        if not isinstance(activity, dict):
            continue

        activity_id = activity.get("id", "")
        name = activity.get("name", "Unknown Activity")
        start_str = activity.get("start_date")
        finish_str = activity.get("finish_date")

        if not start_str:
            continue

        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = (
                datetime.fromisoformat(finish_str.replace("Z", "+00:00"))
                if finish_str
                else None
            )
        except (ValueError, TypeError):
            continue

        is_milestone = activity.get("is_milestone", False)
        is_critical = activity_id in critical_ids or activity.get("is_critical", False)

        event_type = (
            TimelineEventType.MILESTONE if is_milestone else TimelineEventType.ACTIVITY
        )

        events.append(
            TimelineEvent(
                id=f"prog-{programme.id}-{activity_id}",
                case_id=case_id,
                project_id=project_id,
                event_type=event_type,
                source_table=TimelineEventSource.PROGRAMME,
                source_id=str(programme.id),
                title=name,
                summary=(
                    f"{programme.programme_type.title()} - {name}"
                    if programme.programme_type
                    else name
                ),
                start_date=start_dt,
                end_date=end_dt if not is_milestone else None,
                is_critical=is_critical,
                tags=[programme.programme_type] if programme.programme_type else [],
                linked_activity_id=activity_id,
                linked_activity_name=name,
                linked_programme_id=str(programme.id),
                meta={
                    "programme_name": programme.programme_name,
                    "programme_type": programme.programme_type,
                    "percent_complete": activity.get("percent_complete"),
                    "duration": activity.get("duration"),
                },
            )
        )

    return events


def _adapt_delay_events(
    delays: list[DelayEvent],
    case_id: str | None,
) -> list[TimelineEvent]:
    """Convert DelayEvent records to timeline events"""
    events: list[TimelineEvent] = []

    for delay in delays:
        # Use actual_finish as the primary date, fallback to planned_finish
        event_date = (
            delay.actual_finish
            or delay.planned_finish
            or delay.actual_start
            or delay.planned_start
        )
        if not event_date:
            continue

        title = delay.activity_name or f"Delay Event #{delay.id}"

        summary_parts = []
        if delay.delay_days:
            summary_parts.append(
                f"{abs(delay.delay_days)} day{'s' if abs(delay.delay_days) != 1 else ''} {'delay' if delay.delay_days > 0 else 'ahead'}"
            )
        if delay.delay_cause:
            summary_parts.append(f"Cause: {delay.delay_cause}")

        events.append(
            TimelineEvent(
                id=f"delay-{delay.id}",
                case_id=case_id,
                project_id=None,
                event_type=TimelineEventType.DELAY,
                source_table=TimelineEventSource.DELAY_EVENT,
                source_id=str(delay.id),
                title=title,
                summary=" | ".join(summary_parts) if summary_parts else None,
                description=delay.description,
                start_date=delay.planned_start or event_date,
                end_date=delay.actual_finish,
                is_critical=delay.is_on_critical_path,
                delay_days=delay.delay_days,
                tags=[delay.delay_type] if delay.delay_type else [],
                linked_activity_id=delay.activity_id,
                linked_activity_name=delay.activity_name,
                related_ids=delay.linked_correspondence_ids or [],
                meta={
                    "delay_type": delay.delay_type,
                    "delay_cause": delay.delay_cause,
                    "eot_entitlement_days": delay.eot_entitlement_days,
                    "planned_start": (
                        delay.planned_start.isoformat() if delay.planned_start else None
                    ),
                    "planned_finish": (
                        delay.planned_finish.isoformat()
                        if delay.planned_finish
                        else None
                    ),
                    "actual_start": (
                        delay.actual_start.isoformat() if delay.actual_start else None
                    ),
                    "actual_finish": (
                        delay.actual_finish.isoformat() if delay.actual_finish else None
                    ),
                },
            )
        )

    return events


def _adapt_emails(
    emails: list[EmailMessage],
    case_id: str | None,
    project_id: str | None,
) -> list[TimelineEvent]:
    """Convert EmailMessage records to timeline events (point events)"""
    events: list[TimelineEvent] = []

    for email in emails:
        if not email.date_sent:
            continue

        subject = email.subject or "(No Subject)"
        sender = email.sender_name or email.sender_email or "Unknown"

        summary_parts = [f"From: {sender}"]
        if email.as_planned_activity:
            summary_parts.append(f"Activity: {email.as_planned_activity}")
        if email.delay_days:
            summary_parts.append(f"Delay: {email.delay_days} days")

        tags = []
        if email.is_critical_path:
            tags.append("critical_path")
        if email.has_attachments:
            tags.append("has_attachments")

        events.append(
            TimelineEvent(
                id=f"email-{email.id}",
                case_id=str(email.case_id) if email.case_id else case_id,
                project_id=str(email.project_id) if email.project_id else project_id,
                event_type=TimelineEventType.EMAIL,
                source_table=TimelineEventSource.EMAIL_MESSAGE,
                source_id=str(email.id),
                title=subject,
                summary=" | ".join(summary_parts),
                start_date=email.date_sent,
                is_critical=email.is_critical_path or False,
                delay_days=email.delay_days,
                tags=tags,
                linked_activity_name=email.as_planned_activity,
                meta={
                    "sender_email": email.sender_email,
                    "sender_name": email.sender_name,
                    "recipients_to": email.recipients_to,
                    "recipients_cc": email.recipients_cc,
                    "has_attachments": email.has_attachments,
                    "as_planned_activity": email.as_planned_activity,
                    "as_built_activity": email.as_built_activity,
                    "thread_id": email.thread_id,
                },
            )
        )

    return events


def _adapt_evidence_items(
    items: list[EvidenceItem],
    case_id: str | None,
    project_id: str | None,
) -> list[TimelineEvent]:
    """Convert EvidenceItem records to timeline events"""
    events: list[TimelineEvent] = []

    for item in items:
        # Use document_date, fallback to created_at
        event_date = item.document_date or item.created_at
        if not event_date:
            continue

        title = item.title or item.filename or "Unknown Document"

        tags = list(item.manual_tags or []) + list(item.auto_tags or [])
        if item.evidence_type:
            tags.append(item.evidence_type)

        events.append(
            TimelineEvent(
                id=f"evidence-{item.id}",
                case_id=str(item.case_id) if item.case_id else case_id,
                project_id=str(item.project_id) if item.project_id else project_id,
                event_type=TimelineEventType.DOCUMENT,
                source_table=TimelineEventSource.EVIDENCE_ITEM,
                source_id=str(item.id),
                title=title,
                summary=item.description,
                start_date=event_date,
                is_critical=item.is_starred,
                tags=tags[:10],  # Limit tags
                meta={
                    "filename": item.filename,
                    "file_type": item.file_type,
                    "evidence_type": item.evidence_type,
                    "document_category": item.document_category,
                    "author": item.author,
                },
            )
        )

    return events


def _adapt_chronology_items(
    items: list[ChronologyItem],
    case_id: str | None,
    project_id: str | None,
) -> list[TimelineEvent]:
    """Convert ChronologyItem records to timeline events"""
    events: list[TimelineEvent] = []

    for item in items:
        if not item.event_date:
            continue

        tags = list(item.parties_involved or [])

        related_ids = item.evidence_ids or []
        dep_uris = [
            rid
            for rid in related_ids
            if isinstance(rid, str) and rid.startswith("dep://")
        ]
        non_dep_related_ids = [rid for rid in related_ids if rid not in dep_uris]

        events.append(
            TimelineEvent(
                id=f"chrono-{item.id}",
                case_id=str(item.case_id) if item.case_id else case_id,
                project_id=str(item.project_id) if item.project_id else project_id,
                event_type=TimelineEventType.CHRONOLOGY,
                source_table=TimelineEventSource.CHRONOLOGY_ITEM,
                source_id=str(item.id),
                title=item.title or "Untitled Event",
                summary=item.description,
                start_date=item.event_date,
                is_critical=False,
                tags=tags,
                related_ids=non_dep_related_ids,
                meta={
                    "event_type": item.event_type,
                    "parties_involved": item.parties_involved,
                    "claim_id": str(item.claim_id) if item.claim_id else None,
                    "dep_uris": dep_uris,
                },
            )
        )

    return events


# =============================================================================
# Aggregation Service
# =============================================================================


def _aggregate_timeline_events(
    db: Session,
    case_id: str | None = None,
    project_id: str | None = None,
    filters: TimelineFilters | None = None,
) -> list[TimelineEvent]:
    """
    Aggregate events from all source tables into unified timeline.
    Applies filters, merges, and sorts by date.
    """
    if filters is None:
        filters = TimelineFilters()

    all_events: list[TimelineEvent] = []

    # Determine which types to include
    include_types = set(filters.types) if filters.types else set(TimelineEventType)

    # Build base filters for each source
    date_filters = []
    if filters.start_date:
        date_filters.append(("start", filters.start_date))
    if filters.end_date:
        date_filters.append(("end", filters.end_date))

    # 1. Programme Activities
    if (
        TimelineEventType.ACTIVITY in include_types
        or TimelineEventType.MILESTONE in include_types
    ):
        prog_query = db.query(Programme)
        if case_id:
            prog_query = prog_query.filter(Programme.case_id == uuid.UUID(case_id))
        if project_id:
            prog_query = prog_query.filter(
                Programme.project_id == uuid.UUID(project_id)
            )

        programmes = prog_query.all()
        for prog in programmes:
            events = _adapt_programme_activities(prog, case_id, project_id)
            all_events.extend(events)

    # 2. Delay Events
    if TimelineEventType.DELAY in include_types:
        delay_query = db.query(DelayEvent)
        if case_id:
            delay_query = delay_query.filter(DelayEvent.case_id == uuid.UUID(case_id))

        if filters.critical_only:
            delay_query = delay_query.filter(DelayEvent.is_on_critical_path == True)

        delays = delay_query.all()
        all_events.extend(_adapt_delay_events(delays, case_id))

    # 3. Email Messages
    if TimelineEventType.EMAIL in include_types:
        email_query = db.query(EmailMessage).filter(EmailMessage.date_sent.isnot(None))

        if case_id:
            email_query = email_query.filter(EmailMessage.case_id == uuid.UUID(case_id))
        if project_id:
            email_query = email_query.filter(
                EmailMessage.project_id == uuid.UUID(project_id)
            )

        # Date range filtering
        if filters.start_date:
            email_query = email_query.filter(
                EmailMessage.date_sent >= filters.start_date
            )
        if filters.end_date:
            email_query = email_query.filter(EmailMessage.date_sent <= filters.end_date)

        if filters.critical_only:
            email_query = email_query.filter(EmailMessage.is_critical_path == True)

        if filters.search:
            search_term = f"%{filters.search}%"
            email_query = email_query.filter(
                or_(
                    EmailMessage.subject.ilike(search_term),
                    EmailMessage.sender_email.ilike(search_term),
                    EmailMessage.sender_name.ilike(search_term),
                )
            )

        # Limit emails to prevent overwhelming the timeline
        emails = (
            email_query.order_by(desc(EmailMessage.date_sent))
            .limit(min(filters.limit, 1000))
            .all()
        )
        all_events.extend(_adapt_emails(emails, case_id, project_id))

    # 4. Evidence Items
    if TimelineEventType.DOCUMENT in include_types:
        evidence_query = db.query(EvidenceItem)

        if case_id:
            evidence_query = evidence_query.filter(
                EvidenceItem.case_id == uuid.UUID(case_id)
            )
        if project_id:
            evidence_query = evidence_query.filter(
                EvidenceItem.project_id == uuid.UUID(project_id)
            )

        if filters.start_date:
            evidence_query = evidence_query.filter(
                or_(
                    EvidenceItem.document_date >= filters.start_date,
                    and_(
                        EvidenceItem.document_date.is_(None),
                        EvidenceItem.created_at >= filters.start_date,
                    ),
                )
            )

        items = evidence_query.limit(min(filters.limit, 500)).all()
        all_events.extend(_adapt_evidence_items(items, case_id, project_id))

    # 5. Chronology Items
    if TimelineEventType.CHRONOLOGY in include_types:
        chrono_query = db.query(ChronologyItem)

        if case_id:
            chrono_query = chrono_query.filter(
                ChronologyItem.case_id == uuid.UUID(case_id)
            )
        elif project_id:
            chrono_query = chrono_query.filter(
                ChronologyItem.project_id == uuid.UUID(project_id)
            )

        if filters.start_date:
            chrono_query = chrono_query.filter(
                ChronologyItem.event_date >= filters.start_date
            )
        if filters.end_date:
            chrono_query = chrono_query.filter(
                ChronologyItem.event_date <= filters.end_date
            )

        chrono_items = chrono_query.all()
        all_events.extend(_adapt_chronology_items(chrono_items, case_id, project_id))

    # Apply post-aggregation filters
    if filters.types:
        all_events = [e for e in all_events if e.event_type in filters.types]

    if filters.critical_only:
        all_events = [e for e in all_events if e.is_critical]

    if filters.tags:
        tag_set = set(filters.tags)
        all_events = [e for e in all_events if tag_set & set(e.tags)]

    if filters.search:
        search_lower = filters.search.lower()
        all_events = [
            e
            for e in all_events
            if (e.title and search_lower in e.title.lower())
            or (e.summary and search_lower in e.summary.lower())
        ]

    # Date range filtering (for non-email sources that weren't pre-filtered)
    # Use normalized datetimes to avoid timezone-aware vs naive comparison errors
    if filters.start_date:
        start_norm = _normalize_datetime(filters.start_date)
        all_events = [
            e for e in all_events if _normalize_datetime(e.start_date) >= start_norm
        ]
    if filters.end_date:
        end_norm = _normalize_datetime(filters.end_date)
        all_events = [
            e for e in all_events if _normalize_datetime(e.start_date) <= end_norm
        ]

    # Sort by date (most recent first)
    all_events.sort(key=lambda x: x.start_date, reverse=True)

    # Apply limit
    if len(all_events) > filters.limit:
        all_events = all_events[: filters.limit]

    return all_events


def _compute_timeline_stats(events: list[TimelineEvent]) -> TimelineStats:
    """Compute aggregated statistics from timeline events"""
    stats = TimelineStats()
    stats.total_events = len(events)

    # Count by type
    type_counts: dict[str, int] = defaultdict(int)
    for event in events:
        type_counts[event.event_type.value] += 1
    stats.by_type = dict(type_counts)

    # Critical events
    stats.critical_events = sum(1 for e in events if e.is_critical)

    # Total delay days
    stats.total_delay_days = sum(e.delay_days or 0 for e in events if e.delay_days)

    # Date range
    if events:
        dates = [e.start_date for e in events]
        stats.date_range = {
            "min": min(dates),
            "max": max(dates),
        }

    # By month bucketing
    month_counts: dict[str, int] = defaultdict(int)
    for event in events:
        month_key = event.start_date.strftime("%Y-%m")
        month_counts[month_key] += 1

    stats.by_month = [{"month": k, "count": v} for k, v in sorted(month_counts.items())]

    return stats


# =============================================================================
# API Endpoints
# =============================================================================


@router.get("/cases/{case_id}", response_model=TimelineResponse)
def get_case_timeline(
    case_id: str,
    db: DbSession,
    current_user: CurrentUser,
    types: list[TimelineEventType] | None = Query(default=None),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    critical_only: bool = False,
    search: str | None = None,
    limit: int = Query(default=500, le=1000),
    include_stats: bool = False,
):
    """
    Get unified timeline events for a case.
    Used by both Event Timeline (visual) and Chronology (tabular) views.
    """
    # Verify case exists and user has access
    try:
        case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Build filters
    filters = TimelineFilters(
        types=types,
        start_date=start_date,
        end_date=end_date,
        critical_only=critical_only,
        search=search,
        limit=limit,
    )

    # Aggregate events
    events = _aggregate_timeline_events(db, case_id=case_id, filters=filters)

    # Compute stats if requested
    stats = _compute_timeline_stats(events) if include_stats else None

    return TimelineResponse(
        events=events,
        total=len(events),
        has_more=len(events) >= limit,
        stats=stats,
    )


@router.get("/projects/{project_id}", response_model=TimelineResponse)
def get_project_timeline(
    project_id: str,
    db: DbSession,
    current_user: CurrentUser,
    types: list[TimelineEventType] | None = Query(default=None),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    critical_only: bool = False,
    search: str | None = None,
    limit: int = Query(default=500, le=1000),
    include_stats: bool = False,
):
    """
    Get unified timeline events for a project.
    Projects may have emails and programmes without a case.
    """
    # Verify project exists
    try:
        project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Build filters
    filters = TimelineFilters(
        types=types,
        start_date=start_date,
        end_date=end_date,
        critical_only=critical_only,
        search=search,
        limit=limit,
    )

    # Aggregate events
    events = _aggregate_timeline_events(db, project_id=project_id, filters=filters)

    # Compute stats if requested
    stats = _compute_timeline_stats(events) if include_stats else None

    return TimelineResponse(
        events=events,
        total=len(events),
        has_more=len(events) >= limit,
        stats=stats,
    )


@router.get("/cases/{case_id}/stats", response_model=TimelineStats)
def get_timeline_stats(
    case_id: str,
    db: DbSession,
    current_user: CurrentUser,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    bucket: str = Query(default="month", regex="^(day|week|month)$"),
):
    """
    Get aggregated statistics for a case's timeline.
    Useful for charts and dashboards.
    """
    # Verify case exists
    try:
        case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    filters = TimelineFilters(
        start_date=start_date,
        end_date=end_date,
        limit=2000,  # Higher limit for stats
    )

    events = _aggregate_timeline_events(db, case_id=case_id, filters=filters)
    stats = _compute_timeline_stats(events)

    # Re-bucket by requested granularity
    if bucket != "month" and events:
        bucket_counts: dict[str, int] = defaultdict(int)
        for event in events:
            if bucket == "day":
                key = event.start_date.strftime("%Y-%m-%d")
            elif bucket == "week":
                # ISO week
                key = event.start_date.strftime("%Y-W%W")
            else:
                key = event.start_date.strftime("%Y-%m")
            bucket_counts[key] += 1

        stats.by_month = [
            {"bucket": k, "count": v} for k, v in sorted(bucket_counts.items())
        ]

    return stats


@router.get("/cases/{case_id}/chronology", response_model=TimelineResponse)
def get_case_chronology(
    case_id: str,
    db: DbSession,
    current_user: CurrentUser,
    types: list[TimelineEventType] | None = Query(default=None),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    pinned_only: bool = False,
    search: str | None = None,
    skip: int = 0,
    limit: int = Query(default=100, le=500),
    include_stats: bool = True,
):
    """
    Get chronology view for a case - paginated list optimized for tabular display.
    Same data as timeline but with pagination for list view.
    """
    # Verify case exists
    try:
        case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Build filters with higher limit for pagination
    filters = TimelineFilters(
        types=types,
        start_date=start_date,
        end_date=end_date,
        search=search,
        limit=skip + limit + 1,  # Fetch one extra to check has_more
    )

    # Aggregate events
    events = _aggregate_timeline_events(db, case_id=case_id, filters=filters)

    # Filter pinned if requested
    if pinned_only:
        events = [e for e in events if e.is_pinned]

    # Apply pagination
    total = len(events)
    has_more = len(events) > skip + limit
    events = events[skip : skip + limit]

    # Compute stats
    stats = _compute_timeline_stats(events) if include_stats else None

    return TimelineResponse(
        events=events,
        total=total,
        has_more=has_more,
        stats=stats,
    )


# =============================================================================
# Manual Event Management
# =============================================================================


# Note: For manual events, we'll use ChronologyItem as the backing store
# since it already has the right structure and is designed for user-created entries.


@router.post("/cases/{case_id}/events", response_model=TimelineEvent)
def create_manual_event(
    case_id: str,
    data: ManualEventCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    """Create a manual timeline event"""
    # Verify case exists
    try:
        case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Create as ChronologyItem
    item = ChronologyItem(
        id=uuid.uuid4(),
        case_id=uuid.UUID(case_id),
        event_date=data.start_date,
        event_type="manual",
        title=data.title,
        description=data.summary or data.description,
        parties_involved=data.tags,  # Reuse for tags
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    # Return as TimelineEvent
    return TimelineEvent(
        id=f"chrono-{item.id}",
        case_id=case_id,
        event_type=TimelineEventType.CHRONOLOGY,
        source_table=TimelineEventSource.CHRONOLOGY_ITEM,
        source_id=str(item.id),
        title=item.title,
        summary=item.description,
        start_date=item.event_date,
        end_date=data.end_date,
        is_critical=data.is_critical,
        is_pinned=data.is_pinned,
        tags=data.tags,
    )


@router.put("/events/{event_id}", response_model=TimelineEvent)
def update_manual_event(
    event_id: str,
    data: ManualEventUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    """Update a manual timeline event (chronology items only)"""
    # Parse event ID to get source
    if not event_id.startswith("chrono-"):
        raise HTTPException(
            status_code=400, detail="Only manual/chronology events can be updated"
        )

    source_id = event_id.replace("chrono-", "")

    try:
        item = (
            db.query(ChronologyItem)
            .filter(ChronologyItem.id == uuid.UUID(source_id))
            .first()
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event ID format")

    if not item:
        raise HTTPException(status_code=404, detail="Event not found")

    # Update fields
    if data.title is not None:
        item.title = data.title
    if data.summary is not None:
        item.description = data.summary
    if data.start_date is not None:
        item.event_date = data.start_date
    if data.tags is not None:
        item.parties_involved = data.tags

    db.commit()
    db.refresh(item)

    return TimelineEvent(
        id=event_id,
        case_id=str(item.case_id),
        event_type=TimelineEventType.CHRONOLOGY,
        source_table=TimelineEventSource.CHRONOLOGY_ITEM,
        source_id=str(item.id),
        title=item.title,
        summary=item.description,
        start_date=item.event_date,
        is_pinned=data.is_pinned if data.is_pinned is not None else False,
        tags=item.parties_involved or [],
    )


@router.delete("/events/{event_id}")
def delete_manual_event(
    event_id: str,
    db: DbSession,
    current_user: CurrentUser,
):
    """Delete a manual timeline event (chronology items only)"""
    if not event_id.startswith("chrono-"):
        raise HTTPException(
            status_code=400, detail="Only manual/chronology events can be deleted"
        )

    source_id = event_id.replace("chrono-", "")

    try:
        item = (
            db.query(ChronologyItem)
            .filter(ChronologyItem.id == uuid.UUID(source_id))
            .first()
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event ID format")

    if not item:
        raise HTTPException(status_code=404, detail="Event not found")

    db.delete(item)
    db.commit()

    return {"status": "deleted", "event_id": event_id}
