#!/usr/bin/env python3
"""Reindex EmailMessage rows into the OpenSearch `emails` index.

Why this exists
--------------
The Correspondence "Quick Search" / "Deep Research" experience depends on fast retrieval.
OpenSearch is the scalable path for 10k–100k+ emails, but older deployments may have:
- emails indexed without `project_id`, preventing true project-scoped search
- inconsistent `recipients` formats (list[str] vs list[dict])

This script backfills (or rebuilds) OpenSearch docs from Postgres.

Usage examples
--------------
Reindex a single project:
  python reindex_emails_opensearch.py --project-id <uuid>

Reindex a single case:
  python reindex_emails_opensearch.py --case-id <uuid>

Dry run (no writes):
  python reindex_emails_opensearch.py --project-id <uuid> --dry-run

Limit for testing:
  python reindex_emails_opensearch.py --project-id <uuid> --limit 1000
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

# Allow running as a script from the `vericase/api/` folder.
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import or_, not_
from sqlalchemy.orm import load_only

from app.db import SessionLocal
from app.models import EmailMessage
from app.search import index_email_in_opensearch
from app.visibility import build_email_visibility_filter


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex emails into OpenSearch")
    parser.add_argument("--project-id", dest="project_id", default=None)
    parser.add_argument("--case-id", dest="case_id", default=None)
    parser.add_argument(
        "--limit", type=int, default=0, help="Stop after N emails (0 = no limit)"
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write to OpenSearch"
    )

    args = parser.parse_args()

    project_uuid = _parse_uuid(args.project_id)
    case_uuid = _parse_uuid(args.case_id)

    if not project_uuid and not case_uuid:
        raise SystemExit("Provide --project-id or --case-id")

    db = SessionLocal()
    start = time.time()
    processed = 0
    failures = 0

    try:
        load_cols = [
            EmailMessage.id,
            EmailMessage.project_id,
            EmailMessage.case_id,
            EmailMessage.thread_id,
            EmailMessage.thread_group_id,
            EmailMessage.message_id,
            EmailMessage.subject,
            EmailMessage.date_sent,
            EmailMessage.sender_email,
            EmailMessage.sender_name,
            EmailMessage.recipients_to,
            EmailMessage.body_text,
            EmailMessage.body_text_clean,
            EmailMessage.body_preview,
            EmailMessage.has_attachments,
            EmailMessage.matched_stakeholders,
            EmailMessage.matched_keywords,
            EmailMessage.content_hash,
            EmailMessage.meta,
        ]

        q = db.query(EmailMessage).options(load_only(*load_cols))

        # Match the API behavior: skip excluded/hidden messages.
        q = q.filter(build_email_visibility_filter(EmailMessage))
        q = q.filter(
            or_(
                EmailMessage.subject.is_(None), not_(EmailMessage.subject.like("IPM.%"))
            )
        )

        if project_uuid:
            q = q.filter(EmailMessage.project_id == project_uuid)
        if case_uuid:
            q = q.filter(EmailMessage.case_id == case_uuid)

        q = q.order_by(EmailMessage.date_sent.asc().nullsfirst())

        for email in q.yield_per(int(args.batch_size)):
            processed += 1
            if args.limit and processed > args.limit:
                break

            if args.dry_run:
                continue

            try:
                # Prefer canonical/clean text, then stored body, then preview.
                body = (
                    (email.body_text_clean or "")
                    or (email.body_text or "")
                    or (email.body_preview or "")
                )

                index_email_in_opensearch(
                    email_id=str(email.id),
                    case_id=(str(email.case_id) if email.case_id else None),
                    project_id=(str(email.project_id) if email.project_id else None),
                    thread_id=email.thread_id,
                    thread_group_id=email.thread_group_id,
                    message_id=email.message_id,
                    subject=email.subject or "",
                    body_text=body,
                    sender_email=email.sender_email or "",
                    sender_name=email.sender_name or "",
                    recipients=email.recipients_to or [],
                    date_sent=(
                        email.date_sent.isoformat() if email.date_sent else None
                    ),
                    has_attachments=bool(email.has_attachments),
                    matched_stakeholders=email.matched_stakeholders or [],
                    matched_keywords=email.matched_keywords or [],
                    body_text_clean=email.body_text_clean,
                    content_hash=email.content_hash,
                )
            except Exception:
                failures += 1

            if processed % 1000 == 0:
                elapsed = time.time() - start
                rate = processed / elapsed if elapsed > 0 else 0
                print(
                    f"Processed {processed:,} emails ({failures:,} failures) at {rate:,.0f}/s"
                )

        elapsed = time.time() - start
        print(
            f"Done. Processed {processed:,} emails ({failures:,} failures) in {elapsed:,.1f}s"
        )
        if args.dry_run:
            print("Dry run only; no documents were written.")

        return 0

    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
