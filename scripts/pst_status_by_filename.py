"""
Lookup PST processing status + error details by filename.

Why this exists:
- The UI historically only showed "processed of total" which is often "0 of 0" when
  PST pre-count is disabled and/or a job fails early.
- The real failure reason is stored in `pst_files.error_message`.

Usage (from repo root):
  python scripts/pst_status_by_filename.py --contains "Mark.Mitchell@unitedliving.co.uk.001.pst"
  python scripts/pst_status_by_filename.py --exact "Mark.Mitchell@unitedliving.co.uk.001.pst"
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from urllib.parse import urlparse


def _load_database_url() -> str:
    """
    Prefer env var override, otherwise use the app settings.

    We mimic the container layout by adding `vericase/api` to sys.path so imports
    like `from app.config import settings` work consistently.
    """

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    api_root = os.path.join(repo_root, "vericase", "api")
    if api_root not in sys.path:
        sys.path.insert(0, api_root)

    try:
        from app.config import settings  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            f"Could not import app settings to locate DATABASE_URL ({exc}). "
            "Set DATABASE_URL env var and retry."
        )

    db_url = getattr(settings, "DATABASE_URL", None)
    if not db_url:
        raise SystemExit(
            "DATABASE_URL not found in settings; set DATABASE_URL env var."
        )
    return str(db_url)


def _print_row(row: dict[str, Any]) -> None:
    print("-" * 80)
    print(f"filename:               {row.get('filename')}")
    print(f"id:                     {row.get('id')}")
    print(f"processing_status:      {row.get('processing_status')}")
    print(f"file_size_bytes:        {row.get('file_size_bytes')}")
    print(f"processed_emails:       {row.get('processed_emails')}")
    print(f"total_emails:           {row.get('total_emails')}")
    print(f"uploaded_at:            {row.get('uploaded_at')}")
    print(f"processing_started_at:  {row.get('processing_started_at')}")
    print(f"processing_completed_at:{row.get('processing_completed_at')}")
    print(f"project_id:             {row.get('project_id')}")
    print(f"case_id:                {row.get('case_id')}")
    print(f"s3_bucket:              {row.get('s3_bucket')}")
    print(f"s3_key:                 {row.get('s3_key')}")
    err = row.get("error_message")
    print("error_message:")
    print(err if err else "(none)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Lookup PST status by filename")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exact", help="Exact filename match")
    group.add_argument("--contains", help="Substring match (case-insensitive)")
    parser.add_argument(
        "--limit", type=int, default=10, help="Max rows to return (default 10)"
    )
    args = parser.parse_args()

    db_url = _load_database_url()
    engine = create_engine(db_url, pool_pre_ping=True)

    if args.exact:
        sql = text(
            """
            SELECT
              id::text,
              filename,
              processing_status,
              file_size_bytes,
              processed_emails,
              total_emails,
              uploaded_at,
              processing_started_at,
              processing_completed_at,
              project_id::text,
              case_id::text,
              s3_bucket,
              s3_key,
              error_message
            FROM pst_files
            WHERE filename = :filename
            ORDER BY uploaded_at DESC NULLS LAST
            LIMIT :limit
            """
        )
        params = {"filename": args.exact, "limit": int(args.limit)}
    else:
        sql = text(
            """
            SELECT
              id::text,
              filename,
              processing_status,
              file_size_bytes,
              processed_emails,
              total_emails,
              uploaded_at,
              processing_started_at,
              processing_completed_at,
              project_id::text,
              case_id::text,
              s3_bucket,
              s3_key,
              error_message
            FROM pst_files
            WHERE lower(filename) LIKE lower(:pattern)
            ORDER BY uploaded_at DESC NULLS LAST
            LIMIT :limit
            """
        )
        params = {"pattern": f"%{args.contains}%", "limit": int(args.limit)}

    try:
        with engine.begin() as conn:
            rows = conn.execute(sql, params).mappings().all()
    except OperationalError as exc:
        parsed = urlparse(db_url)
        host = parsed.hostname or "(unknown)"
        print("Database connection failed.")
        print(f"- host: {host}")
        print(f"- error: {exc.orig if hasattr(exc, 'orig') else exc}")
        print("")
        if host in {"postgres", "db"}:
            print("It looks like you're using a Docker-internal hostname.")
            print("Try ONE of the following:")
            print("- Run this script inside the container (recommended):")
            print(
                '  docker compose exec api python scripts/pst_status_by_filename.py --contains "<filename>"'
            )
            print("- Or override DATABASE_URL for local access (example):")
            print(
                '  $env:DATABASE_URL="postgresql+psycopg2://USER:PASS@localhost:5432/DBNAME"'
            )
            print('  python scripts/pst_status_by_filename.py --contains "<filename>"')
        else:
            print("Check DATABASE_URL, VPN/network access, and credentials.")
        raise SystemExit(2)

    if not rows:
        print("No matching PST rows found.")
        return

    for r in rows:
        _print_row(dict(r))


if __name__ == "__main__":
    main()
