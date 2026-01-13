#!/usr/bin/env python3
"""Backfill / repair `EmailMessage.body_text_clean` for PST-imported emails.

When to use this
---------------
If historic PST imports produced bad `body_text_clean` (e.g. RTF font-table artifacts like
"Times New Roman; Symbol;"), the UI and OpenSearch may display/index junk even when
`body_html` is present.

This script recomputes `body_text_clean` from existing stored fields (prefer HTML, then text)
and updates rows in Postgres.

Important limitations
---------------------
- If an email was *RTF-only* and you did not store the original RTF body, this script cannot
  reconstruct the true content (you must reprocess the PST to re-extract the raw message).

Typical follow-up
-----------------
After updating Postgres, reindex OpenSearch using `reindex_emails_opensearch.py`.

Usage examples
--------------
Repair a single PST file:
  python backfill_email_body_clean.py --pst-file-id <uuid>

Repair a project:
  python backfill_email_body_clean.py --project-id <uuid>

Dry-run (no writes):
  python backfill_email_body_clean.py --pst-file-id <uuid> --dry-run

Limit for testing:
  python backfill_email_body_clean.py --pst-file-id <uuid> --limit 1000
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import uuid
from pathlib import Path

# Allow running as a script from the `vericase/api/` folder.
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import or_
from sqlalchemy.orm import load_only

from app.db import SessionLocal
from app.email_content import select_best_body
from app.email_normalizer import clean_body_text
from app.models import EmailMessage


_FONT_WORDS = (
    "times new roman",
    "calibri",
    "cambria",
    "arial",
    "helvetica",
    "courier new",
    "wingdings",
    "symbol",
)


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def looks_like_rtf_font_table_junk(text: str | None) -> bool:
    """Heuristic: detect classic RTF fallback artifacts stored as body text."""
    if not text:
        return False

    t = (text or "").strip()
    if not t:
        return False

    tl = t.lower()

    # The most common visible symptom from naive RTF stripping: font names + semicolons.
    font_hits = sum(1 for w in _FONT_WORDS if w in tl)
    if font_hits >= 2 and t.count(";") >= 1 and len(t) <= 800:
        return True

    # Another symptom shown in real PSTs: Exchange conversion headers drifting into body.
    if "microsoft exchange server" in tl and len(t) <= 1500:
        return True

    # Heuristic: mostly short tokens, lots of semicolons, little sentence structure.
    if len(t) <= 400 and t.count(";") >= 2:
        # If it doesn't look like a sentence (few spaces), it's likely junk.
        if t.count(" ") <= 8:
            return True

    return False


def compute_new_body_text_clean(email: EmailMessage) -> str | None:
    """Recompute a canonical clean body from stored fields."""
    selection = select_best_body(
        plain_text=email.body_text or None,
        html_body=email.body_html or None,
        rtf_body=None,
    )

    canonical = (selection.top_text or "").strip()
    full_text = (selection.full_text or "").strip()

    chosen = canonical
    # Mirror ingestion guardrails: avoid empty/too-short top_text.
    if chosen and len(chosen) < 20 and len(full_text) <= 200:
        chosen = full_text
    elif not chosen and full_text and len(full_text) > 200:
        chosen = full_text

    if not chosen:
        return None

    cleaned = clean_body_text(chosen)
    cleaned = cleaned if cleaned is not None else chosen

    # Keep consistent with ingestion: canonical body is normalized for dedupe/search.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return None

    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill EmailMessage.body_text_clean from stored body_html/body_text"
    )
    parser.add_argument("--project-id", dest="project_id", default=None)
    parser.add_argument("--case-id", dest="case_id", default=None)
    parser.add_argument("--pst-file-id", dest="pst_file_id", default=None)
    parser.add_argument(
        "--limit", type=int, default=0, help="Stop after N emails (0 = no limit)"
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write to Postgres"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even when body_text_clean is present and not detected as junk",
    )

    args = parser.parse_args()

    project_uuid = _parse_uuid(args.project_id)
    case_uuid = _parse_uuid(args.case_id)
    pst_uuid = _parse_uuid(args.pst_file_id)

    if not project_uuid and not case_uuid and not pst_uuid:
        raise SystemExit("Provide --pst-file-id or --project-id or --case-id")

    db = SessionLocal()
    start = time.time()

    scanned = 0
    updated = 0
    skipped = 0
    failures = 0

    try:
        load_cols = [
            EmailMessage.id,
            EmailMessage.pst_file_id,
            EmailMessage.project_id,
            EmailMessage.case_id,
            EmailMessage.subject,
            EmailMessage.body_text,
            EmailMessage.body_html,
            EmailMessage.body_text_clean,
        ]

        q = db.query(EmailMessage).options(load_only(*load_cols))

        # Avoid system items.
        q = q.filter(
            or_(EmailMessage.subject.is_(None), ~EmailMessage.subject.like("IPM.%"))
        )

        if project_uuid:
            q = q.filter(EmailMessage.project_id == project_uuid)
        if case_uuid:
            q = q.filter(EmailMessage.case_id == case_uuid)
        if pst_uuid:
            q = q.filter(EmailMessage.pst_file_id == pst_uuid)

        # Prefer deterministic ordering.
        q = q.order_by(EmailMessage.id.asc())

        # IMPORTANT: avoid long-lived server-side cursors (yield_per) for large backfills.
        # In some production environments (e.g. proxies / idle timeouts), streaming cursors
        # can become invalid mid-iteration (psycopg2: "named cursor isn't valid anymore").
        # We page by primary key instead.
        last_id = None
        batch_size = max(1, int(args.batch_size))

        while True:
            page = q
            if last_id is not None:
                page = page.filter(EmailMessage.id > last_id)
            page = page.limit(batch_size).all()
            if not page:
                break

            for email in page:
                scanned += 1
                if args.limit and scanned > args.limit:
                    page = []
                    break

                try:
                    old = email.body_text_clean
                    old_is_junk = looks_like_rtf_font_table_junk(old)

                    if not args.force and old and not old_is_junk:
                        skipped += 1
                        continue

                    # If we have neither HTML nor text, there is nothing we can recover.
                    if not (email.body_html or email.body_text):
                        skipped += 1
                        continue

                    new = compute_new_body_text_clean(email)
                    if not new:
                        skipped += 1
                        continue

                    # If we computed the same thing (or close enough), skip.
                    if (old or "").strip() == new.strip():
                        skipped += 1
                        continue

                    if args.dry_run:
                        updated += 1
                        continue

                    email.body_text_clean = new
                    updated += 1

                except Exception:
                    failures += 1
                    # Ensure the session isn't left in a failed state.
                    db.rollback()

                if scanned % 2000 == 0:
                    elapsed = time.time() - start
                    rate = scanned / elapsed if elapsed > 0 else 0
                    print(
                        f"Scanned {scanned:,} | updated {updated:,} | skipped {skipped:,} | failures {failures:,} | {rate:,.0f}/s"
                    )

            if not args.dry_run:
                db.commit()

            if page:
                last_id = page[-1].id
            else:
                break

        if not args.dry_run:
            db.commit()

        elapsed = time.time() - start
        print(
            f"Done. Scanned {scanned:,}; updated {updated:,}; skipped {skipped:,}; failures {failures:,} in {elapsed:,.1f}s"
        )
        if args.dry_run:
            print("Dry run only; no rows were written.")

        return 0

    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
