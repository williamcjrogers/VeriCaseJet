#!/usr/bin/env python3
"""
Create a new properly configured admin account: admin@veri-case.com
This account will have all security fields properly initialized
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add paths for imports (works in container and locally)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    # Try container import path first
    from app.db import SessionLocal
    from app.models import User, UserRole
    from app.security import hash_password
except ModuleNotFoundError:
    # Fall back to local dev import path
    from api.app.db import SessionLocal
    from api.app.models import User, UserRole
    from api.app.security import hash_password


def create_new_admin():
    """Create admin@veri-case.com with proper security initialization"""

    print("=" * 70)
    print("Creating New Admin Account: admin@veri-case.com")
    print("=" * 70)

    # Get credentials from environment
    new_admin_email = "admin@veri-case.com"
    admin_password = os.getenv("ADMIN_PASSWORD", "ChangeThis123!")
    jwt_secret = os.getenv("JWT_SECRET", "")

    # Environment check
    print("\n🔍 Environment Check:")
    print(f"   New Admin Email: {new_admin_email}")
    print(
        f"   Admin Password: {'✅ Set' if admin_password != 'ChangeThis123!' else '⚠️  Using default'}"
    )
    print(
        f"   JWT Secret: {'✅ Set' if jwt_secret and len(jwt_secret) > 10 else '❌ Missing or too short'}"
    )

    if not jwt_secret or len(jwt_secret) < 32:
        print("\n⚠️  WARNING: JWT_SECRET is missing or weak!")
        print("   Set a secure JWT_SECRET in your environment")

    db = SessionLocal()
    try:
        # Check if new admin already exists
        existing = db.query(User).filter(User.email == new_admin_email).first()

        if existing:
            print(f"\n⚠️  Admin account {new_admin_email} already exists!")
            print("\nDo you want to:")
            print("   1. Update existing account (reset password, fix security)")
            print("   2. Delete and recreate")
            print("   3. Exit")

            choice = input("\nChoice (1/2/3): ").strip()

            if choice == "1":
                print("\n🔧 Updating existing account...")
                update_existing_admin(db, existing, admin_password)
                return
            elif choice == "2":
                print("\n🗑️  Deleting existing account...")
                db.delete(existing)
                db.commit()
                print("✅ Deleted")
            else:
                print("\n❌ Exiting without changes")
                return

        # Create new admin with all proper fields
        print("\n🆕 Creating new admin account...")

        new_admin = User(
            email=new_admin_email,
            password_hash=hash_password(admin_password),
            role=UserRole.ADMIN,
            is_active=True,
            # Security fields - properly initialized
            email_verified=True,  # Admin doesn't need email verification
            verification_token=None,
            reset_token=None,
            reset_token_expires=None,
            # Lockout fields - clean state
            failed_login_attempts=0,
            locked_until=None,
            last_failed_attempt=None,
            # Password management
            password_changed_at=datetime.now(timezone.utc),
            # Display name
            display_name="System Administrator",
        )

        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)

        print("\n✅ Successfully created admin account!")
        print("\n📋 Account Details:")
        print(f"   ID: {new_admin.id}")
        print(f"   Email: {new_admin.email}")
        print(f"   Role: {new_admin.role.value}")
        print(f"   Active: {new_admin.is_active}")
        print(f"   Email Verified: {new_admin.email_verified}")
        print(f"   Failed Login Attempts: {new_admin.failed_login_attempts}")
        print(f"   Account Locked: {'No' if not new_admin.locked_until else 'Yes'}")

        print("\n🔑 Login Credentials:")
        print(f"   Email: {new_admin_email}")
        print(f"   Password: {'*' * len(admin_password)} (from ADMIN_PASSWORD env var)")

        print("\n" + "=" * 70)
        print("✅ Done! You can now log in with admin@veri-case.com")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error creating admin: {e}")
        import traceback

        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


def update_existing_admin(db, admin: User, password: str):
    """Update existing admin account with proper security fields"""

    print("   Resetting password")
    admin.password_hash = hash_password(password)
    admin.password_changed_at = datetime.now(timezone.utc)

    print("   Setting role to ADMIN")
    admin.role = UserRole.ADMIN

    print("   Activating account")
    admin.is_active = True

    print("   Verifying email")
    admin.email_verified = True
    admin.verification_token = None

    print("   Clearing lockouts")
    admin.failed_login_attempts = 0
    admin.locked_until = None
    admin.last_failed_attempt = None

    print("   Clearing reset tokens")
    admin.reset_token = None
    admin.reset_token_expires = None

    if not admin.display_name:
        admin.display_name = "System Administrator"

    try:
        db.commit()
        print("\n✅ Successfully updated admin account!")
        print("\n📋 Account Details:")
        print(f"   ID: {admin.id}")
        print(f"   Email: {admin.email}")
        print(f"   Role: {admin.role.value}")
        print(f"   Active: {admin.is_active}")
        print(f"   Email Verified: {admin.email_verified}")
    except Exception as e:
        print(f"\n❌ Error updating admin: {e}")
        db.rollback()


if __name__ == "__main__":
    create_new_admin()
