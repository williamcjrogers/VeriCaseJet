from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from .db import get_db
from .models import User, Case, PSTFile, Company, UserCompany, Project
from .security_enhanced import current_user_enhanced
from .tasks import celery_app
from .config import settings
from .storage import s3
from typing import Any, Protocol, cast
import uuid
import os
import shutil


class _UploadClient(Protocol):
    def upload_file(self, Filename: str, Bucket: str, Key: str) -> Any: ...


router = APIRouter()


@router.post("/upload-pst")
async def debug_upload_pst(
    file: UploadFile = File(...),  # type: ignore
    db: Session = Depends(get_db),
    user: User = Depends(current_user_enhanced),
) -> dict[str, str]:
    # pyright: reportCallInDefaultInitializer=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
    """
    BYPASS ENDPOINT: Directly upload a PST and create necessary wrapper objects (Case, Company).
    """
    print(f"DEBUG: Received upload request for {file.filename}")

    # DEBUG: Check DB Schema visible to App
    try:
        inspector = inspect(db.get_bind())
        columns = [c["name"] for c in inspector.get_columns("cases")]
        print(f"DEBUG: Columns in 'cases' table: {columns}")
    except Exception as e:
        print(f"DEBUG: Failed to inspect schema: {e}")

    # 1. Ensure Company Exists
    user_company = db.query(UserCompany).filter(UserCompany.user_id == user.id).first()
    company: Company
    if not user_company:
        company = Company(
            company_name=f"{user.email}'s Debug Company", domain="debug.local"
        )
        db.add(company)
        db.flush()

        user_company = UserCompany(
            user_id=user.id, company_id=company.id, role="admin", is_primary=True
        )
        db.add(user_company)
        db.flush()
    else:
        company = cast(Company, user_company.company)

    # 2. Create/Get a Debug Case
    # Use only ID to check existence to avoid selecting missing columns if schema is stale

    # Try raw SQL with text() wrapper
    result = db.execute(
        text("SELECT id FROM cases WHERE name = :name AND owner_id = :owner_id"),
        {"name": "Debug Case", "owner_id": user.id},
    ).first()

    case_id: uuid.UUID
    if not result:
        case_id = uuid.uuid4()
        case = Case(
            id=case_id,
            case_number=f"DBG-{uuid.uuid4().hex[:6].upper()}",
            name="Debug Case",
            description="Auto-generated case for direct PST uploads",
            status="active",
            owner_id=user.id,
            company_id=company.id,
        )
        db.add(case)
        db.flush()
    else:
        case_id = uuid.UUID(str(result[0]))

    # 3. Create/Get a Debug Project
    project = (
        db.query(Project)
        .filter(
            Project.project_name == "Debug Project", Project.owner_user_id == user.id
        )
        .first()
    )
    if not project:
        project = Project(
            id=uuid.uuid4(),
            project_name="Debug Project",
            project_code=f"PRJ-{uuid.uuid4().hex[:6].upper()}",
            owner_user_id=user.id,
        )
        db.add(project)
        db.flush()

    # 4. Save File to Disk/S3
    # Create temp file
    temp_filename = f"/tmp/{uuid.uuid4()}_{file.filename}"
    with open(temp_filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    file_size = os.path.getsize(temp_filename)

    # Upload to MinIO (S3) using the same client factory as the rest of the app.
    s3_key = f"debug-uploads/{case_id}/{file.filename}"
    bucket_name = settings.MINIO_BUCKET
    storage_client: _UploadClient = cast(_UploadClient, s3())

    try:
        storage_client.upload_file(temp_filename, bucket_name, s3_key)
    except Exception as e:
        print(f"S3 Upload failed: {e}")
        raise HTTPException(500, f"Failed to upload to storage: {str(e)}")
    finally:
        try:
            os.remove(temp_filename)
        except OSError:
            pass

    # 5. Create PST Record
    pst_file = PSTFile(
        id=uuid.uuid4(),
        filename=file.filename,  # type: ignore
        case_id=case_id,
        project_id=project.id,
        s3_bucket=bucket_name,  # type: ignore
        s3_key=s3_key,
        file_size=file_size,
        processing_status="pending",
        uploaded_by=user.id,
    )
    db.add(pst_file)
    db.commit()

    # 6. Trigger Processing Task
    try:
        _ = celery_app.send_task(
            "worker_app.worker.process_pst_file",
            args=[str(pst_file.id), str(case_id), str(company.id)],
        )
    except Exception as e:
        print(f"Failed to queue task: {e}")

    return {
        "status": "success",
        "message": "PST uploaded and queued for debug processing",
        "case_id": str(case_id),
        "pst_id": str(pst_file.id),
        "redirect_url": f"/ui/correspondence-enterprise.html?caseId={case_id}",
    }
