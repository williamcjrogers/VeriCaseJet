"""
Document Sharing API Endpoints
Allows users to share documents with other users with permissions
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from .db import get_db
from .models import Document, DocumentShare, FolderShare, User
from .security import current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sharing"])


# Pydantic models
class ShareDocumentRequest(BaseModel):
    user_email: EmailStr
    permission: str = "view"  # "view" or "edit"


class ShareResponse(BaseModel):
    id: str
    document_id: str
    user_email: str
    permission: str
    created_at: datetime | None = None


class SharedDocumentItem(BaseModel):
    id: str
    filename: str
    path: str | None = None
    size: int
    content_type: str | None = None
    title: str | None = None
    permission: str
    shared_by_email: str
    shared_at: datetime | None = None


class ShareFolderRequest(BaseModel):
    path: str
    user_email: EmailStr
    permission: str = "view"


class FolderShareResponse(BaseModel):
    id: str
    folder_path: str
    user_email: str
    permission: str
    created_at: datetime | None = None


# Document sharing endpoints
@router.post("/documents/{doc_id}/share", response_model=ShareResponse)
async def share_document(
    doc_id: str,
    data: ShareDocumentRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> ShareResponse:
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
    existing = (
        db.query(DocumentShare)
        .filter(
            DocumentShare.document_id == doc.id,
            DocumentShare.shared_with == target_user.id,
        )
        .first()
    )

    if existing:
        # Update existing share
        existing.permission = data.permission
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)

        created_at = existing.created_at or datetime.now(timezone.utc)
        return ShareResponse(
            id=str(existing.id),
            document_id=str(existing.document_id),
            user_email=target_user.email,
            permission=existing.permission,
            created_at=created_at,
        )

    # Create new share
    share = DocumentShare(
        document_id=doc.id,
        shared_by=user.id,
        shared_with=target_user.id,
        permission=data.permission,
    )

    db.add(share)
    db.commit()
    db.refresh(share)

    logger.info(
        "Document %s shared with %s by %s", doc.id, target_user.email, user.email
    )

    created_at = share.created_at or datetime.now(timezone.utc)
    return ShareResponse(
        id=str(share.id),
        document_id=str(share.document_id),
        user_email=target_user.email,
        permission=share.permission,
        created_at=created_at,
    )


@router.get("/documents/{doc_id}/shares", response_model=list[ShareResponse])
async def list_document_shares(
    doc_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> list[ShareResponse]:
    """List all shares for a document"""
    try:
        doc_uuid = UUID(doc_id)
    except ValueError:
        raise HTTPException(400, "invalid document id")

    doc = db.get(Document, doc_uuid)
    if not doc or doc.owner_user_id != user.id:
        raise HTTPException(404, "document not found")

    shares = db.query(DocumentShare).filter(DocumentShare.document_id == doc.id).all()

    result: list[ShareResponse] = []
    for share in shares:
        shared_user = db.get(User, share.shared_with)
        if shared_user:
            created_at = share.created_at or datetime.now(timezone.utc)
            result.append(
                ShareResponse(
                    id=str(share.id),
                    document_id=str(share.document_id),
                    user_email=shared_user.email,
                    permission=share.permission,
                    created_at=created_at,
                )
            )

    return result


@router.delete("/documents/{doc_id}/shares/{user_id}")
async def revoke_document_share(
    doc_id: str,
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, str]:
    """Revoke document share"""
    try:
        doc_uuid = UUID(doc_id)
        share_user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "invalid id")

    doc = db.get(Document, doc_uuid)
    if not doc or doc.owner_user_id != user.id:
        raise HTTPException(404, "document not found")

    share = (
        db.query(DocumentShare)
        .filter(
            DocumentShare.document_id == doc.id,
            DocumentShare.shared_with == share_user_uuid,
        )
        .first()
    )

    if not share:
        raise HTTPException(404, "share not found")

    _ = (
        db.query(DocumentShare)
        .filter(DocumentShare.id == share.id)
        .delete(synchronize_session=False)
    )
    db.commit()

    return {"message": "share revoked"}


@router.get("/documents/shared-with-me", response_model=list[SharedDocumentItem])
async def list_shared_documents(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> list[SharedDocumentItem]:
    """List documents shared with the current user"""
    shares = (
        db.query(DocumentShare).filter(DocumentShare.shared_with == user.id).all()
    )

    result: list[SharedDocumentItem] = []
    for share in shares:
        doc = db.get(Document, share.document_id)
        if doc:
            owner = db.get(User, doc.owner_user_id)
            result.append(
                SharedDocumentItem(
                    id=str(doc.id),
                    filename=doc.filename,
                    path=doc.path,
                    size=doc.size or 0,
                    content_type=doc.content_type,
                    title=doc.title,
                    permission=share.permission,
                    shared_by_email=owner.email if owner else "Unknown",
                    shared_at=share.created_at,
                )
            )

    return result


# Folder sharing endpoints
@router.post("/folders/share", response_model=FolderShareResponse)
async def share_folder(
    data: ShareFolderRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> FolderShareResponse:
    """Share a folder with another user"""
    if not data.path:
        raise HTTPException(400, "path is required")

    # Get target user
    target_user = db.query(User).filter(User.email == data.user_email.lower()).first()
    if not target_user:
        raise HTTPException(404, f"user not found: {data.user_email}")

    if target_user.id == user.id:
        raise HTTPException(400, "cannot share with yourself")

    # Check if already shared
    existing = (
        db.query(FolderShare)
        .filter(
            FolderShare.folder_path == data.path,
            FolderShare.owner_id == user.id,
            FolderShare.shared_with == target_user.id,
        )
        .first()
    )

    if existing:
        # Update existing share
        existing.permission = data.permission
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)

        created_at = existing.created_at or datetime.now(timezone.utc)
        return FolderShareResponse(
            id=str(existing.id),
            folder_path=existing.folder_path,
            user_email=target_user.email,
            permission=existing.permission,
            created_at=created_at,
        )

    # Create new share
    share = FolderShare(
        folder_path=data.path,
        owner_id=user.id,
        shared_by=user.id,
        shared_with=target_user.id,
        permission=data.permission,
    )

    db.add(share)
    db.commit()
    db.refresh(share)

    logger.info(
        "Folder %s shared with %s by %s", data.path, data.user_email, user.email
    )

    created_at = share.created_at or datetime.now(timezone.utc)
    return FolderShareResponse(
        id=str(share.id),
        folder_path=share.folder_path,
        user_email=data.user_email,
        permission=share.permission,
        created_at=created_at,
    )


@router.get("/folders/{path:path}/shares", response_model=list[FolderShareResponse])
async def list_folder_shares(
    path: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> list[FolderShareResponse]:
    """List all shares for a folder"""
    clean_path = path.strip().strip("/")

    shares = (
        db.query(FolderShare)
        .filter(
            FolderShare.folder_path == clean_path,
            FolderShare.owner_id == user.id,
        )
        .all()
    )

    result: list[FolderShareResponse] = []
    for share in shares:
        shared_user = db.get(User, share.shared_with)
        if shared_user:
            created_at = share.created_at or datetime.now(timezone.utc)
            result.append(
                FolderShareResponse(
                    id=str(share.id),
                    folder_path=share.folder_path,
                    user_email=shared_user.email,
                    permission=share.permission,
                    created_at=created_at,
                )
            )

    return result


@router.delete("/folders/{path:path}/shares/{user_id}")
async def revoke_folder_share(
    path: str,
    user_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, str]:
    """Revoke folder share"""
    clean_path = path.strip().strip("/")

    try:
        share_user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "invalid user id")

    share = (
        db.query(FolderShare)
        .filter(
            FolderShare.folder_path == clean_path,
            FolderShare.owner_id == user.id,
            FolderShare.shared_with == share_user_uuid,
        )
        .first()
    )

    if not share:
        raise HTTPException(404, "share not found")

    _ = (
        db.query(FolderShare)
        .filter(FolderShare.id == share.id)
        .delete(synchronize_session=False)
    )
    db.commit()

    return {"message": "share revoked"}
