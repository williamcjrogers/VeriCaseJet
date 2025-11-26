"""
Evidence Repository API Endpoints
Case-independent evidence management with intelligent linking
"""

import uuid
import hashlib
import logging
from datetime import datetime, date, timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func, desc
from pydantic import BaseModel

from .security import get_db, current_user
from .models import (
    User, Case, Project, EmailMessage,
    EvidenceItem, EvidenceCollection,
    EvidenceCorrespondenceLink, EvidenceRelation,
    EvidenceCollectionItem, EvidenceActivityLog,
    EvidenceType, DocumentCategory,
    CorrespondenceLinkType, EvidenceRelationType
)
from .storage import presign_put, presign_get, s3
from .config import settings
from .cache import get_cached, set_cached

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evidence", tags=["evidence-repository"])


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class EvidenceUploadInitRequest(BaseModel):
    """Request to initiate evidence upload"""
    filename: str
    file_size: int
    content_type: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None
    tags: list[str] | None = None


class EvidenceUploadInitResponse(BaseModel):
    """Response with presigned upload URL"""
    evidence_id: str
    upload_url: str
    s3_bucket: str
    s3_key: str


class EvidenceItemCreate(BaseModel):
    """Create evidence item after upload"""
    filename: str
    s3_key: str
    file_size: int
    file_hash: str
    mime_type: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None
    evidence_type: str | None = None
    title: str | None = None
    description: str | None = None
    document_date: date | None = None
    tags: list[str] | None = None


class EvidenceItemUpdate(BaseModel):
    """Update evidence item"""
    title: str | None = None
    description: str | None = None
    evidence_type: str | None = None
    document_category: str | None = None
    document_date: date | None = None
    manual_tags: list[str] | None = None
    notes: str | None = None
    is_starred: bool | None = None
    is_privileged: bool | None = None
    is_confidential: bool | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None


class EvidenceItemSummary(BaseModel):
    """Evidence item summary for list view"""
    id: str
    filename: str
    file_type: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    evidence_type: str | None = None
    document_category: str | None = None
    document_date: date | None = None
    title: str | None = None
    processing_status: str
    is_starred: bool = False
    is_reviewed: bool = False
    has_correspondence: bool = False
    correspondence_count: int = 0
    correspondence_link_count: int = 0  # Alias for frontend compatibility
    auto_tags: list[str] = []
    manual_tags: list[str] = []
    case_id: str | None = None
    project_id: str | None = None
    source_type: str | None = None
    source_email_id: str | None = None
    source_email_subject: str | None = None
    source_email_from: str | None = None
    download_url: str | None = None
    created_at: datetime


class EvidenceItemDetail(BaseModel):
    """Full evidence item details"""
    id: str
    filename: str
    original_path: str | None = None
    file_type: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    file_hash: str
    evidence_type: str | None = None
    document_category: str | None = None
    document_date: date | None = None
    title: str | None = None
    author: str | None = None
    description: str | None = None
    page_count: int | None = None
    extracted_text: str | None = None
    extracted_parties: list[dict[str, Any]] = []
    extracted_dates: list[dict[str, Any]] = []
    extracted_amounts: list[dict[str, Any]] = []
    extracted_references: list[dict[str, Any]] = []
    auto_tags: list[str] = []
    manual_tags: list[str] = []
    processing_status: str
    source_type: str | None = None
    source_path: str | None = None
    is_duplicate: bool = False
    is_starred: bool = False
    is_privileged: bool = False
    is_confidential: bool = False
    is_reviewed: bool = False
    notes: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    collection_id: str | None = None
    correspondence_links: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    download_url: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class EvidenceListResponse(BaseModel):
    """Paginated evidence list"""
    total: int
    items: list[EvidenceItemSummary]
    page: int
    page_size: int


class CollectionCreate(BaseModel):
    """Create collection"""
    name: str
    description: str | None = None
    parent_id: str | None = None
    case_id: str | None = None
    project_id: str | None = None
    color: str | None = None
    icon: str | None = None
    filter_rules: dict[str, Any] | None = None


class CollectionUpdate(BaseModel):
    """Update collection"""
    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    filter_rules: dict[str, Any] | None = None


class CollectionSummary(BaseModel):
    """Collection summary"""
    id: str
    name: str
    description: str | None = None
    collection_type: str
    parent_id: str | None = None
    item_count: int = 0
    is_system: bool = False
    color: str | None = None
    icon: str | None = None
    case_id: str | None = None
    project_id: str | None = None


class CorrespondenceLinkCreate(BaseModel):
    """Create correspondence link"""
    email_message_id: str | None = None
    link_type: str = "related"
    correspondence_type: str | None = None
    correspondence_reference: str | None = None
    correspondence_date: date | None = None
    correspondence_from: str | None = None
    correspondence_to: str | None = None
    correspondence_subject: str | None = None
    context_snippet: str | None = None


class AssignRequest(BaseModel):
    """Assign evidence to case/project"""
    case_id: str | None = None
    project_id: str | None = None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_file_type(filename: str) -> str:
    """Extract file extension as type"""
    if '.' in filename:
        return filename.rsplit('.', 1)[1].lower()
    return 'unknown'


def compute_file_hash(file_content: bytes) -> str:
    """Compute SHA-256 hash of file content"""
    return hashlib.sha256(file_content).hexdigest()


