"""
Document Sharing API Endpoints
Allows users to share documents with other users with permissions
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator

from .security import get_db, current_user
from .models import User, UserRole, Document, DocumentShare, FolderShare

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sharing"])

# Pydantic models
class ShareDocumentRequest(BaseModel):
    user_email: EmailStr
    permission: str = "view"  # "view" or "edit"
    
    @field_validator('permission')
    @classmethod
    def validate_permission(cls, v: str) -> str:
        """Validate permission is either view or edit"""
        if v not in ['view', 'edit']:
            raise ValueError("Permission must be 'view' or 'edit'")
        return v

class ShareResponse(BaseModel):
    id: str
    document_id: str
    user_email: str
    permission: str
    created_at: datetime

class SharedDocumentItem(BaseModel):
    id: str
    filename: str
    path: Optional[str] = None
    size: int
    content_type: Optional[str] = None
    title: Optional[str] = None
    permission: str
    shared_by_email: str
    shared_at: datetime

class ShareFolderRequest(BaseModel):
    user_email: EmailStr
    permission: str = "view"
    
    @field_validator('permission')
    @classmethod
    def validate_permission(cls, v: str) -> str:
        """Validate permission is either view or edit"""
        if v not in ['view', 'edit']:
            raise ValueError("Permission must be 'view' or 'edit'")
        return v

class FolderShareResponse(BaseModel):
    id: str
    folder_path: str
    user_email: str
    permission: str
    created_at: datetime

# Document sharing endpoints
@router.post("/documents/{doc_id}/share", response_model=ShareResponse)
async def share_document(
    doc_id: str,
    data: ShareDocumentRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Share a document with another user"""
    # Get document
    try:
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid document id")
    
    doc = db.get(Document, doc_uuid)
    if not doc or doc.owner_user_id != user.id:
        raise HTTPException(404, "document not found")
    
    # Validate permission
    if data.permission not in ["view", "edit"]:
        raise HTTPException(400, "permission must be 'view' or 'edit'")
    
    # Get target user
    target_user = db.query(User).filter(User.email == data.user_email.lower()).first()
    if not target_user:
        raise HTTPException(404, f"user not found: {data.user_email}")
    
    if target_user.id == user.id:
        raise HTTPException(400, "cannot share with yourself")
    
    # Check if already shared
    existing = db.query(DocumentShare).filter(
        DocumentShare.document_id == doc.id,
        DocumentShare.shared_with == target_user.id
    ).first()
    
    if existing:
        # Update existing share
        try:
            existing.permission = data.permission
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating document share: {e}")
            raise HTTPException(500, "Failed to update share")
        
        return ShareResponse(
            id=str(existing.id),
            document_id=str(existing.document_id),
            user_email=target_user.email,
            permission=existing.permission,
            created_at=existing.created_at
        )
    
    # Create new share
    try:
        share = DocumentShare(
            document_id=doc.id,
            shared_by=user.id,
            shared_with=target_user.id,
            permission=data.permission
        )
        
        db.add(share)
        db.commit()
        db.refresh(share)
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating document share: {e}")
        raise HTTPException(500, "Failed to create share")
    
    # Sanitize email addresses for logging (prevent log injection)
    safe_target_email = target_user.email.replace('\n', '').replace('\r', '')
    safe_user_email = user.email.replace('\n', '').replace('\r', '')
    logger.info(f"Document {doc.id} shared with {safe_target_email} by {safe_user_email}")
    
    return ShareResponse(
        id=str(share.id),
        document_id=str(share.document_id),
        user_email=target_user.email,
        permission=share.permission,
        created_at=share.created_at
    )

