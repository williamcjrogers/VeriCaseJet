#!/bin/bash
set -e

echo "Running database migrations..."
cd /app/pst-analysis-engine/api
alembic upgrade head

echo "Starting application..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
