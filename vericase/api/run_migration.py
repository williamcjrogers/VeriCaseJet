"""
Run Alembic migration with proper environment loading
"""

import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from parent directory
env_file = Path(__file__).parent.parent / ".env"
print(f"Loading environment from: {env_file}")
load_dotenv(env_file)

# Run alembic upgrade head
print("Running alembic upgrade head...")
result = subprocess.run(
    ["alembic", "upgrade", "head"], cwd=Path(__file__).parent, capture_output=False
)

sys.exit(result.returncode)
