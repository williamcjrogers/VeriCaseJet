#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENDOR_DIR="$SCRIPT_DIR/vendor"
export PYTHONPATH="${VENDOR_DIR}:${PYTHONPATH:-}"

echo "=== VeriCase App Runner Startup ==="
echo "Working directory: $(pwd)"
echo "Python version: $(python3 --version)"
echo "Vendor directory: ${VENDOR_DIR}"

if [ ! -d "$VENDOR_DIR" ]; then
  echo "ERROR: Dependency directory 'vendor' not found. Did the App Runner build step run pip install?"
  exit 1
fi

echo "Running database migrations..."
python3 apply_migrations.py

echo "Starting uvicorn..."
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2

