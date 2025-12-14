#!/bin/bash
set -e

echo "=== VeriCase Startup ==="

echo "Waiting for Postgres to accept connections..."
python - <<'PY'
import os
import sys
import time

import psycopg2

database_url = os.getenv("DATABASE_URL", "")
if database_url.startswith("postgresql+psycopg2://"):
  database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)

deadline = time.time() + int(os.getenv("DB_WAIT_SECONDS", "60"))
last_error = None

while time.time() < deadline:
  try:
    conn = psycopg2.connect(database_url)
    conn.close()
    print("Postgres is ready.")
    sys.exit(0)
  except Exception as exc:
    last_error = exc
    time.sleep(2)

print(f"Postgres did not become ready in time: {last_error}")
sys.exit(1)
PY

echo "Running migrations (Alembic preferred)..."

# Prefer Alembic-managed migrations; fall back to legacy script if needed
set +e
alembic upgrade head
status=$?
set -e

if [ "$status" -ne 0 ]; then
  echo "Alembic migrations failed with exit code $status, falling back to legacy apply_migrations.py"
  if [ -f "/code/apply_migrations.py" ]; then
    python /code/apply_migrations.py
  else
    echo "Legacy migration script /code/apply_migrations.py not found; cannot run migrations."
    exit 1
  fi
fi

echo "Creating/resetting admin user..."
python -m app.reset_admin || echo "Warning: Could not reset admin user"

echo "Starting Uvicorn..."
# Use exec to replace shell with uvicorn process
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips '*'
