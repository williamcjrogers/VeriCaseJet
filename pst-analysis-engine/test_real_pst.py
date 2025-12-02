import sys
import asyncio
import uuid
import os
from datetime import datetime
sys.path.append('/code')

from app.db import engine, SessionLocal
from app.models import User, Project, Document, PSTFile, DocStatus
from app.config import settings
from sqlalchemy import text

# Real PST File Path on Pod
PST_FILENAME = "Mark.Emery@unitedliving.co.uk.001.pst"
PST_PATH = f"/code/{PST_FILENAME}"

async def real_upload():
    print("Testing S3 connection for REAL PST upload...")
    if not os.path.exists(PST_PATH):
        print(f"ERROR: File {PST_PATH} not found!")
        sys.exit(1)
        
    file_size = os.path.getsize(PST_PATH)
    print(f"File found: {PST_FILENAME} ({file_size / 1024 / 1024:.2f} MB)")

    try:
        import boto3
        from botocore.config import Config
        
        if settings.AWS_ACCESS_KEY_ID:
            print("Using static credentials")
            s3 = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
        else:
            print("Using IRSA (Role based auth)")
            s3 = boto3.client(
                's3',
                config=Config(signature_version="s3v4"),
                region_name=settings.AWS_REGION
            )
            
        bucket = settings.S3_BUCKET
        
        # Upload real file
        s3_key = f"real_pst_test/{uuid.uuid4()}/{PST_FILENAME}"
        print(f"Uploading real file to {bucket}/{s3_key}...")
        
        # Use upload_file for large files (handles multipart automatically)
        s3.upload_file(PST_PATH, bucket, s3_key)
        print("Upload successful!")
        return s3_key, file_size
    except Exception as e:
        print(f"S3 ERROR: {e}")
        raise

def test_db_insert(s3_key, file_size):
    print("Testing DB Insert for Real PST...")
    db = SessionLocal()
    try:
        # Get admin user
        user = db.query(User).filter(User.email == "admin@vericase.com").first()
        if not user:
            print("Creating admin user...")
            # ... (User creation logic if needed, but likely exists)
            pass 
        user_id = user.id if user else None
            
        # Get project
        project = db.query(Project).first()
        if not project:
            print("No project found, creating dummy")
            project = Project(
                id=uuid.uuid4(),
                name="Real PST Test Project",
                description="Project for Real PST Test"
            )
            db.add(project)
            db.commit()
        
        print(f"Using Project: {project.id}")
        
        # Insert PSTFile
        print("Inserting PSTFile record...")
        pst = PSTFile(
            filename=PST_FILENAME,
            project_id=project.id,
            s3_bucket=settings.S3_BUCKET,
            s3_key=s3_key,
            file_size_bytes=file_size,
            processing_status="pending",
            uploaded_by=user_id
        )
        db.add(pst)
        db.commit()
        print(f"PSTFile inserted with ID: {pst.id}")
        
    except Exception as e:
        print(f"DB ERROR: {e}")
    finally:
        db.close()

async def main():
    try:
        key, size = await real_upload()
        test_db_insert(key, size)
    except Exception as e:
        print(f"MAIN ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
