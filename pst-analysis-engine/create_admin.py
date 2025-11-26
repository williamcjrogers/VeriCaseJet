#!/usr/bin/env python3
"""Create admin user for VeriCase"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from api.app.db import SessionLocal
from api.app.models import User
from api.app.security import hash_password

def create_admin():
    db = SessionLocal()
    try:
        # Delete existing admin if exists
        db.query(User).filter(User.email == 'admin@vericase.com').delete()
        db.commit()
        
        # Create new admin with proper password hash
        password_hash = hash_password('VeriCase123!')
        
        admin = User(
            email='admin@vericase.com',
            password_hash=password_hash,
            role='ADMIN',
            is_active=True,
            email_verified=True,
            display_name='Administrator'
        )
        
        db.add(admin)
        db.commit()
        db.refresh(admin)
        
        print(f"✅ Admin user created successfully!")
        print(f"   Email: {admin.email}")
        print(f"   Role: {admin.role}")
        print(f"   Active: {admin.is_active}")
        print(f"   Password: VeriCase123!")
        print(f"   Hash length: {len(password_hash)}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin()
