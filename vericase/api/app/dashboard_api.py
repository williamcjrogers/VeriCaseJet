"""
Master Dashboard API
Provides aggregated overview of user's projects, cases, and activity
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Annotated, Any, Dict as TypingDict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    Project,
    Case,
    CaseUser,
    User,
    UserRole,
    PSTFile,
    EmailMessage,
    EvidenceItem,
    Document,
    CollaborationActivity,
    EvidenceActivityLog,
    Workspace,
)
from .security import current_user
from .cache import get_cached, set_cached
from .config import settings

try:
    from .aws_services import get_aws_services
except Exception:  # pragma: no cover
    get_aws_services = None

logger = logging.getLogger(__name__)


def _ensure_tz_aware(dt: datetime | None) -> datetime:
    """
    Ensure a datetime is timezone-aware (UTC).
    Returns a very old UTC datetime if input is None.
    """
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        # Naive datetime - assume it's UTC
        return dt.replace(tzinfo=timezone.utc)
    return dt


import json
import time


def debug_log(
    hypothesis_id: str,
    message: str,
    data: TypingDict[str, Any] | None = None,
    line_num: int | None = None,
) -> None:
    if not bool(getattr(settings, "PST_AGENT_LOG_ENABLED", False)):
        return
    log_path = (
        os.getenv("PST_AGENT_LOG_PATH")
        or getattr(settings, "PST_AGENT_LOG_PATH", None)
        or os.getenv("VERICASE_DEBUG_LOG_PATH")
        or str(Path(".cursor") / "debug.log")
    )
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    _ = int(time.time() * 1000)
    entry_id = f"log_{_}_{int(time.time()) % 10000}"
    timestamp = _
    location = f"dashboard_api.py:{line_num or 'unknown'}"
    entry: TypingDict[str, Any] = {
        "id": entry_id,
        "timestamp": timestamp,
        "location": location,
        "message": message,
        "data": data or {},
        "sessionId": "debug-session",
        "runId": "run1",
        "hypothesisId": hypothesis_id,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        logger.debug("dashboard_api debug_log write failed", exc_info=True)


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
DbDep = Annotated[Session, Depends(get_db)]

# ============================================================================
# Redis Cache Configuration (shared across workers)
# ============================================================================
CACHE_TTL_SECONDS = 30  # Cache dashboard data for 30 seconds


def _get_cached(key: str) -> dict[str, Any] | None:
    """Get value from Redis cache"""
    result = get_cached(f"dashboard:{key}")
    debug_log(
        "C",
        "dashboard cache get",
        {
            "key": key,
            "type": str(type(result)),
            "is_none": result is None,
            "is_truthy": bool(result),
        },
        43,
    )
    if result:
        logger.debug(f"Dashboard cache HIT: {key}")
    return result


def _set_cached(key: str, value: dict[str, Any]) -> None:
    """Store value in Redis cache"""
    success = set_cached(f"dashboard:{key}", value, ttl_seconds=CACHE_TTL_SECONDS)
    debug_log("B", "dashboard cache set", {"key": key, "success": success}, 51)


# ============================================================================
# Response Models
# ============================================================================


class WorkItemSummary(BaseModel):
    """Unified work item representing either a Project or Case"""

    id: str
    type: str  # 'project' or 'case'
    name: str
    description: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Type-specific fields
    project_code: str | None = None  # For projects
    case_number: str | None = None  # For cases
    contract_type: str | None = None
    project_id: str | None = None  # For cases linked to a project
    project_name: str | None = None

    # Statistics
    email_count: int = 0
    evidence_count: int = 0
    pst_count: int = 0

    # User role on this item
    user_role: str = "viewer"
    is_owner: bool = False


class DashboardStats(BaseModel):
    """Aggregate statistics for the dashboard"""

    total_projects: int = 0
    total_cases: int = 0
    total_emails: int = 0
    total_evidence: int = 0
    items_needing_attention: int = 0
    recent_activity_count: int = 0


class DeadlineItem(BaseModel):
    """Unified deadline item for dashboard display"""

    id: str
    title: str
    date: datetime
    type: str  # 'deadline', 'deliverable', 'response_due'
    source_id: str  # Case ID or Claim ID
    source_name: str  # Case Name
    status: str = "pending"


class DashboardOverviewResponse(BaseModel):
    """Complete dashboard overview response"""

    user: dict[str, Any]
    stats: DashboardStats
    work_items: list[WorkItemSummary]
    recent_activity: list[dict[str, Any]]
    upcoming_deadlines: list[DeadlineItem] = []
    permissions: dict[str, bool]


class CreateWorkItemRequest(BaseModel):
    """Request to create a new project or case"""

    type: str = Field(..., pattern="^(project|case)$")
    name: str = Field(..., min_length=2, max_length=255)
    description: str | None = None
    project_code: str | None = None  # Required for projects
    case_number: str | None = None  # Auto-generated for cases if not provided
    contract_type: str | None = None


class ControlCentreStats(BaseModel):
    """Time-filtered statistics for Control Centre"""

    emails_today: int = 0
    emails_7d: int = 0
    emails_total: int = 0
    evidence_today: int = 0
    evidence_7d: int = 0
    evidence_total: int = 0
    documents_today: int = 0
    documents_7d: int = 0
    documents_total: int = 0


class ActivityItem(BaseModel):
    """Single activity item for activity feed"""

    id: str
    action: str
    resource_type: str
    description: str
    workspace: str | None = None
    user_name: str | None = None
    timestamp: datetime


class ControlCentreResponse(BaseModel):
    """Complete Control Centre stats response"""

    user: dict[str, Any]
    stats: ControlCentreStats
    my_activity: list[ActivityItem] = []
    team_activity: list[ActivityItem] = []
    permissions: dict[str, bool]


# ============================================================================
# Helper Functions
# ============================================================================


def get_user_projects(db: Session, user: User) -> list[Project]:
    """Get all projects accessible to a user"""
    if user.role == UserRole.ADMIN:
        # Admins see all projects
        return db.query(Project).order_by(desc(Project.created_at)).all()
    else:
        # Users see projects they own
        return (
            db.query(Project)
            .filter(Project.owner_user_id == user.id)
            .order_by(desc(Project.created_at))
            .all()
        )


def get_user_cases(db: Session, user: User) -> list[Case]:
    """Get all cases accessible to a user"""
    if user.role == UserRole.ADMIN:
        # Admins see all cases
        return db.query(Case).order_by(desc(Case.created_at)).all()
    else:
        # Users see cases they own or are assigned to
        # region agent log A
        assigned_count = (
            db.query(func.count(CaseUser.case_id))
            .filter(CaseUser.user_id == user.id)
            .scalar()
            or 0
        )
        debug_log(
            "A",
            "assigned case count",
            {"user_id": str(user.id), "count": assigned_count},
            145,
        )
        # endregion
        return (
            db.query(Case)
            .filter(
                or_(
                    Case.owner_id == user.id,
                    Case.id.in_(
                        select(CaseUser.case_id).where(CaseUser.user_id == user.id)
                    ),
                )
            )
            .order_by(desc(Case.created_at))
            .all()
        )


def get_all_project_stats_batch(
    db: Session, project_ids: list[UUID]
) -> dict[UUID, dict[str, int]]:
    """Get statistics for all projects in a single batch query - eliminates N+1"""
    if not project_ids:
        return {}

    # Batch email counts
    email_rows = (
        db.query(EmailMessage.project_id, func.count(EmailMessage.id))
        .filter(EmailMessage.project_id.in_(project_ids))
        .group_by(EmailMessage.project_id)
        .all()
    )
    email_counts: dict[UUID | None, int] = {row[0]: row[1] for row in email_rows}

    # Batch evidence counts
    evidence_rows = (
        db.query(EvidenceItem.project_id, func.count(EvidenceItem.id))
        .filter(EvidenceItem.project_id.in_(project_ids))
        .group_by(EvidenceItem.project_id)
        .all()
    )
    evidence_counts: dict[UUID | None, int] = {row[0]: row[1] for row in evidence_rows}

    # Batch PST counts
    pst_rows = (
        db.query(PSTFile.project_id, func.count(PSTFile.id))
        .filter(PSTFile.project_id.in_(project_ids))
        .group_by(PSTFile.project_id)
        .all()
    )
    pst_counts: dict[UUID | None, int] = {row[0]: row[1] for row in pst_rows}

    # Combine into result dict
    return {
        pid: {
            "email_count": email_counts.get(pid, 0),
            "evidence_count": evidence_counts.get(pid, 0),
            "pst_count": pst_counts.get(pid, 0),
        }
        for pid in project_ids
    }


def get_all_case_stats_batch(
    db: Session, case_ids: list[UUID]
) -> dict[UUID, dict[str, int]]:
    """Get statistics for all cases in a single batch query - eliminates N+1"""
    if not case_ids:
        return {}

    # Batch email counts
    email_rows = (
        db.query(EmailMessage.case_id, func.count(EmailMessage.id))
        .filter(EmailMessage.case_id.in_(case_ids))
        .group_by(EmailMessage.case_id)
        .all()
    )
    email_counts: dict[UUID | None, int] = {row[0]: row[1] for row in email_rows}

    # Batch evidence counts
    evidence_rows = (
        db.query(EvidenceItem.case_id, func.count(EvidenceItem.id))
        .filter(EvidenceItem.case_id.in_(case_ids))
        .group_by(EvidenceItem.case_id)
        .all()
    )
    evidence_counts: dict[UUID | None, int] = {row[0]: row[1] for row in evidence_rows}

    # Batch PST counts
    pst_rows = (
        db.query(PSTFile.case_id, func.count(PSTFile.id))
        .filter(PSTFile.case_id.in_(case_ids))
        .group_by(PSTFile.case_id)
        .all()
    )
    pst_counts: dict[UUID | None, int] = {row[0]: row[1] for row in pst_rows}

    # Combine into result dict
    return {
        cid: {
            "email_count": email_counts.get(cid, 0),
            "evidence_count": evidence_counts.get(cid, 0),
            "pst_count": pst_counts.get(cid, 0),
        }
        for cid in case_ids
    }


def get_project_stats(db: Session, project_id: UUID) -> dict[str, int]:
    """Get statistics for a single project (legacy, prefer batch version)"""
    return get_all_project_stats_batch(db, [project_id]).get(
        project_id, {"email_count": 0, "evidence_count": 0, "pst_count": 0}
    )


def get_case_stats(db: Session, case_id: UUID) -> dict[str, int]:
    """Get statistics for a single case (legacy, prefer batch version)"""
    return get_all_case_stats_batch(db, [case_id]).get(
        case_id, {"email_count": 0, "evidence_count": 0, "pst_count": 0}
    )


def get_user_role_on_case(db: Session, user: User, case_id: UUID) -> str:
    """Determine user's role on a specific case"""
    if user.role == UserRole.ADMIN:
        return "admin"

    case_user = (
        db.query(CaseUser)
        .filter(CaseUser.case_id == case_id, CaseUser.user_id == user.id)
        .first()
    )

    if case_user:
        return case_user.role

    return "viewer"


