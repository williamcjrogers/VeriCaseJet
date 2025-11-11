#!/bin/bash
set -e

echo "=== VeriCase Application Startup ==="
echo "Working directory: $(pwd)"
echo "Python version: $(python3 --version)"

cd pst-analysis-engine/api

echo "⚠️  SKIPPING database migrations for testing..."
echo "⚠️  Database tables may not exist!"

echo "Starting application on port ${PORT:-8000}..."
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
