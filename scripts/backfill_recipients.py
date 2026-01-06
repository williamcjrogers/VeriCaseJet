#!/usr/bin/env python3
"""
Backfill recipients_to, recipients_cc, recipients_bcc columns from email metadata.

This script finds emails where recipient arrays are empty but metadata contains
recipients_display information, then parses and populates the array columns.

Usage:
    python scripts/backfill_recipients.py [--dry-run] [--batch-size 1000] [--limit 10000]

Options:
    --dry-run      Preview changes without writing to database
    --batch-size   Number of records to update per batch (default: 500)
    --limit        Maximum number of records to process (default: no limit)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from email.utils import getaddresses, parseaddr
from pathlib import Path
from typing import Any

# Add the app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "vericase" / "api"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def parse_recipient_string(raw_string: str | None) -> list[str]:
    """
    Parse a raw recipient string into a list of individual email addresses.

    Handles formats like:
    - "John Doe <john@example.com>, Jane Smith <jane@example.com>"
    - "john@example.com; jane@example.com"
    - "John Doe <john@example.com>"
    - "john@example.com"
    - "'Display Name' <email@domain.com>"
    """
    if not raw_string or not raw_string.strip():
        return []

    recipients: list[str] = []

    # Clean up the string
    cleaned = raw_string.strip()

    # Try standard email parsing first (handles RFC 2822 format)
    try:
        # getaddresses handles comma-separated lists
        parsed = getaddresses([cleaned])
        for name, email in parsed:
            if email:
                # Format as "Name <email>" or just "email"
                if name:
                    recipients.append(f"{name} <{email}>")
                else:
                    recipients.append(email)
    except Exception:
        pass

    # If standard parsing didn't work, try manual splitting
    if not recipients:
        # Split by common delimiters
        for delimiter in [";", ","]:
            if delimiter in cleaned:
                parts = cleaned.split(delimiter)
                for part in parts:
                    part = part.strip()
                    if part:
                        # Try to extract email from part
                        name, email = parseaddr(part)
                        if email:
                            if name:
                                recipients.append(f"{name} <{email}>")
                            else:
                                recipients.append(email)
                        elif "@" in part:
                            # Fallback: just use the part if it looks like an email
                            recipients.append(part)
                break

        # If still no recipients and string contains @, use as-is
        if not recipients and "@" in cleaned:
            # Try to extract email pattern
            email_pattern = r"[\w\.-]+@[\w\.-]+\.\w+"
            matches = re.findall(email_pattern, cleaned)
            recipients.extend(matches)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_recipients: list[str] = []
    for r in recipients:
        r_lower = r.lower()
        if r_lower not in seen:
            seen.add(r_lower)
            unique_recipients.append(r)

    return unique_recipients


def get_database_url() -> str:
    """Get database URL from environment or use default."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://vericase:vericase@localhost:5432/vericase",
    )


def count_emails_to_update(session: Any) -> dict[str, int]:
    """Count emails that need recipient backfill."""
    counts = {}

    for field in ["to", "cc", "bcc"]:
        query = text(
            f"""
            SELECT COUNT(*) FROM email_messages
            WHERE (recipients_{field} IS NULL OR recipients_{field} = '{{}}')
            AND metadata->'recipients_display'->>'{field}' IS NOT NULL
            AND metadata->'recipients_display'->>'{field}' != ''
        """
        )
        result = session.execute(query)
        counts[field] = result.scalar() or 0

    # Also count total emails with any empty recipients but metadata available
    query = text(
        """
        SELECT COUNT(*) FROM email_messages
        WHERE (
            (recipients_to IS NULL OR recipients_to = '{}')
            OR (recipients_cc IS NULL OR recipients_cc = '{}')
            OR (recipients_bcc IS NULL OR recipients_bcc = '{}')
        )
        AND metadata->'recipients_display' IS NOT NULL
    """
    )
    result = session.execute(query)
    counts["total_with_metadata"] = result.scalar() or 0

    return counts


def fetch_emails_batch(
    session: Any, offset: int, batch_size: int
) -> list[dict[str, Any]]:
    """Fetch a batch of emails that need recipient backfill."""
    query = text(
        """
        SELECT 
            id,
            metadata->'recipients_display' as recipients_display,
            recipients_to,
            recipients_cc,
            recipients_bcc
        FROM email_messages
        WHERE (
            ((recipients_to IS NULL OR recipients_to = '{}')
             AND metadata->'recipients_display'->>'to' IS NOT NULL
             AND metadata->'recipients_display'->>'to' != '')
            OR
            ((recipients_cc IS NULL OR recipients_cc = '{}')
             AND metadata->'recipients_display'->>'cc' IS NOT NULL
             AND metadata->'recipients_display'->>'cc' != '')
            OR
            ((recipients_bcc IS NULL OR recipients_bcc = '{}')
             AND metadata->'recipients_display'->>'bcc' IS NOT NULL
             AND metadata->'recipients_display'->>'bcc' != '')
        )
        ORDER BY id
        LIMIT :batch_size OFFSET :offset
    """
    )

    result = session.execute(query, {"batch_size": batch_size, "offset": offset})
    rows = result.fetchall()

    return [
        {
            "id": row.id,
            "recipients_display": row.recipients_display or {},
            "recipients_to": row.recipients_to,
            "recipients_cc": row.recipients_cc,
            "recipients_bcc": row.recipients_bcc,
        }
        for row in rows
    ]


