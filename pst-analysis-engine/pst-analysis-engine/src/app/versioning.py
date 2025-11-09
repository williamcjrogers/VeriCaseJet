"""
Document versioning API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc
from .security import get_db, current_user
from .models import User, Document, DocumentVersion
from .storage import presign_get
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/versions", tags=["versions"])

class VersionResponse(BaseModel):
    id: str
    version_number: int
    filename: str
    size: int
    content_type: str | None
    created_by: str | None
    created_at: datetime
    comment: str | None

class VersionListResponse(BaseModel):
    total: int
    current_version: int
    versions: List[VersionResponse]

@router.get("/documents/{document_id}", response_model=VersionListResponse)
def list_document_versions(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get all versions of a document"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Invalid document ID format: {document_id}")
        raise HTTPException(400, "invalid document id")
    
    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")
    
    versions = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_uuid
    ).order_by(desc(DocumentVersion.version_number)).all()
    
    # Get current version number (latest + 1, or 1 if no versions)
    current_version = versions[0].version_number + 1 if versions else 1
    
    # Build version list with error handling for each version
    version_items = []
    for v in versions:
        try:
            creator_email = None
            if v.created_by:
                creator = db.get(User, v.created_by)
                if creator:
                    creator_email = creator.email
            
            version_items.append(VersionResponse(
                id=str(v.id),
                version_number=v.version_number,
                filename=v.filename,
                size=v.size or 0,
                content_type=v.content_type,
                created_by=creator_email,
                created_at=v.created_at,
                comment=v.comment
            ))
        except Exception as e:
            logger.error(f"Error processing version {v.id}: {e}")
            continue
    
    return VersionListResponse(
        total=len(version_items),
        current_version=current_version,
        versions=version_items
    )

@router.post("/documents/{document_id}")
def create_version(
    document_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Create a new version of a document (when replacing file)"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Invalid document ID format: {document_id}")
        raise HTTPException(400, "invalid document id")
    
    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")
    
    # Get next version number
    latest_version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_uuid
    ).order_by(desc(DocumentVersion.version_number)).first()
    
    next_version = (latest_version.version_number + 1) if latest_version else 1
    
    # Create version record from current document state
    try:
        version = DocumentVersion(
            document_id=doc_uuid,
            version_number=next_version,
            s3_key=document.s3_key,
            filename=document.filename,
            size=document.size,
            content_type=document.content_type,
            created_by=user.id,
            comment=body.get('comment', '')
        )
        
        db.add(version)
        
        # Update document with new file info if provided
        if 'new_s3_key' in body:
            document.s3_key = body['new_s3_key']
        if 'new_filename' in body:
            document.filename = body['new_filename']
        if 'new_size' in body:
            document.size = body['new_size']
        if 'new_content_type' in body:
            document.content_type = body['new_content_type']
        
        document.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(version)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create document version: {e}")
        raise HTTPException(status_code=500, detail="Failed to create version")
    
    return {
        "message": "version created",
        "version_id": str(version.id),
        "version_number": version.version_number
    }

@router.post("/documents/{document_id}/restore/{version_number}")
def restore_version(
    document_id: str,
    version_number: int,
    body: dict = Body(default={}),
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Restore a document to a previous version"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Invalid document ID format: {document_id}")
        raise HTTPException(400, "invalid document id")
    
    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")
    
    # Find the version to restore
    version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_uuid,
        DocumentVersion.version_number == version_number
    ).first()
    
    if not version:
        raise HTTPException(404, "version not found")
    
    # Save current state as a new version before restoring
    try:
        latest_version = db.query(DocumentVersion).filter(
            DocumentVersion.document_id == doc_uuid
        ).order_by(desc(DocumentVersion.version_number)).first()
        
        next_version = (latest_version.version_number + 1) if latest_version else 1
        
        current_version = DocumentVersion(
            document_id=doc_uuid,
            version_number=next_version,
            s3_key=document.s3_key,
            filename=document.filename,
            size=document.size,
            content_type=document.content_type,
            created_by=user.id,
            comment=f"Auto-save before restoring to version {version_number}"
        )
        db.add(current_version)
        
        # Restore to selected version
        document.s3_key = version.s3_key
        document.filename = version.filename
        document.size = version.size
        document.content_type = version.content_type
        document.updated_at = datetime.now(timezone.utc)
        
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to restore document version: {e}")
        raise HTTPException(status_code=500, detail="Failed to restore version")
    
    return {
        "message": "version restored",
        "restored_to": version_number,
        "backup_version": next_version
    }

@router.get("/documents/{document_id}/{version_number}/download")
def get_version_url(
    document_id: str,
    version_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get signed URL for a specific document version"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Invalid document ID format: {document_id}")
        raise HTTPException(400, "invalid document id")
    
    document = db.get(Document, doc_uuid)
    if not document or document.owner_user_id != user.id:
        raise HTTPException(404, "document not found")
    
    version = db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc_uuid,
        DocumentVersion.version_number == version_number
    ).first()
    
    if not version:
        raise HTTPException(404, "version not found")
    
    try:
        url = presign_get(version.s3_key, 300)
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate download URL")
    
    return {
        "url": url,
        "filename": version.filename,
        "content_type": version.content_type,
        "version_number": version.version_number
    }
