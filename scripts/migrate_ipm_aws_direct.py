#!/usr/bin/env python3
"""
Direct AWS RDS IPM Migration Script
Uses AWS Secrets Manager to get credentials and connects directly to RDS
"""

import os
import sys
import json
import subprocess
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def get_aws_secret(secret_id, region="eu-west-2"):
    """Get secret from AWS Secrets Manager"""
    try:
        result = subprocess.run(
            [
                "aws",
                "secretsmanager",
                "get-secret-value",
                "--secret-id",
                secret_id,
                "--region",
                region,
                "--query",
                "SecretString",
                "--output",
                "text",
            ],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "AWS_PROFILE": "VericaseDocsAdmin"},
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving secret: {e}")
        print(f"Error output: {e.stderr}")
        sys.exit(1)


def main():
    print("\n=== VeriCase IPM Migration (AWS RDS Direct) ===\n")

    # Configuration
    DB_HOST = "database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com"
    DB_NAME = "vericase"
    DB_USER = "vericase"
    DB_PORT = 5432
    SECRET_ID = "rds!db-5818fc76-6f0c-4d02-8aa4-df3d01776ed3"

    # Get password from AWS Secrets Manager
    print("Retrieving database password from AWS Secrets Manager...")
    secret = get_aws_secret(SECRET_ID)
    DB_PASSWORD = secret["password"]
    print("✓ Password retrieved successfully\n")

    # Create database connection
    database_url = (
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    print(f"Connecting to: {DB_HOST}/{DB_NAME}")

    try:
        engine = create_engine(database_url, poolclass=NullPool)

        with engine.connect() as conn:
            # Step 1: Count items
            print("\nStep 1: Counting IPM items that need to be hidden...")
            count_sql = text(
                """
                SELECT COUNT(*) 
                FROM email_messages 
                WHERE (subject LIKE 'IPM.Activity%' 
                   OR subject LIKE 'IPM.Appointment%' 
                   OR subject LIKE 'IPM.Task%' 
                   OR subject LIKE 'IPM.Contact%'
                   OR subject LIKE 'IPM.StickyNote%' 
                   OR subject LIKE 'IPM.Schedule%'
                   OR subject LIKE 'IPM.DistList%' 
                   OR subject LIKE 'IPM.Post%')
                AND (metadata IS NULL 
                   OR metadata->>'is_hidden' IS NULL 
                   OR metadata->>'is_hidden' = 'false')
            """
            )

            result = conn.execute(count_sql)
            count = result.scalar()
            print(f"✓ Found {count} IPM items to hide\n")

            if count == 0:
                print("No items to migrate. Exiting.")
                return

            # Step 2: Show sample items
            print("Step 2: Sample items (first 5):")
            sample_sql = text(
                """
                SELECT id, subject, 
                       COALESCE(metadata->>'is_hidden', 'not set') as current_hidden_status
                FROM email_messages 
                WHERE (subject LIKE 'IPM.Activity%' 
                   OR subject LIKE 'IPM.Appointment%' 
                   OR subject LIKE 'IPM.Task%' 
                   OR subject LIKE 'IPM.Contact%'
                   OR subject LIKE 'IPM.StickyNote%' 
                   OR subject LIKE 'IPM.Schedule%'
                   OR subject LIKE 'IPM.DistList%' 
                   OR subject LIKE 'IPM.Post%')
                AND (metadata IS NULL 
                   OR metadata->>'is_hidden' IS NULL 
                   OR metadata->>'is_hidden' = 'false')
                LIMIT 5
            """
            )

            result = conn.execute(sample_sql)
            for row in result:
                print(f"  ID: {row[0]}, Subject: {row[1][:50]}..., Hidden: {row[2]}")

            # Step 3: Confirmation
            print("\nThis will update {} items by setting:".format(count))
            print("  - is_hidden: true")
            print("  - is_spam: true")
            print("  - spam_category: non_email")
            print("  - spam_score: 100")

            confirm = input("\nDo you want to proceed? (yes/no): ")
            if confirm.lower() != "yes":
                print("Migration cancelled.")
                return

            # Step 4: Execute update
            print("\nStep 3: Executing migration...")
            update_sql = text(
                """
                UPDATE email_messages
                SET metadata = COALESCE(metadata, '{}'::jsonb) || 
                    '{"is_hidden": true, "is_spam": true, "spam_category": "non_email", "spam_score": 100}'::jsonb
                WHERE (subject LIKE 'IPM.Activity%' 
                   OR subject LIKE 'IPM.Appointment%' 
                   OR subject LIKE 'IPM.Task%' 
                   OR subject LIKE 'IPM.Contact%'
                   OR subject LIKE 'IPM.StickyNote%' 
                   OR subject LIKE 'IPM.Schedule%'
                   OR subject LIKE 'IPM.DistList%' 
                   OR subject LIKE 'IPM.Post%')
                AND (metadata IS NULL 
                   OR metadata->>'is_hidden' IS NULL 
                   OR metadata->>'is_hidden' = 'false')
            """
            )

            result = conn.execute(update_sql)
            conn.commit()
            updated = result.rowcount
            print(f"✓ Migration completed! Updated {updated} rows\n")

            # Step 5: Verify
            print("Step 4: Verification - counting hidden IPM items...")
            verify_sql = text(
                """
                SELECT COUNT(*) 
                FROM email_messages 
                WHERE metadata->>'is_hidden' = 'true' 
                AND subject LIKE 'IPM.%'
            """
            )

            result = conn.execute(verify_sql)
            hidden_count = result.scalar()
            print(f"✓ Total hidden IPM items: {hidden_count}\n")

            print("=== Migration Complete ===")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
