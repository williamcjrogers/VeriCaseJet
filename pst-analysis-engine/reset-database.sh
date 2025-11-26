#!/bin/bash
# Reset Database Script - Wipes all data and recreates fresh schema

set -e

echo "============================================"
echo "  VeriCase Database Reset Tool"
echo "============================================"
echo ""
echo "WARNING: This will DELETE ALL data in your database!"
echo ""
read -p "Are you sure you want to continue? Type 'YES' to proceed: " confirmation

if [ "$confirmation" != "YES" ]; then
    echo "Operation cancelled."
    exit 0
fi

echo ""
echo "Starting database reset..."
echo ""

# Navigate to script directory
cd "$(dirname "$0")"

# 1. Delete SQLite database file
if [ -f "vericase.db" ]; then
    echo "[1/5] Removing SQLite database file..."
    rm -f vericase.db
    echo "      ✓ Deleted: vericase.db"
else
    echo "[1/5] No SQLite database found (skipping)"
fi

# 2. Clean up upload directories
echo ""
echo "[2/5] Cleaning upload directories..."
for dir in uploads data; do
    if [ -d "$dir" ]; then
        find "$dir" -type f -delete 2>/dev/null || true
        echo "      ✓ Cleaned: $dir"
    fi
done

# 3. Check for PostgreSQL database
echo ""
echo "[3/5] Checking for PostgreSQL database..."
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

if [ ! -z "$DATABASE_URL" ]; then
    if [[ "$DATABASE_URL" == *"sqlite"* ]]; then
        echo "      Using SQLite - already handled"
    elif [[ "$DATABASE_URL" == *"postgres"* ]]; then
        echo "      PostgreSQL detected"
        echo "      Attempting to reset PostgreSQL database..."
        
        python3 -c "
import psycopg2
import os
import sys

DATABASE_URL = os.getenv('DATABASE_URL', '')
if not DATABASE_URL:
    print('      No DATABASE_URL found')
    sys.exit(0)

# Convert SQLAlchemy URL to psycopg2 format
if DATABASE_URL.startswith('postgresql+psycopg2://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql+psycopg2://', 'postgresql://')

try:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute('''
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'public'
    ''')
    tables = [row[0] for row in cursor.fetchall()]
    
    # Drop all tables
    if tables:
        print(f'      Dropping {len(tables)} tables...')
        for table in tables:
            cursor.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
        print('      ✓ All tables dropped')
    
    conn.close()
    print('      ✓ PostgreSQL reset complete')
except Exception as e:
    print(f'      Warning: Could not reset PostgreSQL: {e}')
" || true
    fi
else
    echo "      No DATABASE_URL configured"
fi

# 4. Recreate fresh schema
echo ""
echo "[4/5] Recreating fresh database schema..."

if [ ! -z "$DATABASE_URL" ] && [[ "$DATABASE_URL" == *"postgres"* ]]; then
    echo "      Applying PostgreSQL migrations..."
    python3 api/apply_migrations.py || true
else
    echo "      Creating fresh SQLite database..."
    python3 -c "
from pathlib import Path
import sqlite3

db_path = Path('vericase.db')
conn = sqlite3.connect(str(db_path))
print(f'      ✓ Created SQLite database: {db_path}')
conn.close()
" || true
fi

# 5. Create default admin user
echo ""
echo "[5/5] Creating default admin user..."
python3 api/create_admin.py 2>&1 | sed 's/^/      /' || true

echo ""
echo "============================================"
echo "  Database Reset Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Start the API server: cd api && uvicorn app.main:app --reload"
echo "  2. Login with default credentials (check create_admin.py output)"
echo ""


