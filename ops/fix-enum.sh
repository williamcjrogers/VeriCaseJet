#!/bin/bash
# Quick fix for user_role enum - run this on App Runner

echo "Fixing user_role enum..."

python3 << 'EOF'
import psycopg2
import os

try:
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    
    # Add uppercase enum values
    cur.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'ADMIN'")
    cur.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'MANAGER'")  
    cur.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'USER'")
    cur.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'VIEWER'")
    
    conn.commit()
    print("✓ Enum values added successfully")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"✗ Error: {e}")
    exit(1)
EOF

echo "Done!"
