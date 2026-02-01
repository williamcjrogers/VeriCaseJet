"""Document CRUD, search, and related Pydantic models.

Extracted from main.py to reduce module size.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .config import settings
from .models import Document, DocStatus, User, UserRole
from .storage import presign_get, delete_object
from .search import search as os_search, delete_document as os_delete
from .security import get_db, current_user
from .csrf import verify_csrf_token

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DocumentSummary(BaseModel):
    id: str
    filename: str
    path: str | None = None
    status: str
    size: int
    content_type: str | None = None
    title: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentSummary]


class PathListResponse(BaseModel):
    paths: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        logger.debug(f"Invalid UUID format: {value}")
        raise HTTPException(400, "invalid document id")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/documents", response_model=DocumentListResponse)
def list_documents(
    path_prefix: str | None = Query(default=None),
    exact_folder: bool = Query(default=False),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    # Admin sees all documents except other users' private documents
    if user.role == UserRole.ADMIN:
        # Start with all documents
        query = db.query(Document)
        # Then filter out private documents from other users
        from sqlalchemy import or_, and_

        query = query.filter(
            or_(
                Document.path.is_(None),  # Documents with no path
                ~Document.path.like("private/%"),  # Not in private folder
                and_(
                    Document.path.like("private/%"), Document.owner_user_id == user.id
                ),  # Or it's admin's own private folder
            )
        )
    else:
        # Regular users see only their own documents
        query = db.query(Document).filter(Document.owner_user_id == user.id)
    if path_prefix is not None:
        if path_prefix == "":
            # Empty string means root - show documents with no path or empty path
            query = query.filter((Document.path.is_(None)) | (Document.path == ""))
        else:
            safe_path = path_prefix.strip().strip("/")
            if safe_path:
                if exact_folder:
                    # Match exact folder only, not subfolders
                    query = query.filter(Document.path == safe_path)
                else:
                    # Match folder and all subfolders
                    like_pattern = f"{safe_path}/%"
                    query = query.filter(
                        (Document.path == safe_path)
                        | (Document.path.like(like_pattern))
                    )
    if status:
        try:
            status_enum = DocStatus(status.upper())
        except ValueError:
            raise HTTPException(400, "invalid status value")
        query = query.filter(Document.status == status_enum)
    total = query.count()
    docs = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        DocumentSummary(
            id=str(doc.id),
            filename=doc.filename,
            path=doc.path,
            status=doc.status.value if doc.status else DocStatus.NEW.value,
            size=doc.size or 0,
            content_type=doc.content_type,
            title=doc.title,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        for doc in docs
    ]
    return DocumentListResponse(total=total, items=items)


@router.get("/documents/paths", response_model=PathListResponse)
def list_paths(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    paths = (
        db.query(Document.path)
        .filter(Document.owner_user_id == user.id, Document.path.isnot(None))
        .distinct()
        .all()
    )
    path_values = sorted(p[0] for p in paths if p[0])
    return PathListResponse(paths=path_values)


@router.get("/documents/recent", response_model=DocumentListResponse)
def get_recent_documents(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get recently accessed or created documents"""
    try:
        from datetime import datetime, timedelta

        # Get documents accessed in last 30 days, or fall back to recently created
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

        # Try to get recently accessed first
        recent_query = (
            db.query(Document)
            .filter(
                Document.owner_user_id == user.id,
                Document.last_accessed_at.isnot(None),
                Document.last_accessed_at >= thirty_days_ago,
            )
            .order_by(Document.last_accessed_at.desc())
        )

        recent_docs = recent_query.limit(limit).all()

        # If not enough recently accessed, add recently created
        if len(recent_docs) < limit:
            created_query = (
                db.query(Document)
                .filter(Document.owner_user_id == user.id)
                .order_by(Document.created_at.desc())
            )

            created_docs = created_query.limit(limit - len(recent_docs)).all()

            # Merge and deduplicate
            seen_ids = {doc.id for doc in recent_docs}
            for doc in created_docs:
                if doc.id not in seen_ids:
                    recent_docs.append(doc)
                    seen_ids.add(doc.id)
    except Exception as e:
        import logging

        logging.error(f"Database error in get_recent_documents: {e}")
        raise HTTPException(500, "Failed to fetch recent documents")

    items = [
        DocumentSummary(
            id=str(doc.id),
            filename=doc.filename,
            path=doc.path,
            status=doc.status.value if doc.status else DocStatus.NEW.value,
            size=doc.size or 0,
            content_type=doc.content_type,
            title=doc.title,
            created_at=doc.created_at,
            updated_at=doc.updated_at or doc.created_at,
        )
        for doc in recent_docs
    ]

    return DocumentListResponse(total=len(items), items=items)


# Documents
@router.get("/documents/{doc_id}")
def get_document(
    doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    doc = db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404, "not found")
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "path": doc.path,
        "status": doc.status.value,
        "content_type": doc.content_type,
        "size": doc.size,
        "bucket": doc.bucket,
        "s3_key": doc.s3_key,
        "title": doc.title,
        "metadata": doc.meta,
        "text_excerpt": (doc.text_excerpt or "")[:1000],
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


@router.get("/documents/{doc_id}/signed_url")
def get_signed_url(
    doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    doc = db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404, "not found")
    return {
        "url": presign_get(doc.s3_key, 300),
        "filename": doc.filename,
        "content_type": doc.content_type,
    }


@router.patch("/documents/{doc_id}")
def update_document(
    doc_id: str,
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    """Update document metadata (path, title, etc.)"""
    try:
        doc = db.get(Document, _parse_uuid(doc_id))
        if not doc or doc.owner_user_id != user.id:
            raise HTTPException(404, "not found")

        if "path" in body:
            new_path = body["path"]
            if new_path == "":
                new_path = None
            doc.path = new_path

        if "title" in body:
            doc.title = body["title"]

        if "filename" in body:
            doc.filename = body["filename"]

        doc.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(doc)

        return {
            "id": str(doc.id),
            "filename": doc.filename,
            "path": doc.path,
            "title": doc.title,
            "updated_at": doc.updated_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        import logging

        logging.error(f"Error updating document: {e}")
        db.rollback()
        raise HTTPException(500, "Failed to update document")


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document_endpoint(
    doc_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf_token),
):
    doc = db.get(Document, _parse_uuid(doc_id))
    if not doc or doc.owner_user_id != user.id:
        raise HTTPException(404, "not found")
    try:
        delete_object(doc.s3_key)
    except Exception:
        logger.exception("Failed to delete object %s from storage", doc.s3_key)
    try:
        os_delete(str(doc.id))
    except Exception:
        logger.exception("Failed to delete document %s from search index", doc.id)
    db.delete(doc)
    db.commit()
    return Response(status_code=204)


# Search
@router.get("/search")
def search(
    q: str = Query(..., min_length=1, max_length=500),
    path_prefix: str | None = None,
    user: User = Depends(current_user),
):
    try:
        res = os_search(q, size=25, path_prefix=path_prefix)
        hits = []
        for h in res.get("hits", {}).get("hits", []):
            src = h.get("_source", {})
            hits.append(
                {
                    "id": src.get("id"),
                    "filename": src.get("filename"),
                    "title": src.get("title"),
                    "path": src.get("path"),
                    "content_type": src.get("content_type"),
                    "score": h.get("_score"),
                    "snippet": (
                        " ... ".join(
                            h.get("highlight", {}).get(
                                "text", src.get("text", "")[:200:]
                            )
                        )
                        if h.get("highlight")
                        else None
                    ),
                }
            )
        return {"count": len(hits), "hits": hits}
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(500, "Search failed")