# ============================================================================
# Control Centre Helper Functions
# ============================================================================


def get_time_filtered_counts(db: Session, user: User) -> ControlCentreStats:
    """Get email, evidence, and document counts filtered by time periods"""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)

    # Get accessible project/case IDs for the user
    projects = get_user_projects(db, user)
    cases = get_user_cases(db, user)
    project_ids = [p.id for p in projects]
    case_ids = [c.id for c in cases]

    # Email counts
    email_base_query = db.query(func.count(EmailMessage.id))
    if project_ids or case_ids:
        email_filter = []
        if project_ids:
            email_filter.append(EmailMessage.project_id.in_(project_ids))
        if case_ids:
            email_filter.append(EmailMessage.case_id.in_(case_ids))
        email_base_query = email_base_query.filter(or_(*email_filter))

    emails_total = email_base_query.scalar() or 0

    emails_today = (
        email_base_query.filter(EmailMessage.created_at >= today_start).scalar() or 0
    )
    emails_7d = (
        email_base_query.filter(EmailMessage.created_at >= seven_days_ago).scalar() or 0
    )

    # Evidence counts
    evidence_base_query = db.query(func.count(EvidenceItem.id))
    if project_ids or case_ids:
        evidence_filter = []
        if project_ids:
            evidence_filter.append(EvidenceItem.project_id.in_(project_ids))
        if case_ids:
            evidence_filter.append(EvidenceItem.case_id.in_(case_ids))
        evidence_base_query = evidence_base_query.filter(or_(*evidence_filter))

    evidence_total = evidence_base_query.scalar() or 0
    evidence_today = (
        evidence_base_query.filter(EvidenceItem.created_at >= today_start).scalar() or 0
    )
    evidence_7d = (
        evidence_base_query.filter(EvidenceItem.created_at >= seven_days_ago).scalar()
        or 0
    )

    # Document counts (user's own documents)
    documents_total = (
        db.query(func.count(Document.id))
        .filter(Document.owner_user_id == user.id)
        .scalar()
        or 0
    )
    documents_today = (
        db.query(func.count(Document.id))
        .filter(Document.owner_user_id == user.id, Document.created_at >= today_start)
        .scalar()
        or 0
    )
    documents_7d = (
        db.query(func.count(Document.id))
        .filter(
            Document.owner_user_id == user.id, Document.created_at >= seven_days_ago
        )
        .scalar()
        or 0
    )

    return ControlCentreStats(
        emails_today=emails_today,
        emails_7d=emails_7d,
        emails_total=emails_total,
        evidence_today=evidence_today,
        evidence_7d=evidence_7d,
        evidence_total=evidence_total,
        documents_today=documents_today,
        documents_7d=documents_7d,
        documents_total=documents_total,
    )


