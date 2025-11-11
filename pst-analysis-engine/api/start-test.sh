#!/bin/bash
set -e

echo "=== VeriCase Startup - Testing Mode ==="
echo "Testing database connectivity..."

cd pst-analysis-engine/api

# Test database connection
python3 -c "
import psycopg2
import os
try:
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    print('✅ Database connection successful')
    conn.close()
except Exception as e:
    print(f'❌ Database connection failed: {e}')
    exit(1)
"

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
