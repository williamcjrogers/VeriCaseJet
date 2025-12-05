#!/usr/bin/env python3
"""
Reset admin password for VeriCase local Docker development.
Run this script inside the Docker container or with direct DB access.
"""
import os
import sys

# Add the api/app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'api', 'app'))

from passlib.hash import pbkdf2_sha256 as hasher
import psycopg2

# Database connection - using Docker service names
DB_HOST = os.environ.get('DB_HOST', 'localhost')  # 'postgres' inside container, 'localhost' from host
DB_PORT = os.environ.get('DB_PORT', '5432')
DB_NAME = os.environ.get('DB_NAME', 'vericase')
DB_USER = os.environ.get('DB_USER', 'vericase')
DB_PASS = os.environ.get('DB_PASS', 'vericase')

# New password to set
NEW_PASSWORD = "VeriCase1234?!"
ADMIN_EMAIL = "admin@veri-case.com"

def hash_password(p: str) -> str:
    """Hash password using same method as the application"""
    return hasher.hash(p)

def main():
    print(f"Connecting to PostgreSQL at {DB_HOST}:{DB_PORT}...")
    
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cursor = conn.cursor()
        
        # Check if admin exists
        cursor.execute("SELECT id, email, display_name, is_active, role FROM users WHERE email = %s", (ADMIN_EMAIL,))
        admin = cursor.fetchone()
        
        if admin:
            print(f"Found admin user: {admin[1]} ({admin[2]})")
            print(f"  - Active: {admin[3]}")
            print(f"  - Role: {admin[4]}")
            
            # Generate new password hash
            new_hash = hash_password(NEW_PASSWORD)
            print(f"\nResetting password to: {NEW_PASSWORD}")
            
            # Update password
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE email = %s",
                (new_hash, ADMIN_EMAIL)
            )
            conn.commit()
            
            print("✅ Password reset successful!")
            print(f"\n📋 Login credentials:")
            print(f"   Email: {ADMIN_EMAIL}")
            print(f"   Password: {NEW_PASSWORD}")
        else:
            print(f"❌ Admin user '{ADMIN_EMAIL}' not found!")
            
            # List all users
            cursor.execute("SELECT email, display_name, role FROM users")
            users = cursor.fetchall()
            print(f"\nExisting users ({len(users)}):")
            for u in users:
                print(f"  - {u[0]} ({u[1]}) - {u[2]}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
