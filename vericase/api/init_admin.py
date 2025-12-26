"""
Initialize admin user for production deployment
Run this after database migration: python init_admin.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from api.app.db import SessionLocal
from api.app.models import User, UserRole
from api.app.security import hash_password


def create_admin_user():
    """Create the initial admin user if it doesn't exist"""
    db = SessionLocal()
    try:
        # Check if admin already exists
        admin_email = os.getenv("ADMIN_EMAIL", "admin@vericase.com")
        existing_admin = db.query(User).filter(User.email == admin_email).first()

        if existing_admin:
            print(f"Admin user {admin_email} already exists")
            return

        # Create admin user
        admin_password = os.getenv("ADMIN_PASSWORD", "ChangeThis123!")

        admin_user = User(
            email=admin_email,
            username=admin_email.split("@")[0],
            password_hash=hash_password(admin_password),
            role=UserRole.ADMIN,
            is_active=True,
            requires_approval=False,
        )

        db.add(admin_user)
        db.commit()

        print("Admin user created successfully!")
        print(f"Email: {admin_email}")
        print(f"Password: {'*' * len(admin_password)} (from ADMIN_PASSWORD env var)")
        print("\n⚠️  IMPORTANT: Change the admin password after first login!")

    except Exception as e:
        print(f"Error creating admin user: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("Initializing VeriCase admin user...")
    create_admin_user()
