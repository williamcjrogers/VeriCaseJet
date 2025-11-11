#!/bin/bash
set -e

echo "=== VeriCase Startup ==="
cd pst-analysis-engine/api
echo "Starting on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
