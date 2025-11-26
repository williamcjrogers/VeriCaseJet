#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENGINE_DIR="$REPO_ROOT"

if [[ ! -d "$ENGINE_DIR" ]]; then
  echo "Could not locate pst-analysis-engine directory at $ENGINE_DIR" >&2
  exit 1
fi

echo "Resetting VeriCase local state from $REPO_ROOT"

if command -v docker-compose >/dev/null 2>&1; then
  echo "Stopping Docker stack and removing volumes..."
  (cd "$ENGINE_DIR" && docker-compose down -v)
else
  echo "Warning: docker-compose not found in PATH. Skipping container shutdown." >&2
fi

paths=(
  "$ENGINE_DIR/data"
  "$ENGINE_DIR/uploads"
  "$ENGINE_DIR/evidence"
  "$ENGINE_DIR/vericase.db"
)

for target in "${paths[@]}"; do
  if [[ -e "$target" ]]; then
    rel=${target#$REPO_ROOT/}
    echo "Removing $rel"
    rm -rf "$target"
  fi
done

echo "Local state reset complete. Next run will start with a clean environment."
