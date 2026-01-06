import requests

api = "https://veri-case.com/api"
keep_id = "3b359c4b-96b3-4c6d-ba68-d16d7ce10017"

projects = requests.get(f"{api}/projects").json()
print(f"Found {len(projects)} projects")

to_delete = [p for p in projects if p["id"] != keep_id]
print(f"Will delete {len(to_delete)} projects")

for p in to_delete:
    name = p["project_name"]
    code = p["project_code"]
    print(f"Deleting {name} ({code})...", end="", flush=True)
    try:
        r = requests.delete(f"{api}/projects/{p['id']}", timeout=60)
        if r.status_code == 200:
            print(" OK")
        else:
            print(f" FAILED: {r.status_code}")
            print(f"   {r.text[:200]}")
    except Exception as e:
        print(f" ERROR: {e}")

# Final check
remaining = requests.get(f"{api}/projects").json()
print(f"\nRemaining projects: {len(remaining)}")
for p in remaining:
    print(f"  - {p['project_name']} ({p['project_code']})")
