import requests
import json
import uuid
from datetime import datetime

# Mimic the frontend payload
payload = {
    "project_name": f"Dashboard Test Project {uuid.uuid4().hex[:4]}",
    "project_code": f"DASH-{uuid.uuid4().hex[:4]}",
    "description": "Created via test script mimicking dashboard",
    "contract_type": "NEC"
}

print(f"Attempting to create project: {payload}")

# The endpoint is /api/projects (from simple_cases.py)
# We need to run this INSIDE the pod where localhost:8000 is available
url = "http://localhost:8000/api/projects"

# Bypass HTTPSRedirectMiddleware by claiming we are already on HTTPS
headers = {
    "X-Forwarded-Proto": "https"
}

try:
    response = requests.post(url, json=payload, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code in [200, 201]:
        print("SUCCESS: Project created successfully via API!")
    else:
        print("FAILURE: API returned error.")
        
except Exception as e:
    print(f"ERROR: {e}")
