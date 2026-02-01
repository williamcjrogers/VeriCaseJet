"""
Job status + progress streaming (Celery-backed).

Why:
- UI needs a consistent, non-fragmented way to run long operations and show progress.
- We already use Celery for PST/OCR. This exposes a small job API for workspace analysis.
"""


import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sse_starlette.sse import EventSourceResponse

from .db import get_db
from .models import User, UserRole, Workspace
from .security import current_user
from .tasks import celery_app

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


def _is_admin(user: User) -> bool:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    return str(role_val).upper() == UserRole.ADMIN.value


def _require_workspace_access(db: Session, workspace_id: str, user: User) -> Workspace:
    ws_uuid = _parse_uuid(workspace_id, "workspace_id")
    ws = db.query(Workspace).filter(Workspace.id == ws_uuid).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if ws.owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Access denied")
    return ws


class JobStatusResponse(BaseModel):
    id: str
    state: str
    ready: bool
    successful: bool
    failed: bool
    updated_at: str
    meta: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    error: str | None = None


def _serialize_job(ar: AsyncResult) -> tuple[dict[str, Any], str | None]:
    state = str(ar.state or "PENDING")
    info = ar.info
    meta: dict[str, Any] = info if isinstance(info, dict) else {}

    error: str | None = None
    result: Any | None = None
    if state == "FAILURE":
        # Don't leak stack traces; keep it short.
        try:
            error = str(info)[:500] if info is not None else "Job failed"
        except Exception:
            error = "Job failed"
    elif state == "SUCCESS":
        try:
            result = ar.result
        except Exception:
            result = None

    payload: dict[str, Any] = {
        "id": str(ar.id or ""),
        "state": state,
        "ready": bool(ar.ready()),
        "successful": bool(ar.successful()),
        "failed": bool(ar.failed()),
        "meta": meta,
        "result": result,
        "error": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return payload, meta.get("workspace_id") if isinstance(meta, dict) else None


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    workspace_id: str = Query(..., description="Workspace scope for access control"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> JobStatusResponse:
    _ = _require_workspace_access(db, workspace_id, user)

    ar = AsyncResult(job_id, app=celery_app)
    payload, meta_ws = _serialize_job(ar)

    # If the job has workspace metadata, enforce that it matches the requested workspace.
    if meta_ws and str(meta_ws) != str(_parse_uuid(workspace_id, "workspace_id")):
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(**payload)


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    workspace_id: str = Query(..., description="Workspace scope for access control"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Revoke a running or pending Celery job."""
    _ = _require_workspace_access(db, workspace_id, user)

    ar = AsyncResult(job_id, app=celery_app)
    _, meta_ws = _serialize_job(ar)

    if meta_ws and str(meta_ws) != str(_parse_uuid(workspace_id, "workspace_id")):
        raise HTTPException(status_code=404, detail="Job not found")

    ar.revoke(terminate=True)
    return {"id": job_id, "status": "cancelled"}


@router.get("/{job_id}/events")
async def stream_job_events(
    request: Request,
    job_id: str,
    workspace_id: str = Query(..., description="Workspace scope for access control"),
    interval_s: float = Query(1.0, ge=0.25, le=10.0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> EventSourceResponse:
    _ = _require_workspace_access(db, workspace_id, user)

    async def _gen():
        last_fingerprint: str | None = None
        while True:
            if await request.is_disconnected():
                break

            ar = AsyncResult(job_id, app=celery_app)
            payload, meta_ws = _serialize_job(ar)

            # Enforce workspace match if meta present.
            try:
                ws_uuid = _parse_uuid(workspace_id, "workspace_id")
                if meta_ws and str(meta_ws) != str(ws_uuid):
                    yield {"event": "error", "data": "not_found"}
                    break
            except HTTPException:
                yield {"event": "error", "data": "bad_request"}
                break

            # Only emit when something changed (keeps the stream quiet).
            try:
                fingerprint = json.dumps(
                    {
                        "state": payload.get("state"),
                        "meta": payload.get("meta"),
                        "error": payload.get("error"),
                    },
                    sort_keys=True,
                    default=str,
                )
            except Exception:
                fingerprint = None

            if fingerprint and fingerprint != last_fingerprint:
                last_fingerprint = fingerprint
                yield {"event": "status", "data": json.dumps(payload, default=str)}

            if bool(payload.get("ready")):
                break

            await asyncio.sleep(float(interval_s))

    return EventSourceResponse(_gen())
