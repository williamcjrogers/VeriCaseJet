#!/bin/bash

# This script is designed to analyze PST files using the PST analysis engine.
# Usage: ./analyze.sh <path_to_pst_file>

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path_to_pst_file>"
    exit 1
fi

PST_FILE="$1"

# Check if the PST file exists
if [ ! -f "$PST_FILE" ]; then
    echo "Error: PST file '$PST_FILE' not found."
    exit 1
fi

# Activate the Python environment if necessary
# source /path/to/your/venv/bin/activate

# Run the analysis using the main entry point of the application
if ! python -m src "$PST_FILE"; then
    echo "Error: Analysis failed"
    exit 1
fi