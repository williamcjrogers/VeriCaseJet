#!/usr/bin/env python3
"""
Direct database script to clear pending and failed PST files.
Use this if the API is not accessible.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text

# Get database URL from environment or use default
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://vericase:vericase@localhost:5432/vericase"
)


def main():
    """Clear pending and failed PST files directly from database"""

    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(description="Clear pending and failed PST files")
    parser.add_argument("--project-id", help="Project ID to filter (optional)")
    parser.add_argument("--case-id", help="Case ID to filter (optional)")
    parser.add_argument(
        "--stuck-hours",
        type=float,
        default=1.0,
        help="Hours after which processing/queued is considered stuck (default: 1)",
    )
    parser.add_argument(
        "--status",
        choices=["pending", "failed", "queued", "processing", "all"],
        default="all",
        help="Filter by status (default: all stuck/failed)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually delete (default is dry-run)"
    )
    parser.add_argument("--database-url", help="Database connection string")

    args = parser.parse_args()

    if args.database_url:
        global DATABASE_URL
        DATABASE_URL = args.database_url

    print("=== VeriCase PST Cleanup (Direct DB) ===\n")

    # Create database connection
    try:
        engine = create_engine(DATABASE_URL)
        conn = engine.connect()
        print("✓ Connected to database\n")
    except Exception as e:
        print(f"✗ Failed to connect to database: {e}")
        sys.exit(1)

    try:
        # Build the query
        conditions = []
        params = {}

        if args.project_id:
            conditions.append("project_id = :project_id")
            params["project_id"] = args.project_id
            print(f"Filter: Project ID = {args.project_id}")

        if args.case_id:
            conditions.append("case_id = :case_id")
            params["case_id"] = args.case_id
            print(f"Filter: Case ID = {args.case_id}")

        # Status filtering
        if args.status == "pending":
            conditions.append("processing_status = 'pending'")
        elif args.status == "failed":
            conditions.append("processing_status = 'failed'")
        elif args.status == "queued":
            conditions.append("processing_status = 'queued'")
        elif args.status == "processing":
            conditions.append("processing_status = 'processing'")
        else:  # 'all' - includes pending, failed, and stuck
            # Get stuck threshold
            stuck_time = datetime.now(timezone.utc) - timedelta(hours=args.stuck_hours)
            params["stuck_time"] = stuck_time

            conditions.append(
                "(processing_status IN ('pending', 'failed') OR "
                "(processing_status IN ('processing', 'queued') AND "
                "COALESCE(processing_started_at, uploaded_at) < :stuck_time))"
            )

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # First, get the PST files that match
        query = f"""
            SELECT 
                id,
                filename,
                processing_status,
                uploaded_at,
                processing_started_at,
                total_emails,
                processed_emails,
                error_message
            FROM pst_files
            WHERE {where_clause}
            ORDER BY uploaded_at DESC
        """

        result = conn.execute(text(query), params)
        pst_files = result.fetchall()

        if not pst_files:
            print("\n✓ No PST files found matching criteria")
            return

        print(f"\nFound {len(pst_files)} PST file(s) to clean up:\n")

        # Display details
        total_emails = 0
        pst_ids = []

        for pst in pst_files:
            pst_ids.append(str(pst.id))
            total_emails += pst.total_emails or 0

            print(f"  [{pst.processing_status}] {pst.filename}")
            print(f"    ID: {pst.id}")
            print(f"    Uploaded: {pst.uploaded_at}")
            if pst.processing_started_at:
                print(f"    Started: {pst.processing_started_at}")
            print(f"    Emails: {pst.processed_emails or 0}/{pst.total_emails or 0}")
            if pst.error_message:
                print(f"    Error: {pst.error_message[:100]}")
            print()

        # Count related records
        if pst_ids:
            # Count emails
            email_count_query = """
                SELECT COUNT(*) as count
                FROM email_messages
                WHERE pst_file_id::text = ANY(:pst_ids)
            """
            email_result = conn.execute(text(email_count_query), {"pst_ids": pst_ids})
            email_count = email_result.scalar()

            # Count attachments
            attachment_count_query = """
                SELECT COUNT(*) as count
                FROM email_attachments
                WHERE email_message_id IN (
                    SELECT id FROM email_messages 
                    WHERE pst_file_id::text = ANY(:pst_ids)
                )
            """
            attachment_result = conn.execute(
                text(attachment_count_query), {"pst_ids": pst_ids}
            )
            attachment_count = attachment_result.scalar()

            # Count evidence items
            evidence_count_query = """
                SELECT COUNT(*) as count
                FROM evidence_items
                WHERE source_email_id IN (
                    SELECT id FROM email_messages 
                    WHERE pst_file_id::text = ANY(:pst_ids)
                )
            """
            evidence_result = conn.execute(
                text(evidence_count_query), {"pst_ids": pst_ids}
            )
            evidence_count = evidence_result.scalar()

            print("Summary:")
            print(f"  - PST Files: {len(pst_files)}")
            print(f"  - Email Messages: {email_count}")
            print(f"  - Email Attachments: {attachment_count}")
            print(f"  - Evidence Items: {evidence_count}")
            print()

        if not args.apply:
            print("⚠️  This is a DRY-RUN (preview only)")
            print("   Add --apply to actually delete these records")
            print("   Note: This will NOT delete S3 objects")
            return

        # Actually delete
        print("⚠️  DELETING records...")

        trans = conn.begin()
        try:
            # Delete in order: evidence_items -> email_attachments -> email_messages -> pst_files

            # Delete evidence items
            if evidence_count > 0:
                conn.execute(
                    text(
                        """
                    DELETE FROM evidence_items
                    WHERE source_email_id IN (
                        SELECT id FROM email_messages 
                        WHERE pst_file_id::text = ANY(:pst_ids)
                    )
                """
                    ),
                    {"pst_ids": pst_ids},
                )
                print(f"  ✓ Deleted {evidence_count} evidence items")

            # Delete email attachments
            if attachment_count > 0:
                conn.execute(
                    text(
                        """
                    DELETE FROM email_attachments
                    WHERE email_message_id IN (
                        SELECT id FROM email_messages 
                        WHERE pst_file_id::text = ANY(:pst_ids)
                    )
                """
                    ),
                    {"pst_ids": pst_ids},
                )
                print(f"  ✓ Deleted {attachment_count} email attachments")

            # Delete email messages
            if email_count > 0:
                conn.execute(
                    text(
                        """
                    DELETE FROM email_messages
                    WHERE pst_file_id::text = ANY(:pst_ids)
                """
                    ),
                    {"pst_ids": pst_ids},
                )
                print(f"  ✓ Deleted {email_count} email messages")

            # Delete PST files
            conn.execute(
                text(
                    """
                DELETE FROM pst_files
                WHERE id::text = ANY(:pst_ids)
            """
                ),
                {"pst_ids": pst_ids},
            )
            print(f"  ✓ Deleted {len(pst_files)} PST files")

            trans.commit()
            print("\n✓ Cleanup completed successfully!")
            print("  Note: S3 objects were NOT deleted (only database records)")

        except Exception as e:
            trans.rollback()
            print(f"\n✗ Error during deletion: {e}")
            sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
