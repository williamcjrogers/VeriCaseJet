#!/usr/bin/env python3
"""
Diagnostic script to check project/case conflicts and clean up if needed
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from app.db import SessionLocal
    from app.models import Case, User
except ModuleNotFoundError:
    from api.app.db import SessionLocal
    from api.app.models import Case, User

from sqlalchemy import func


def check_projects():
    """Check for project/case conflicts"""
    db = SessionLocal()
    try:
        print("=" * 70)
        print("VeriCase Project/Case Diagnostic")
        print("=" * 70)

        # Check for admin
        admin = db.query(User).filter(User.email == "admin@veri-case.com").first()
        if not admin:
            admin = db.query(User).filter(User.email == "admin@vericase.com").first()

        if admin:
            print(f"\n✅ Admin found: {admin.email} (ID: {admin.id})")
        else:
            print("\n❌ No admin account found!")
            return

        # Check cases
        print("\n📋 Cases:")
        cases = db.query(Case).order_by(Case.created_at.desc()).limit(20).all()

        if not cases:
            print("   No cases found")
        else:
            for case in cases:
                print(f"   - {case.case_number}: {case.name}")
                print(f"     Owner: {case.owner_id}")
                print(f"     Created: {case.created_at}")

        # Check for duplicates
        print("\n🔍 Checking for duplicate case numbers...")
        duplicates = (
            db.query(Case.case_number, func.count(Case.case_number).label("count"))
            .group_by(Case.case_number)
            .having(func.count(Case.case_number) > 1)
            .all()
        )

        if duplicates:
            print(f"   ⚠️  Found {len(duplicates)} duplicate case numbers:")
            for dup in duplicates:
                print(f"      - {dup.case_number}: {dup.count} occurrences")
        else:
            print("   ✅ No duplicate case numbers found")

        print("\n" + "=" * 70)
        print("Diagnostic complete")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    check_projects()
