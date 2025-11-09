"""
Correspondence API Endpoints
Email correspondence management for PST analysis
"""

import uuid
import asyncio
import os
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, and_, func
from pydantic import BaseModel

from .security import get_db, current_user
from .models import (
    Case, PSTFile, EmailMessage, EmailAttachment,
    Stakeholder, Keyword, Project, User,
    Company, UserCompany, Document, DocStatus
)
from .storage import presign_put, s3, settings
from .tasks import celery_app

logger = logging.getLogger(__name__)
# Main router for correspondence features
router = APIRouter(prefix="/api/correspondence", tags=["correspondence"])

# Secondary router for wizard endpoints (no prefix for compatibility)
wizard_router = APIRouter(prefix="/api", tags=["wizard"])

# Unified router for both projects and cases
unified_router = APIRouter(prefix="/api/unified", tags=["unified"])


# ========================================
# PYDANTIC MODELS
# ========================================

class PSTUploadInitRequest(BaseModel):
    """Request to initiate PST upload"""
    case_id: Optional[str] = None  # Made optional
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

    # Verify case or project exists and user has access
    if not request.case_id and not request.project_id:
        raise HTTPException(400, "Either case_id or project_id must be provided")

    if request.case_id:
        case = db.query(Case).filter_by(id=request.case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
        entity_prefix = f"case_{request.case_id}"
    else:
        project = db.query(Project).filter_by(id=request.project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
        entity_prefix = f"project_{request.project_id}"

    # Generate PST file record
    pst_file_id = str(uuid.uuid4())
    s3_bucket = settings.S3_PST_BUCKET or settings.S3_BUCKET
    s3_key = f"{entity_prefix}/pst/{pst_file_id}/{request.filename}"
    
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
    import redis  # type: ignore[import-untyped]
    
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
    case_id: Optional[str] = Query(None, description="Case ID"),
    project_id: Optional[str] = Query(None, description="Project ID"),
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
    List emails for a case or project with filtering and pagination
    """

    # Verify case or project exists
    if not case_id and not project_id:
        raise HTTPException(400, "Either case_id or project_id must be provided")

    if case_id:
        case = db.query(Case).filter_by(id=case_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
        # Build query
        query = db.query(EmailMessage).filter_by(case_id=case_id)
    else:
        project = db.query(Project).filter_by(id=project_id).first()
        if not project:
            raise HTTPException(404, "Project not found")
        # Build query
        query = db.query(EmailMessage).filter_by(project_id=project_id)
    
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

    # Determine entity filter (case_id or project_id)
    if email.case_id:
        entity_filter = EmailMessage.case_id == email.case_id
    elif email.project_id:
        entity_filter = EmailMessage.project_id == email.project_id
    else:
        raise HTTPException(400, "Email has no case_id or project_id")

    # Find by message-id threading
    if email.message_id:
        # Find all emails with same conversation
        thread_emails = db.query(EmailMessage).filter(
            and_(
                entity_filter,
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
                entity_filter,
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
    project_name: Optional[str] = None
    project_code: Optional[str] = None
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
    case_name: Optional[str] = None
    case_id_custom: Optional[str] = None
    resolution_route: Optional[str] = None
    claimant: Optional[str] = None
    defendant: Optional[str] = None
    client: Optional[str] = None
    case_status: Optional[str] = "active"
    stakeholders: Optional[List[dict]] = []
    keywords: Optional[List[dict]] = []
    legal_team: Optional[List[dict]] = []
    heads_of_claim: Optional[List[dict]] = []
    deadlines: Optional[List[dict]] = []


# ========================================
# STAKEHOLDER AND KEYWORD ENDPOINTS
# ========================================

@wizard_router.get("/projects")
async def list_projects(
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """List projects for the current user"""
    projects = (
        db.query(Project)
        .filter(Project.owner_user_id == user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(p.id),
            "project_name": p.project_name,
            "project_code": p.project_code,
            "contract_type": p.contract_type,
        }
        for p in projects
    ]

@wizard_router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get a single project with lightweight related info (for dashboard)"""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    proj = (
        db.query(Project)
        .filter(Project.id == project_uuid, Project.owner_user_id == user.id)
        .first()
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    stakeholders = db.query(Stakeholder).filter_by(project_id=project_uuid).all()
    keywords = db.query(Keyword).filter_by(project_id=project_uuid).all()
    
    return {
        "id": str(proj.id),
        "projectName": proj.project_name,
        "projectCode": proj.project_code,
        "contractType": proj.contract_type,
        "project-stakeholders": {
            "stakeholders": [
                {
                    "stakeholder-role": s.role,
                    "stakeholder-name": s.name,
                    "stakeholder-email": s.email,
                    "organization": s.organization,
                }
                for s in stakeholders
            ],
            "keywords": [{"name": k.keyword_name} for k in keywords],
        },
    }

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
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    
    stakeholders = db.query(Stakeholder).filter(Stakeholder.project_id == project_uuid).all()
    
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
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")
    
    keywords = db.query(Keyword).filter(Keyword.project_id == project_uuid).all()
    
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
    
    # Generate default values if not provided
    project_name = request.project_name or f"Project {datetime.now().strftime('%Y%m%d-%H%M')}"
    project_code = request.project_code or f"PROJ-{uuid.uuid4().hex[:8].upper()}"
    
    project = Project(
        id=project_id,
        project_name=project_name,
        project_code=project_code,
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
        email_val = s.get('email', '')
        email_domain = email_val.split('@')[1] if email_val and '@' in str(email_val) else None
        stakeholder = Stakeholder(
            project_id=project_id,
            case_id=None,  # Project-level stakeholder
            role=s.get('role', ''),
            name=s.get('name', ''),
            email=email_val,
            organization=s.get('organization'),
            email_domain=email_domain
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
    
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        if "projects_project_code_key" in message:
            raise HTTPException(status_code=409, detail="Project code already exists")
        logger.error("Integrity error creating project %s: %s", project_id, message)
        raise HTTPException(status_code=400, detail="Invalid project data")
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create project %s: %s", project_id, exc)
        raise HTTPException(status_code=500, detail="Failed to create project")
    
    logger.info(f"Created project: {project_id}")
    
    # Inform if defaults were used
    auto_generated = []
    if not request.project_name:
        auto_generated.append("project name")
    if not request.project_code:
        auto_generated.append("project code")
    
    message = 'Project created successfully'
    if auto_generated:
        message += f'. Auto-generated: {", ".join(auto_generated)}'
    
    return {
        'id': project_id,
        'project_name': project_name,
        'project_code': project_code,
        'success': True,
        'message': message
    }


@wizard_router.post("/cases", status_code=201)
async def create_case(
    request: CaseCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Create new case"""
    
    # Ensure user is associated with a company
    user_company = (
        db.query(UserCompany)
        .filter(UserCompany.user_id == user.id, UserCompany.is_primary.is_(True))
        .first()
    )
    if user_company:
        company = user_company.company
    else:
        company = Company(name=f"{user.display_name or user.email}'s Company")
        db.add(company)
        db.flush()
        user_company = UserCompany(
            user_id=user.id,
            company_id=company.id,
            role="admin",
            is_primary=True
        )
        db.add(user_company)
        db.flush()
    
    case_uuid = uuid.uuid4()
    case_number = request.case_id_custom or f"CASE-{uuid.uuid4().hex[:10].upper()}"
    status_value = request.case_status or "active"
    
    case = Case(
        id=case_uuid,
        case_number=case_number,
        case_id_custom=request.case_id_custom,
        name=request.case_name or f"Case {datetime.now().strftime('%Y%m%d-%H%M')}",
        description=None,
        project_name=request.case_name,
        resolution_route=request.resolution_route,
        contract_type=request.resolution_route,
        claimant=request.claimant,
        defendant=request.defendant,
        client=request.client,
        status=status_value,
        case_status=status_value,
        legal_team=request.legal_team or [],
        heads_of_claim=request.heads_of_claim or [],
        deadlines=request.deadlines or [],
        owner_id=user.id,
        company_id=company.id
    )
    db.add(case)
    db.flush()
    
    # Add stakeholders
    for s in (request.stakeholders or []):
        email_val = s.get('email', '')
        email_domain = email_val.split('@')[1] if email_val and '@' in str(email_val) else None
        stakeholder = Stakeholder(
            case_id=case.id,
            project_id=None,
            role=s.get('role', ''),
            name=s.get('name', ''),
            email=email_val,
            organization=s.get('organization'),
            email_domain=email_domain
        )
        db.add(stakeholder)
    
    # Add keywords
    for k in (request.keywords or []):
        keyword = Keyword(
            case_id=case.id,
            project_id=None,
            keyword_name=k.get('name', ''),
            variations=k.get('variations'),
            is_regex=k.get('is_regex', False)
        )
        db.add(keyword)
    
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        logger.error("Integrity error creating case %s: %s", case_uuid, message)
        raise HTTPException(status_code=400, detail="Case could not be created (duplicate number?)")
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create case %s: %s", case_uuid, exc)
        raise HTTPException(status_code=500, detail="Failed to create case")
    
    logger.info("Created case %s for user %s", case_uuid, user.email)
    
    # Inform if defaults were used
    auto_generated = []
    if not request.case_name:
        auto_generated.append("case name")
    
    message = 'Case created successfully'
    if auto_generated:
        message += f'. Auto-generated: {", ".join(auto_generated)}'
    
    return {
        'id': str(case.id),
        'case_number': case.case_number,
        'case_name': case.name,
        'success': True,
        'message': message
    }


@wizard_router.post("/evidence/upload")
async def upload_evidence(
    profileId: str = Form(...),
    profileType: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Simplified upload endpoint for wizard dashboard.
    Streams file directly to S3/MinIO and queues processing tasks.
    """
    if profileType not in {"project", "case"}:
        raise HTTPException(status_code=400, detail="Invalid profile type")

    try:
        profile_uuid = uuid.UUID(profileId)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="Missing file")

    case_id = None
    project_id = None
    company_id = None

    if profileType == "case":
        case = db.query(Case).filter(Case.id == profile_uuid).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        case_id = str(case.id)
        company_id = str(case.company_id) if case.company_id else None
        project_id = None
    else:
        project = db.query(Project).filter(Project.id == profile_uuid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        project_id = str(project.id)
        company_id = str(project.owner_user_id) if getattr(project, "owner_user_id", None) else None
        if file.filename.lower().endswith(".pst"):
            raise HTTPException(status_code=400, detail="PST ingestion requires a case. Please create a case first.")

    # Prepare S3 key
    safe_name = file.filename.replace(" ", "_")
    s3_key = f"uploads/{profileType}/{profileId}/{uuid.uuid4()}_{safe_name}"
    content_type = file.content_type or "application/octet-stream"

    # Determine file size
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)

    # Upload to storage in a thread to avoid blocking event loop
    await asyncio.to_thread(
        s3().upload_fileobj,
        file.file,
        settings.MINIO_BUCKET,
        s3_key,
        ExtraArgs={"ContentType": content_type}
    )

    # Record document metadata
    document = Document(
        filename=file.filename,
        path=f"{profileType}/{profileId}",
        content_type=content_type,
        size=size,
        bucket=settings.MINIO_BUCKET,
        s3_key=s3_key,
        status=DocStatus.NEW,
        owner_user_id=user.id,
        meta={
            "profile_type": profileType,
            "profile_id": profileId,
            "uploaded_by": str(user.id)
        }
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # Queue processing
    if file.filename.lower().endswith(".pst"):
        # For projects, pass a placeholder case_id that worker will recognize
        task_case_id = case_id if case_id else "00000000-0000-0000-0000-000000000000"
        celery_app.send_task(
            "worker_app.worker.process_pst_file",
            args=[str(document.id), task_case_id, company_id or ""]
        )
        processing_state = "PROCESSING_PST"
    else:
        celery_app.send_task("worker_app.worker.ocr_and_index", args=[str(document.id)])
        processing_state = "QUEUED"

    return {
        "id": str(document.id),
        "status": processing_state,
        "case_id": case_id,
        "project_id": project_id,
        "s3_key": s3_key
    }


# ========================================
# UNIFIED ENDPOINTS (Work with both Projects and Cases)
# ========================================

@unified_router.get("/{entity_id}/evidence")
async def get_unified_evidence(
    entity_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get evidence/emails for either a project or case"""
    # Try to find as case first
    case = db.query(Case).filter(Case.id == entity_id).first()
    if case:
        # Use existing case evidence logic
        emails = db.query(EmailMessage).filter(
            EmailMessage.case_id == entity_id
        ).order_by(EmailMessage.date_sent.desc()).all()
    else:
        # Try as project
        project = db.query(Project).filter(Project.id == entity_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Entity not found")

        # Get emails associated with project
        emails = db.query(EmailMessage).filter(
            EmailMessage.project_id == entity_id
        ).order_by(EmailMessage.date_sent.desc()).all()

    return [
        {
            "id": str(email.id),
            "subject": email.subject,
            "sender_email": email.sender_email,
            "sender_name": email.sender_name,
            "recipients_to": email.recipients_to,
            "recipients_cc": email.recipients_cc,
            "date_sent": email.date_sent.isoformat() if email.date_sent else None,
            "body_text": email.body_text,
            "body_preview": email.body_preview,
            "importance": email.importance,
            "has_attachments": email.has_attachments,
            "pst_file_id": str(email.pst_file_id) if email.pst_file_id else None,
            "matched_stakeholders": email.matched_stakeholders,
            "matched_keywords": email.matched_keywords
        }
        for email in emails
    ]


@unified_router.get("/{entity_id}")
async def get_unified_entity(
    entity_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get details for either a project or case"""
    # Try to find as case first
    case = db.query(Case).filter(Case.id == entity_id).first()
    if case:
        return {
            "id": str(case.id),
            "type": "case",
            "name": case.name or case.case_number,
            "case_number": case.case_number,
            "status": case.status,
            "created_at": case.created_at.isoformat() if case.created_at else None
        }
    
    # Try as project
    project = db.query(Project).filter(Project.id == entity_id).first()
    if project:
        return {
            "id": str(project.id),
            "type": "project",
            "name": project.project_name,
            "project_code": project.project_code,
            "status": "active",  # Projects don't have status field
            "created_at": project.created_at.isoformat() if hasattr(project, 'created_at') else None
        }
    
    raise HTTPException(status_code=404, detail="Entity not found")


@unified_router.get("/{entity_id}/stakeholders")
async def get_unified_stakeholders(
    entity_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get stakeholders for either a project or case"""
    # Check if it's a case
    stakeholders = db.query(Stakeholder).filter(Stakeholder.case_id == entity_id).all()
    
    # If no case stakeholders, try project
    if not stakeholders:
        stakeholders = db.query(Stakeholder).filter(Stakeholder.project_id == entity_id).all()
    
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


@unified_router.get("/{entity_id}/keywords")  
async def get_unified_keywords(
    entity_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Get keywords for either a project or case"""
    # Check if it's a case
    keywords = db.query(Keyword).filter(Keyword.case_id == entity_id).all()
    
    # If no case keywords, try project
    if not keywords:
        keywords = db.query(Keyword).filter(Keyword.project_id == entity_id).all()
    
    return [
        {
            "id": str(k.id),
            "name": k.keyword_name,
            "variations": k.variations
        }
        for k in keywords
    ]

