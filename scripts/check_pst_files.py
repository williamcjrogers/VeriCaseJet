import os
import sys
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add the parent directory to sys.path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vericase.api.app.config import settings
from vericase.api.app.models import PSTFile


def check_pst_files(case_id_str):
    try:
        case_id = uuid.UUID(case_id_str)
    except ValueError:
        print(f"Invalid UUID: {case_id_str}")
        return

    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        print(f"Checking PST files for case_id: {case_id}")
        pst_files = db.query(PSTFile).filter(PSTFile.case_id == case_id).all()

        if not pst_files:
            print("No PST files found for this case.")
        else:
            print(f"Found {len(pst_files)} PST files:")
            for pst in pst_files:
                print(f"  ID: {pst.id}")
                print(f"  Filename: {pst.filename}")
                print(f"  Status: {pst.processing_status}")
                print(f"  Uploaded At: {pst.uploaded_at}")
                print(f"  Error: {pst.error_message}")
                print("-" * 20)

    except Exception as e:
        print(f"Error querying database: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_pst_files(sys.argv[1])
    else:
        print("Usage: python check_pst_files.py <case_id>")
