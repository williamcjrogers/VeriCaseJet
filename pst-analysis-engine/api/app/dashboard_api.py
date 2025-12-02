"""
Master Dashboard API
Provides aggregated overview of user's projects, cases, and activity
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_
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
)
from .security import current_user
from .cache import get_cached, set_cached

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
DbDep = Annotated[Session, Depends(get_db)]

# ============================================================================
# Redis Cache Configuration (shared across workers)
# ============================================================================
CACHE_TTL_SECONDS = 30  # Cache dashboard data for 30 seconds


def _get_cached(key: str) -> dict[str, Any] | None:
    """Get value from Redis cache"""
    result = get_cached(f"dashboard:{key}")
    if result:
        logger.debug(f"Dashboard cache HIT: {key}")
    return result  # pyright: ignore[reportReturnType]


def _set_cached(key: str, value: dict[str, Any]) -> None:
    """Store value in Redis cache"""
    set_cached(f"dashboard:{key}", value, ttl_seconds=CACHE_TTL_SECONDS)


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


class DashboardOverviewResponse(BaseModel):
    """Complete dashboard overview response"""

    user: dict[str, Any]
    stats: DashboardStats
    work_items: list[WorkItemSummary]
    recent_activity: list[dict[str, Any]]
    permissions: dict[str, bool]


class CreateWorkItemRequest(BaseModel):
    """Request to create a new project or case"""

    type: str = Field(..., pattern="^(project|case)$")
    name: str = Field(..., min_length=2, max_length=255)
    description: str | None = None
    project_code: str | None = None  # Required for projects
    case_number: str | None = None  # Auto-generated for cases if not provided
    contract_type: str | None = None


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
        case_ids_from_assignments = (
            db.query(CaseUser.case_id).filter(CaseUser.user_id == user.id).subquery()
        )

        return (
            db.query(Case)
            .filter(
                or_(Case.owner_id == user.id, Case.id.in_(case_ids_from_assignments))
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
# API Endpoints
# ============================================================================


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    db: DbDep, user: User = Depends(current_user)
) -> DashboardOverviewResponse:
    """
    Get complete dashboard overview for the current user.
    Returns aggregated projects, cases, statistics, and recent activity.
    """
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
                email_count=stats["email_count"],
                evidence_count=stats["evidence_count"],
                pst_count=stats["pst_count"],
                user_role=user_role,
                is_owner=(case.owner_id == user.id),
            )
        )

    # Sort work items by updated_at descending (most recent first)
    work_items.sort(
        key=lambda x: x.updated_at
        or x.created_at
        or datetime.min.replace(tzinfo=timezone.utc),
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
                and (
                    w.updated_at.replace(tzinfo=timezone.utc)
                    if w.updated_at.tzinfo is None
                    else w.updated_at
                )
                > datetime.now(timezone.utc) - timedelta(days=7)
            ]
        ),
    )

    # Build permissions based on user role
    permissions = {
        "can_create_project": user.role in [UserRole.ADMIN, UserRole.EDITOR],
        "can_create_case": user.role in [UserRole.ADMIN, UserRole.EDITOR],
        "can_manage_users": user.role == UserRole.ADMIN,
        "can_access_admin": user.role == UserRole.ADMIN,
        "can_delete_items": user.role == UserRole.ADMIN,
    }

    # Recent activity (simplified - just return recent work items)
    recent_activity = [
        {
            "type": "updated",
            "item_type": w.type,
            "item_id": w.id,
            "item_name": w.name,
            "timestamp": (
                (w.updated_at or w.created_at).isoformat()
                if (w.updated_at or w.created_at)
                else None
            ),
        }
        for w in work_items[:10]
        if w.updated_at or w.created_at
    ]

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
        permissions=permissions,
    )


@router.get("/overview/public")
async def get_dashboard_overview_public(db: DbDep) -> dict[str, Any]:
    """
    Public dashboard overview without authentication.
    Used when auth is disabled or for initial page load.
    Cached for 30 seconds to improve performance.
    """
    # Check cache first
    cached = _get_cached("dashboard_public")
    if cached is not None:
        return cached

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
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "updated_at": case.updated_at.isoformat() if case.updated_at else None,
                "case_number": case.case_number,
                "contract_type": case.contract_type,
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


@router.get("/quick-stats")
async def get_quick_stats(db: DbDep) -> dict[str, int]:
    """
    Get quick statistics for header display.
    Lightweight endpoint for frequent polling.
    Cached for 30 seconds in Redis for multi-worker sharing.
    """
    # Check cache first
    cached = _get_cached("quick_stats")
    if cached is not None:
        return cached  # pyright: ignore[reportReturnType]

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
