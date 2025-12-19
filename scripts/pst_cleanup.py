"""PST cleanup utility

Purpose
-------
Clean up duplicate/failed/stuck PST uploads for a given project or case.

This script is designed to be *safe*:
- Supports --dry-run (default)
- Prints exactly what it will delete/update
- Can optionally delete related S3 objects (PST + attachments)![1766115762363](image/pst_cleanup/1766115762363.png)![1766115765323](image/pst_cleanup/1766115765323.png)

What it does
------------
For the selected scope (project_id or case_id):

1) Identify PSTFile rows that are:
   - failed
   - stuck in processing/queued for longer than a threshold
   - duplicates (same filename and same file_size_bytes) where no emails were extracted

2) For each PSTFile selected for cleanup:
   - Delete EmailAttachment rows linked to EmailMessage rows of that pst_file_id
   - Delete EvidenceItem rows that were created from those emails (source_email_id)
   - Delete EmailMessage rows
   - Delete PSTFile row OR mark as failed (configurable)

3) Optionally delete S3 objects:
   - PST object at pst_file.s3_bucket/pst_file.s3_key
   - Attachment objects referenced by EmailAttachment.s3_bucket/s3_key

Usage examples
--------------
Dry run (recommended first):
  python scripts/pst_cleanup.py --project-id dca0... --stuck-hours 1

Actually delete:
  python scripts/pst_cleanup.py --project-id dca0... --stuck-hours 1 --apply

Also delete S3 objects (dangerous):
  python scripts/pst_cleanup.py --project-id dca0... --stuck-hours 1 --apply --delete-s3

"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import uuid


# Ensure repo root is on sys.path so `vericase.*` imports work when running as a script
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@dataclass
class PSTCandidate:
    id: uuid.UUID
    filename: str
    status: str
    file_size_bytes: Optional[int]
    uploaded_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_emails: int
    processed_emails: int
    s3_bucket: Optional[str]
    s3_key: str
    error_message: Optional[str]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_uuid(val: str) -> uuid.UUID:
    return uuid.UUID(val)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    # Some columns are stored without tz; assume UTC.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_stuck(
    status: str,
    started_at: Optional[datetime],
    uploaded_at: Optional[datetime],
    stuck_delta: timedelta,
) -> bool:
    if status not in {"processing", "queued"}:
        return False
    ref = _as_utc(started_at) or _as_utc(uploaded_at)
    if ref is None:
        return True
    return (_utcnow() - ref) > stuck_delta


def _is_failed(status: str) -> bool:
    return status == "failed"


def _is_duplicate_group_key(
    filename: str, file_size_bytes: Optional[int]
) -> tuple[str, Optional[int]]:
    return (filename or "", file_size_bytes)


def load_candidates(
    db, project_id: uuid.UUID | None, case_id: uuid.UUID | None
) -> list[PSTCandidate]:
    from vericase.api.app.models import PSTFile

    q = db.query(PSTFile)
    if project_id:
        q = q.filter(PSTFile.project_id == project_id)
    if case_id:
        q = q.filter(PSTFile.case_id == case_id)

    rows = q.order_by(PSTFile.uploaded_at.desc()).all()
    out: list[PSTCandidate] = []
    for r in rows:
        out.append(
            PSTCandidate(
                id=r.id,
                filename=r.filename,
                status=(r.processing_status or "pending"),
                file_size_bytes=r.file_size_bytes,
                uploaded_at=_as_utc(r.uploaded_at),
                started_at=_as_utc(r.processing_started_at),
                completed_at=_as_utc(r.processing_completed_at),
                total_emails=int(r.total_emails or 0),
                processed_emails=int(r.processed_emails or 0),
                s3_bucket=r.s3_bucket,
                s3_key=r.s3_key,
                error_message=r.error_message,
            )
        )
    return out


def pick_for_cleanup(
    candidates: list[PSTCandidate],
    stuck_hours: float,
    include_failed: bool,
    include_stuck: bool,
    include_duplicates: bool,
    include_filename_contains: Optional[str] = None,
) -> list[PSTCandidate]:
    stuck_delta = timedelta(hours=stuck_hours)

    selected: dict[uuid.UUID, PSTCandidate] = {}

    if include_failed:
        for c in candidates:
            if _is_failed(c.status):
                selected[c.id] = c

    if include_stuck:
        for c in candidates:
            if _is_stuck(c.status, c.started_at, c.uploaded_at, stuck_delta):
                selected[c.id] = c

    if include_duplicates:
        # Define duplicates as same (filename, file_size_bytes) and all have 0 emails.
        # Keep the newest one (uploaded_at) and delete the rest.
        groups: dict[tuple[str, Optional[int]], list[PSTCandidate]] = {}
        for c in candidates:
            groups.setdefault(
                _is_duplicate_group_key(c.filename, c.file_size_bytes), []
            ).append(c)

        for _, group in groups.items():
            if len(group) <= 1:
                continue
            # Only treat as dupes if none extracted anything.
            if any(
                (g.total_emails or 0) > 0 or (g.processed_emails or 0) > 0
                for g in group
            ):
                continue
            group_sorted = sorted(
                group,
                key=lambda x: (
                    x.uploaded_at or datetime.min.replace(tzinfo=timezone.utc)
                ),
                reverse=True,
            )
            # Keep the first (most recent) entry, select the rest for cleanup
            for g in group_sorted[1:]:
                selected[g.id] = g

    if include_filename_contains:
        token = include_filename_contains.lower()
        for c in candidates:
            if token in (c.filename or "").lower():
                selected[c.id] = c

    # Return stable order: oldest first so we clear backlog deterministically
    return sorted(
        selected.values(),
        key=lambda x: (x.uploaded_at or datetime.min.replace(tzinfo=timezone.utc)),
    )


def delete_related_rows(db, pst_id: uuid.UUID, dry_run: bool) -> dict[str, int]:
    """Delete EmailAttachment, EvidenceItem, EmailMessage, then PSTFile.

    EvidenceItem is linked by source_email_id.
    """
    from vericase.api.app.models import (
        EmailMessage,
        EmailAttachment,
        PSTFile,
        EvidenceItem,
    )

    # Find email ids
    email_ids = [
        row[0]
        for row in db.query(EmailMessage.id)
        .filter(EmailMessage.pst_file_id == pst_id)
        .all()
    ]

    # Attachments
    att_q = (
        db.query(EmailAttachment).filter(
            EmailAttachment.email_message_id.in_(email_ids)
        )
        if email_ids
        else db.query(EmailAttachment).filter(False)
    )
    ev_q = (
        db.query(EvidenceItem).filter(EvidenceItem.source_email_id.in_(email_ids))
        if email_ids
        else db.query(EvidenceItem).filter(False)
    )
    em_q = (
        db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids))
        if email_ids
        else db.query(EmailMessage).filter(False)
    )

    counts = {
        "email_messages": len(email_ids),
        "email_attachments": int(att_q.count()) if email_ids else 0,
        "evidence_items": int(ev_q.count()) if email_ids else 0,
        "pst_files": 1,
    }

    if dry_run:
        return counts

    # Delete in dependency order
    if email_ids:
        att_q.delete(synchronize_session=False)
        ev_q.delete(synchronize_session=False)
        em_q.delete(synchronize_session=False)

    db.query(PSTFile).filter(PSTFile.id == pst_id).delete(synchronize_session=False)
    return counts


def list_s3_objects_for_pst(db, pst_id: uuid.UUID) -> dict[str, list[tuple[str, str]]]:
    """Return buckets/keys for PST object and attachment objects."""
    from vericase.api.app.models import PSTFile, EmailAttachment, EmailMessage

    pst = db.query(PSTFile).filter(PSTFile.id == pst_id).first()
    if not pst:
        return {"pst": [], "attachments": []}

    # PST object
    pst_objs: list[tuple[str, str]] = []
    if pst.s3_bucket and pst.s3_key:
        pst_objs.append((pst.s3_bucket, pst.s3_key))

    # Attachment objects
    email_ids = [
        row[0]
        for row in db.query(EmailMessage.id)
        .filter(EmailMessage.pst_file_id == pst_id)
        .all()
    ]
    attachments: list[tuple[str, str]] = []
    if email_ids:
        for b, k in (
            db.query(EmailAttachment.s3_bucket, EmailAttachment.s3_key)
            .filter(EmailAttachment.email_message_id.in_(email_ids))
            .all()
        ):
            if b and k:
                attachments.append((b, k))

    # de-dupe
    attachments = sorted(set(attachments))
    return {"pst": pst_objs, "attachments": attachments}


def delete_s3_objects(objs: Iterable[tuple[str, str]], dry_run: bool) -> int:
    """Delete objects from S3/MinIO using app.storage.s3() client."""
    from vericase.api.app.storage import s3

    client = s3()
    if client is None:
        raise RuntimeError("No S3 client configured")

    deleted = 0
    for bucket, key in objs:
        if dry_run:
            deleted += 1
            continue
        client.delete_object(Bucket=bucket, Key=key)
        deleted += 1
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=str, default=None)
    parser.add_argument("--case-id", type=str, default=None)
    parser.add_argument("--stuck-hours", type=float, default=1.0)

    parser.add_argument("--include-failed", action="store_true", default=True)
    parser.add_argument("--include-stuck", action="store_true", default=True)
    parser.add_argument("--include-duplicates", action="store_true", default=True)
    parser.add_argument("--filename-contains", type=str, default=None)

    parser.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--delete-s3", action="store_true", default=False)

    args = parser.parse_args()

    project_id = _parse_uuid(args.project_id) if args.project_id else None
    case_id = _parse_uuid(args.case_id) if args.case_id else None

    if not project_id and not case_id:
        raise SystemExit("Must provide --project-id or --case-id")

    # Import via repo package layout
    from vericase.api.app.db import SessionLocal

    db = SessionLocal()
    try:
        candidates = load_candidates(db, project_id, case_id)
        selected = pick_for_cleanup(
            candidates,
            stuck_hours=args.stuck_hours,
            include_failed=args.include_failed,
            include_stuck=args.include_stuck,
            include_duplicates=args.include_duplicates,
            include_filename_contains=args.filename_contains,
        )

        dry_run = not args.apply

        print("\n=== PST CLEANUP ===")
        print(f"Scope: project_id={project_id} case_id={case_id}")
        print(f"Mode: {'DRY-RUN' if dry_run else 'APPLY'}")
        print(f"Delete S3: {args.delete_s3}")
        print(f"Candidates: {len(candidates)}  Selected: {len(selected)}")

        grand = {
            "pst_files": 0,
            "email_messages": 0,
            "email_attachments": 0,
            "evidence_items": 0,
            "s3_objects": 0,
        }

        for pst in selected:
            print("\n---")
            print(
                f"PST {pst.id} | {pst.filename} | status={pst.status} | size={pst.file_size_bytes} | emails={pst.total_emails}/{pst.processed_emails}"
            )
            print(
                f"uploaded_at={pst.uploaded_at} started_at={pst.started_at} completed_at={pst.completed_at}"
            )
            if pst.error_message:
                print(f"error={pst.error_message}")

            # DB counts
            counts = delete_related_rows(db, pst.id, dry_run=True)
            print(f"Would delete rows: {counts}")

            for k, v in counts.items():
                grand[k] += v

            # S3
            if args.delete_s3:
                s3_objs = list_s3_objects_for_pst(db, pst.id)
                s3_all = s3_objs["pst"] + s3_objs["attachments"]
                print(
                    f"S3 objects (pst={len(s3_objs['pst'])}, attachments={len(s3_objs['attachments'])})"
                )
                grand["s3_objects"] += len(set(s3_all))

            if not dry_run:
                # Actually delete
                delete_related_rows(db, pst.id, dry_run=False)
                if args.delete_s3:
                    s3_objs = list_s3_objects_for_pst(db, pst.id)
                    s3_all = list(set(s3_objs["pst"] + s3_objs["attachments"]))
                    delete_s3_objects(s3_all, dry_run=False)
                db.commit()

        print("\n=== SUMMARY ===")
        print(grand)
        if dry_run:
            print("\nDry-run only. Re-run with --apply to execute.")

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