def get_user_activity(
    db: Session, user: User, limit: int = 10
) -> tuple[list[ActivityItem], list[ActivityItem]]:
    """Get activity items for 'My Activity' and 'Team Activity' tabs"""
    my_activity: list[ActivityItem] = []
    team_activity: list[ActivityItem] = []

    # Get workspace names for context
    workspace_names: dict[str, str] = {}
    workspaces = db.query(Workspace).all()
    for ws in workspaces:
        workspace_names[str(ws.id)] = ws.name

    # Get user names for team activity
    user_names: dict[str, str] = {}
    users = db.query(User).all()
    for u in users:
        user_names[str(u.id)] = u.display_name or u.email.split("@")[0]

    # Query CollaborationActivity for recent activity
    collab_activities = (
        db.query(CollaborationActivity)
        .order_by(desc(CollaborationActivity.created_at))
        .limit(50)
        .all()
    )

    for activity in collab_activities:
        # Determine workspace from activity details if available
        workspace_name = None
        if activity.details and isinstance(activity.details, dict):
            ws_id = activity.details.get("workspace_id")
            if ws_id:
                workspace_name = workspace_names.get(str(ws_id))

        item = ActivityItem(
            id=str(activity.id),
            action=activity.action,
            resource_type=activity.resource_type,
            description=_format_activity_description(activity),
            workspace=workspace_name,
            user_name=(
                user_names.get(str(activity.user_id)) if activity.user_id else None
            ),
            timestamp=_ensure_tz_aware(activity.created_at),
        )

        if activity.user_id == user.id:
            if len(my_activity) < limit:
                my_activity.append(item)
        else:
            if len(team_activity) < limit:
                team_activity.append(item)

    # Also query EvidenceActivityLog for evidence-specific activity
    evidence_activities = (
        db.query(EvidenceActivityLog)
        .order_by(desc(EvidenceActivityLog.created_at))
        .limit(50)
        .all()
    )

    for activity in evidence_activities:
        workspace_name = None
        if activity.details and isinstance(activity.details, dict):
            ws_id = activity.details.get("workspace_id")
            if ws_id:
                workspace_name = workspace_names.get(str(ws_id))

        item = ActivityItem(
            id=str(activity.id),
            action=activity.action,
            resource_type="evidence",
            description=_format_evidence_activity_description(activity),
            workspace=workspace_name,
            user_name=(
                user_names.get(str(activity.user_id)) if activity.user_id else None
            ),
            timestamp=_ensure_tz_aware(activity.created_at),
        )

        if activity.user_id == user.id:
            if len(my_activity) < limit:
                my_activity.append(item)
        else:
            if len(team_activity) < limit:
                team_activity.append(item)

    # Sort by timestamp descending
    my_activity.sort(key=lambda x: x.timestamp, reverse=True)
    team_activity.sort(key=lambda x: x.timestamp, reverse=True)

    return my_activity[:limit], team_activity[:limit]


