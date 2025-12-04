#!/bin/bash
cd /code
python3 << 'PYEOF'
from app.security import get_db
from app.models import Project, User

db = next(get_db())
admin = db.query(User).filter_by(email="admin@vericase.com").first()

if not admin:
    print("ERROR: Admin user not found")
    exit(1)

project = Project(
    id="dca0d854-1655-4498-97f3-399b47a4d65f",
    project_name="Evidence Uploads",
    project_code="DEFAULT",
    owner_user_id=admin.id
)

db.add(project)
db.commit()
print("✓ Project created successfully!")
PYEOF
