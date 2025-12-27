#!/usr/bin/env python3
"""
Manual script to link emails to programme activities.

This runs the linking logic synchronously (without needing Celery).
Use this after uploading a programme to populate the correspondence tab with
programme activity, as-built activity, delay days, etc.

Usage:
    python scripts/link_programme_emails.py --project-id <uuid>
    python scripts/link_programme_emails.py --case-id <uuid>
    python scripts/link_programme_emails.py --project-id <uuid> --overwrite
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "vericase" / "api"))

from app.db import SessionLocal
from app.programme_linking import link_emails_to_programme_activities


def main():
    parser = argparse.ArgumentParser(
        description="Link emails to programme activities (populates correspondence tab)"
    )
    parser.add_argument(
        "--project-id", type=str, help="Project UUID to link emails for"
    )
    parser.add_argument("--case-id", type=str, help="Case UUID to link emails for")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing activity links (default: only fill missing)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for processing (default: 500)",
    )

    args = parser.parse_args()

    if not args.project_id and not args.case_id:
        print("ERROR: Must provide either --project-id or --case-id")
        parser.print_help()
        sys.exit(1)

    print("=" * 60)
    print("Programme-to-Email Linking")
    print("=" * 60)
    print(f"Project ID: {args.project_id or 'N/A'}")
    print(f"Case ID: {args.case_id or 'N/A'}")
    print(f"Overwrite existing: {args.overwrite}")
    print(f"Batch size: {args.batch_size}")
    print("-" * 60)

    db = SessionLocal()

    try:

        def progress_callback(done: int, total: int):
            if total > 0:
                percent = int((done / total) * 100)
                print(f"  Progress: {done}/{total} ({percent}%)", end="\r")

        print("Starting linking process...")

        result = link_emails_to_programme_activities(
            db=db,
            project_id=args.project_id,
            case_id=args.case_id,
            overwrite_existing=args.overwrite,
            batch_size=args.batch_size,
            progress_cb=progress_callback,
        )

        print("\n" + "-" * 60)
        print("RESULT:")
        print("-" * 60)

        for key, value in result.items():
            print(f"  {key}: {value}")

        if result.get("status") == "completed":
            print("\n✅ Linking completed successfully!")
            print(
                f"   Updated {result.get('updated', 0)} email(s) with programme activity data."
            )
            print("\n   Refresh the Correspondence tab to see the populated columns:")
            print("   - Programme Activity (as planned)")
            print("   - Planned Finish Date")
            print("   - As-Built Activity")
            print("   - As-Built Finish Date")
            print("   - Delay (days)")
        elif result.get("status") == "skipped":
            print(
                f"\n⚠️  Linking skipped: {result.get('reason', 'No programmes available')}"
            )
            print(
                "\n   Make sure you have uploaded at least one programme with activities."
            )
        else:
            print(f"\n❌ Linking failed: {result.get('error', 'Unknown error')}")

    except Exception as e:
        print(f"\n❌ Error during linking: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