def _format_activity_description(activity: CollaborationActivity) -> str:
    """Format a collaboration activity into a human-readable description"""
    action = activity.action.lower().replace("_", " ")
    resource = activity.resource_type.lower()
    return f"{action.capitalize()} {resource}"


def _format_evidence_activity_description(activity: EvidenceActivityLog) -> str:
    """Format an evidence activity into a human-readable description"""
    action = activity.action.lower().replace("_", " ")
    return f"{action.capitalize()} evidence item"


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    db: DbDep, user: Annotated[User, Depends(current_user)]
) -> DashboardOverviewResponse:
    """
    Get complete dashboard overview for the current user.
    Returns aggregated projects, cases, statistics, and recent activity.
    """
    try:
        debug_log(
            "E",
            "get_dashboard_overview entered",
            {"user_id": str(user.id), "role": user.role.value},
            292,
        )
        # Gather projects and cases
        projects = get_user_projects(db, user)
        cases = get_user_cases(db, user)

        # Batch fetch all stats in just 6 queries total (instead of 3 * (projects + cases))
        project_ids = [p.id for p in projects]
        case_ids = [c.id for c in cases]

        project_stats = get_all_project_stats_batch(db, project_ids)
        case_stats = get_all_case_stats_batch(db, case_ids)

        # Build unified work items list
        work_items: list[WorkItemSummary] = []
        total_emails = 0
        total_evidence = 0

        # Add projects to work items (using batch-loaded stats)
        for project in projects:
            stats = project_stats.get(
                project.id, {"email_count": 0, "evidence_count": 0, "pst_count": 0}
            )
            total_emails += stats["email_count"]
            total_evidence += stats["evidence_count"]

            work_items.append(
                WorkItemSummary(
                    id=str(project.id),
                    type="project",
                    name=project.project_name,
                    description=None,
                    status="active",
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                    project_code=project.project_code,
                    contract_type=project.contract_type,
                    project_id=str(project.id),
                    project_name=project.project_name,
                    email_count=stats["email_count"],
                    evidence_count=stats["evidence_count"],
                    pst_count=stats["pst_count"],
                    user_role="admin" if user.role == UserRole.ADMIN else "owner",
                    is_owner=(project.owner_user_id == user.id),
                )
            )

        # Add cases to work items (using batch-loaded stats)
        for case in cases:
            stats = case_stats.get(
                case.id, {"email_count": 0, "evidence_count": 0, "pst_count": 0}
            )
            total_emails += stats["email_count"]
            total_evidence += stats["evidence_count"]

            user_role = get_user_role_on_case(db, user, case.id)

            work_items.append(
                WorkItemSummary(
                    id=str(case.id),
                    type="case",
                    name=case.name,
                    description=case.description,
                    status=case.status or "active",
                    created_at=case.created_at,
                    updated_at=case.updated_at,
                    case_number=case.case_number,
                    contract_type=case.contract_type,
                    project_id=str(case.project_id) if case.project_id else None,
                    project_name=case.project_name,
                    email_count=stats["email_count"],
                    evidence_count=stats["evidence_count"],
                    pst_count=stats["pst_count"],
                    user_role=user_role,
                    is_owner=(case.owner_id == user.id),
                )
            )

        # Collect upcoming deadlines from cases
        upcoming_deadlines: list[DeadlineItem] = []
        for case in cases:
            if case.deadlines and isinstance(case.deadlines, list):
                for i, d in enumerate(case.deadlines):
                    if not isinstance(d, dict):
                        continue

                    # Safe extraction with defaults
                    d_title = d.get("title", "Untitled Deadline")
                    d_date_str = d.get("date")
                    d_status = d.get("status", "pending")

                    if d_date_str:
                        try:
                            # Handle string date parsing if needed, but assuming ISO format
                            d_date = datetime.fromisoformat(
                                str(d_date_str).replace("Z", "+00:00")
                            )
                            d_date = _ensure_tz_aware(d_date)

                            upcoming_deadlines.append(
                                DeadlineItem(
                                    id=f"case_{case.id}_{i}",
                                    title=d_title,
                                    date=d_date,
                                    type="deadline",
                                    source_id=str(case.id),
                                    source_name=case.name,
                                    status=d_status,
                                )
                            )
                        except (ValueError, TypeError):
                            logger.warning(
                                f"Invalid deadline date format in case {case.id}: {d_date_str}"
                            )

        # Sort deadlines by date (soonest first)
        upcoming_deadlines.sort(key=lambda x: x.date)

        # Sort work items by updated_at descending (most recent first)
        # Use helper to ensure all datetimes are timezone-aware for comparison
        work_items.sort(
            key=lambda x: _ensure_tz_aware(x.updated_at or x.created_at),
            reverse=True,
        )

        # Build stats
        stats = DashboardStats(
            total_projects=len(projects),
            total_cases=len(cases),
            total_emails=total_emails,
            total_evidence=total_evidence,
            items_needing_attention=sum(1 for w in work_items if w.pst_count == 0),
            recent_activity_count=len(
                [
                    w
                    for w in work_items
                    if w.updated_at
                    and _ensure_tz_aware(w.updated_at)
                    > datetime.now(timezone.utc) - timedelta(days=7)
                ]
            ),
        )

        # Build permissions based on user role
        permissions = {
            "can_create_project": user.role in [UserRole.ADMIN, UserRole.POWER_USER],
            "can_create_case": user.role in [UserRole.ADMIN, UserRole.POWER_USER],
            "can_manage_users": user.role in [UserRole.ADMIN, UserRole.MANAGEMENT_USER],
            "can_manage_deadlines": user.role
            in [UserRole.ADMIN, UserRole.POWER_USER, UserRole.MANAGEMENT_USER],
            "can_access_admin": user.role == UserRole.ADMIN,
            "can_delete_items": user.role == UserRole.ADMIN,
        }

        # Recent activity (simplified - just return recent work items)
        recent_activity: list[dict[str, Any]] = []
        for w in work_items[:10]:
            if w.updated_at or w.created_at:
                ts_val = w.updated_at or w.created_at
                # region agent log D
                debug_log(
                    "D",
                    "timestamp formatting",
                    {
                        "item_id": w.id,
                        "ts_none": ts_val is None,
                        "ts_type": str(type(ts_val)) if ts_val else None,
                    },
                    412,
                )
                # endregion
                recent_activity.append(
                    {
                        "type": "updated",
                        "item_type": w.type,
                        "item_id": w.id,
                        "item_name": w.name,
                        "timestamp": ts_val.isoformat() if ts_val else None,
                    }
                )

        return DashboardOverviewResponse(
            user={
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name or user.email.split("@")[0],
                "role": user.role.value,
            },
            stats=stats,
            work_items=work_items,
            recent_activity=recent_activity,
            upcoming_deadlines=upcoming_deadlines,
            permissions=permissions,
        )
    except Exception as e:
        logger.exception("Dashboard overview failed")
        raise HTTPException(status_code=500, detail=f"Dashboard load error: {str(e)}")


