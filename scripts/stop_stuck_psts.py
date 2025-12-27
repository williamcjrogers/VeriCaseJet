"""Stop all failed or stuck PST processing tasks

This script identifies PST files that are:
1. Already marked as 'failed'
2. Stuck in 'processing' or 'queued' status for too long
3. Have been processing for an unreasonable amount of time

It then updates their status to 'failed' to prevent further processing attempts.

Usage:
    # Dry run (see what would be stopped)
    python scripts/stop_stuck_psts.py --dry-run

    # Actually stop them
    python scripts/stop_stuck_psts.py --apply

    # Custom stuck threshold (default 2 hours)
    python scripts/stop_stuck_psts.py --apply --stuck-hours 1
"""

import argparse
from datetime import datetime, timedelta, timezone
import os
import sys

# Ensure repo root is on sys.path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main():
    parser = argparse.ArgumentParser(
        description="Stop all failed or stuck PST processing tasks"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually apply changes (default is dry-run)",
    )
    parser.add_argument(
        "--stuck-hours",
        type=float,
        default=2.0,
        help="Hours after which a processing PST is considered stuck (default: 2)",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="Optional: only stop PSTs for a specific project",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        default=None,
        help="Optional: only stop PSTs for a specific case",
    )

    args = parser.parse_args()

    from vericase.api.app.db import SessionLocal
    from vericase.api.app.models import PSTFile
    import uuid

    db = SessionLocal()
    try:
        # Build query
        query = db.query(PSTFile)

        if args.project_id:
            query = query.filter(PSTFile.project_id == uuid.UUID(args.project_id))
        if args.case_id:
            query = query.filter(PSTFile.case_id == uuid.UUID(args.case_id))

        # Get all PST files
        all_psts = query.all()

        # Calculate stuck threshold
        now = datetime.now(timezone.utc)
        stuck_threshold = timedelta(hours=args.stuck_hours)

        # Identify PSTs to stop
        psts_to_stop = []

        for pst in all_psts:
            status = pst.processing_status or "pending"

            # Already failed - include for reporting
            if status == "failed":
                psts_to_stop.append((pst, "already_failed"))
                continue

            # Check if stuck in processing or queued
            if status in ("processing", "queued"):
                # Determine reference time
                ref_time = None
                if pst.processing_started_at:
                    # Has timezone info?
                    if pst.processing_started_at.tzinfo is None:
                        ref_time = pst.processing_started_at.replace(
                            tzinfo=timezone.utc
                        )
                    else:
                        ref_time = pst.processing_started_at
                elif pst.uploaded_at:
                    if pst.uploaded_at.tzinfo is None:
                        ref_time = pst.uploaded_at.replace(tzinfo=timezone.utc)
                    else:
                        ref_time = pst.uploaded_at

                # Check if stuck
                if ref_time is None or (now - ref_time) > stuck_threshold:
                    psts_to_stop.append((pst, "stuck"))

        # Report findings
        print("\n" + "=" * 80)
        print("PST PROCESSING STOP REPORT")
        print("=" * 80)
        print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        print(f"Stuck threshold: {args.stuck_hours} hours")
        print(f"Total PSTs found: {len(all_psts)}")
        print(f"PSTs to stop: {len(psts_to_stop)}")
        print("=" * 80)

        if not psts_to_stop:
            print("\n✓ No stuck or failed PSTs found!")
            return 0

        # Show details
        stopped_count = 0
        already_failed_count = 0

        for pst, reason in psts_to_stop:
            status = pst.processing_status or "pending"

            print(f"\n{'─' * 80}")
            print(f"PST ID: {pst.id}")
            print(f"Filename: {pst.filename}")
            print(f"Status: {status}")
            print(f"Reason: {reason}")
            print(f"Uploaded: {pst.uploaded_at}")
            print(f"Started: {pst.processing_started_at}")
            print(f"Completed: {pst.processing_completed_at}")
            print(f"Total emails: {pst.total_emails}")
            print(f"Processed emails: {pst.processed_emails}")
            if pst.error_message:
                print(f"Error: {pst.error_message[:200]}")

            # Update if applying
            if args.apply:
                if reason == "already_failed":
                    already_failed_count += 1
                    print("  → Already marked as failed, no change needed")
                else:
                    # Stop the PST
                    pst.processing_status = "failed"

                    # Add/update error message
                    stop_message = f"Stopped by admin at {now.isoformat()} - stuck in '{status}' status for >{args.stuck_hours}h"
                    if pst.error_message:
                        pst.error_message = f"{pst.error_message}\n{stop_message}"
                    else:
                        pst.error_message = stop_message

                    # Set completion time
                    if not pst.processing_completed_at:
                        pst.processing_completed_at = now.replace(tzinfo=None)

                    stopped_count += 1
                    print("  → ✓ Stopped and marked as failed")

        # Commit if applying
        if args.apply:
            db.commit()
            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            print(f"✓ Stopped: {stopped_count}")
            print(f"  Already failed: {already_failed_count}")
            print(f"  Total: {len(psts_to_stop)}")
            print("\n✓ Changes committed to database")
        else:
            print("\n" + "=" * 80)
            print("DRY-RUN COMPLETE")
            print("=" * 80)
            print(
                f"Would stop: {len([p for p in psts_to_stop if p[1] != 'already_failed'])}"
            )
            print(
                f"Already failed: {len([p for p in psts_to_stop if p[1] == 'already_failed'])}"
            )
            print("\nRe-run with --apply to actually stop these PSTs")

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