@router.get("/documents/{doc_id}/shares", response_model=List[ShareResponse])
async def list_document_shares(
    doc_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """List all shares for a document"""
    try:
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid document id")
    
    doc = db.get(Document, doc_uuid)
    if not doc or doc.owner_user_id != user.id:
        raise HTTPException(404, "document not found")
    
    shares = db.query(DocumentShare).filter(
        DocumentShare.document_id == doc.id
    ).all()
    
    result = []
    for share in shares:
        shared_user = db.get(User, share.shared_with)
        if shared_user:
            result.append(ShareResponse(
                id=str(share.id),
                document_id=str(share.document_id),
                user_email=shared_user.email,
                permission=share.permission,
                created_at=share.created_at
            ))
    
    return result

@router.delete("/documents/{doc_id}/shares/{user_id}")
async def revoke_document_share(
    doc_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Revoke document share"""
    try:
        doc_uuid = UUID(doc_id)
        share_user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "invalid id")
    
    doc = db.get(Document, doc_uuid)
    if not doc or doc.owner_user_id != user.id:
        raise HTTPException(404, "document not found")
    
    share = db.query(DocumentShare).filter(
        DocumentShare.document_id == doc.id,
        DocumentShare.shared_with == share_user_uuid
    ).first()
    
    if not share:
        raise HTTPException(404, "share not found")
    
    db.delete(share)
    db.commit()
    
    return {"message": "share revoked"}

@router.get("/documents/shared-with-me", response_model=List[SharedDocumentItem])
async def list_shared_documents(
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """List documents shared with the current user"""
    try:
        # Query uses parameterized SQLAlchemy ORM (SQL injection safe)
        shares = db.query(DocumentShare).filter(
            DocumentShare.shared_with == user.id
        ).all()
    except Exception as e:
        logger.error(f"Database error fetching shared documents: {e}")
        raise HTTPException(500, "Failed to fetch shared documents")
    
    result = []
    for share in shares:
        try:
            doc = db.get(Document, share.document_id)
            if not doc:
                continue
        except Exception as e:
            logger.error(f"Error fetching document {share.document_id}: {e}")
            continue
        
        if doc:
            owner = db.get(User, doc.owner_user_id)
            result.append(SharedDocumentItem(
                id=str(doc.id),
                filename=doc.filename,
                path=doc.path,
                size=doc.size or 0,
                content_type=doc.content_type,
                title=doc.title,
                permission=share.permission,
                shared_by_email=owner.email if owner else "Unknown",
                shared_at=share.created_at
            ))
    
    return result

# Folder sharing endpoints
@router.post("/folders/share", response_model=FolderShareResponse)
async def share_folder(
    path: str,
    data: ShareFolderRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Share a folder with another user"""
    if not path:
        raise HTTPException(400, "path is required")
    
    path = path.strip().strip("/")
    
    # Validate permission
    if data.permission not in ["view", "edit"]:
        raise HTTPException(400, "permission must be 'view' or 'edit'")
    
    # Get target user
    target_user = db.query(User).filter(User.email == data.user_email.lower()).first()
    if not target_user:
        raise HTTPException(404, f"user not found: {data.user_email}")
    
    if target_user.id == user.id:
        raise HTTPException(400, "cannot share with yourself")
    
    # Check if already shared
    existing = db.query(FolderShare).filter(
        FolderShare.folder_path == path,
        FolderShare.owner_id == user.id,
        FolderShare.shared_with == target_user.id
    ).first()
    
    if existing:
        # Update existing share
        try:
            existing.permission = data.permission
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating folder share: {e}")
            raise HTTPException(500, "Failed to update folder share")
        
        return FolderShareResponse(
            id=str(existing.id),
            folder_path=existing.folder_path,
            user_email=target_user.email,
            permission=existing.permission,
            created_at=existing.created_at
        )
    
    # Create new share
    try:
        share = FolderShare(
            folder_path=path,
            owner_id=user.id,
            shared_by=user.id,
            shared_with=target_user.id,
            permission=data.permission
        )
        
        db.add(share)
        db.commit()
        db.refresh(share)
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating folder share: {e}")
        raise HTTPException(500, "Failed to create folder share")
    
    # Sanitize email addresses and path for logging (prevent log injection)
    safe_target_email = target_user.email.replace('\n', '').replace('\r', '')
    safe_user_email = user.email.replace('\n', '').replace('\r', '')
    safe_path = path.replace('\n', '').replace('\r', '')
    logger.info(f"Folder {safe_path} shared with {safe_target_email} by {safe_user_email}")
    
    return FolderShareResponse(
        id=str(share.id),
        folder_path=share.folder_path,
        user_email=target_user.email,
        permission=share.permission,
        created_at=share.created_at
    )

@router.get("/folders/{path:path}/shares", response_model=List[FolderShareResponse])
async def list_folder_shares(
    path: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """List all shares for a folder"""
    path = path.strip().strip("/")
    
    shares = db.query(FolderShare, User).join(
        User, FolderShare.shared_with == User.id
    ).filter(
        FolderShare.folder_path == path,
        FolderShare.owner_id == user.id
    ).all()
    
    return [
        FolderShareResponse(
            id=str(share.id),
            folder_path=share.folder_path,
            user_email=shared_user.email,
            permission=share.permission,
            created_at=share.created_at
        )
        for share, shared_user in shares
    ]

@router.delete("/folders/{path:path}/shares/{user_id}")
async def revoke_folder_share(
    path: str,
    user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Revoke folder share"""
    path = path.strip().strip("/")
    
    try:
        share_user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "invalid user id")
    
    share = db.query(FolderShare).filter(
        FolderShare.folder_path == path,
        FolderShare.owner_id == user.id,
        FolderShare.shared_with == share_user_uuid
    ).first()
    
    if not share:
        raise HTTPException(404, "share not found")
    
    db.delete(share)
    db.commit()
    
    return {"message": "share revoked"}
