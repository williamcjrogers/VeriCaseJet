"""Programme-to-email auto-linking utilities.

This module contains pure-ish logic used by background tasks to map each email to
an "as planned" (baseline) and "as built/current" activity based on the email
sent date.

Design goals:
- Avoid per-request computation in API endpoints.
- Batch updates for large email datasets.
- Be tolerant of mixed programme_type naming conventions.

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import uuid


@dataclass(frozen=True)
class ActivityWindow:
    activity_id: str | None
    name: str
    start: datetime
    finish: datetime
    is_critical: bool


def _to_naive_utc(dt: datetime) -> datetime:
    """Convert aware datetimes to naive UTC; leave naive datetimes as-is."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # Support a trailing Z just in case.
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).replace(tzinfo=None)
    except Exception:
        return None


def build_activity_windows(
    programme_activities: list[dict[str, Any]] | None, critical_ids: set[str]
) -> list[ActivityWindow]:
    """Convert stored JSON activities into comparable date windows."""
    if not programme_activities:
        return []

    windows: list[ActivityWindow] = []

    for a in programme_activities:
        if not isinstance(a, dict):
            continue

        start_dt = _parse_iso_datetime(a.get("start_date"))
        finish_dt = _parse_iso_datetime(a.get("finish_date"))
        if not start_dt or not finish_dt:
            continue

        name = str(a.get("name") or "").strip()
        if not name:
            continue

        activity_id = a.get("id")
        activity_id_str = str(activity_id) if activity_id is not None else None
        windows.append(
            ActivityWindow(
                activity_id=activity_id_str,
                name=name,
                start=start_dt,
                finish=finish_dt,
                is_critical=(activity_id_str in critical_ids),
            )
        )

    return windows


def choose_active_activity(
    windows: list[ActivityWindow], target: datetime
) -> ActivityWindow | None:
    """Choose a best-fit activity window for target datetime.

    Strategy:
    1) Filter to activities active on the date (inclusive).
    2) Prefer critical path activities if any are active.
    3) Prefer the activity whose finish date is closest to the target date.

    Returns:
        Selected ActivityWindow or None.
    """
    if not windows:
        return None

    target = _to_naive_utc(target)

    active = [w for w in windows if w.start <= target <= w.finish]
    if not active:
        return None

    critical_active = [w for w in active if w.is_critical]
    candidates = critical_active if critical_active else active

    def _score(w: ActivityWindow) -> tuple[float, float]:
        # Primary: absolute seconds to finish (smaller = closer)
        # Secondary: absolute seconds to start (smaller = closer)
        finish_delta = abs((w.finish - target).total_seconds())
        start_delta = abs((target - w.start).total_seconds())
        return (finish_delta, start_delta)

    return min(candidates, key=_score)


def _normalize_programme_type(value: str | None) -> str:
    if not value:
        return ""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


_BASELINE_TYPES = {
    "baseline",
    "as_planned",
    "asplanned",
    "planned",
    "programme_baseline",
}

_CURRENT_TYPES = {
    "current",
    "as_built",
    "asbuilt",
    "actual",
    "interim",
    "update",
    "revised",
}


def pick_baseline_and_current_programmes(
    programmes: Iterable[Any],
) -> tuple[Any | None, Any | None]:
    """Pick baseline and current programmes from an iterable of Programme ORM objects.

    Returns:
        (baseline, current) tuple where:
        - baseline is the earliest baseline/as_planned programme (or earliest overall if none typed)
        - current is the latest as_built/actual programme, or None if no as_built exists

    Important: If no as_built type programme exists, current will be None.
    This prevents baseline data from incorrectly populating as_built fields.
    """
    programmes_list = [p for p in programmes]
    if not programmes_list:
        return (None, None)

    def _programme_sort_key(p: Any) -> datetime:
        # Prefer programme_date, fallback to created_at, else very old
        dt = getattr(p, "programme_date", None) or getattr(p, "created_at", None)
        if isinstance(dt, datetime):
            return _to_naive_utc(dt)
        return datetime.min

    baseline_candidates = [
        p
        for p in programmes_list
        if _normalize_programme_type(getattr(p, "programme_type", None))
        in _BASELINE_TYPES
    ]
    current_candidates = [
        p
        for p in programmes_list
        if _normalize_programme_type(getattr(p, "programme_type", None))
        in _CURRENT_TYPES
    ]

    # Baseline: prefer explicitly typed baseline, fallback to earliest programme
    baseline = (
        min(baseline_candidates, key=_programme_sort_key)
        if baseline_candidates
        else min(programmes_list, key=_programme_sort_key)
    )

    # Current/As-built: ONLY use if we have an explicit as_built type programme
    # Do NOT fallback to baseline - this prevents baseline from populating as_built fields
    current = (
        max(current_candidates, key=_programme_sort_key) if current_candidates else None
    )

    return (baseline, current)


