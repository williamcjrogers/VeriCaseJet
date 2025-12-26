#!/usr/bin/env python3
"""
Fix admin@vericase.com account - ensure all security fields are properly initialized
Run this to diagnose and repair the admin account
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


def diagnose_admin_account(db):
    """Check admin account status and identify issues"""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@vericase.com")
    admin = db.query(User).filter(User.email == admin_email).first()

    if not admin:
        print(f"❌ Admin user {admin_email} does not exist")
        return None

    print(f"\n✅ Admin user found: {admin_email}")
    print(f"   ID: {admin.id}")
    print(f"   Role: {admin.role}")
    print(f"   Active: {admin.is_active}")

    issues = []

    # Check critical fields
    if not admin.password_hash:
        issues.append("Missing password hash")

    if not admin.email_verified:
        issues.append("Email not verified (will show warning)")

    if admin.failed_login_attempts > 0:
        issues.append(f"Has {admin.failed_login_attempts} failed login attempts")

    if admin.locked_until and admin.locked_until > datetime.now(timezone.utc):
        issues.append(f"Account is LOCKED until {admin.locked_until}")

    if not admin.role or admin.role != UserRole.ADMIN:
        issues.append(f"Role is {admin.role}, not ADMIN")

    if not admin.is_active:
        issues.append("Account is not active")

    # Display findings
    if issues:
        print("\n⚠️  Issues found:")
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
    else:
        print("\n✅ All security fields look good")

    # Display security field status
    print("\n📋 Security Fields:")
    print(f"   Email Verified: {admin.email_verified}")
    print(f"   Failed Login Attempts: {admin.failed_login_attempts}")
    print(f"   Locked Until: {admin.locked_until or 'Not locked'}")
    print(f"   Last Failed Attempt: {admin.last_failed_attempt or 'None'}")
    print(f"   Password Changed At: {admin.password_changed_at or 'Unknown'}")
    print(f"   Last Login: {admin.last_login_at or 'Never'}")

    return admin


def fix_admin_account(db, admin):
    """Fix admin account issues"""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@vericase.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "ChangeThis123!")

    print("\n🔧 Fixing admin account...")

    # Ensure proper role
    if admin.role != UserRole.ADMIN:
        print(f"   Setting role to ADMIN (was {admin.role})")
        admin.role = UserRole.ADMIN

    # Ensure active
    if not admin.is_active:
        print("   Activating account")
        admin.is_active = True

    # Reset password with current env var
    print("   Resetting password from ADMIN_PASSWORD env var")
    admin.password_hash = hash_password(admin_password)
    admin.password_changed_at = datetime.now(timezone.utc)

    # Mark email as verified (admin doesn't need verification)
    if not admin.email_verified:
        print("   Marking email as verified")
        admin.email_verified = True
        admin.verification_token = None

    # Clear any lockouts
    if admin.locked_until:
        print("   Clearing account lockout")
        admin.locked_until = None

    # Reset failed login attempts
    if admin.failed_login_attempts > 0:
        print("   Resetting failed login attempts")
        admin.failed_login_attempts = 0
        admin.last_failed_attempt = None

    # Clear any reset tokens
    admin.reset_token = None
    admin.reset_token_expires = None

    try:
        db.commit()
        print("\n✅ Admin account fixed successfully!")
        print(f"\n📧 Email: {admin_email}")
        print(f"🔑 Password: {'*' * len(admin_password)} (from ADMIN_PASSWORD env var)")
        print("\n⚠️  Make sure JWT_SECRET is properly configured in your environment")
        return True
    except Exception as e:
        print(f"\n❌ Error fixing admin account: {e}")
        db.rollback()
        return False


def create_admin_if_missing(db):
    """Create admin if it doesn't exist"""
    admin_email = os.getenv("ADMIN_EMAIL", "admin@vericase.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "ChangeThis123!")

    print(f"\n🆕 Creating new admin user: {admin_email}")

    admin_user = User(
        email=admin_email,
        password_hash=hash_password(admin_password),
        role=UserRole.ADMIN,
        is_active=True,
        email_verified=True,  # Admin doesn't need verification
        display_name="Administrator",
        verification_token=None,
        failed_login_attempts=0,
        locked_until=None,
        reset_token=None,
        reset_token_expires=None,
        password_changed_at=datetime.now(timezone.utc),
    )

    try:
        db.add(admin_user)
        db.commit()
        print("✅ Admin user created successfully!")
        print(f"📧 Email: {admin_email}")
        print(f"🔑 Password: {'*' * len(admin_password)} (from ADMIN_PASSWORD env var)")
        return True
    except Exception as e:
        print(f"❌ Error creating admin: {e}")
        db.rollback()
        return False


def main():
    """Main function"""
    print("=" * 70)
    print("VeriCase Admin Account Diagnostic & Repair Tool")
    print("=" * 70)

    # Check environment
    admin_email = os.getenv("ADMIN_EMAIL", "admin@vericase.com")
    admin_password = os.getenv("ADMIN_PASSWORD", "ChangeThis123!")
    jwt_secret = os.getenv("JWT_SECRET", "")

    print("\n🔍 Environment Check:")
    print(f"   ADMIN_EMAIL: {admin_email}")
    print(
        f"   ADMIN_PASSWORD: {'✅ Set' if admin_password != 'ChangeThis123!' else '⚠️  Using default'}"
    )
    print(
        f"   JWT_SECRET: {'✅ Set' if jwt_secret and len(jwt_secret) > 10 else '❌ Missing or too short'}"
    )

    if not jwt_secret or len(jwt_secret) < 32:
        print("\n⚠️  WARNING: JWT_SECRET is missing or weak!")
        print("   Set a secure JWT_SECRET in your environment")
        print("   Example: export JWT_SECRET=$(openssl rand -hex 32)")

    db = SessionLocal()
    try:
        # Diagnose
        admin = diagnose_admin_account(db)

        if not admin:
            # Create new admin
            create_admin_if_missing(db)
        else:
            # Fix existing admin
            fix_admin_account(db, admin)

        print("\n" + "=" * 70)
        print("✅ Done! You can now try logging in with admin@vericase.com")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
