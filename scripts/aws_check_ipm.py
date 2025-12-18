#!/usr/bin/env python3
"""
Connect to AWS RDS and check/migrate IPM items.
Usage: python scripts/aws_check_ipm.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "vericase" / "api"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

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
    # Prompt for database
    print("Which database do you want to check?")
    print("1. Local Docker (localhost:54321)")
    print("2. AWS RDS (database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com)")
    print("3. Custom URL")

    choice = input("Enter choice (1/2/3): ").strip()

    if choice == "1":
        database_url = (
            "postgresql+psycopg2://vericase:vericase@localhost:54321/vericase"
        )
    elif choice == "2":
        password = input("Enter AWS database password: ").strip()
        database_url = f"postgresql+psycopg2://vericase:{password}@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/vericase"
    elif choice == "3":
        database_url = input("Enter DATABASE_URL: ").strip()
    else:
        print("Invalid choice")
        return

    print("\nConnecting to database...")
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Check column name
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
            print("ERROR: Neither 'meta' nor 'metadata' column found!")
            return

        column_name = columns[0]
        print(f"Using column: {column_name}")

        # Build pattern conditions
        pattern_conditions = " OR ".join(
            [f"subject LIKE '{pattern}%'" for pattern in NON_EMAIL_PATTERNS]
        )

        # Count total IPM items
        total_query = text(
            f"""
            SELECT COUNT(*) FROM email_messages
            WHERE ({pattern_conditions})
        """
        )
        result = session.execute(total_query)
        total_ipm = result.scalar()
        print(f"\nTotal IPM items found: {total_ipm}")

        # Count items needing hiding
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
        print(f"Items needing to be hidden: {count}")

        if count == 0:
            print("\n✓ All IPM items are already hidden!")
            return

        # Show samples
        print("\nSample subjects:")
        sample_query = text(
            f"""
            SELECT subject FROM email_messages
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

        # Confirm
        confirm = input(f"\nMark {count} items as hidden? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return

        # Update
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
        print(f"✓ Verification: {hidden_count} total IPM items are now hidden")

    except Exception as e:
        print(f"\nERROR: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
