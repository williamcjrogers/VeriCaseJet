"""
Favorites API endpoints for starring/bookmarking documents
"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session, joinedload
from .security import get_db, current_user
from .models import User, Document, Favorite
from typing import List
from pydantic import BaseModel
from datetime import datetime
import uuid

router = APIRouter(prefix="/favorites", tags=["favorites"])

class FavoriteResponse(BaseModel):
    id: str
    document_id: str
    filename: str
    path: str | None
    size: int
    content_type: str | None
    created_at: datetime

class FavoriteListResponse(BaseModel):
    total: int
    items: List[FavoriteResponse]

@router.post("/{document_id}")
def add_favorite(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Add a document to favorites"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "invalid document id")
    
    # Check document exists and user has access
    document = db.get(Document, doc_uuid)
    if not document:
        raise HTTPException(404, "document not found")
    
    # Check if already favorited
    existing = db.query(Favorite).filter(
        Favorite.user_id == user.id,
        Favorite.document_id == doc_uuid
    ).first()
    
    if existing:
        return {"message": "already favorited", "id": str(existing.id)}
    
    # Create favorite
    favorite = Favorite(user_id=user.id, document_id=doc_uuid)
    db.add(favorite)
    db.commit()
    db.refresh(favorite)
    
    return {"message": "favorited", "id": str(favorite.id)}

@router.delete("/{document_id}")
def remove_favorite(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Remove a document from favorites"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "invalid document id")
    
    favorite = db.query(Favorite).filter(
        Favorite.user_id == user.id,
        Favorite.document_id == doc_uuid
    ).first()
    
    if not favorite:
        raise HTTPException(404, "favorite not found")
    
    db.delete(favorite)
    db.commit()
    
    return {"message": "unfavorited"}

@router.get("", response_model=FavoriteListResponse)
def list_favorites(
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Get all favorited documents for current user"""
    favorites = db.query(Favorite).options(
        joinedload(Favorite.document)
    ).filter(
        Favorite.user_id == user.id
    ).order_by(
        Favorite.created_at.desc()
    ).all()
    
    items = []
    for fav in favorites:
        if fav.document:
            items.append(FavoriteResponse(
                id=str(fav.id),
                document_id=str(fav.document.id),
                filename=fav.document.filename,
                path=fav.document.path,
                size=fav.document.size or 0,
                content_type=fav.document.content_type,
                created_at=fav.created_at
            ))
    
    return FavoriteListResponse(total=len(items), items=items)

@router.get("/check/{document_id}")
def check_favorite(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user)
):
    """Check if a document is favorited"""
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "invalid document id")
    
    favorite = db.query(Favorite).filter(
        Favorite.user_id == user.id,
        Favorite.document_id == doc_uuid
    ).first()
    
    return {"is_favorited": favorite is not None}
