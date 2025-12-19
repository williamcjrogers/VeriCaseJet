#!/usr/bin/env python3
"""Create admin user for VeriCase"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.db import SessionLocal
from app.models import User
from app.security import hash_password


def create_admin():
    db = SessionLocal()
    try:
        # Delete existing admin if exists
        db.query(User).filter(User.email == "admin@vericase.com").delete()
        db.commit()

        # Create new admin with proper password hash
        password_hash = hash_password("VeriCase123!")

        admin = User(
            email="admin@vericase.com",
            password_hash=password_hash,
            role="ADMIN",
            is_active=True,
            email_verified=True,
            display_name="Administrator",
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        print("✅ Admin user created successfully!")
        print("   Email: {admin.email}")
        print("   Role: {admin.role}")
        print("   Active: {admin.is_active}")
        print("   Password: VeriCase123!")
        print("   Hash length: {len(password_hash)}")

    except Exception:
        print("❌ Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
