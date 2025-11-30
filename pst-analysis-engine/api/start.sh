#!/bin/bash
set -e

echo "=== VeriCase Startup ==="

# Wait for Postgres (simple check or just rely on depends_on + retry)
# In production, we might want a proper wait-for-it script, but for now:

echo "Running migrations..."
python /code/apply_migrations.py

echo "Creating/resetting admin user..."
python -m app.reset_admin || echo "Warning: Could not reset admin user"

echo "Starting Uvicorn..."
# Use exec to replace shell with uvicorn process
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