def link_emails_to_programme_activities(
    *,
    db: Any,
    project_id: str | None = None,
    case_id: str | None = None,
    overwrite_existing: bool = False,
    batch_size: int = 500,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Link emails to baseline/current programme activities and persist to DB.

    Args:
        db: SQLAlchemy Session
        project_id: Project UUID string
        case_id: Case UUID string
        overwrite_existing: If False, only fill missing fields
        batch_size: ORM batch size
        progress_cb: Optional callback(progress_count, total_count)

    Returns:
        Stats dict
    """
    from sqlalchemy import func, or_

    from .models import EmailMessage, Programme

    if not project_id and not case_id:
        return {"status": "failed", "error": "Must provide project_id or case_id"}

    project_uuid: uuid.UUID | None = None
    case_uuid: uuid.UUID | None = None
    try:
        if project_id:
            project_uuid = uuid.UUID(project_id)
        if case_id:
            case_uuid = uuid.UUID(case_id)
    except ValueError:
        return {
            "status": "failed",
            "error": "Invalid UUID format for project_id/case_id",
        }

    # Determine email scope
    if project_uuid is not None:
        email_scope_filter = EmailMessage.project_id == project_uuid
    else:
        email_scope_filter = EmailMessage.case_id == case_uuid

    # Find programmes
    programmes_query = db.query(Programme)
    if project_uuid is not None:
        programmes_query = programmes_query.filter(Programme.project_id == project_uuid)

    if case_uuid is not None:
        programmes_query = programmes_query.filter(Programme.case_id == case_uuid)

    programmes = programmes_query.order_by(Programme.programme_date.desc()).all()

    # Fallback: if linking by project but no programmes are linked to project_id,
    # infer a single case_id from the project's emails and use case programmes.
    inferred_case_uuid: uuid.UUID | None = None
    if project_uuid is not None and not programmes:
        distinct_case_ids = (
            db.query(EmailMessage.case_id)
            .filter(EmailMessage.project_id == project_uuid)
            .filter(EmailMessage.case_id.isnot(None))
            .distinct()
            .all()
        )
        distinct_case_ids = [
            row[0] for row in distinct_case_ids if row and row[0] is not None
        ]
        if len(distinct_case_ids) == 1:
            inferred_case_uuid = distinct_case_ids[0]
            programmes = (
                db.query(Programme)
                .filter(Programme.case_id == inferred_case_uuid)
                .order_by(Programme.programme_date.desc())
                .all()
            )

    baseline, current = pick_baseline_and_current_programmes(programmes)
    # Only skip if no baseline available - current (as_built) is optional
    if baseline is None:
        return {
            "status": "skipped",
            "reason": "No baseline programme available for linking",
            "project_id": project_id,
            "case_id": case_id,
            "inferred_case_id": str(inferred_case_uuid) if inferred_case_uuid else None,
        }

    baseline_critical = set(getattr(baseline, "critical_path", None) or [])
    current_critical = (
        set(getattr(current, "critical_path", None) or []) if current else set()
    )

    baseline_windows = build_activity_windows(
        getattr(baseline, "activities", None), baseline_critical
    )
    # Only build current windows if we have an as_built programme
    current_windows = (
        build_activity_windows(getattr(current, "activities", None), current_critical)
        if current
        else []
    )

    stats: dict[str, Any] = {
        "status": "running",
        "project_id": project_id,
        "case_id": case_id,
        "inferred_case_id": str(inferred_case_uuid) if inferred_case_uuid else None,
        "baseline_programme_id": str(getattr(baseline, "id", "")),
        "current_programme_id": str(getattr(current, "id", "")) if current else None,
        "has_as_built_programme": current is not None,
        "total_emails": 0,
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    email_query = (
        db.query(EmailMessage)
        .filter(email_scope_filter)
        .filter(EmailMessage.date_sent.isnot(None))
    )

    if not overwrite_existing:
        # Only filter for missing fields that we can actually populate
        missing_conditions = [
            EmailMessage.as_planned_activity.is_(None),
            EmailMessage.as_planned_finish_date.is_(None),
        ]
        # Only include as_built conditions if we have an as_built programme
        if current is not None:
            missing_conditions.extend(
                [
                    EmailMessage.as_built_activity.is_(None),
                    EmailMessage.as_built_finish_date.is_(None),
                    EmailMessage.delay_days.is_(None),
                ]
            )
        email_query = email_query.filter(or_(*missing_conditions))

    total_count = (
        db.query(func.count(EmailMessage.id)).filter(email_scope_filter).scalar() or 0
    )
    stats["total_emails"] = int(total_count)

    # Process with offset pagination (simple + predictable)
    offset = 0
    while True:
        batch = (
            email_query.order_by(EmailMessage.date_sent.asc())
            .offset(offset)
            .limit(batch_size)
            .all()
        )
        if not batch:
            break

        mappings: list[dict[str, Any]] = []

        for e in batch:
            stats["processed"] += 1
            try:
                sent = getattr(e, "date_sent", None)
                if not isinstance(sent, datetime):
                    stats["skipped"] += 1
                    continue

                sent_naive = _to_naive_utc(sent)

                planned = choose_active_activity(baseline_windows, sent_naive)
                built = choose_active_activity(current_windows, sent_naive)

                planned_finish = planned.finish if planned else None
                built_finish = built.finish if built else None

                # Respect overwrite_existing=False by only writing to empty fields
                update: dict[str, Any] = {"id": e.id}

                if (
                    overwrite_existing
                    or getattr(e, "as_planned_activity", None) is None
                ):
                    update["as_planned_activity"] = planned.name if planned else None
                if (
                    overwrite_existing
                    or getattr(e, "as_planned_finish_date", None) is None
                ):
                    update["as_planned_finish_date"] = planned_finish

                if overwrite_existing or getattr(e, "as_built_activity", None) is None:
                    update["as_built_activity"] = built.name if built else None
                if (
                    overwrite_existing
                    or getattr(e, "as_built_finish_date", None) is None
                ):
                    update["as_built_finish_date"] = built_finish

                # Compute delay days from whichever values will be stored.
                planned_dt = update.get(
                    "as_planned_finish_date", getattr(e, "as_planned_finish_date", None)
                )
                built_dt = update.get(
                    "as_built_finish_date", getattr(e, "as_built_finish_date", None)
                )

                if planned_dt is not None and built_dt is not None:
                    try:
                        delay_val = (
                            _to_naive_utc(built_dt) - _to_naive_utc(planned_dt)
                        ).days
                    except Exception:
                        delay_val = None
                else:
                    delay_val = None

                if overwrite_existing or getattr(e, "delay_days", None) is None:
                    update["delay_days"] = delay_val

                # If nothing would change, skip
                if len(update.keys()) <= 1:
                    stats["skipped"] += 1
                    continue

                mappings.append(update)

            except Exception:
                stats["errors"] += 1

        if mappings:
            db.bulk_update_mappings(EmailMessage, mappings)
            db.commit()
            stats["updated"] += len(mappings)
        else:
            stats["skipped"] += len(batch)

        offset += batch_size

        if progress_cb is not None:
            progress_cb(min(offset, stats["total_emails"]), stats["total_emails"])

    stats["status"] = "completed"
    return stats
