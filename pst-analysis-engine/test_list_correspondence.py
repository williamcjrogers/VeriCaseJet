import requests
import json

# The endpoint is /api/correspondence/pst/files
url = "http://localhost:8000/api/correspondence/pst/files"

# Bypass HTTPSRedirectMiddleware
headers = {
    "X-Forwarded-Proto": "https"
}

try:
    print(f"Calling {url}...")
    response = requests.get(url, headers=headers)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"Total PST Files: {data.get('total')}")
        items = data.get('items', [])
        if len(items) > 0:
            print("Latest PST File:")
            print(json.dumps(items[0], indent=2))
            print("SUCCESS: Retrieved PST file list!")
        else:
            print("WARNING: No PST files found in list (did the upload work?)")
    else:
        print(f"FAILURE: API returned error: {response.text}")
        
except Exception as e:
    print(f"ERROR: {e}")
