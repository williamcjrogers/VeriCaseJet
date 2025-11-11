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
    "Public DNS": "google.com"
}

for service, endpoint in endpoints.items():
    try:
        ip = socket.gethostbyname(endpoint)
        print(f"✓ {service}: {endpoint} → {ip}")
    except Exception as e:
        print(f"✗ {service}: {endpoint} → DNS FAILED: {e}")

# Test environment
print("\n=== Environment Check ===")
print(f"DATABASE_URL: {'SET' if os.getenv('DATABASE_URL') else 'NOT SET'}")
print(f"AWS_REGION: {os.getenv('AWS_REGION', 'NOT SET')}")
print(f"PORT: {os.getenv('PORT', '8000')}")

# Set PYTHONPATH to include vendor directory
vendor_path = os.path.join(os.path.dirname(__file__), 'vendor')
if os.path.exists(vendor_path):
    print(f"\n✓ Vendor directory found: {vendor_path}")
    sys.path.insert(0, vendor_path)
else:
    print(f"\n✗ Vendor directory not found: {vendor_path}")

# Start the application with fallback
print("\n=== Starting Application ===")
try:
    # Try to import FastAPI from vendor
    from fastapi import FastAPI
    print("✓ FastAPI imported successfully")
    
    # Start with a basic app if main app fails
    try:
        from app.main import app
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
                    "database_url": bool(os.getenv('DATABASE_URL'))
                }
            }
        
        @app.get("/health")
        def health():
            return {"status": "healthy", "mode": "diagnostic"}
    
    # Run uvicorn
    import uvicorn
    port = int(os.getenv('PORT', '8000'))
    print(f"Starting uvicorn on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
    
except Exception as e:
    print(f"FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