@router.get("/overview/public")
async def get_dashboard_overview_public(db: DbDep) -> dict[str, Any]:
    """
    Public dashboard overview without authentication.
    Used when auth is disabled or for initial page load.
    Cached for 30 seconds to improve performance.
    """
    # Check cache first
    cached = _get_cached("dashboard_public")
    debug_log(
        "E",
        "get_dashboard_overview_public entered",
        {"cache_hit": cached is not None},
        446,
    )
    if cached is not None:
        return cached

    try:
        # Get all projects and cases without user filtering
        projects = db.query(Project).order_by(desc(Project.created_at)).limit(50).all()
        cases = db.query(Case).order_by(desc(Case.created_at)).limit(50).all()

        # Batch fetch all stats (6 queries total instead of 3 * (projects + cases))
        project_ids = [p.id for p in projects]
        case_ids = [c.id for c in cases]
        project_stats = get_all_project_stats_batch(db, project_ids)
        case_stats = get_all_case_stats_batch(db, case_ids)

        work_items: list[dict[str, Any]] = []
        total_emails = 0
        total_evidence = 0

        # Add projects (using batch-loaded stats)
        for project in projects:
            stats = project_stats.get(
                project.id, {"email_count": 0, "evidence_count": 0, "pst_count": 0}
            )
            total_emails += stats["email_count"]
            total_evidence += stats["evidence_count"]

            work_items.append(
                {
                    "id": str(project.id),
                    "type": "project",
                    "name": project.project_name,
                    "description": None,
                    "status": "active",
                    "created_at": (
                        project.created_at.isoformat() if project.created_at else None
                    ),
                    "updated_at": (
                        project.updated_at.isoformat() if project.updated_at else None
                    ),
                    "project_code": project.project_code,
                    "contract_type": project.contract_type,
                    "project_id": str(project.id),
                    "project_name": project.project_name,
                    "email_count": stats["email_count"],
                    "evidence_count": stats["evidence_count"],
                    "pst_count": stats["pst_count"],
                    "user_role": "editor",
                    "is_owner": False,
                }
            )

        # Add cases (using batch-loaded stats)
        for case in cases:
            stats = case_stats.get(
                case.id, {"email_count": 0, "evidence_count": 0, "pst_count": 0}
            )
            total_emails += stats["email_count"]
            total_evidence += stats["evidence_count"]

            work_items.append(
                {
                    "id": str(case.id),
                    "type": "case",
                    "name": case.name,
                    "description": case.description,
                    "status": case.status or "active",
                    "created_at": (
                        case.created_at.isoformat() if case.created_at else None
                    ),
                    "updated_at": (
                        case.updated_at.isoformat() if case.updated_at else None
                    ),
                    "case_number": case.case_number,
                    "contract_type": case.contract_type,
                    "project_id": str(case.project_id) if case.project_id else None,
                    "project_name": case.project_name,
                    "email_count": stats["email_count"],
                    "evidence_count": stats["evidence_count"],
                    "pst_count": stats["pst_count"],
                    "user_role": "editor",
                    "is_owner": False,
                }
            )

        # Sort by most recent
        work_items.sort(
            key=lambda x: x.get("updated_at") or x.get("created_at") or "", reverse=True
        )

        result: dict[str, Any] = {
            "user": {
                "id": "anonymous",
                "email": "user@vericase.com",
                "display_name": "User",
                "role": "EDITOR",
            },
            "stats": {
                "total_projects": len(projects),
                "total_cases": len(cases),
                "total_emails": total_emails,
                "total_evidence": total_evidence,
                "items_needing_attention": sum(
                    1 for w in work_items if w.get("pst_count", 0) == 0
                ),
                "recent_activity_count": len(work_items),
            },
            "work_items": work_items,
            "recent_activity": [],
            "upcoming_deadlines": [],
            "permissions": {
                "can_create_project": True,
                "can_create_case": True,
                "can_manage_users": False,
                "can_access_admin": False,
                "can_delete_items": False,
            },
        }

        # Cache the result
        _set_cached("dashboard_public", result)
        return result
    except Exception as e:
        logger.exception("Dashboard public overview failed")
        raise HTTPException(status_code=500, detail=f"Dashboard public error: {str(e)}")


