#!/usr/bin/env python3
"""
Check and migrate non-email items (IPM.Activity, etc.) to mark them as hidden.

This script handles both 'meta' and 'metadata' column names.

Usage:
    python scripts/check_and_migrate_non_emails.py
"""

import os
import sys
from pathlib import Path

# Add the app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "vericase" / "api"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Patterns to match (same as spam_filter.py non_email category)
NON_EMAIL_PATTERNS = [
    "IPM.Activity",
    "IPM.Appointment",
    "IPM.Task",
    "IPM.Contact",
    "IPM.StickyNote",
    "IPM.Schedule",
    "IPM.DistList",
    "IPM.Post",
]


def main():
    # Get database URL from environment or use default
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://vericase:vericase@localhost:54321/vericase",
    )

    print("Connecting to database...")
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # First, check if the column is 'meta' or 'metadata'
        check_column_query = text(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'email_messages' 
            AND column_name IN ('meta', 'metadata')
        """
        )

        result = session.execute(check_column_query)
        columns = [row[0] for row in result]

        if not columns:
            print(
                "ERROR: Neither 'meta' nor 'metadata' column found in email_messages table!"
            )
            return

        column_name = columns[0]
        print(f"Found column: {column_name}")

        # Build the WHERE clause for all patterns
        pattern_conditions = " OR ".join(
            [f"subject LIKE '{pattern}%'" for pattern in NON_EMAIL_PATTERNS]
        )

        # First, count how many will be affected
        count_query = text(
            f"""
            SELECT COUNT(*) FROM email_messages
            WHERE ({pattern_conditions})
            AND ({column_name} IS NULL 
                 OR {column_name}->>'is_hidden' IS NULL 
                 OR {column_name}->>'is_hidden' = 'false')
        """
        )

        result = session.execute(count_query)
        count = result.scalar()

        print(f"\nFound {count} non-email items to mark as hidden")

        if count == 0:
            print("Nothing to update!")
            return

        # Show a few examples
        print("\nSample subjects:")
        sample_query = text(
            f"""
            SELECT subject 
            FROM email_messages
            WHERE ({pattern_conditions})
            AND ({column_name} IS NULL 
                 OR {column_name}->>'is_hidden' IS NULL 
                 OR {column_name}->>'is_hidden' = 'false')
            LIMIT 10
        """
        )
        result = session.execute(sample_query)
        for row in result:
            print(f"  - {row[0][:100]}")

        # Confirm before proceeding
        confirm = input(f"\nMark {count} items as hidden? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return

        # Update the meta/metadata field to mark as hidden
        update_query = text(
            f"""
            UPDATE email_messages
            SET {column_name} = COALESCE({column_name}, '{{}}'::jsonb) ||
                '{{"is_hidden": true, "is_spam": true, "spam_category": "non_email", "spam_score": 100}}'::jsonb
            WHERE ({pattern_conditions})
            AND ({column_name} IS NULL 
                 OR {column_name}->>'is_hidden' IS NULL 
                 OR {column_name}->>'is_hidden' = 'false')
        """
        )

        result = session.execute(update_query)
        session.commit()

        print(f"\n✓ Successfully marked {result.rowcount} items as hidden!")

        # Verify
        verify_query = text(
            f"""
            SELECT COUNT(*) FROM email_messages
            WHERE ({pattern_conditions})
            AND {column_name}->>'is_hidden' = 'true'
        """
        )
        result = session.execute(verify_query)
        hidden_count = result.scalar()
        print(f"✓ Verification: {hidden_count} non-email items are now hidden")

    except Exception as e:
        print(f"\nERROR: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
