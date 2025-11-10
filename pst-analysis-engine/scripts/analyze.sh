#!/bin/bash
set -Eeuo pipefail
IFS=$'\n\t'

# Print a helpful message and exit when any command fails
on_error() {
    local exit_code=$?
    local line_no=$LINENO
    echo "Error: Command failed with exit code ${exit_code} on line ${line_no}." >&2
}
trap on_error ERR

# This script is designed to analyze PST files using the PST analysis engine.
# Usage: ./analyze.sh <path_to_pst_file>

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path_to_pst_file>" >&2
    exit 1
fi

PST_FILE="$1"

# Ensure 'python' is available
if ! command -v python >/dev/null 2>&1; then
    echo "Error: 'python' not found in PATH. Please install Python or update PATH." >&2
    exit 127
fi

# Check if the PST file exists
if [ ! -f "$PST_FILE" ]; then
    echo "Error: PST file '$PST_FILE' not found." >&2
    exit 1
fi

# Activate the Python environment if necessary
# source /path/to/your/venv/bin/activate

# Run the analysis using the main entry point of the application
if ! python -m src "$PST_FILE"; then
    echo "Error: Analysis failed for file '$PST_FILE'." >&2
    exit 1
fi