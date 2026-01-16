#!/usr/bin/env python3
"""Backfill / repair standalone email-import rows to match PST per-message extraction.

Why this exists
--------------
Standalone uploads (.eml / .msg) should look identical to PST-ingested messages in the
Correspondence UI. Early versions of email-import could store:
- bytes repr strings like ``b'\\r\\n...'`` (shows up as junk in the UI)
- inconsistent body fields (preview/canonical/full mismatch vs PST pipeline)
- offloaded bodies under the wrong threshold/format

This script repairs EmailMessage rows created via email-import by recomputing:
- body_text (full body text, PST-parity)
- body_html (original HTML when present)
- body_text_clean (canonical top-message, PST-parity)
- body_preview (first 10k of full body/html, PST-parity)
- content_hash (dedupe hash, PST-parity)
- meta normalizer/body_selection fields (best-effort parity)

Typical follow-up
-----------------
If you rely on OpenSearch search/highlights, reindex using:
  python reindex_emails_opensearch.py --project-id <uuid>

Usage examples
--------------
Repair a single email-import batch (synthetic PST container):
  python backfill_email_import_parity.py --pst-file-id <uuid>

Repair a project:
  python backfill_email_import_parity.py --project-id <uuid>

Dry-run:
  python backfill_email_import_parity.py --project-id <uuid> --dry-run
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import time
import uuid
from pathlib import Path

# Allow running as a script from the `vericase/api/` folder.
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import or_  # noqa: E402
from sqlalchemy.orm import load_only  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.email_content import decode_maybe_bytes, select_best_body  # noqa: E402
from app.email_normalizer import (  # noqa: E402
    NORMALIZER_RULESET_HASH,
    NORMALIZER_VERSION,
    build_content_hash,
    clean_body_text,
)
from app.models import EmailMessage  # noqa: E402
from app.storage import get_object, put_object  # noqa: E402


_BYTES_LITERAL_RE = re.compile(r"^b(['\"]).*\\1$", re.DOTALL)


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def _looks_like_html_markup(text: str | None) -> bool:
    if not text or not isinstance(text, str):
        return False
    s = text.lstrip()
    if not s:
        return False
    if re.match(r"(?is)^<!doctype\\s+html\\b", s):
        return True
    if re.match(r"(?is)^<\\s*(html|head|body)\\b", s):
        return True
    if re.search(
        r"<\\s*\\/?\\s*(div|span|p|br|table|tr|td|th|style|meta|link|font|center|a)\\b",
        s,
        flags=re.IGNORECASE,
    ):
        return True
    return len(re.findall(r"<\\s*\\/?\\s*[A-Za-z][A-Za-z0-9:_-]*\\b", s)) >= 8


def _decode_bytes_literal(text: str | None) -> str | None:
    """Reverse accidental str(bytes) storage: \"b'...\\r\\n...'\" -> decoded text."""
    if not text or not isinstance(text, str):
        return text
    candidate = text.strip()
    if not (candidate.startswith("b'") or candidate.startswith('b"')):
        return text
    if not _BYTES_LITERAL_RE.match(candidate):
        return text
    try:
        val = ast.literal_eval(candidate)
    except Exception:
        return text
    if isinstance(val, (bytes, bytearray)):
        return decode_maybe_bytes(bytes(val)) or ""
    return text


