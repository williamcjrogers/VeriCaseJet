"""
Programme Management API
Handles upload and parsing of Asta Powerproject and PDF schedules
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional
# Use defusedxml to prevent XXE attacks
DEFUSED_XML = True
try:
    from defusedxml import ElementTree as ET  # type: ignore[reportMissingModuleSource]
except ImportError:
    # Fallback to standard library with security warnings
    import xml.etree.ElementTree as ET
    import logging
    logger = logging.getLogger(__name__)
    logger.warning("defusedxml not installed - XML parsing may be vulnerable to XXE attacks. Install with: pip install defusedxml")
    DEFUSED_XML = False
from datetime import datetime, timezone
import json
import io

from .db import get_db
from .models import Programme, DelayEvent, Case, Document, Evidence
from .auth import get_current_user_email
import logging

# Initialize logger
logger = logging.getLogger(__name__)

router = APIRouter()


def _sanitize_for_log(value) -> str:
    """Remove control characters to avoid log injection in logs."""
    try:
        return str(value).replace("\n", "").replace("\r", "")
    except Exception:
        return "<unprintable>"


def parse_asta_xml(xml_content: bytes) -> dict:
    """
    Parse Asta Powerproject XML export to extract activities, dates, and critical path
    
    Asta XML structure typically includes:
    - PROJECT element with metadata
    - TASK elements with IDs, names, start/finish dates
    - LINKS for dependencies
    - EXCEPTIONS_CALENDAR for working days
    """
    try:
        # In production, require defusedxml
        import os as _os
        if not DEFUSED_XML and _os.getenv("ENV", "development").lower() == "production":
            raise ValueError("Secure XML parser (defusedxml) is required in production")
        root = ET.fromstring(xml_content)
        
        activities = []
        critical_path = []
        milestones = []
        
        # Find project metadata
        project_elem = root.find('.//PROJECT')
        project_start = None
        project_finish = None
        
        if project_elem is not None:
            start_str = project_elem.get('START_DATE') or project_elem.get('start_date')
            finish_str = project_elem.get('FINISH_DATE') or project_elem.get('finish_date')
            
            if start_str:
                project_start = parse_asta_date(start_str)
            if finish_str:
                project_finish = parse_asta_date(finish_str)
        
        # Parse tasks/activities
        for task in root.findall('.//TASK'):
            activity = {
                'id': task.get('ID') or task.get('id'),
                'name': task.get('NAME') or task.get('name') or task.text,
                'start_date': parse_asta_date(task.get('START_DATE') or task.get('start_date')),
                'finish_date': parse_asta_date(task.get('FINISH_DATE') or task.get('finish_date')),
                'duration': task.get('DURATION') or task.get('duration') or '0',
                'percent_complete': task.get('PERCENT_COMPLETE') or task.get('percent_complete') or '0',
                'is_critical': task.get('CRITICAL') == 'true' or task.get('critical') == 'true',
                'is_milestone': task.get('MILESTONE') == 'true' or task.get('milestone') == 'true',
            }
            
            activities.append(activity)
            
            if activity['is_critical']:
                critical_path.append(activity['id'])
            
            if activity['is_milestone']:
                milestones.append({
                    'id': activity['id'],
                    'name': activity['name'],
                    'date': activity['start_date']
                })
        
        # If no project dates found, calculate from activities
        if not project_start and activities:
            dates = [a['start_date'] for a in activities if a['start_date']]
            if dates:
                project_start = min(dates)
        
        if not project_finish and activities:
            dates = [a['finish_date'] for a in activities if a['finish_date']]
            if dates:
                project_finish = max(dates)
        
        return {
            'activities': activities,
            'critical_path': critical_path,
            'milestones': milestones,
            'project_start': project_start,
            'project_finish': project_finish,
            'total_activities': len(activities)
        }
        
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML format: {str(e)}")


def parse_asta_date(date_str: Optional[str]) -> Optional[str]:
    """
    Parse Asta date string to ISO format
    Asta typically uses: YYYY-MM-DD or DD/MM/YYYY
    """
    if not date_str:
        return None
    
    # Try ISO format first
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.isoformat()
    except (ValueError, TypeError):
        pass
    
    # Try DD/MM/YYYY
    try:
        dt = datetime.strptime(date_str, '%d/%m/%Y')
        return dt.isoformat()
    except (ValueError, TypeError):
        pass
    
    # Try other common formats
    for fmt in ['%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y']:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.isoformat()
        except (ValueError, TypeError):
            continue
    
    logger.warning(f"Unable to parse date string: {date_str}")
    return date_str  # Return as-is if can't parse


def parse_pdf_schedule(pdf_content: bytes) -> dict:
    """
    Extract schedule data from PDF
    Uses Apache Tika for text extraction
    """
    # TODO: Implement PDF parsing using Tika
    # For now, return placeholder structure
    return {
        'activities': [],
        'critical_path': [],
        'milestones': [],
        'project_start': None,
        'project_finish': None,
        'total_activities': 0,
        'note': 'PDF parsing requires manual activity extraction or OCR'
    }


@router.post("/api/programmes/upload")
async def upload_programme(
    file: UploadFile = File(...),
    case_id: int = Form(...),
    programme_type: str = Form(...),  # as_planned, as_built, interim
    programme_date: str = Form(...),
    version_number: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user_email)
):
    """
    Upload and parse Asta Powerproject or PDF programme
    
    Supported formats:
    - .xml (Asta XML export - recommended)
    - .pp (Asta Powerproject - requires XML export first)
    - .pdf (PDF schedule - limited parsing)
    """
    # Verify case exists
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Read file content
    content = await file.read()
    
    # Determine file type and parse
    safe_name = file.filename or ""
    filename_lower = safe_name.lower()
    
    if filename_lower.endswith('.xml'):
        parsed_data = parse_asta_xml(content)
    elif filename_lower.endswith('.pp'):
        raise HTTPException(
            status_code=400,
            detail="Asta .pp files must be exported to XML format first. In Asta Powerproject: File > Export > XML"
        )
    elif filename_lower.endswith('.pdf'):
        parsed_data = parse_pdf_schedule(content)
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload .xml (Asta XML) or .pdf"
        )
    
    # Create document record
    try:
        document = Document(
            filename=file.filename,
            file_size=len(content),
            mime_type=file.content_type or 'application/octet-stream',
            uploaded_by=current_user,
            s3_key=f"programmes/{case_id}/{file.filename}"
        )
    except Exception as e:
        logger.error(f"Failed to create document record: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Failed to create document record"
        )
    
    try:
        db.add(document)
        db.flush()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save document to database: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Failed to save document to database"
        )
    
    # Create programme record
    try:
        prog_date = datetime.fromisoformat(programme_date) if programme_date else datetime.now(timezone.utc)
    except (ValueError, TypeError):
        prog_date = datetime.now(timezone.utc)
    
    try:
        proj_start = datetime.fromisoformat(parsed_data['project_start']) if parsed_data.get('project_start') else None
    except (ValueError, TypeError):
        proj_start = None
    
    try:
        proj_finish = datetime.fromisoformat(parsed_data['project_finish']) if parsed_data.get('project_finish') else None
    except (ValueError, TypeError):
        proj_finish = None
    
    programme = Programme(
        case_id=case_id,
        document_id=document.id,
        programme_type=programme_type,
        programme_date=prog_date,
        version_number=version_number,
        activities=parsed_data['activities'],
        critical_path=parsed_data['critical_path'],
        milestones=parsed_data['milestones'],
        project_start=proj_start,
        project_finish=proj_finish,
        notes=f"Uploaded by {current_user}. {parsed_data['total_activities']} activities parsed."
    )
    try:
        db.add(programme)
        db.commit()
        db.refresh(programme)
    except Exception:
        db.rollback()
        logger.error("Failed to create programme record", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to create programme record"
        )
    
    return {
        "programme_id": programme.id,
        "document_id": document.id,
        "activities_parsed": parsed_data['total_activities'],
        "critical_activities": len(parsed_data['critical_path']),
        "milestones": len(parsed_data['milestones']),
        "project_start": parsed_data.get('project_start'),
        "project_finish": parsed_data.get('project_finish')
    }


@router.get("/api/programmes/{programme_id}")
async def get_programme(
    programme_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user_email)
):
    """Get programme details"""
    try:
        programme = db.query(Programme).filter(Programme.id == programme_id).first()
    except Exception as e:
        logger.error("Database error fetching programme id=%s", _sanitize_for_log(programme_id), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch programme")
    if not programme:
        raise HTTPException(status_code=404, detail="Programme not found")
    
    return {
        "id": programme.id,
        "case_id": programme.case_id,
        "programme_type": programme.programme_type,
        "programme_date": programme.programme_date.isoformat() if programme.programme_date else None,
        "version_number": programme.version_number,
        "project_start": programme.project_start.isoformat() if programme.project_start else None,
        "project_finish": programme.project_finish.isoformat() if programme.project_finish else None,
        "activities": programme.activities,
        "critical_path": programme.critical_path,
        "milestones": programme.milestones,
        "total_activities": len(programme.activities) if programme.activities else 0,
        "notes": programme.notes
    }


@router.get("/api/cases/{case_id}/programmes")
async def list_case_programmes(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user_email)
):
    """List all programmes for a case"""
    try:
        programmes = (
            db.query(Programme)
              .filter(Programme.case_id == case_id)
              .order_by(Programme.programme_date.desc())
              .all()
        )
    except Exception:
        logger.error("Database error listing programmes for case_id=%s", _sanitize_for_log(case_id), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list programmes")

    result = []
    for p in programmes:
        result.append({
            "id": p.id,
            "programme_type": p.programme_type,
            "programme_date": p.programme_date.isoformat() if p.programme_date else None,
            "version_number": p.version_number,
            "total_activities": len(p.activities) if p.activities else 0,
            "project_start": p.project_start.isoformat() if p.project_start else None,
            "project_finish": p.project_finish.isoformat() if p.project_finish else None,
        })
    return result


@router.post("/api/programmes/compare")
async def compare_programmes(
    as_planned_id: int,
    as_built_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user_email)
):
    """
    Compare as-planned vs as-built programmes to identify delays
    
    Returns:
    - Delays on critical path
    - Total float consumed
    - Activities with slippage
    """
    try:
        as_planned = db.query(Programme).filter(Programme.id == as_planned_id).first()
        as_built = db.query(Programme).filter(Programme.id == as_built_id).first()
    except Exception:
        logger.error(
            "Database error fetching programmes for comparison planned_id=%s built_id=%s",
            _sanitize_for_log(as_planned_id), _sanitize_for_log(as_built_id),
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to fetch programmes for comparison")
    
    if not as_planned or not as_built:
        raise HTTPException(status_code=404, detail="Programme not found")
    
    if as_planned.case_id != as_built.case_id:
        raise HTTPException(status_code=400, detail="Programmes must be from the same case")
    
    delays = []
    critical_delays = []

    def _parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(date_str) if date_str else None
        except (ValueError, TypeError):
            return None
    
    # Match activities by ID
    planned_activities = {}
    for a in as_planned.activities or []:
        activity_id = a.get('id')
        if activity_id:
            planned_activities[activity_id] = a
    
    built_activities = {}
    for a in as_built.activities or []:
        activity_id = a.get('id')
        if activity_id:
            built_activities[activity_id] = a
    
    for activity_id, planned in planned_activities.items():
        built = built_activities.get(activity_id)
        if not built:
            continue
        
        # Calculate delay
        planned_start = planned.get('start_date')
        planned_finish = planned.get('finish_date')
        built_start = built.get('start_date')
        built_finish = built.get('finish_date')
        
        if planned_finish and built_finish:
            planned_dt = _parse_iso_date(planned_finish)
            built_dt = _parse_iso_date(built_finish)
            if planned_dt is None or built_dt is None:
                continue
            
            delay_days = (built_dt - planned_dt).days
            
            if delay_days != 0:
                is_critical = activity_id in (as_planned.critical_path or [])
                
                delay_info = {
                    'activity_id': activity_id,
                    'activity_name': planned['name'],
                    'planned_finish': planned_finish,
                    'actual_finish': built_finish,
                    'delay_days': delay_days,
                    'is_critical': is_critical
                }
                
                delays.append(delay_info)
                
                if is_critical:
                    critical_delays.append(delay_info)
                    
                    try:
                        # Create delay event record
                        delay_event = DelayEvent(
                            case_id=as_planned.case_id,
                            programme_id=as_built.id,
                            activity_id=activity_id,
                            activity_name=planned.get('name', 'Unknown'),
                            planned_start=_parse_iso_date(planned_start),
                            planned_finish=planned_dt,
                            actual_start=_parse_iso_date(built_start),
                            actual_finish=built_dt,
                            delay_days=delay_days,
                            is_on_critical_path=True,
                            delay_type='critical',
                            notes="Auto-detected from programme comparison"
                        )
                        db.add(delay_event)
                    except (ValueError, TypeError, KeyError) as e:
                        logger.debug(
                            "Skipping delay event creation for activity_id=%s due to invalid data",
                            _sanitize_for_log(activity_id),
                            exc_info=True
                        )
                        continue
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to persist comparison results", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save comparison results")
    
    # Calculate summary statistics
    delay_days_list = [d.get('delay_days', 0) for d in delays]
    critical_delay_days = [d.get('delay_days', 0) for d in critical_delays]
    positive_delays = [d for d in delays if d.get('delay_days', 0) > 0]
    
    return {
        "case_id": as_planned.case_id,
        "as_planned_programme": as_planned_id,
        "as_built_programme": as_built_id,
        "total_delays": len(delays),
        "critical_delays": len(critical_delays),
        "delays": sorted(delays, key=lambda x: abs(x.get('delay_days', 0)), reverse=True)[:50],
        "critical_delays": critical_delays,
        "summary": {
            "longest_delay": max(delay_days_list) if delay_days_list else 0,
            "total_delay_days": sum(critical_delay_days),
            "activities_delayed": len(positive_delays)
        }
    }


@router.get("/api/cases/{case_id}/delays")
async def list_delays(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user_email)
):
    """List all delay events for a case"""
    try:
        delays = (
            db.query(DelayEvent)
              .filter(DelayEvent.case_id == case_id)
              .order_by(DelayEvent.delay_days.desc())
              .all()
        )
    except Exception as e:
        logger.error("Database error listing delays for case_id=%s", _sanitize_for_log(case_id), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list delays")

    result = []
    for d in delays:
        result.append({
            "id": d.id,
            "activity_name": d.activity_name,
            "delay_days": d.delay_days,
            "delay_type": d.delay_type,
            "delay_cause": d.delay_cause,
            "is_on_critical_path": d.is_on_critical_path,
            "planned_finish": d.planned_finish.isoformat() if d.planned_finish else None,
            "actual_finish": d.actual_finish.isoformat() if d.actual_finish else None,
            "linked_correspondence": d.linked_correspondence_ids,
            "notes": d.notes
        })
    return result


@router.patch("/api/delays/{delay_id}/link-correspondence")
async def link_correspondence_to_delay(
    delay_id: int,
    evidence_ids: List[int],
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user_email)
):
    """Link correspondence (evidence) to a delay event"""
    try:
        delay = db.query(DelayEvent).filter(DelayEvent.id == delay_id).first()
    except Exception as e:
        logger.error("Database error fetching delay id=%s", _sanitize_for_log(delay_id), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch delay")
    if not delay:
        raise HTTPException(status_code=404, detail="Delay event not found")
    
    # Update linked correspondence
    current_links = delay.linked_correspondence_ids or []
    new_links = list(set(current_links + evidence_ids))
    
    delay.linked_correspondence_ids = new_links
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(
            "Failed to update linked correspondence for delay id=%s",
            _sanitize_for_log(delay_id),
            exc_info=True
        )
        raise HTTPException(status_code=500, detail="Failed to update delay links")
    
    return {
        "delay_id": delay_id,
        "linked_correspondence": new_links,
        "total_linked": len(new_links)
    }
