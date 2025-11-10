"""
Simple Cases API for testing without authentication
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, select
from typing import List
from datetime import datetime, timezone
import uuid
import logging

from .db import get_db
from .models import Case

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["simple-cases"])

@router.get("/cases")
def list_cases_simple(db: Session = Depends(get_db)):
    """List all cases without authentication (for testing)"""
    try:
        # Use SQLAlchemy parameterized Core/ORM query to prevent SQL injection
        stmt = select(Case).order_by(desc(Case.created_at)).limit(50)
        cases = db.execute(stmt).scalars().all()
        
        result = []
        for case in cases:
            try:
                # Safe attribute access with error handling
                result.append({
                    "id": str(case.id),
                    "name": case.name or "Untitled Case",
                    "case_number": getattr(case, 'case_number', f"CASE-{case.id}"),
                    "description": case.description,
                    "project_name": getattr(case, 'project_name', None),
                    "contract_type": getattr(case, 'contract_type', None),
                    "dispute_type": getattr(case, 'dispute_type', None),
                    "status": getattr(case, 'status', 'active'),
                    "created_at": case.created_at.isoformat() if case.created_at else None,
                    "evidence_count": 0,  # TODO: Count evidence
                    "issue_count": 0      # TODO: Count issues
                })
            except (AttributeError, TypeError, ValueError) as e:
                logger.warning(f"Error processing case {case.id}: {e}", exc_info=True)
                continue
        
        return result
        
    except Exception as e:
        logger.error(f"Database error while listing cases: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve cases")

@router.post("/cases")
def create_case_simple(case_data: dict, db: Session = Depends(get_db)):
    """Create a case without authentication (for testing)"""
    try:
        # Validate case_data is a dictionary
        if not isinstance(case_data, dict):
            raise HTTPException(status_code=400, detail="Invalid request data")
        
        try:
            case = Case(
                id=uuid.uuid4(),
                name=case_data.get('name', 'New Case'),
                description=case_data.get('description'),
                # Add other fields if they exist in the model
            )
        except (ValueError, TypeError) as e:
            logger.error(f"Error creating Case object: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid case data: {str(e)}")
        
        # Only add fields that exist in the model
        if hasattr(Case, 'case_number'):
            case.case_number = case_data.get('case_number', f"CASE-{uuid.uuid4().hex[:8]}")
        if hasattr(Case, 'project_name'):
            case.project_name = case_data.get('project_name')
        if hasattr(Case, 'contract_type'):
            case.contract_type = case_data.get('contract_type')
        if hasattr(Case, 'dispute_type'):
            case.dispute_type = case_data.get('dispute_type')
        if hasattr(Case, 'status'):
            case.status = 'active'
        
        try:
            db.add(case)
            db.commit()
            db.refresh(case)
        except Exception as db_error:
            db.rollback()
            logger.error(f"Database error while creating case: {db_error}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to create case in database")
        
        return {
            "id": str(case.id),
            "name": case.name,
            "case_number": getattr(case, 'case_number', f"CASE-{case.id}"),
            "description": case.description,
            "project_name": getattr(case, 'project_name', None),
            "contract_type": getattr(case, 'contract_type', None),
            "dispute_type": getattr(case, 'dispute_type', None),
            "status": getattr(case, 'status', 'active'),
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "evidence_count": 0,
            "issue_count": 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating case: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create case")