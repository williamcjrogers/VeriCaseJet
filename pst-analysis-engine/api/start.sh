#!/bin/bash
set -e

echo "=== VeriCase Application Startup ==="
echo "Working directory: $(pwd)"
echo "Python version: $(python3 --version)"

cd pst-analysis-engine/api

echo "Testing database connectivity..."
python3 -c "import psycopg2; import os; conn = psycopg2.connect(os.environ['DATABASE_URL']); print('✅ Database connected'); conn.close()" || echo "⚠️  Database connection failed"

echo "Running database migrations..."
alembic upgrade head

echo "Starting application on port ${PORT:-8000}..."
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
