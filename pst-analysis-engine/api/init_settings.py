"""
Initialize default application settings
Run this after database migration to create default settings
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from api.app.db import SessionLocal, engine
from api.app.models import AppSetting

def init_default_settings():
    """Create default settings if they don't exist"""
    db = SessionLocal()
    try:
        default_settings = [
            {
                'key': 'textract_page_threshold',
                'value': '100',
                'description': 'PDFs with more pages than this threshold will use Tika instead of AWS Textract'
            },
            {
                'key': 'textract_max_pages',
                'value': '500',
                'description': 'Maximum number of pages Textract can process (AWS limit)'
            }
        ]
        
        for setting_data in default_settings:
            existing = db.query(AppSetting).filter(AppSetting.key == setting_data['key']).first()
            if not existing:
                setting = AppSetting(
                    key=setting_data['key'],
                    value=setting_data['value'],
                    description=setting_data['description']
                )
                db.add(setting)
                print("Created default setting: {setting_data['key']} = {setting_data['value']}")
            else:
                print("Setting {setting_data['key']} already exists")
        
        db.commit()
        print("Default settings initialized successfully!")
        
    except Exception as e:
        print("Error initializing settings: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("Initializing VeriCase default settings...")
    init_default_settings()