def log_activity(
    db: Session,
    action: str,
    user_id: uuid.UUID,
    evidence_item_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Log evidence activity"""
    activity = EvidenceActivityLog(
        evidence_item_id=evidence_item_id,
        collection_id=collection_id,
        action=action,
        action_details=details,
        user_id=user_id,
        ip_address=ip_address
    )
    db.add(activity)


def get_default_user(db: Session) -> User:
    """Get or create default admin user"""
    user = db.query(User).filter(User.email == "admin@vericase.com").first()
    if not user:
        from .security import hash_password
        from .models import UserRole
        user = User(
            email="admin@vericase.com",
            password_hash=hash_password("admin123"),
            role=UserRole.ADMIN,
            is_active=True,
            email_verified=True,
            display_name="Administrator"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ============================================================================
# UPLOAD ENDPOINTS
# ============================================================================

@router.post("/upload/init", response_model=EvidenceUploadInitResponse)
async def init_evidence_upload(
    request: EvidenceUploadInitRequest,
    db: Session = Depends(get_db)
):
    """
    Initialize evidence file upload
    Returns presigned S3 URL for direct browser upload
    Case/project association is optional
    """
    user = get_default_user(db)
    
    # Generate evidence file record
    evidence_id = str(uuid.uuid4())
    s3_bucket = settings.S3_BUCKET or settings.MINIO_BUCKET
    
    # Build S3 key - organize by date and ID
    date_prefix = datetime.now().strftime('%Y/%m')
    safe_filename = request.filename.replace(' ', '_')
    s3_key = f"evidence/{date_prefix}/{evidence_id}/{safe_filename}"
    
    # Generate presigned upload URL (valid for 4 hours for large files)
    content_type = request.content_type or "application/octet-stream"
    upload_url = presign_put(
        s3_key,
        content_type,
        expires=14400,
        bucket=s3_bucket
    )
    
    logger.info(f"Initiated evidence upload: {evidence_id}")
    
    return EvidenceUploadInitResponse(
        evidence_id=evidence_id,
        upload_url=upload_url,
        s3_bucket=s3_bucket,
        s3_key=s3_key
    )


@router.post("/upload/complete")
async def complete_evidence_upload(
    request: EvidenceItemCreate,
    db: Session = Depends(get_db)
):
    """
    Complete evidence upload after file is uploaded to S3
    Creates the evidence item record
    """
    user = get_default_user(db)
    s3_bucket = settings.S3_BUCKET or settings.MINIO_BUCKET
    
    # Check for duplicates by hash
    existing = db.query(EvidenceItem).filter(
        EvidenceItem.file_hash == request.file_hash
    ).first()
    
    is_duplicate = existing is not None
    duplicate_of_id = existing.id if existing else None
    
    # Create evidence item
    evidence_item = EvidenceItem(
        filename=request.filename,
        file_type=get_file_type(request.filename),
        mime_type=request.mime_type,
        file_size=request.file_size,
        file_hash=request.file_hash,
        s3_bucket=s3_bucket,
        s3_key=request.s3_key,
        evidence_type=request.evidence_type,
        title=request.title or request.filename,
        description=request.description,
        document_date=request.document_date,
        manual_tags=request.tags or [],
        processing_status='pending',
        source_type='direct_upload',
        case_id=uuid.UUID(request.case_id) if request.case_id else None,
        project_id=uuid.UUID(request.project_id) if request.project_id else None,
        collection_id=uuid.UUID(request.collection_id) if request.collection_id else None,
        is_duplicate=is_duplicate,
        duplicate_of_id=duplicate_of_id,
        uploaded_by=user.id
    )
    
    db.add(evidence_item)
    db.commit()
    db.refresh(evidence_item)
    
    # Log activity
    log_activity(
        db, 'upload', user.id,
        evidence_item_id=evidence_item.id,
        details={'filename': request.filename, 'size': request.file_size}
    )
    db.commit()
    
    # TODO: Queue background processing task for OCR/classification
    
    logger.info(f"Created evidence item: {evidence_item.id}")
    
    return {
        'id': str(evidence_item.id),
        'filename': evidence_item.filename,
        'is_duplicate': is_duplicate,
        'duplicate_of_id': str(duplicate_of_id) if duplicate_of_id else None,
        'processing_status': evidence_item.processing_status,
        'message': 'Evidence uploaded successfully'
    }


@router.post("/upload/direct")
async def direct_upload_evidence(
    file: UploadFile = File(...),
    case_id: str | None = Form(None),
    project_id: str | None = Form(None),
    collection_id: str | None = Form(None),
    evidence_type: str | None = Form(None),
    tags: str | None = Form(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Direct file upload (streams file to S3)
    For smaller files - convenience endpoint
    """
    user = get_default_user(db)
    
    if not file.filename:
        raise HTTPException(400, "Missing filename")
    
    # Read file content
    content = await file.read()
    file_hash = compute_file_hash(content)
    file_size = len(content)
    
    # Check for duplicates
    existing = db.query(EvidenceItem).filter(
        EvidenceItem.file_hash == file_hash
    ).first()
    
    is_duplicate = existing is not None
    duplicate_of_id = existing.id if existing else None
    
    # Upload to S3
    s3_bucket = settings.S3_BUCKET or settings.MINIO_BUCKET
    evidence_id = str(uuid.uuid4())
    date_prefix = datetime.now().strftime('%Y/%m')
    safe_filename = file.filename.replace(' ', '_')
    s3_key = f"evidence/{date_prefix}/{evidence_id}/{safe_filename}"
    
    s3_client = s3()
    s3_client.put_object(
        Bucket=s3_bucket,
        Key=s3_key,
        Body=content,
        ContentType=file.content_type or "application/octet-stream"
    )
    
    # Parse tags
    tag_list = []
    if tags:
        tag_list = [t.strip() for t in tags.split(',') if t.strip()]
    
    # Create evidence item
    evidence_item = EvidenceItem(
        id=uuid.UUID(evidence_id),
        filename=file.filename,
        file_type=get_file_type(file.filename),
        mime_type=file.content_type,
        file_size=file_size,
        file_hash=file_hash,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        evidence_type=evidence_type,
        title=file.filename,
        manual_tags=tag_list,
        processing_status='pending',
        source_type='direct_upload',
        case_id=uuid.UUID(case_id) if case_id else None,
        project_id=uuid.UUID(project_id) if project_id else None,
        collection_id=uuid.UUID(collection_id) if collection_id else None,
        is_duplicate=is_duplicate,
        duplicate_of_id=duplicate_of_id,
        uploaded_by=user.id
    )
    
    db.add(evidence_item)
    
    # Log activity
    log_activity(
        db, 'upload', user.id,
        evidence_item_id=evidence_item.id,
        details={'filename': file.filename, 'size': file_size}
    )
    
    db.commit()
    db.refresh(evidence_item)
    
    return {
        'id': str(evidence_item.id),
        'filename': evidence_item.filename,
        'is_duplicate': is_duplicate,
        'duplicate_of_id': str(duplicate_of_id) if duplicate_of_id else None,
        'processing_status': evidence_item.processing_status,
        'message': 'Evidence uploaded successfully'
    }


# ============================================================================
# EVIDENCE ITEM ENDPOINTS
# ============================================================================

@router.get("/items", response_model=EvidenceListResponse)
async def list_evidence(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = Query(None, description="Search in filename, title, text"),
    evidence_type: str | None = Query(None),
    document_category: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    has_correspondence: bool | None = Query(None),
    is_starred: bool | None = Query(None),
    is_reviewed: bool | None = Query(None),
    include_email_info: bool = Query(False, description="Include emails from correspondence as evidence items"),
    unassigned: bool | None = Query(None, description="Only show items not in any case/project"),
    case_id: str | None = Query(None),
    project_id: str | None = Query(None),
    collection_id: str | None = Query(None),
    processing_status: str | None = Query(None),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="asc or desc"),
    db: Session = Depends(get_db),
) -> EvidenceListResponse:
    """
    List evidence items with filtering and pagination
    """
    query = db.query(EvidenceItem)
    
    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                EvidenceItem.filename.ilike(search_term),
                EvidenceItem.title.ilike(search_term),
                EvidenceItem.extracted_text.ilike(search_term),
                EvidenceItem.description.ilike(search_term)
            )
        )
    
    if evidence_type:
        query = query.filter(EvidenceItem.evidence_type == evidence_type)
    
    if document_category:
        query = query.filter(EvidenceItem.document_category == document_category)
    
    if date_from:
        query = query.filter(EvidenceItem.document_date >= date_from)
    
    if date_to:
        query = query.filter(EvidenceItem.document_date <= date_to)
    
    if tags:
        tag_list = [t.strip() for t in tags.split(',')]
        for tag in tag_list:
            query = query.filter(
                or_(
                    EvidenceItem.manual_tags.contains([tag]),
                    EvidenceItem.auto_tags.contains([tag])
                )
            )
    
    if is_starred is not None:
        query = query.filter(EvidenceItem.is_starred == is_starred)
    
    if is_reviewed is not None:
        query = query.filter(EvidenceItem.is_reviewed == is_reviewed)
    
    if unassigned:
        query = query.filter(
            and_(
                EvidenceItem.case_id.is_(None),
                EvidenceItem.project_id.is_(None)
            )
        )
    
    if case_id:
        query = query.filter(EvidenceItem.case_id == uuid.UUID(case_id))
    
    if project_id:
        query = query.filter(EvidenceItem.project_id == uuid.UUID(project_id))
    
    if collection_id:
        # Join with collection items
        query = query.join(
            EvidenceCollectionItem,
            EvidenceCollectionItem.evidence_item_id == EvidenceItem.id
        ).filter(
            EvidenceCollectionItem.collection_id == uuid.UUID(collection_id)
        )
    
    if processing_status:
        query = query.filter(EvidenceItem.processing_status == processing_status)
    
    # Get total count before pagination
    total = query.count()
    
    # Apply sorting
    sort_column = getattr(EvidenceItem, sort_by, EvidenceItem.created_at)
    if sort_order == "desc":
        query = query.order_by(desc(sort_column))
    else:
        query = query.order_by(sort_column)
    
    # Apply pagination
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()
    
    # Get correspondence counts for items
    item_ids = [item.id for item in items]
    correspondence_counts = {}
    if item_ids:
        counts = db.query(
            EvidenceCorrespondenceLink.evidence_item_id,
            func.count(EvidenceCorrespondenceLink.id)
        ).filter(
            EvidenceCorrespondenceLink.evidence_item_id.in_(item_ids)
        ).group_by(EvidenceCorrespondenceLink.evidence_item_id).all()
        
        correspondence_counts = {str(item_id): count for item_id, count in counts}
    
    # Get source email info for items with source_email_id
    email_info = {}
    source_email_ids = [item.source_email_id for item in items if item.source_email_id]
    if source_email_ids:
        emails = db.query(EmailMessage).filter(
            EmailMessage.id.in_(source_email_ids)
        ).all()
        email_info = {
            email.id: {
                'subject': email.subject,
                'from': email.sender_email or email.sender_name
            }
            for email in emails
        }
    
    # Build response
    summaries: list[EvidenceItemSummary] = []
    for item in items:
        corr_count = correspondence_counts.get(str(item.id), 0)
        
        # Get source email info
        source_email_subject = None
        source_email_from = None
        if item.source_email_id and item.source_email_id in email_info:
            ei = email_info[item.source_email_id]
            source_email_subject = ei.get('subject')
            source_email_from = ei.get('from')
        
        # Generate download URL
        download_url = None
        try:
            download_url = presign_get(item.s3_key, expires=3600)
        except:
            pass
        
        summaries.append(EvidenceItemSummary(
            id=str(item.id),
            filename=item.filename,
            file_type=item.file_type,
            mime_type=item.mime_type,
            file_size=item.file_size,
            evidence_type=item.evidence_type,
            document_category=item.document_category,
            document_date=item.document_date if isinstance(item.document_date, date) else (item.document_date.date() if item.document_date else None),
            title=item.title,
            processing_status=item.processing_status or 'pending',
            is_starred=item.is_starred or False,
            is_reviewed=item.is_reviewed or False,
            has_correspondence=corr_count > 0,
            correspondence_count=corr_count,
            correspondence_link_count=corr_count,
            auto_tags=item.auto_tags or [],
            manual_tags=item.manual_tags or [],
            case_id=str(item.case_id) if item.case_id else None,
            project_id=str(item.project_id) if item.project_id else None,
            source_type=item.source_type,
            source_email_id=str(item.source_email_id) if item.source_email_id else None,
            source_email_subject=source_email_subject,
            source_email_from=source_email_from,
            download_url=download_url,
            created_at=item.created_at
        ))
    
    # Include emails as evidence items if requested
    email_total = 0
    if include_email_info:
        email_query = db.query(EmailMessage)
        
        if project_id:
            email_query = email_query.filter(EmailMessage.project_id == uuid.UUID(project_id))
        if case_id:
            email_query = email_query.filter(EmailMessage.case_id == uuid.UUID(case_id))
        
        if search:
            search_term = f"%{search}%"
            email_query = email_query.filter(
                or_(
                    EmailMessage.subject.ilike(search_term),
                    EmailMessage.sender_email.ilike(search_term),
                    EmailMessage.body_text.ilike(search_term)
                )
            )
        
        if date_from:
            email_query = email_query.filter(EmailMessage.date_sent >= date_from)
        if date_to:
            email_query = email_query.filter(EmailMessage.date_sent <= date_to)
        
        email_total = email_query.count()
        
        # Only fetch emails if we have room in pagination
        if len(summaries) < page_size:
            # Calculate offset for emails
            evidence_count = total
            email_offset = max(0, (page - 1) * page_size - evidence_count)
            email_limit = page_size - len(summaries)
            
            if page == 1 or email_offset >= 0:
                emails = email_query.order_by(desc(EmailMessage.date_sent)).offset(email_offset).limit(email_limit).all()
                
                for email in emails:
                    summaries.append(EvidenceItemSummary(
                        id=f"email-{email.id}",
                        filename=f"{email.subject or 'No Subject'}.eml",
                        file_type="eml",
                        mime_type="message/rfc822",
                        file_size=len(email.body_text or '') + len(email.body_html or ''),
                        evidence_type="correspondence",
                        document_category="email",
                        document_date=email.date_sent.date() if email.date_sent else None,
                        title=email.subject,
                        processing_status='completed',
                        is_starred=False,
                        is_reviewed=False,
                        has_correspondence=True,
                        correspondence_count=1,
                        correspondence_link_count=0,
                        auto_tags=[],
                        manual_tags=[],
                        case_id=str(email.case_id) if email.case_id else None,
                        project_id=str(email.project_id) if email.project_id else None,
                        source_type="pst",
                        source_email_id=str(email.id),
                        source_email_subject=email.subject,
                        source_email_from=email.sender_email,
                        download_url=None,
                        created_at=email.created_at
                    ))
    
    return EvidenceListResponse(
        total=total + email_total,
        items=summaries,
        page=page,
        page_size=page_size
    )