def _get_full_body_text(email: EmailMessage) -> str:
    """Return best-effort full body text, including offloaded content if present."""
    meta = email.meta if isinstance(email.meta, dict) else {}
    text = email.body_text or ""

    # Only fetch offloaded content when the DB body is missing.
    # (Early email-import versions offloaded *canonical* bodies but still kept full body in DB.)
    if not text and email.body_full_s3_key:
        bucket = (
            meta.get("body_offload_bucket")
            or getattr(settings, "S3_EMAIL_BODY_BUCKET", None)
            or settings.S3_BUCKET
            or settings.MINIO_BUCKET
        )
        try:
            blob = get_object(email.body_full_s3_key, bucket=bucket)
            text = blob.decode("utf-8", errors="replace")
        except Exception:
            # Keep fallback to DB-stored body_text.
            pass

    # Undo accidental bytes repr strings.
    return _decode_bytes_literal(text) or ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair email-import rows to PST-parity body extraction"
    )
    parser.add_argument("--project-id", dest="project_id", default=None)
    parser.add_argument("--case-id", dest="case_id", default=None)
    parser.add_argument("--pst-file-id", dest="pst_file_id", default=None)
    parser.add_argument(
        "--limit", type=int, default=0, help="Stop after N emails (0 = no limit)"
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write to Postgres/S3"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even when values look OK (default only fixes obvious issues)",
    )

    args = parser.parse_args()

    project_uuid = _parse_uuid(args.project_id)
    case_uuid = _parse_uuid(args.case_id)
    pst_uuid = _parse_uuid(args.pst_file_id)

    if not project_uuid and not case_uuid and not pst_uuid:
        raise SystemExit("Provide --pst-file-id or --project-id or --case-id")

    body_offload_threshold = (
        getattr(settings, "PST_BODY_OFFLOAD_THRESHOLD", 50000) or 50000
    )
    body_offload_bucket = (
        getattr(settings, "S3_EMAIL_BODY_BUCKET", None)
        or settings.S3_BUCKET
        or settings.MINIO_BUCKET
    )

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
            EmailMessage.sender_email,
            EmailMessage.sender_name,
            EmailMessage.recipients_to,
            EmailMessage.recipients_cc,
            EmailMessage.recipients_bcc,
            EmailMessage.date_sent,
            EmailMessage.body_text,
            EmailMessage.body_html,
            EmailMessage.body_text_clean,
            EmailMessage.body_preview,
            EmailMessage.body_full_s3_key,
            EmailMessage.content_hash,
            EmailMessage.meta,
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

        # Only target standalone email-import rows.
        source_field = EmailMessage.meta["source"].as_string()
        q = q.filter(source_field.in_(["eml_import", "msg_import"]))

        # Stable ordering + page by PK.
        q = q.order_by(EmailMessage.id.asc())

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
                    meta = email.meta if isinstance(email.meta, dict) else {}

                    # Quick heuristic: if nothing looks broken and not forcing, skip.
                    existing_clean = (email.body_text_clean or "").strip()
                    if (
                        not args.force
                        and existing_clean
                        and not (
                            existing_clean.startswith("b'")
                            or existing_clean.startswith('b"')
                        )
                        and not (
                            str(email.body_text or "").strip().startswith("b'")
                            or str(email.body_text or "").strip().startswith('b"')
                        )
                    ):
                        skipped += 1
                        continue

                    full_text_in = _get_full_body_text(email)
                    html_in = _decode_bytes_literal(email.body_html) or email.body_html
                    html_in = str(html_in) if html_in is not None else None

                    plain_in = full_text_in or None

                    # If HTML is missing but the text clearly looks like HTML markup, treat it as HTML.
                    if not html_in and plain_in and _looks_like_html_markup(plain_in):
                        html_in = plain_in
                        plain_in = None

                    selection = select_best_body(
                        plain_text=plain_in,
                        html_body=html_in,
                        rtf_body=None,
                    )

                    body_html_content = html_in or None
                    full_body_text = (selection.full_text or "").strip()

                    canonical_body = (selection.top_text or "").strip()
                    if (
                        canonical_body
                        and len(canonical_body) < 20
                        and len(full_body_text) <= 200
                    ):
                        canonical_body = full_body_text
                    elif (
                        not canonical_body
                        and full_body_text
                        and len(full_body_text) > 200
                    ):
                        canonical_body = full_body_text

                    cleaned = clean_body_text(canonical_body)
                    if cleaned is not None:
                        canonical_body = cleaned

                    canonical_body = (
                        re.sub(r"\\s+", " ", canonical_body).strip()
                        if canonical_body
                        else ""
                    )

                    body_preview_source = full_body_text or body_html_content or ""
                    body_preview = (
                        body_preview_source[:10000] if body_preview_source else None
                    )

                    # Offload parity: only offload when above the PST threshold.
                    new_body_full_s3_key = None
                    store_body_text = full_body_text
                    if (
                        full_body_text
                        and len(full_body_text) > int(body_offload_threshold)
                        and body_offload_bucket
                    ):
                        entity_folder = (
                            f"case_{email.case_id}"
                            if email.case_id
                            else (
                                f"project_{email.project_id}"
                                if email.project_id
                                else "no_entity"
                            )
                        )
                        dt_part = (
                            email.date_sent.isoformat()
                            if email.date_sent
                            else "no_date"
                        )
                        new_body_full_s3_key = f"email-bodies/{entity_folder}/{dt_part}_{uuid.uuid4().hex}.txt"

                        if not args.dry_run:
                            put_object(
                                new_body_full_s3_key,
                                full_body_text.encode("utf-8"),
                                "text/plain; charset=utf-8",
                                bucket=body_offload_bucket,
                            )
                        store_body_text = ""
                    else:
                        # If the row previously used an offload key under the old (too-low) threshold,
                        # drop it for parity (leave the object in S3; it becomes unreferenced).
                        new_body_full_s3_key = None

                    content_hash = build_content_hash(
                        canonical_body or None,
                        email.sender_email,
                        email.sender_name,
                        email.recipients_to,
                        email.subject,
                        email.date_sent,
                    )

                    # Decide if anything would change.
                    changed = False
                    if (email.body_text or "") != (store_body_text or ""):
                        changed = True
                    if (email.body_html or "") != (body_html_content or ""):
                        changed = True
                    if (email.body_text_clean or "") != (canonical_body or ""):
                        changed = True
                    if (email.body_preview or "") != (body_preview or ""):
                        changed = True
                    if (email.content_hash or "") != (content_hash or ""):
                        changed = True
                    if (email.body_full_s3_key or "") != (new_body_full_s3_key or ""):
                        changed = True

                    if not changed:
                        skipped += 1
                        continue

                    if args.dry_run:
                        updated += 1
                        continue

                    # Persist updates.
                    email.body_text = store_body_text or None
                    email.body_html = body_html_content
                    email.body_text_clean = canonical_body or None
                    email.body_preview = body_preview
                    email.body_full_s3_key = new_body_full_s3_key
                    email.content_hash = content_hash

                    # Best-effort meta parity.
                    meta = meta if isinstance(meta, dict) else {}
                    meta.update(
                        {
                            "normalizer_version": NORMALIZER_VERSION,
                            "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
                            "body_source": selection.selected_source,
                            "body_selection": selection.diagnostics,
                            "body_quoted_len": len(selection.quoted_text or ""),
                            "body_signature_len": len(selection.signature_text or ""),
                            "body_offloaded": bool(new_body_full_s3_key),
                            "body_offload_bucket": (
                                body_offload_bucket if new_body_full_s3_key else None
                            ),
                            "body_offload_key": new_body_full_s3_key,
                            "body_full_s3_key": new_body_full_s3_key,
                        }
                    )
                    email.meta = meta

                    updated += 1

                except Exception:
                    failures += 1
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
            print("Dry run only; no rows/objects were written.")

        return 0

    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