@router.get("/quick-stats")
async def get_quick_stats(db: DbDep) -> dict[str, int]:
    """
    Get quick statistics for header display.
    Lightweight endpoint for frequent polling.
    Cached for 30 seconds in Redis for multi-worker sharing.
    """
    # Check cache first
    cached = _get_cached("quick_stats")
    debug_log("C", "quick_stats cache check", {"hit": cached is not None}, 572)
    if cached is not None:
        return cached

    project_count = db.query(func.count(Project.id)).scalar() or 0
    case_count = db.query(func.count(Case.id)).scalar() or 0
    email_count = db.query(func.count(EmailMessage.id)).scalar() or 0
    evidence_count = db.query(func.count(EvidenceItem.id)).scalar() or 0

    result = {
        "projects": project_count,
        "cases": case_count,
        "emails": email_count,
        "evidence": evidence_count,
    }

    # Cache the result
    _set_cached("quick_stats", result)
    return result


async def _get_processing_stats() -> dict[str, Any]:
    """Best-effort Celery/Redis processing stats."""
    queue_length = None
    active_workers = None

    try:
        import redis  # type: ignore

        r = redis.Redis.from_url(settings.REDIS_URL)
        queue_length = int(r.llen(settings.CELERY_QUEUE))
    except Exception as e:
        logger.debug("Redis queue length unavailable: %s", e)

    try:
        from .tasks import celery_app

        insp = celery_app.control.inspect()
        active = insp.active() or {}
        active_workers = len(active.keys())
    except Exception as e:
        logger.debug("Celery worker inspect unavailable: %s", e)

    return {"queue_length": queue_length, "active_workers": active_workers}


