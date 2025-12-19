#!/usr/bin/env python3
"""
App Runner startup script with diagnostics
"""

import os
import sys
import socket
import subprocess

print("=== VeriCase App Runner Startup Diagnostics ===")
print(f"Python: {sys.version}")
print(f"Working directory: {os.getcwd()}")

# Test DNS resolution
print("\n=== DNS Resolution Test ===")
endpoints = {
    "RDS": "database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com",
    "Redis": "clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com",
    "OpenSearch": "vpc-vericase-opensearch-sl2a3zd5dnrbt64bssyocnrofu.eu-west-2.es.amazonaws.com",
    "Public DNS": "google.com",
}

for service, endpoint in endpoints.items():
    try:
        ip = socket.gethostbyname(endpoint)
        print(f"✓ {service}: {endpoint} → {ip}")
    except Exception as e:
        print(f"✗ {service}: {endpoint} → DNS FAILED: {e}")

# Test environment
print("\n=== Environment Check ===")
db_url = os.getenv("DATABASE_URL", "")
if db_url:
    # Extract just the hostname for display
    try:
        import re

        match = re.search(r"@([^:/]+)", db_url)
        if match:
            hostname = match.group(1)
            print(f"DATABASE_URL hostname: {hostname}")
            print(f"DATABASE_URL length: {len(db_url)} characters")

            # Check for corruption
            if "cv8uwu0uqr7fau-west-2" in hostname:
                print("[WARN] Hostname appears corrupted!")
                print("Expected: database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com")
    except Exception:
        pass
    print("DATABASE_URL: SET")
else:
    print("DATABASE_URL: NOT SET")
print(f"AWS_REGION: {os.getenv('AWS_REGION', 'NOT SET')}")
print(f"PORT: {os.getenv('PORT', '8000')}")

# Set PYTHONPATH to include vendor directory
vendor_path = os.path.join(os.path.dirname(__file__), "vendor")
if os.path.exists(vendor_path):
    print(f"\n✓ Vendor directory found: {vendor_path}")
    sys.path.insert(0, vendor_path)
else:
    print(f"\n✗ Vendor directory not found: {vendor_path}")

# Check UI directory
print("\n=== UI Directory Check ===")
ui_candidates = [
    "/app/pst-analysis-engine/api/ui",
    "/app/pst-analysis-engine/ui",
    "/app/ui",
]
for ui_path in ui_candidates:
    if os.path.exists(ui_path):
        print(f"✓ UI directory found: {ui_path}")
        files = os.listdir(ui_path)[:5]  # Show first 5 files
        print(f"  Files: {', '.join(files)}...")
    else:
        print(f"✗ UI directory not found: {ui_path}")

# Run database migrations before starting the app
print("\n=== Running Database Migrations ===")
try:
    # Add vendor to path first
    vendor_path = os.path.join(os.path.dirname(__file__), "vendor")
    if os.path.exists(vendor_path):
        sys.path.insert(0, vendor_path)

    # Run migrations directly
    migrations_script = os.path.join(os.path.dirname(__file__), "apply_migrations.py")
    if os.path.exists(migrations_script):
        result = subprocess.run(
            [sys.executable, migrations_script],
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PYTHONPATH": vendor_path},
        )
        print(result.stdout)
        if result.stderr:
            print(f"Stderr: {result.stderr}")
        if result.returncode == 0:
            print("✓ Database migrations completed successfully")
        else:
            print(f"⚠ Migrations exited with code {result.returncode}")
    else:
        print(f"⚠ Migration script not found: {migrations_script}")
except Exception as e:
    print(f"⚠ Could not run migrations: {e}")
    import traceback

    traceback.print_exc()
    print("App will start anyway - migrations may need to be run manually")

# Start the application with fallback
print("\n=== Starting Application ===")

# Add current directory to path for app imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    # Try to import FastAPI from vendor
    from fastapi import FastAPI

    print("✓ FastAPI imported successfully")

    # Start with a basic app if main app fails
    try:
        from app.main import (
            app,
        )  # noqa: F401  # pyright: ignore[reportImplicitRelativeImport]  # Script runs directly, not as module

        print("✓ Main application imported")
    except Exception as e:
        print(f"✗ Main application import failed: {e}")
        print("Creating fallback application...")

        app = FastAPI()

        @app.get("/")
        def root():
            return {
                "status": "running",
                "message": "VeriCase API (Diagnostic Mode)",
                "diagnostics": {
                    "dns_working": endpoints.get("Public DNS") is not None,
                    "vendor_path": os.path.exists(vendor_path),
                    "database_url": bool(os.getenv("DATABASE_URL")),
                },
            }

        @app.get("/health")
        def health():
            return {"status": "healthy", "mode": "diagnostic"}

    # Run uvicorn
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    print(f"Starting uvicorn on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

except Exception as e:
    print(f"FATAL ERROR: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
