param(
  [switch]$Fix
)

$ErrorActionPreference = 'Stop'

# Ensure running from the script directory
Set-Location -LiteralPath (Split-Path -LiteralPath $MyInvocation.MyCommand.Path)

# Prefer venv python if present
$python = if (Test-Path .\.venv\Scripts\python.exe) { '.\.venv\Scripts\python.exe' } else { 'python' }

# Run Black
& $python -m black . --quiet

# Ruff: check or fix
if ($Fix) {
  & $python -m ruff check . --fix
} else {
  & $python -m ruff check .
}