@router.get("/system-health")
async def get_system_health(
    db: DbDep,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Get real-time system health from AWS where available."""
    if get_aws_services is None:
        raise HTTPException(
            status_code=503, detail="AWS services not configured in this deployment"
        )

    aws = get_aws_services()

    eks_health = await aws.get_eks_cluster_health()
    rds_instance = settings.RDS_INSTANCE_ID or "vericase-prod"
    db_metrics = await aws.get_rds_metrics(
        db_instance=rds_instance,
        metrics=["CPUUtilization", "DatabaseConnections", "FreeableMemory"],
    )
    s3_bytes = await aws.get_s3_bucket_size(settings.S3_BUCKET)
    log_group = settings.CLOUDWATCH_LOG_GROUP or "/aws/eks/vericase/api"
    recent_errors = await aws.get_cloudwatch_logs(
        log_group=log_group, filter_pattern="ERROR", hours=1
    )
    processing_stats = await _get_processing_stats()

    evidence_count = db.query(func.count(EvidenceItem.id)).scalar() or 0

    return {
        "timestamp": datetime.now(timezone.utc),
        "eks": eks_health,
        "database": {
            "instance": rds_instance,
            "cpu": db_metrics.get("CPUUtilization"),
            "connections": db_metrics.get("DatabaseConnections"),
            "freeable_memory": db_metrics.get("FreeableMemory"),
        },
        "storage": {
            "bucket": settings.S3_BUCKET,
            "size_gb": (s3_bytes / (1024**3)) if s3_bytes else None,
            "evidence_count": evidence_count,
        },
        "processing": processing_stats,
        "errors": {
            "count": len(recent_errors),
            "recent": recent_errors[:5],
            "log_group": log_group,
        },
    }


@router.get("/control-centre-stats", response_model=ControlCentreResponse)
async def get_control_centre_stats(
    db: DbDep, user: Annotated[User, Depends(current_user)]
) -> ControlCentreResponse:
    """
    Get Control Centre statistics including time-filtered counts and activity feeds.
    Returns stats for emails, evidence, documents (today, 7 days, total)
    plus separate activity feeds for current user and team members.
    """
    try:
        # Get time-filtered statistics
        stats = get_time_filtered_counts(db, user)

        # Get activity feeds
        my_activity, team_activity = get_user_activity(db, user, limit=10)

        # Build permissions based on user role
        permissions = {
            "can_create_workspace": user.role in [UserRole.ADMIN, UserRole.POWER_USER],
            "can_create_project": user.role in [UserRole.ADMIN, UserRole.POWER_USER],
            "can_create_case": user.role in [UserRole.ADMIN, UserRole.POWER_USER],
            "can_manage_users": user.role in [UserRole.ADMIN, UserRole.MANAGEMENT_USER],
            "can_manage_deadlines": user.role
            in [UserRole.ADMIN, UserRole.POWER_USER, UserRole.MANAGEMENT_USER],
            "can_access_admin": user.role == UserRole.ADMIN,
        }

        return ControlCentreResponse(
            user={
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name or user.email.split("@")[0],
                "role": user.role.value,
                "last_login": (
                    user.last_login_at.isoformat() if user.last_login_at else None
                ),
            },
            stats=stats,
            my_activity=my_activity,
            team_activity=team_activity,
            permissions=permissions,
        )
    except Exception as e:
        logger.exception("Control Centre stats failed")
        raise HTTPException(
            status_code=500, detail=f"Control Centre stats error: {str(e)}"
        )