def update_recipients(
    session: Any,
    email_id: str,
    recipients_to: list[str] | None,
    recipients_cc: list[str] | None,
    recipients_bcc: list[str] | None,
) -> None:
    """Update recipient columns for an email."""
    # Build dynamic update based on what needs updating
    updates = []
    params: dict[str, Any] = {"id": email_id}

    if recipients_to is not None:
        updates.append("recipients_to = :recipients_to")
        params["recipients_to"] = recipients_to

    if recipients_cc is not None:
        updates.append("recipients_cc = :recipients_cc")
        params["recipients_cc"] = recipients_cc

    if recipients_bcc is not None:
        updates.append("recipients_bcc = :recipients_bcc")
        params["recipients_bcc"] = recipients_bcc

    if not updates:
        return

    query = text(
        f"""
        UPDATE email_messages
        SET {', '.join(updates)}
        WHERE id = :id
    """
    )

    session.execute(query, params)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill email recipients from metadata"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of records to process per batch (default: 500)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to process (default: no limit)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed progress for each record",
    )
    args = parser.parse_args()

    database_url = get_database_url()
    print("Connecting to database...")
    print(f"  URL: {database_url.split('@')[1] if '@' in database_url else 'local'}")

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Count emails to update
        print("\nAnalyzing emails with missing recipients...")
        counts = count_emails_to_update(session)

        print("\nEmails with metadata available for backfill:")
        print(f"  - recipients_to:  {counts['to']:,} emails")
        print(f"  - recipients_cc:  {counts['cc']:,} emails")
        print(f"  - recipients_bcc: {counts['bcc']:,} emails")
        print(f"  - Total with any metadata: {counts['total_with_metadata']:,} emails")

        total_to_process = counts["to"] + counts["cc"] + counts["bcc"]
        if total_to_process == 0:
            print("\nNo emails need backfilling!")
            return 0

        if args.dry_run:
            print("\n[DRY RUN] - No changes will be made")

        # Process in batches
        offset = 0
        processed = 0
        updated = 0

        print(f"\nProcessing emails in batches of {args.batch_size}...")

        while True:
            if args.limit and processed >= args.limit:
                print(f"\nReached limit of {args.limit} records")
                break

            batch = fetch_emails_batch(session, offset, args.batch_size)
            if not batch:
                break

            batch_updates = 0

            for row in batch:
                email_id = row["id"]
                recipients_display = row["recipients_display"]

                # Parse recipients from metadata
                new_to = None
                new_cc = None
                new_bcc = None

                # Only update if current value is empty
                if not row["recipients_to"] and recipients_display.get("to"):
                    parsed = parse_recipient_string(recipients_display["to"])
                    if parsed:
                        new_to = parsed

                if not row["recipients_cc"] and recipients_display.get("cc"):
                    parsed = parse_recipient_string(recipients_display["cc"])
                    if parsed:
                        new_cc = parsed

                if not row["recipients_bcc"] and recipients_display.get("bcc"):
                    parsed = parse_recipient_string(recipients_display["bcc"])
                    if parsed:
                        new_bcc = parsed

                if new_to or new_cc or new_bcc:
                    if args.verbose:
                        print(f"  {email_id}:")
                        if new_to:
                            print(
                                f"    to:  {new_to[:2]}{'...' if len(new_to) > 2 else ''}"
                            )
                        if new_cc:
                            print(
                                f"    cc:  {new_cc[:2]}{'...' if len(new_cc) > 2 else ''}"
                            )
                        if new_bcc:
                            print(
                                f"    bcc: {new_bcc[:2]}{'...' if len(new_bcc) > 2 else ''}"
                            )

                    if not args.dry_run:
                        update_recipients(session, email_id, new_to, new_cc, new_bcc)

                    batch_updates += 1
                    updated += 1

                processed += 1

                if args.limit and processed >= args.limit:
                    break

            if batch_updates > 0 and not args.dry_run:
                session.commit()

            offset += args.batch_size

            # Progress update
            print(f"  Processed {processed:,} emails, updated {updated:,}...")

        print(
            f"\n{'[DRY RUN] Would have updated' if args.dry_run else 'Updated'} "
            f"{updated:,} emails out of {processed:,} processed"
        )

        if not args.dry_run:
            session.commit()
            print("Changes committed successfully!")

        return 0

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        session.rollback()
        return 1
    except Exception as e:
        print(f"\nError: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