@router.get("/items/{evidence_id}", response_model=EvidenceItemDetail)
async def get_evidence_detail(
    evidence_id: str,
    db: Session = Depends(get_db)
):
    """Get full evidence item details"""
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid evidence ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Get correspondence links
    links = db.query(EvidenceCorrespondenceLink).filter(
        EvidenceCorrespondenceLink.evidence_item_id == evidence_uuid
    ).all()
    
    correspondence_links = []
    for link in links:
        link_data = {
            'id': str(link.id),
            'link_type': link.link_type,
            'link_confidence': link.link_confidence,
            'is_verified': link.is_verified,
            'context_snippet': link.context_snippet
        }
        if link.email_message_id:
            email = db.query(EmailMessage).filter(
                EmailMessage.id == link.email_message_id
            ).first()
            if email:
                link_data['email'] = {
                    'id': str(email.id),
                    'subject': email.subject,
                    'sender': email.sender_email,
                    'date': email.date_sent.isoformat() if email.date_sent else None
                }
        else:
            link_data['correspondence'] = {
                'type': link.correspondence_type,
                'reference': link.correspondence_reference,
                'date': link.correspondence_date.isoformat() if link.correspondence_date else None,
                'from': link.correspondence_from,
                'to': link.correspondence_to,
                'subject': link.correspondence_subject
            }
        correspondence_links.append(link_data)
    
    # Get relations
    relations = db.query(EvidenceRelation).filter(
        or_(
            EvidenceRelation.source_evidence_id == evidence_uuid,
            EvidenceRelation.target_evidence_id == evidence_uuid
        )
    ).all()
    
    relation_list = []
    for rel in relations:
        other_id = rel.target_evidence_id if rel.source_evidence_id == evidence_uuid else rel.source_evidence_id
        other_item = db.query(EvidenceItem).filter(EvidenceItem.id == other_id).first()
        relation_list.append({
            'id': str(rel.id),
            'relation_type': rel.relation_type,
            'direction': 'outgoing' if rel.source_evidence_id == evidence_uuid else 'incoming',
            'is_verified': rel.is_verified,
            'related_item': {
                'id': str(other_item.id),
                'filename': other_item.filename,
                'title': other_item.title
            } if other_item else None
        })
    
    # Generate download URL
    download_url = presign_get(
        item.s3_key,
        expires=3600,
        bucket=item.s3_bucket,
        response_disposition=f'attachment; filename="{item.filename}"'
    )
    
    # Log view activity
    user = get_default_user(db)
    log_activity(db, 'view', user.id, evidence_item_id=item.id)
    db.commit()
    
    return EvidenceItemDetail(
        id=str(item.id),
        filename=item.filename,
        original_path=item.original_path,
        file_type=item.file_type,
        mime_type=item.mime_type,
        file_size=item.file_size,
        file_hash=item.file_hash,
        evidence_type=item.evidence_type,
        document_category=item.document_category,
        document_date=item.document_date.date() if item.document_date else None,
        title=item.title,
        author=item.author,
        description=item.description,
        page_count=item.page_count,
        extracted_text=item.extracted_text[:5000] if item.extracted_text else None,
        extracted_parties=item.extracted_parties or [],
        extracted_dates=item.extracted_dates or [],
        extracted_amounts=item.extracted_amounts or [],
        extracted_references=item.extracted_references or [],
        auto_tags=item.auto_tags or [],
        manual_tags=item.manual_tags or [],
        processing_status=item.processing_status or 'pending',
        source_type=item.source_type,
        source_path=item.source_path,
        is_duplicate=item.is_duplicate or False,
        is_starred=item.is_starred or False,
        is_privileged=item.is_privileged or False,
        is_confidential=item.is_confidential or False,
        is_reviewed=item.is_reviewed or False,
        notes=item.notes,
        case_id=str(item.case_id) if item.case_id else None,
        project_id=str(item.project_id) if item.project_id else None,
        collection_id=str(item.collection_id) if item.collection_id else None,
        correspondence_links=correspondence_links,
        relations=relation_list,
        download_url=download_url,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.patch("/items/{evidence_id}")
async def update_evidence(
    evidence_id: str,
    updates: EvidenceItemUpdate,
    db: Session = Depends(get_db)
):
    """Update evidence item metadata"""
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid evidence ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Apply updates
    update_data = updates.dict(exclude_unset=True)
    for field, value in update_data.items():
        if field in ['case_id', 'project_id', 'collection_id'] and value:
            value = uuid.UUID(value)
        setattr(item, field, value)
    
    # Log activity
    user = get_default_user(db)
    log_activity(
        db, 'update', user.id,
        evidence_item_id=item.id,
        details={'updated_fields': list(update_data.keys())}
    )
    
    db.commit()
    db.refresh(item)
    
    return {'id': str(item.id), 'message': 'Evidence updated successfully'}


@router.delete("/items/{evidence_id}")
async def delete_evidence(
    evidence_id: str,
    db: Session = Depends(get_db)
):
    """Delete evidence item"""
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid evidence ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Log activity before deletion
    user = get_default_user(db)
    log_activity(
        db, 'delete', user.id,
        details={'evidence_id': evidence_id, 'filename': item.filename}
    )
    
    # Delete from S3
    try:
        s3_client = s3()
        s3_client.delete_object(Bucket=item.s3_bucket, Key=item.s3_key)
    except Exception as e:
        logger.warning(f"Failed to delete S3 object: {e}")
    
    # Delete database record
    db.delete(item)
    db.commit()
    
    return {'message': 'Evidence deleted successfully'}


@router.post("/items/{evidence_id}/assign")
async def assign_evidence(
    evidence_id: str,
    assignment: AssignRequest,
    db: Session = Depends(get_db)
):
    """Assign evidence to a case and/or project"""
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid evidence ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Validate case exists if provided
    if assignment.case_id:
        case = db.query(Case).filter(Case.id == uuid.UUID(assignment.case_id)).first()
        if not case:
            raise HTTPException(404, "Case not found")
        item.case_id = case.id
    
    # Validate project exists if provided
    if assignment.project_id:
        project = db.query(Project).filter(Project.id == uuid.UUID(assignment.project_id)).first()
        if not project:
            raise HTTPException(404, "Project not found")
        item.project_id = project.id
    
    # Log activity
    user = get_default_user(db)
    log_activity(
        db, 'assign', user.id,
        evidence_item_id=item.id,
        details={'case_id': assignment.case_id, 'project_id': assignment.project_id}
    )
    
    db.commit()
    
    return {
        'id': str(item.id),
        'case_id': str(item.case_id) if item.case_id else None,
        'project_id': str(item.project_id) if item.project_id else None,
        'message': 'Evidence assigned successfully'
    }


@router.post("/items/{evidence_id}/star")
async def toggle_star(
    evidence_id: str,
    db: Session = Depends(get_db)
):
    """Toggle starred status"""
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid evidence ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    item.is_starred = not item.is_starred
    db.commit()
    
    return {'id': str(item.id), 'is_starred': item.is_starred}


# ============================================================================
# CORRESPONDENCE LINK ENDPOINTS
# ============================================================================

@router.get("/items/{evidence_id}/correspondence")
async def get_evidence_correspondence(
    evidence_id: str,
    db: Session = Depends(get_db)
):
    """Get all correspondence linked to evidence item"""
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid evidence ID format")
    
    links = db.query(EvidenceCorrespondenceLink).filter(
        EvidenceCorrespondenceLink.evidence_item_id == evidence_uuid
    ).all()
    
    result = []
    for link in links:
        link_data = {
            'id': str(link.id),
            'link_type': link.link_type,
            'link_confidence': link.link_confidence,
            'link_method': link.link_method,
            'is_auto_linked': link.is_auto_linked,
            'is_verified': link.is_verified,
            'context_snippet': link.context_snippet,
            'page_reference': link.page_reference,
            'created_at': link.created_at.isoformat() if link.created_at else None
        }
        
        if link.email_message_id:
            email = db.query(EmailMessage).filter(
                EmailMessage.id == link.email_message_id
            ).first()
            if email:
                link_data['email'] = {
                    'id': str(email.id),
                    'subject': email.subject,
                    'sender_email': email.sender_email,
                    'sender_name': email.sender_name,
                    'date_sent': email.date_sent.isoformat() if email.date_sent else None,
                    'has_attachments': email.has_attachments
                }
        else:
            link_data['external_correspondence'] = {
                'type': link.correspondence_type,
                'reference': link.correspondence_reference,
                'date': link.correspondence_date.isoformat() if link.correspondence_date else None,
                'from': link.correspondence_from,
                'to': link.correspondence_to,
                'subject': link.correspondence_subject
            }
        
        result.append(link_data)
    
    return {'evidence_id': evidence_id, 'links': result, 'total': len(result)}


@router.post("/items/{evidence_id}/link-email")
async def link_evidence_to_email(
    evidence_id: str,
    link_request: CorrespondenceLinkCreate,
    db: Session = Depends(get_db)
):
    """Manually link evidence to an email or external correspondence"""
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid evidence ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Validate email if provided
    email_message_id = None
    if link_request.email_message_id:
        email = db.query(EmailMessage).filter(
            EmailMessage.id == uuid.UUID(link_request.email_message_id)
        ).first()
        if not email:
            raise HTTPException(404, "Email message not found")
        email_message_id = email.id
        
        # Check if link already exists
        existing = db.query(EvidenceCorrespondenceLink).filter(
            and_(
                EvidenceCorrespondenceLink.evidence_item_id == evidence_uuid,
                EvidenceCorrespondenceLink.email_message_id == email_message_id
            )
        ).first()
        if existing:
            raise HTTPException(409, "Link already exists")
    
    user = get_default_user(db)
    
    # Create link
    link = EvidenceCorrespondenceLink(
        evidence_item_id=evidence_uuid,
        email_message_id=email_message_id,
        link_type=link_request.link_type,
        link_confidence=100,  # Manual links are 100% confidence
        link_method='manual',
        correspondence_type=link_request.correspondence_type,
        correspondence_reference=link_request.correspondence_reference,
        correspondence_date=link_request.correspondence_date,
        correspondence_from=link_request.correspondence_from,
        correspondence_to=link_request.correspondence_to,
        correspondence_subject=link_request.correspondence_subject,
        context_snippet=link_request.context_snippet,
        is_auto_linked=False,
        is_verified=True,
        linked_by=user.id,
        verified_by=user.id,
        verified_at=datetime.now()
    )
    
    db.add(link)
    
    # Log activity
    log_activity(
        db, 'link', user.id,
        evidence_item_id=evidence_uuid,
        details={'email_id': link_request.email_message_id, 'link_type': link_request.link_type}
    )
    
    db.commit()
    db.refresh(link)
    
    return {'id': str(link.id), 'message': 'Link created successfully'}


@router.delete("/correspondence-links/{link_id}")
async def delete_correspondence_link(
    link_id: str,
    db: Session = Depends(get_db)
):
    """Delete a correspondence link"""
    try:
        link_uuid = uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(400, "Invalid link ID format")
    
    link = db.query(EvidenceCorrespondenceLink).filter(
        EvidenceCorrespondenceLink.id == link_uuid
    ).first()
    if not link:
        raise HTTPException(404, "Link not found")
    
    db.delete(link)
    db.commit()
    
    return {'message': 'Link deleted successfully'}


# ============================================================================
# COLLECTION ENDPOINTS
# ============================================================================

@router.get("/collections")
async def list_collections(
    include_system: bool = Query(True),
    case_id: str | None = Query(None),
    project_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[CollectionSummary]:
    """List all collections"""
    query = db.query(EvidenceCollection)
    
    if not include_system:
        query = query.filter(EvidenceCollection.is_system == False)
    
    if case_id:
        query = query.filter(
            or_(
                EvidenceCollection.case_id == uuid.UUID(case_id),
                EvidenceCollection.case_id.is_(None)
            )
        )
    
    if project_id:
        query = query.filter(
            or_(
                EvidenceCollection.project_id == uuid.UUID(project_id),
                EvidenceCollection.project_id.is_(None)
            )
        )
    
    collections = query.order_by(
        EvidenceCollection.sort_order,
        EvidenceCollection.name
    ).all()
    
    return [
        CollectionSummary(
            id=str(c.id),
            name=c.name,
            description=c.description,
            collection_type=c.collection_type or 'manual',
            parent_id=str(c.parent_id) if c.parent_id else None,
            item_count=c.item_count or 0,
            is_system=c.is_system or False,
            color=c.color,
            icon=c.icon,
            case_id=str(c.case_id) if c.case_id else None,
            project_id=str(c.project_id) if c.project_id else None
        )
        for c in collections
    ]


@router.post("/collections")
async def create_collection(
    collection: CollectionCreate,
    db: Session = Depends(get_db)
):
    """Create a new collection"""
    user = get_default_user(db)
    
    # Build path
    path = f"/{collection.name}"
    depth = 0
    if collection.parent_id:
        parent = db.query(EvidenceCollection).filter(
            EvidenceCollection.id == uuid.UUID(collection.parent_id)
        ).first()
        if parent:
            path = f"{parent.path}/{collection.name}"
            depth = (parent.depth or 0) + 1
    
    new_collection = EvidenceCollection(
        name=collection.name,
        description=collection.description,
        collection_type='manual' if not collection.filter_rules else 'smart',
        filter_rules=collection.filter_rules or {},
        parent_id=uuid.UUID(collection.parent_id) if collection.parent_id else None,
        path=path,
        depth=depth,
        case_id=uuid.UUID(collection.case_id) if collection.case_id else None,
        project_id=uuid.UUID(collection.project_id) if collection.project_id else None,
        color=collection.color,
        icon=collection.icon,
        is_system=False,
        created_by=user.id
    )
    
    db.add(new_collection)
    
    # Log activity
    log_activity(
        db, 'create_collection', user.id,
        collection_id=new_collection.id,
        details={'name': collection.name}
    )
    
    db.commit()
    db.refresh(new_collection)
    
    return {
        'id': str(new_collection.id),
        'name': new_collection.name,
        'message': 'Collection created successfully'
    }


@router.patch("/collections/{collection_id}")
async def update_collection(
    collection_id: str,
    updates: CollectionUpdate,
    db: Session = Depends(get_db)
):
    """Update a collection"""
    try:
        collection_uuid = uuid.UUID(collection_id)
    except ValueError:
        raise HTTPException(400, "Invalid collection ID format")
    
    collection = db.query(EvidenceCollection).filter(
        EvidenceCollection.id == collection_uuid
    ).first()
    if not collection:
        raise HTTPException(404, "Collection not found")
    
    if collection.is_system:
        raise HTTPException(403, "Cannot modify system collections")
    
    update_data = updates.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(collection, field, value)
    
    db.commit()
    db.refresh(collection)
    
    return {'id': str(collection.id), 'message': 'Collection updated successfully'}


@router.delete("/collections/{collection_id}")
async def delete_collection(
    collection_id: str,
    db: Session = Depends(get_db)
):
    """Delete a collection"""
    try:
        collection_uuid = uuid.UUID(collection_id)
    except ValueError:
        raise HTTPException(400, "Invalid collection ID format")
    
    collection = db.query(EvidenceCollection).filter(
        EvidenceCollection.id == collection_uuid
    ).first()
    if not collection:
        raise HTTPException(404, "Collection not found")
    
    if collection.is_system:
        raise HTTPException(403, "Cannot delete system collections")
    
    db.delete(collection)
    db.commit()
    
    return {'message': 'Collection deleted successfully'}


@router.post("/collections/{collection_id}/items/{evidence_id}")
async def add_to_collection(
    collection_id: str,
    evidence_id: str,
    db: Session = Depends(get_db)
):
    """Add evidence item to collection"""
    try:
        collection_uuid = uuid.UUID(collection_id)
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid ID format")
    
    # Verify both exist
    collection = db.query(EvidenceCollection).filter(
        EvidenceCollection.id == collection_uuid
    ).first()
    if not collection:
        raise HTTPException(404, "Collection not found")
    
    item = db.query(EvidenceItem).filter(
        EvidenceItem.id == evidence_uuid
    ).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Check if already in collection
    existing = db.query(EvidenceCollectionItem).filter(
        and_(
            EvidenceCollectionItem.collection_id == collection_uuid,
            EvidenceCollectionItem.evidence_item_id == evidence_uuid
        )
    ).first()
    if existing:
        raise HTTPException(409, "Item already in collection")
    
    user = get_default_user(db)
    
    # Add to collection
    collection_item = EvidenceCollectionItem(
        collection_id=collection_uuid,
        evidence_item_id=evidence_uuid,
        added_method='manual',
        added_by=user.id
    )
    
    db.add(collection_item)
    db.commit()
    
    return {'message': 'Item added to collection'}


@router.delete("/collections/{collection_id}/items/{evidence_id}")
async def remove_from_collection(
    collection_id: str,
    evidence_id: str,
    db: Session = Depends(get_db)
):
    """Remove evidence item from collection"""
    try:
        collection_uuid = uuid.UUID(collection_id)
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid ID format")
    
    item = db.query(EvidenceCollectionItem).filter(
        and_(
            EvidenceCollectionItem.collection_id == collection_uuid,
            EvidenceCollectionItem.evidence_item_id == evidence_uuid
        )
    ).first()
    if not item:
        raise HTTPException(404, "Item not in collection")
    
    db.delete(item)
    db.commit()
    
    return {'message': 'Item removed from collection'}


# ============================================================================
# STATISTICS ENDPOINTS
# ============================================================================

@router.get("/stats")
async def get_evidence_stats(
    case_id: str | None = Query(None),
    project_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get evidence repository statistics (cached for 60 seconds)"""
    # Build cache key
    cache_key = f"evidence:stats:{case_id or 'all'}:{project_id or 'all'}"
    
    # Check cache first
    cached = get_cached(cache_key)
    if cached:
        return cached
    
    # Cache miss - compute stats
    query = db.query(EvidenceItem)
    
    if case_id:
        query = query.filter(EvidenceItem.case_id == uuid.UUID(case_id))
    if project_id:
        query = query.filter(EvidenceItem.project_id == uuid.UUID(project_id))
    
    total = query.count()
    
    # Count by type
    type_counts = db.query(
        EvidenceItem.evidence_type,
        func.count(EvidenceItem.id)
    ).group_by(EvidenceItem.evidence_type).all()
    
    # Count by status
    status_counts = db.query(
        EvidenceItem.processing_status,
        func.count(EvidenceItem.id)
    ).group_by(EvidenceItem.processing_status).all()
    
    # Count unassigned
    unassigned = db.query(EvidenceItem).filter(
        and_(
            EvidenceItem.case_id.is_(None),
            EvidenceItem.project_id.is_(None)
        )
    ).count()
    
    # Count with correspondence
    with_correspondence = db.query(
        func.count(func.distinct(EvidenceCorrespondenceLink.evidence_item_id))
    ).scalar() or 0
    
    # Recent uploads (last 7 days)
    week_ago = datetime.now() - timedelta(days=7)
    recent = query.filter(EvidenceItem.created_at >= week_ago).count()
    
    result = {
        'total': total,
        'unassigned': unassigned,
        'with_correspondence': with_correspondence,
        'recent_uploads': recent,
        'by_type': {str(t): c for t, c in type_counts if t},
        'by_status': {str(s): c for s, c in status_counts if s}
    }
    
    # Cache for 60 seconds (stats don't need to be real-time)
    set_cached(cache_key, result, ttl_seconds=60)
    
    return result


# ============================================================================
# EVIDENCE TYPE REFERENCE
# ============================================================================

@router.get("/types")
async def get_evidence_types():
    """Get list of valid evidence types"""
    return {
        'evidence_types': [t.value for t in EvidenceType],
        'document_categories': [c.value for c in DocumentCategory],
        'link_types': [l.value for l in CorrespondenceLinkType],
        'relation_types': [r.value for r in EvidenceRelationType]
    }


# ============================================================================
# METADATA & PREVIEW ENDPOINTS
# ============================================================================

@router.get("/items/{evidence_id}/metadata")
async def get_evidence_metadata(
    evidence_id: str,
    extract_fresh: bool = Query(False, description="Force re-extraction of metadata"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Get comprehensive metadata for an evidence item.
    
    Extracts metadata from:
    - PDFs: Author, title, creation date, page count, producer
    - Images: EXIF data (camera, date taken, GPS), dimensions
    - Office docs: Author, title, company, created/modified dates
    - Text files: Encoding, word count, character count
    - Emails: From, To, Subject, Date, attachments
    """
    from .evidence_metadata import extract_evidence_metadata
    
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Check if we have cached metadata and don't need fresh extraction
    if item.extracted_metadata and not extract_fresh:
        return {
            'evidence_id': evidence_id,
            'metadata': item.extracted_metadata,
            'cached': True
        }
    
    # Extract metadata
    try:
        metadata = await extract_evidence_metadata(item.s3_key, item.s3_bucket)
        
        # Cache the metadata
        item.extracted_metadata = metadata
        item.metadata_extracted_at = datetime.now()
        db.commit()
        
        return {
            'evidence_id': evidence_id,
            'metadata': metadata,
            'cached': False
        }
    except Exception as e:
        logger.error(f"Error extracting metadata for {evidence_id}: {e}")
        return {
            'evidence_id': evidence_id,
            'metadata': {
                'extraction_status': 'error',
                'extraction_error': str(e),
                'filename': item.filename,
                'file_size': item.file_size,
                'mime_type': item.mime_type
            },
            'cached': False
        }


@router.get("/items/{evidence_id}/preview")
async def get_evidence_preview(
    evidence_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Get preview data for an evidence item.
    
    Returns appropriate preview based on file type:
    - Images: Direct presigned URL
    - PDFs: Presigned URL (viewable in browser)
    - Text files: Text content preview
    - Office docs: Text content preview (via Tika)
    - Other: Fallback info
    """
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    mime_type = item.mime_type or "application/octet-stream"
    preview_type = "unsupported"
    preview_url = None
    preview_content = None
    page_count = None
    dimensions = None
    
    # Generate presigned URL for direct viewing
    try:
        preview_url = presign_get(item.s3_key, expires=3600)  # 1 hour expiry
    except Exception as e:
        logger.warning(f"Could not generate presigned URL: {e}")
    
    # Determine preview type and get appropriate data
    if mime_type.startswith("image/"):
        preview_type = "image"
        # Get dimensions from metadata if available
        if item.extracted_metadata:
            dimensions = {
                'width': item.extracted_metadata.get('width'),
                'height': item.extracted_metadata.get('height')
            }
    
    elif mime_type == "application/pdf":
        preview_type = "pdf"
        if item.extracted_metadata:
            page_count = item.extracted_metadata.get('page_count')
    
    elif mime_type.startswith("text/") or item.filename.endswith(('.txt', '.csv', '.json', '.xml', '.html', '.md', '.log')):
        preview_type = "text"
        # Get text preview from storage
        try:
            from .storage import get_object
            content = get_object(item.s3_key)
            if content:
                # Try to decode as text
                for encoding in ["utf-8", "latin-1", "cp1252"]:
                    try:
                        preview_content = content.decode(encoding)[:10000]  # First 10KB
                        break
                    except:
                        continue
        except Exception as e:
            logger.warning(f"Could not get text preview: {e}")
    
    elif mime_type in ["application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"]:
        preview_type = "office"
        # Get text preview from metadata
        if item.extracted_metadata:
            preview_content = item.extracted_metadata.get('text_preview')
            page_count = item.extracted_metadata.get('page_count') or item.extracted_metadata.get('slide_count')
    
    elif mime_type in ["message/rfc822", "application/vnd.ms-outlook"] or item.filename.endswith(('.eml', '.msg')):
        preview_type = "email"
        if item.extracted_metadata:
            preview_content = {
                'from': item.extracted_metadata.get('email_from'),
                'to': item.extracted_metadata.get('email_to'),
                'cc': item.extracted_metadata.get('email_cc'),
                'subject': item.extracted_metadata.get('email_subject'),
                'date': item.extracted_metadata.get('email_date'),
                'body_preview': item.extracted_metadata.get('text_preview')
            }
    
    elif mime_type.startswith("audio/"):
        preview_type = "audio"
    
    elif mime_type.startswith("video/"):
        preview_type = "video"
    
    return {
        'evidence_id': evidence_id,
        'filename': item.filename,
        'mime_type': mime_type,
        'file_size': item.file_size,
        'preview_type': preview_type,
        'preview_url': preview_url,
        'preview_content': preview_content,
        'page_count': page_count,
        'dimensions': dimensions,
        'can_preview_inline': preview_type in ['image', 'pdf', 'text', 'audio', 'video'],
        'download_url': preview_url  # Same URL works for download
    }


@router.post("/items/{evidence_id}/extract-metadata")
async def trigger_metadata_extraction(
    evidence_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Trigger asynchronous metadata extraction for an evidence item.
    
    This queues the extraction job and returns immediately.
    Check the metadata endpoint for results.
    """
    from .evidence_metadata import extract_evidence_metadata
    
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # For now, do synchronous extraction
    # TODO: Move to Celery task for large files
    try:
        metadata = await extract_evidence_metadata(item.s3_key, item.s3_bucket)
        
        # Update the evidence item with extracted data
        item.extracted_metadata = metadata
        item.metadata_extracted_at = datetime.now()
        
        # Update evidence type and category based on extraction
        if metadata.get('mime_type'):
            mime = metadata['mime_type']
            if mime.startswith('image/'):
                item.evidence_type = EvidenceType.image
            elif mime == 'application/pdf':
                item.evidence_type = EvidenceType.pdf
            elif 'word' in mime or mime.endswith('.document'):
                item.evidence_type = EvidenceType.word_document
            elif 'excel' in mime or 'spreadsheet' in mime:
                item.evidence_type = EvidenceType.spreadsheet
        
        # Extract title from metadata if not set
        if not item.title and metadata.get('title'):
            item.title = metadata['title']
        
        # Extract author from metadata
        if metadata.get('author') and not item.author:
            item.author = metadata['author']
        
        # Extract page count from metadata
        if metadata.get('page_count') and not item.page_count:
            item.page_count = metadata['page_count']
        
        # Extract document date - check multiple possible fields
        doc_date = None
        date_fields = ['created_date', 'modified_date', 'date_taken', 'email_date']
        for field in date_fields:
            if metadata.get(field):
                doc_date = metadata[field]
                break
        
        if doc_date:
            try:
                if isinstance(doc_date, str):
                    # Handle ISO format dates
                    parsed_date = datetime.fromisoformat(doc_date.replace('Z', '+00:00'))
                    item.document_date = parsed_date
                elif isinstance(doc_date, datetime):
                    item.document_date = doc_date
            except Exception as e:
                logger.warning(f"Could not parse date {doc_date}: {e}")
        
        item.processing_status = 'processed'
        db.commit()
        
        return {
            'evidence_id': evidence_id,
            'status': 'completed',
            'metadata': metadata
        }
    except Exception as e:
        logger.error(f"Error extracting metadata for {evidence_id}: {e}")
        item.processing_status = 'error'
        db.commit()
        raise HTTPException(500, f"Metadata extraction failed: {str(e)}")


@router.get("/items/{evidence_id}/thumbnail")
async def get_evidence_thumbnail(
    evidence_id: str,
    size: str = Query("medium", description="Thumbnail size: small (64), medium (200), large (400)"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Get thumbnail URL for an evidence item (images and PDFs).
    
    For images, returns a direct presigned URL.
    For PDFs, returns the first page as image (if thumbnail generation is enabled).
    For other types, returns a type-based placeholder info.
    """
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    mime_type = item.mime_type or "application/octet-stream"
    
    # Size mapping
    size_map = {'small': 64, 'medium': 200, 'large': 400}
    thumb_size = size_map.get(size, 200)
    
    # For images, just return the presigned URL (client can resize)
    if mime_type.startswith("image/"):
        try:
            url = presign_get(item.s3_key, expires=3600)
            return {
                'evidence_id': evidence_id,
                'thumbnail_type': 'image',
                'thumbnail_url': url,
                'size': thumb_size,
                'original_dimensions': {
                    'width': item.extracted_metadata.get('width') if item.extracted_metadata else None,
                    'height': item.extracted_metadata.get('height') if item.extracted_metadata else None
                }
            }
        except Exception as e:
            logger.warning(f"Could not generate thumbnail URL: {e}")
    
    # For other types, return placeholder info
    icon_map = {
        'application/pdf': 'pdf',
        'application/msword': 'word',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'word',
        'application/vnd.ms-excel': 'excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'excel',
        'application/vnd.ms-powerpoint': 'powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'powerpoint',
        'message/rfc822': 'email',
        'application/vnd.ms-outlook': 'email',
        'text/plain': 'text',
        'text/csv': 'spreadsheet',
        'application/json': 'code',
        'text/html': 'web',
        'audio/': 'audio',
        'video/': 'video',
    }
    
    icon = 'file'
    for pattern, icon_name in icon_map.items():
        if pattern in mime_type:
            icon = icon_name
            break
    
    return {
        'evidence_id': evidence_id,
        'thumbnail_type': 'placeholder',
        'icon': icon,
        'mime_type': mime_type,
        'filename': item.filename,
        'size': thumb_size
    }


@router.get("/items/{evidence_id}/text-content")
async def get_evidence_text_content(
    evidence_id: str,
    max_length: int = Query(50000, description="Maximum characters to return"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Get extracted text content from an evidence item.
    
    Uses Tika for text extraction from PDFs, Office docs, etc.
    Returns plain text suitable for full-text search or display.
    """
    import httpx
    import os
    from .storage import get_object
    
    TIKA_URL = os.getenv("TIKA_URL", "http://tika:9998")
    
    try:
        evidence_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(400, "Invalid ID format")
    
    item = db.query(EvidenceItem).filter(EvidenceItem.id == evidence_uuid).first()
    if not item:
        raise HTTPException(404, "Evidence item not found")
    
    # Check if we have cached text
    if item.extracted_text:
        return {
            'evidence_id': evidence_id,
            'text': item.extracted_text[:max_length],
            'total_length': len(item.extracted_text),
            'truncated': len(item.extracted_text) > max_length,
            'cached': True
        }
    
    # Get file content
    try:
        content = get_object(item.s3_key)
        if not content:
            raise HTTPException(404, "File content not found")
    except Exception as e:
        raise HTTPException(500, f"Could not retrieve file: {str(e)}")
    
    # For text files, just decode
    mime_type = item.mime_type or ""
    if mime_type.startswith("text/") or item.filename.endswith(('.txt', '.csv', '.json', '.xml', '.html', '.md')):
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                text = content.decode(encoding)
                break
            except:
                continue
        else:
            text = content.decode("utf-8", errors="ignore")
    else:
        # Use Tika for other formats
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.put(
                    f"{TIKA_URL}/tika",
                    content=content,
                    headers={"Accept": "text/plain"}
                )
                if response.status_code == 200:
                    text = response.text
                else:
                    raise HTTPException(500, "Text extraction failed")
        except httpx.TimeoutException:
            raise HTTPException(504, "Text extraction timed out")
        except Exception as e:
            raise HTTPException(500, f"Text extraction failed: {str(e)}")
    
    # Cache the extracted text
    item.extracted_text = text
    db.commit()
    
    return {
        'evidence_id': evidence_id,
        'text': text[:max_length],
        'total_length': len(text),
        'truncated': len(text) > max_length,
        'cached': False
    }


# ============================================================================
# SYNC / BACKFILL ENDPOINTS
# ============================================================================

@router.post("/sync-attachments")
async def sync_email_attachments_to_evidence(
    project_id: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """
    Sync email attachments to evidence repository.
    
    This backfills evidence_items from email_attachments that don't yet
    have corresponding evidence records. Useful after PST processing
    if evidence items weren't created.
    """
    from .models import EmailAttachment
    import os
    
    # Find attachments that don't have corresponding evidence items
    # by checking if there's no evidence item with matching attachment hash
    existing_hashes = db.query(EvidenceItem.file_hash).filter(
        EvidenceItem.file_hash.isnot(None)
    ).distinct().all()
    existing_hash_set = {h[0] for h in existing_hashes if h[0]}
    
    # Query attachments
    attachment_query = db.query(EmailAttachment).join(
        EmailMessage, EmailAttachment.email_message_id == EmailMessage.id
    )
    
    if project_id:
        try:
            project_uuid = uuid.UUID(project_id)
            attachment_query = attachment_query.filter(EmailMessage.project_id == project_uuid)
        except ValueError:
            raise HTTPException(400, "Invalid project_id format")
    
    attachments = attachment_query.filter(
        EmailAttachment.is_inline == False,  # Skip inline images
        EmailAttachment.s3_key.isnot(None)   # Must have S3 key
    ).all()
    
    created_count = 0
    skipped_count = 0
    error_count = 0
    
    for att in attachments:
        try:
            # Skip if we already have this attachment's hash
            if att.attachment_hash and att.attachment_hash in existing_hash_set:
                skipped_count += 1
                continue
            
            # Get the parent email to find project_id
            email = db.query(EmailMessage).filter(
                EmailMessage.id == att.email_message_id
            ).first()
            
            if not email:
                error_count += 1
                continue
            
            # Determine file type from extension
            file_ext = os.path.splitext(att.filename or '')[1].lower().lstrip('.') if att.filename else ''
            
            # Create EvidenceItem
            evidence_item = EvidenceItem(
                filename=att.filename or 'unnamed_attachment',
                original_path=f"EmailAttachment:{att.id}",
                file_type=file_ext or None,
                mime_type=att.content_type,
                file_size=att.file_size_bytes,
                file_hash=att.attachment_hash,
                s3_bucket=att.s3_bucket or settings.S3_BUCKET,
                s3_key=att.s3_key,
                evidence_type='email_attachment',
                source_type='pst_extraction',
                source_email_id=email.id,
                project_id=email.project_id,
                case_id=email.case_id,
                processing_status='pending',
                auto_tags=['email-attachment', 'synced-from-attachments'],
            )
            db.add(evidence_item)
            
            # Add hash to our set to avoid duplicates within this run
            if att.attachment_hash:
                existing_hash_set.add(att.attachment_hash)
            
            created_count += 1
            
            # Commit in batches
            if created_count % 100 == 0:
                db.commit()
                logger.info(f"Synced {created_count} attachments so far...")
                
        except Exception as e:
            logger.error(f"Error syncing attachment {att.id}: {e}")
            error_count += 1
    
    # Final commit
    db.commit()
    
    return {
        'status': 'completed',
        'created': created_count,
        'skipped': skipped_count,
        'errors': error_count,
        'total_processed': created_count + skipped_count + error_count
    }


@router.get("/sync-status")
async def get_sync_status(
    project_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get sync status between email_attachments and evidence_items.
    Shows how many attachments don't have corresponding evidence records.
    """
    from .models import EmailAttachment
    
    # Count total non-inline attachments
    att_query = db.query(func.count(EmailAttachment.id)).join(
        EmailMessage, EmailAttachment.email_message_id == EmailMessage.id
    ).filter(
        EmailAttachment.is_inline == False,
        EmailAttachment.s3_key.isnot(None)
    )
    
    if project_id:
        try:
            project_uuid = uuid.UUID(project_id)
            att_query = att_query.filter(EmailMessage.project_id == project_uuid)
        except ValueError:
            raise HTTPException(400, "Invalid project_id format")
    
    total_attachments = att_query.scalar() or 0
    
    # Count evidence items from PST extraction
    ev_query = db.query(func.count(EvidenceItem.id)).filter(
        EvidenceItem.source_type == 'pst_extraction'
    )
    
    if project_id:
        try:
            project_uuid = uuid.UUID(project_id)
            ev_query = ev_query.filter(EvidenceItem.project_id == project_uuid)
        except ValueError:
            pass
    
    total_evidence = ev_query.scalar() or 0
    
    # Estimate missing (rough - doesn't account for duplicates)
    missing_estimate = max(0, total_attachments - total_evidence)
    
    return {
        'total_attachments': total_attachments,
        'total_evidence_items': total_evidence,
        'missing_estimate': missing_estimate,
        'sync_needed': missing_estimate > 0
    }


@router.post("/extract-all-metadata")
async def extract_all_metadata(
    limit: int = Query(100, description="Max items to process"),
    force: bool = Query(False, description="Re-extract even if already processed"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """
    Bulk extract metadata for evidence items.
    
    This processes items that haven't had metadata extracted yet
    and populates document_date, author, page_count, etc.
    """
    from .evidence_metadata import extract_evidence_metadata
    
    # Find items needing metadata extraction
    query = db.query(EvidenceItem)
    
    if not force:
        query = query.filter(
            or_(
                EvidenceItem.metadata_extracted_at.is_(None),
                EvidenceItem.document_date.is_(None)
            )
        )
    
    items = query.limit(limit).all()
    
    processed = 0
    updated_dates = 0
    errors = 0
    
    for item in items:
        try:
            metadata = await extract_evidence_metadata(item.s3_key, item.s3_bucket)
            
            # Update extracted metadata
            item.extracted_metadata = metadata
            item.metadata_extracted_at = datetime.now()
            
            # Extract document date
            doc_date = None
            date_fields = ['created_date', 'modified_date', 'date_taken', 'email_date']
            for field in date_fields:
                if metadata.get(field):
                    doc_date = metadata[field]
                    break
            
            if doc_date:
                try:
                    if isinstance(doc_date, str):
                        parsed_date = datetime.fromisoformat(doc_date.replace('Z', '+00:00'))
                        item.document_date = parsed_date
                        updated_dates += 1
                    elif isinstance(doc_date, datetime):
                        item.document_date = doc_date
                        updated_dates += 1
                except:
                    pass
            
            # Update other fields
            if metadata.get('author') and not item.author:
                item.author = metadata['author']
            if metadata.get('page_count') and not item.page_count:
                item.page_count = metadata['page_count']
            if metadata.get('title') and not item.title:
                item.title = metadata['title']
            
            item.processing_status = 'processed'
            processed += 1
            
            # Commit periodically
            if processed % 10 == 0:
                db.commit()
                logger.info(f"Processed {processed} items, {updated_dates} dates updated...")
                
        except Exception as e:
            logger.error(f"Error extracting metadata for {item.id}: {e}")
            errors += 1
    
    db.commit()
    
    return {
        'status': 'completed',
        'processed': processed,
        'dates_updated': updated_dates,
        'errors': errors,
        'remaining': db.query(func.count(EvidenceItem.id)).filter(
            EvidenceItem.metadata_extracted_at.is_(None)
        ).scalar() or 0
    }

