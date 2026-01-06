#!/usr/bin/env python3
"""
Backfill body_text from body_html for emails that have empty body_text.

This script addresses the issue where emails were imported with body_html content
but body_text was left NULL because the plain text extraction failed or wasn't
properly implemented at the time of import.
"""

import os
import sys
from pathlib import Path

# Add the API app to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vericase" / "api"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import email content functions
from app.email_content import select_best_body
from app.email_normalizer import normalise


def get_database_url() -> str:
    """Get database URL from environment or use default."""
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/vericase"
    )


def backfill_body_text(batch_size: int = 100, dry_run: bool = True):
    """
    Backfill body_text from body_html for emails with NULL body_text.

    Args:
        batch_size: Number of records to process per batch
        dry_run: If True, don't commit changes
    """
    database_url = get_database_url()
    print("Connecting to database...")
    print(f"Dry run: {dry_run}")

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Count emails needing update
        count_query = text(
            """
            SELECT COUNT(*) 
            FROM email_messages 
            WHERE body_text IS NULL 
              AND body_html IS NOT NULL 
              AND LENGTH(body_html) > 0
        """
        )
        total_count = session.execute(count_query).scalar()
        print(f"Found {total_count} emails with NULL body_text and non-empty body_html")

        if total_count == 0:
            print("Nothing to do!")
            return

        # Process in batches
        offset = 0
        updated = 0
        errors = 0

        while offset < total_count:
            # Fetch batch
            batch_query = text(
                """
                SELECT id, body_html, body_text_clean
                FROM email_messages 
                WHERE body_text IS NULL 
                  AND body_html IS NOT NULL 
                  AND LENGTH(body_html) > 0
                ORDER BY id
                LIMIT :limit OFFSET :offset
            """
            )

            rows = session.execute(
                batch_query, {"limit": batch_size, "offset": offset}
            ).fetchall()

            if not rows:
                break

            for row in rows:
                email_id = row[0]
                body_html = row[1]
                existing_clean = row[2]

                try:
                    # Convert HTML to text
                    body_selection = select_best_body(
                        plain_text=None, html_body=body_html, rtf_body=None
                    )

                    body_text = body_selection.full_text or ""
                    body_text_clean = normalise(body_selection.top_text or body_text)

                    if body_text:
                        if not dry_run:
                            update_query = text(
                                """
                                UPDATE email_messages 
                                SET body_text = :body_text,
                                    body_text_clean = COALESCE(body_text_clean, :body_text_clean)
                                WHERE id = :id
                            """
                            )
                            session.execute(
                                update_query,
                                {
                                    "id": email_id,
                                    "body_text": body_text,
                                    "body_text_clean": (
                                        body_text_clean if not existing_clean else None
                                    ),
                                },
                            )
                        updated += 1

                        if updated % 100 == 0:
                            print(f"  Processed {updated} emails...")
                            if not dry_run:
                                session.commit()

                except Exception as e:
                    errors += 1
                    print(f"  Error processing email {email_id}: {e}")

            offset += batch_size

        if not dry_run:
            session.commit()

        print("\nCompleted!")
        print(f"  Updated: {updated}")
        print(f"  Errors: {errors}")
        print(f"  Dry run: {dry_run}")

        if dry_run:
            print("\nRun with --execute to apply changes")

    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Backfill body_text from body_html")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute changes (default is dry-run)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for processing (default: 100)",
    )
    args = parser.parse_args()

    backfill_body_text(batch_size=args.batch_size, dry_run=not args.execute)


if __name__ == "__main__":
    main()
