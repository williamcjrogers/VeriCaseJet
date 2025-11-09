"""
Correspondence API Endpoints
Email correspondence management for PST analysis
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from pydantic import BaseModel

from .security import get_db, current_user
from .models import (
    Case, PSTFile, EmailMessage, EmailAttachment, 
    Stakeholder, Keyword, Project, User
)
from .storage import presign_put, s3, settings
from .tasks import celery_app

logger = logging.getLogger(__name__)
# Main router for correspondence features
router = APIRouter(prefix="/api/correspondence", tags=["correspondence"])

# Secondary router for wizard endpoints (no prefix for compatibility)
wizard_router = APIRouter(prefix="/api", tags=["wizard"])


# ========================================
# PYDANTIC MODELS
# ========================================

class PSTUploadInitRequest(BaseModel):
    """Request to initiate PST upload"""
    case_id: str
    filename: str
    file_size: int
    project_id: Optional[str] = None


class PSTUploadInitResponse(BaseModel):
    """Response with presigned upload URL"""
    pst_file_id: str
    upload_url: str
    s3_bucket: str
    s3_key: str
    

class PSTProcessingStatus(BaseModel):
    """PST processing status"""
    pst_file_id: str
    status: str  # queued, processing, completed, failed
    total_emails: int
    processed_emails: int
    progress_percent: float
    error_message: Optional[str] = None


class EmailMessageSummary(BaseModel):
    """Email message summary for list view"""
    id: str
    subject: Optional[str]
    sender_email: Optional[str]
    sender_name: Optional[str]
    date_sent: Optional[datetime]
    has_attachments: bool
    matched_stakeholders: Optional[List[str]]
    matched_keywords: Optional[List[str]]
    importance: Optional[str]


class EmailMessageDetail(BaseModel):
    """Full email message details"""
    id: str
    subject: Optional[str]
    sender_email: Optional[str]
    sender_name: Optional[str]
    recipients_to: Optional[List[dict]]
    recipients_cc: Optional[List[dict]]
    date_sent: Optional[datetime]
    date_received: Optional[datetime]
    body_text: Optional[str]
    body_html: Optional[str]
    has_attachments: bool
    attachments: List[dict]
    matched_stakeholders: Optional[List[str]]
    matched_keywords: Optional[List[str]]
    importance: Optional[str]
    pst_message_path: Optional[str]


class EmailListResponse(BaseModel):
    """Paginated email list"""
    total: int
    emails: List[EmailMessageSummary]
    page: int
    page_size: int


# ========================================
# PST UPLOAD ENDPOINTS
# ========================================

@router.post("/pst/upload/init", response_model=PSTUploadInitResponse)
async def init_pst_upload(
    request: PSTUploadInitRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Initialize PST file upload
    Returns presigned S3 URL for direct browser upload
    """
    
    # Verify case exists and user has access
    case = db.query(Case).filter_by(id=request.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    
    # Generate PST file record
    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    s3_key = f"case_{request.case_id}/pst/{pst_file_id}/{request.filename}"
    
    # Create PST file record
    pst_file = PSTFile(
        id=pst_file_id,
        filename=request.filename,
        case_id=request.case_id,
        project_id=request.project_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size=request.file_size,
        processing_status='queued',
        uploaded_by=user.id
    )
    
    db.add(pst_file)
    db.commit()
    
    # Generate presigned upload URL (valid for 4 hours for large files)
    upload_url = presign_put(s3_bucket, s3_key, expires_in=14400)
    
    logger.info(f"Initiated PST upload: {pst_file_id} for case {request.case_id}")
    
    return PSTUploadInitResponse(
        pst_file_id=pst_file_id,
        upload_url=upload_url,
        s3_bucket=s3_bucket,
        s3_key=s3_key
    )


@router.post("/pst/{pst_file_id}/process")
async def start_pst_processing(
    pst_file_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Start PST processing after upload completes
    Enqueues Celery task for background processing
    """
    
    # Get PST file record
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")
    
    # Verify case access
    case = db.query(Case).filter_by(id=pst_file.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    
    # Enqueue Celery task using coordinator for better scalability
    task = celery_app.send_task(
        'worker_app.worker.coordinate_pst_processing',  # Use coordinator
        args=[pst_file_id, pst_file.s3_bucket, pst_file.s3_key],
        queue=settings.CELERY_PST_QUEUE if hasattr(settings, 'CELERY_PST_QUEUE') else settings.CELERY_QUEUE
    )
    
    logger.info(f"Enqueued PST processing task {task.id} for file {pst_file_id}")
    
    return {
        'success': True,
        'task_id': task.id,
        'pst_file_id': pst_file_id,
        'message': 'PST processing started'
    }


@router.get("/pst/{pst_file_id}/status", response_model=PSTProcessingStatus)
async def get_pst_status(
    pst_file_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get PST processing status with Redis-based progress tracking"""
    import redis
    
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    if not pst_file:
        raise HTTPException(404, "PST file not found")
    
    # Try to get detailed progress from Redis
    try:
        redis_client = redis.from_url(settings.REDIS_URL)
        redis_key = f"pst:{pst_file_id}"
        redis_data = redis_client.hgetall(redis_key)
        
        if redis_data:
            # Decode Redis data (bytes to string)
            redis_data = {k.decode(): v.decode() for k, v in redis_data.items()}
            
            # Get chunk progress
            total_chunks = int(redis_data.get('total_chunks', 0))
            completed_chunks = int(redis_data.get('completed_chunks', 0))
            failed_chunks = int(redis_data.get('failed_chunks', 0))
            
            # Calculate progress based on chunks
            if total_chunks > 0:
                progress = ((completed_chunks + failed_chunks) / total_chunks) * 100.0
            else:
                progress = 0.0
                
            # Get processed emails from Redis
            processed_emails = int(redis_data.get('processed_emails', pst_file.processed_emails or 0))
            
            # Update database with latest count
            if processed_emails > (pst_file.processed_emails or 0):
                pst_file.processed_emails = processed_emails
                db.commit()
            
            return PSTProcessingStatus(
                pst_file_id=str(pst_file.id),
                status=redis_data.get('status', pst_file.processing_status),
                total_emails=pst_file.total_emails or 0,
                processed_emails=processed_emails,
                progress_percent=round(progress, 1),
                error_message=pst_file.error_message
            )
    except Exception as e:
        logger.warning(f"Could not get Redis progress for {pst_file_id}: {e}")
    
    # Fall back to database progress
    progress = 0.0
    if pst_file.total_emails > 0:
        progress = (pst_file.processed_emails / pst_file.total_emails) * 100.0
    
    return PSTProcessingStatus(
        pst_file_id=str(pst_file.id),
        status=pst_file.processing_status,
        total_emails=pst_file.total_emails or 0,
        processed_emails=pst_file.processed_emails or 0,
        progress_percent=round(progress, 1),
        error_message=pst_file.error_message
    )


# ========================================
# EMAIL CORRESPONDENCE ENDPOINTS
# ========================================

@router.get("/emails", response_model=EmailListResponse)
async def list_emails(
    case_id: str = Query(..., description="Case ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None, description="Search in subject and body"),
    stakeholder_id: Optional[str] = Query(None, description="Filter by stakeholder"),
    keyword_id: Optional[str] = Query(None, description="Filter by keyword"),
    has_attachments: Optional[bool] = Query(None, description="Filter by attachments"),
    date_from: Optional[datetime] = Query(None, description="Date range start"),
    date_to: Optional[datetime] = Query(None, description="Date range end"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    List emails for a case with filtering and pagination
    """
    
    # Verify case exists
    case = db.query(Case).filter_by(id=case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    
    # Build query
    query = db.query(EmailMessage).filter_by(case_id=case_id)
    
    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                EmailMessage.subject.ilike(search_term),
                EmailMessage.body_text.ilike(search_term),
                EmailMessage.sender_email.ilike(search_term),
                EmailMessage.sender_name.ilike(search_term)
            )
        )
    
    if stakeholder_id:
        query = query.filter(
            func.jsonb_exists(EmailMessage.matched_stakeholders, stakeholder_id)
        )
    
    if keyword_id:
        query = query.filter(
            func.jsonb_exists(EmailMessage.matched_keywords, keyword_id)
        )
    
    if has_attachments is not None:
        query = query.filter_by(has_attachments=has_attachments)
    
    if date_from:
        query = query.filter(EmailMessage.date_sent >= date_from)
    
    if date_to:
        query = query.filter(EmailMessage.date_sent <= date_to)
    
    # Get total count
    total = query.count()
    
    # Apply pagination and ordering
    offset = (page - 1) * page_size
    emails = query.order_by(EmailMessage.date_sent.desc()).offset(offset).limit(page_size).all()
    
    # Convert to summaries
    email_summaries = [
        EmailMessageSummary(
            id=str(e.id),
            subject=e.subject,
            sender_email=e.sender_email,
            sender_name=e.sender_name,
            date_sent=e.date_sent,
            has_attachments=e.has_attachments,
            matched_stakeholders=e.matched_stakeholders,
            matched_keywords=e.matched_keywords,
            importance=e.importance
        )
        for e in emails
    ]
    
    return EmailListResponse(
        total=total,
        emails=email_summaries,
        page=page,
        page_size=page_size
    )


@router.get("/emails/{email_id}", response_model=EmailMessageDetail)
async def get_email_detail(
    email_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get full email details including attachments"""
    
    email = db.query(EmailMessage).filter_by(id=email_id).first()
    if not email:
        raise HTTPException(404, "Email not found")
    
    # Get attachments
    attachments = db.query(EmailAttachment).filter_by(email_message_id=email_id).all()
    
    # Generate presigned URLs for attachments
    attachment_list = []
    for att in attachments:
        try:
            from .storage import presign_get
            download_url = presign_get(att.s3_bucket, att.s3_key, expires_in=3600)
            attachment_list.append({
                'id': str(att.id),
                'filename': att.filename,
                'content_type': att.content_type,
                'file_size': att.file_size,
                'download_url': download_url,
                'has_been_ocred': att.has_been_ocred
            })
        except Exception as e:
            logger.error(f"Error generating presigned URL for attachment {att.id}: {e}")
    
    return EmailMessageDetail(
        id=str(email.id),
        subject=email.subject,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        recipients_to=email.recipients_to,
        recipients_cc=email.recipients_cc,
        date_sent=email.date_sent,
        date_received=email.date_received,
        body_text=email.body_text,
        body_html=email.body_html,
        has_attachments=email.has_attachments,
        attachments=attachment_list,
        matched_stakeholders=email.matched_stakeholders,
        matched_keywords=email.matched_keywords,
        importance=email.importance,
        pst_message_path=email.pst_message_path
    )


@router.get("/emails/{email_id}/thread")
async def get_email_thread(
    email_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get full email thread containing this email"""
    
    email = db.query(EmailMessage).filter_by(id=email_id).first()
    if not email:
        raise HTTPException(404, "Email not found")
    
    # Build thread by finding all related emails
    thread_emails = []
    
    # Find by message-id threading
    if email.message_id:
        # Find all emails with same conversation
        thread_emails = db.query(EmailMessage).filter(
            and_(
                EmailMessage.case_id == email.case_id,
                or_(
                    EmailMessage.message_id == email.message_id,
                    EmailMessage.in_reply_to == email.message_id,
                    EmailMessage.email_references.contains(email.message_id)
                )
            )
        ).order_by(EmailMessage.date_sent).all()
    
    # Fall back to conversation index
    if not thread_emails and email.conversation_index:
        thread_emails = db.query(EmailMessage).filter(
            and_(
                EmailMessage.case_id == email.case_id,
                EmailMessage.conversation_index == email.conversation_index
            )
        ).order_by(EmailMessage.date_sent).all()
    
    # Convert to summaries
    thread_summaries = [
        {
            'id': str(e.id),
            'subject': e.subject,
            'sender_email': e.sender_email,
            'sender_name': e.sender_name,
            'date_sent': e.date_sent.isoformat() if e.date_sent else None,
            'has_attachments': e.has_attachments,
            'is_current': str(e.id) == email_id
        }
        for e in thread_emails
    ]
    
    return {
        'thread_size': len(thread_summaries),
        'emails': thread_summaries
    }


# ========================================
# PROJECTS & CASES (for wizard)
# ========================================

class ProjectCreateRequest(BaseModel):
    """Create project from wizard"""
    project_name: str
    project_code: str
    start_date: Optional[datetime] = None
    completion_date: Optional[datetime] = None
    contract_type: Optional[str] = None
    stakeholders: Optional[List[dict]] = []
    keywords: Optional[List[dict]] = []
    # Retrospective analysis fields
    analysis_type: Optional[str] = None  # 'retrospective' or 'project'
    project_aliases: Optional[str] = None
    site_address: Optional[str] = None
    include_domains: Optional[str] = None
    exclude_people: Optional[str] = None
    project_terms: Optional[str] = None
    exclude_keywords: Optional[str] = None


class CaseCreateRequest(BaseModel):
    """Create case from wizard"""
    case_name: str
    case_id_custom: Optional[str] = None
    resolution_route: Optional[str] = None
    claimant: Optional[str] = None
    defendant: Optional[str] = None
    client: Optional[str] = None
    stakeholders: Optional[List[dict]] = []
    keywords: Optional[List[dict]] = []


# ========================================
# STAKEHOLDER AND KEYWORD ENDPOINTS
# ========================================

@wizard_router.get("/cases/{case_id}/stakeholders")
async def get_case_stakeholders(
    case_id: str,
    db: Session = Depends(get_db)
):
    """Get stakeholders for a case"""
    stakeholders = db.query(Stakeholder).filter_by(case_id=case_id).all()
    
    return [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization
        }
        for s in stakeholders
    ]

@wizard_router.get("/cases/{case_id}/keywords")
async def get_case_keywords(
    case_id: str,
    db: Session = Depends(get_db)
):
    """Get keywords for a case"""
    keywords = db.query(Keyword).filter_by(case_id=case_id).all()
    
    return [
        {
            "id": str(k.id),
            "name": k.keyword_name,
            "variations": k.variations
        }
        for k in keywords
    ]

@wizard_router.get("/projects/{project_id}/stakeholders")
async def get_project_stakeholders(
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get stakeholders for a project"""
    stakeholders = db.query(Stakeholder).filter_by(project_id=project_id).all()
    
    return [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization
        }
        for s in stakeholders
    ]

@wizard_router.get("/projects/{project_id}/keywords")
async def get_project_keywords(
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get keywords for a project"""
    keywords = db.query(Keyword).filter_by(project_id=project_id).all()
    
    return [
        {
            "id": str(k.id),
            "name": k.keyword_name,
            "variations": k.variations
        }
        for k in keywords
    ]

@wizard_router.post("/projects", status_code=201)
async def create_project(
    request: ProjectCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Create new project"""
    
    project_id = str(uuid.uuid4())
    
    project = Project(
        id=project_id,
        project_name=request.project_name,
        project_code=request.project_code,
        start_date=request.start_date,
        completion_date=request.completion_date,
        contract_type=request.contract_type,
        analysis_type=request.analysis_type,
        project_aliases=request.project_aliases,
        site_address=request.site_address,
        include_domains=request.include_domains,
        exclude_people=request.exclude_people,
        project_terms=request.project_terms,
        exclude_keywords=request.exclude_keywords,
        owner_user_id=user.id
    )
    
    db.add(project)
    
    # Add stakeholders
    for s in (request.stakeholders or []):
        stakeholder = Stakeholder(
            project_id=project_id,
            case_id=None,  # Project-level stakeholder
            role=s.get('role', ''),
            name=s.get('name', ''),
            email=s.get('email'),
            organization=s.get('organization'),
            email_domain=s.get('email', '').split('@')[1] if s.get('email') and '@' in s.get('email') else None
        )
        db.add(stakeholder)
    
    # Add keywords
    for k in (request.keywords or []):
        keyword = Keyword(
            project_id=project_id,
            case_id=None,
            keyword_name=k.get('name', ''),
            variations=k.get('variations'),
            is_regex=k.get('is_regex', False)
        )
        db.add(keyword)
    
    db.commit()
    
    logger.info(f"Created project: {project_id}")
    
    return {
        'id': project_id,
        'success': True,
        'message': 'Project created successfully'
    }


@wizard_router.post("/cases", status_code=201)
async def create_case(
    request: CaseCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Create new case"""
    
    case_id = str(uuid.uuid4())
    
    case = Case(
        id=case_id,
        case_name=request.case_name,
        case_id_custom=request.case_id_custom,
        resolution_route=request.resolution_route,
        claimant=request.claimant,
        defendant=request.defendant,
        case_status='active',
        client=request.client
    )
    
    db.add(case)
    
    # Add stakeholders
    for s in (request.stakeholders or []):
        stakeholder = Stakeholder(
            case_id=case_id,
            project_id=None,
            role=s.get('role', ''),
            name=s.get('name', ''),
            email=s.get('email'),
            organization=s.get('organization'),
            email_domain=s.get('email', '').split('@')[1] if s.get('email') and '@' in s.get('email') else None
        )
        db.add(stakeholder)
    
    # Add keywords
    for k in (request.keywords or []):
        keyword = Keyword(
            case_id=case_id,
            project_id=None,
            keyword_name=k.get('name', ''),
            variations=k.get('variations'),
            is_regex=k.get('is_regex', False)
        )
        db.add(keyword)
    
    db.commit()
    
    logger.info(f"Created case: {case_id}")
    
    return {
        'id': case_id,
        'success': True,
        'message': 'Case created successfully'
    }

