import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from uuid import uuid4
from fastapi import FastAPI, Depends, HTTPException, Query, Body, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from .config import settings
from .db import Base, engine
from .models import Document, DocStatus, User, ShareLink, Folder
from .storage import ensure_bucket, presign_put, presign_get, multipart_start, presign_part, multipart_complete, s3, get_object, put_object, delete_object
from .search import ensure_index, search as os_search, delete_document as os_delete
from .tasks import celery_app
from .security import get_db, current_user, hash_password, verify_password, sign_token
from .watermark import build_watermarked_pdf, normalize_watermark_text
from pydantic import BaseModel
from .users import router as users_router
from .sharing import router as sharing_router
from .favorites import router as favorites_router
from .versioning import router as versioning_router
from .ai_intelligence import router as ai_router
from .ai_orchestrator import router as orchestrator_router
from .cases import router as cases_router
from .simple_cases import router as simple_cases_router
from .programmes import router as programmes_router

logger = logging.getLogger(__name__)
bearer = HTTPBearer()


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, "invalid document id")


class DocumentSummary(BaseModel):
    id: str
    filename: str
    path: Optional[str] = None
    status: str
    size: int
    content_type: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class DocumentListResponse(BaseModel):
    total: int
    items: List[DocumentSummary]


class PathListResponse(BaseModel):
    paths: List[str]
app = FastAPI(title="VeriCase Docs API", version="0.3.0")

# Include routers
app.include_router(users_router)
app.include_router(sharing_router)
app.include_router(favorites_router)
app.include_router(versioning_router)
app.include_router(ai_router)
app.include_router(orchestrator_router)
app.include_router(simple_cases_router)  # Must come BEFORE cases_router to match first
app.include_router(cases_router)
app.include_router(programmes_router)

origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
_here = Path(__file__).resolve()
_base_dir = _here.parent.parent  # /code or repo/api
_ui_candidates = [
    _base_dir / "ui",
    _base_dir.parent / "ui",
]
UI_DIR = next((c for c in _ui_candidates if c.exists()), None)
if UI_DIR:
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
else:
    logger.warning("UI directory not found in candidates %s; /ui mount disabled", _ui_candidates)

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine); ensure_bucket(); ensure_index()
# Auth
@app.post("/api/auth/register")
@app.post("/auth/signup")  # Keep old endpoint for compatibility
def signup(payload: dict = Body(...), db: Session = Depends(get_db)):
    email=(payload.get("email") or "").strip().lower(); password=payload.get("password") or ""
    display_name = (payload.get("display_name") or payload.get("full_name") or "").strip()
    from .models import User
    if db.query(User).filter(User.email==email).first(): raise HTTPException(409,"email already registered")
    user=User(email=email, password_hash=hash_password(password), display_name=display_name or None); db.add(user); db.commit()
    token=sign_token(str(user.id), user.email)
    return {"access_token": token, "token_type": "bearer", "user":{"id":str(user.id),"email":user.email,"display_name":display_name,"full_name":display_name}}

@app.post("/api/auth/login")
@app.post("/auth/login")  # Keep old endpoint for compatibility
def login(payload: dict = Body(...), db: Session = Depends(get_db)):
    email=(payload.get("email") or "").strip().lower(); password=payload.get("password") or ""
    user=db.query(User).filter(User.email==email).first()
    if not user or not verify_password(password, user.password_hash): raise HTTPException(401,"invalid credentials")
    token=sign_token(str(user.id), user.email)
    display_name = getattr(user, "display_name", None) or ""
    return {"access_token": token, "token_type": "bearer", "user":{"id":str(user.id),"email":user.email,"display_name":display_name,"full_name":display_name}}

@app.get("/api/auth/me")
def get_current_user_info(creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    from .security import current_user
    user = current_user(creds, db)
    display_name = getattr(user, "display_name", None) or ""
    return {"id":str(user.id),"email":user.email,"display_name":display_name,"full_name":display_name}

# Projects/Cases
@app.post("/api/projects")
@app.post("/api/cases")
def create_case(payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .models import Case, Company, UserCompany
    
    # Get or create company for this user
    user_company = db.query(UserCompany).filter(UserCompany.user_id == user.id, UserCompany.is_primary == True).first()
    if user_company:
        company = user_company.company
    else:
        # Create new company
        company = Company(name=payload.get("company_name") or "My Company")
        db.add(company)
        db.flush()
        # Link user to company
        user_company = UserCompany(user_id=user.id, company_id=company.id, role="admin", is_primary=True)
        db.add(user_company)
        db.flush()
    
    # Extract case data from wizard payload
    details = payload.get("details", {})
    stakeholders = payload.get("stakeholders", {})
    
    case = Case(
        case_number=details.get("projectCode") or f"CASE-{uuid4().hex[:8].upper()}",
        name=details.get("projectName") or "Untitled Case",
        description=details.get("description") or "",
        project_name=details.get("projectName"),
        contract_type=payload.get("contractType") or stakeholders.get("contractType"),
        status="active",
        owner_id=user.id,
        company_id=company.id
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    
    return {
        "id": str(case.id),
        "case_number": case.case_number,
        "name": case.name,
        "status": case.status
    }

# Uploads (presign and complete)
@app.post("/uploads/init")
def init_upload(body: dict = Body(...), user: User = Depends(current_user)):
    """Initialize file upload - returns upload_id and presigned URL"""
    filename=body.get("filename"); ct=body.get("content_type") or "application/octet-stream"
    size=int(body.get("size") or 0)
    
    # Generate unique upload ID and S3 key
    upload_id = str(uuid4())
    s3_key = f"uploads/{user.id}/{upload_id}/{filename}"
    
    # Get presigned PUT URL
    upload_url = presign_put(s3_key, ct)
    
    return {
        "upload_id": upload_id,
        "upload_url": upload_url,
        "s3_key": s3_key
    }

@app.post("/uploads/presign")
def presign_upload(body: dict = Body(...), user: User = Depends(current_user)):
    filename=body.get("filename"); ct=body.get("content_type") or "application/octet-stream"
    path=(body.get("path") or "").strip().strip("/")
    key=f"{path + '/' if path else ''}{uuid.uuid4()}/{filename}"
    url=presign_put(key, ct); return {"key":key, "url":url}
@app.post("/uploads/complete")
def complete_upload(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .models import Document, DocStatus
    
    # Support both new (upload_id) and legacy (key) formats
    upload_id = body.get("upload_id")
    filename = body.get("filename") or "file"
    
    if upload_id:
        # New format: construct key from upload_id
        key = f"uploads/{user.id}/{upload_id}/{filename}"
    else:
        # Legacy format: use provided key
        key = body.get("key")
    
    ct = body.get("content_type") or "application/octet-stream"
    size = int(body.get("size") or 0)
    title = body.get("title")
    path = body.get("path")
    
    # Set empty paths to None so they're treated consistently
    if path == "": path = None
    
    doc=Document(
        filename=filename, 
        path=path, 
        content_type=ct, 
        size=size, 
        bucket=settings.MINIO_BUCKET, 
        s3_key=key, 
        title=title, 
        status=DocStatus.NEW, 
        owner_user_id=user.id
    )
    db.add(doc); db.commit(); 
    
    # Check if PST file - trigger PST processor instead of OCR
    if filename.lower().endswith('.pst'):
        # Get case_id and company_id from body or user
        case_id = body.get("case_id") or str(user.id)  # Default to user ID if no case
        company_id = body.get("company_id", "1")
        
        celery_app.send_task(
            "worker_app.worker.process_pst_file", 
            args=[str(doc.id), case_id, company_id]
        )
        return {"id": str(doc.id), "status":"PROCESSING_PST", "message": "PST file queued for extraction"}
    else:
        # Queue OCR and AI classification for other files
        celery_app.send_task("worker_app.worker.ocr_and_index", args=[str(doc.id)])
        return {"id": str(doc.id), "status":"QUEUED", "ai_enabled": True}

@app.post("/uploads/multipart/start")
def multipart_start_ep(body: dict = Body(...), user: User = Depends(current_user)):
    filename=body.get("filename"); ct=body.get("content_type") or "application/octet-stream"
    path=(body.get("path") or "").strip().strip("/"); key=f"{path + '/' if path else ''}{uuid.uuid4()}/{filename}"
    upload_id=multipart_start(key, ct); return {"key":key, "uploadId": upload_id}
@app.get("/uploads/multipart/part")
def multipart_part_url(key: str, uploadId: str, partNumber: int, user: User = Depends(current_user)):
    return {"url": presign_part(key, uploadId, partNumber)}
@app.post("/uploads/multipart/complete")
def multipart_complete_ep(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    key=body["key"]; upload_id=body["uploadId"]; parts=body["parts"]; multipart_complete(key, upload_id, parts)
    filename=body.get("filename") or "file"; ct=body.get("content_type") or "application/octet-stream"
    size=int(body.get("size") or 0); title=body.get("title"); path=body.get("path")
    # Set empty paths to None so they're treated consistently
    if path == "": path = None
    
    doc=Document(
        filename=filename, 
        path=path, 
        content_type=ct, 
        size=size, 
        bucket=settings.MINIO_BUCKET, 
        s3_key=key, 
        title=title, 
        status=DocStatus.NEW, 
        owner_user_id=user.id
    )
    db.add(doc); db.commit(); celery_app.send_task("worker_app.worker.ocr_and_index", args=[str(doc.id)])
    return {"id": str(doc.id), "status":"QUEUED"}


@app.get("/documents", response_model=DocumentListResponse)
def list_documents(
    path_prefix: Optional[str] = Query(default=None),
    exact_folder: bool = Query(default=False),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    from .models import UserRole
    
    # Admin sees all documents except other users' private documents
    if user.role == UserRole.ADMIN:
        # Start with all documents
        query = db.query(Document)
        # Then filter out private documents from other users
        from sqlalchemy import or_, and_
        query = query.filter(
            or_(
                Document.path.is_(None),  # Documents with no path
                ~Document.path.like('private/%'),  # Not in private folder
                and_(Document.path.like('private/%'), Document.owner_user_id == user.id)  # Or it's admin's own private folder
            )
        )
    else:
        # Regular users see only their own documents
        query = db.query(Document).filter(Document.owner_user_id == user.id)
    if path_prefix is not None:
        if path_prefix == "":
            # Empty string means root - show documents with no path or empty path
            query = query.filter((Document.path == None) | (Document.path == ""))
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
                        (Document.path == safe_path) | (Document.path.like(like_pattern))
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


@app.get("/documents/paths", response_model=PathListResponse)
def list_paths(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    paths = (
        db.query(Document.path)
        .filter(Document.owner_user_id == user.id, Document.path.isnot(None))
        .distinct().all()
    )
    path_values = sorted(
        p[0]
        for p in paths
        if p[0]
    )
    return PathListResponse(paths=path_values)

@app.get("/documents/recent", response_model=DocumentListResponse)
def get_recent_documents(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get recently accessed or created documents"""
    from datetime import datetime, timedelta
    
    # Get documents accessed in last 30 days, or fall back to recently created
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Try to get recently accessed first
    recent_query = db.query(Document).filter(
        Document.owner_user_id == user.id,
        Document.last_accessed_at.isnot(None),
        Document.last_accessed_at >= thirty_days_ago
    ).order_by(Document.last_accessed_at.desc())
    
    recent_docs = recent_query.limit(limit).all()
    
    # If not enough recently accessed, add recently created
    if len(recent_docs) < limit:
        created_query = db.query(Document).filter(
            Document.owner_user_id == user.id
        ).order_by(Document.created_at.desc())
        
        created_docs = created_query.limit(limit - len(recent_docs)).all()
        
        # Merge and deduplicate
        seen_ids = {doc.id for doc in recent_docs}
        for doc in created_docs:
            if doc.id not in seen_ids:
                recent_docs.append(doc)
                seen_ids.add(doc.id)
    
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
@app.get("/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc=db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404,"not found")
    return {"id":str(doc.id),"filename":doc.filename,"path":doc.path,"status":doc.status.value,
            "content_type":doc.content_type,"size":doc.size,"bucket":doc.bucket,"s3_key":doc.s3_key,
            "title":doc.title,"metadata":doc.meta,"text_excerpt":(doc.text_excerpt or "")[:1000],
            "created_at":doc.created_at,"updated_at":doc.updated_at}
@app.get("/documents/{doc_id}/signed_url")
def get_signed_url(doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc=db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404,"not found")
    return {"url": presign_get(doc.s3_key, 300), "filename": doc.filename, "content_type": doc.content_type}


@app.patch("/documents/{doc_id}")
def update_document(doc_id: str, body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Update document metadata (path, title, etc.)"""
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
    
    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "path": doc.path,
        "title": doc.title,
        "updated_at": doc.updated_at
    }

@app.delete("/documents/{doc_id}", status_code=204)
def delete_document_endpoint(doc_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
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
@app.get("/search")
def search(q: str = Query(..., min_length=1), path_prefix: Optional[str] = None, user: User = Depends(current_user)):
    res=os_search(q, size=25, path_prefix=path_prefix); hits=[]
    for h in res.get("hits",{}).get("hits",[]):
        src=h.get("_source",{})
        hits.append({"id":src.get("id"),"filename":src.get("filename"),"title":src.get("title"),
                     "path":src.get("path"),"content_type":src.get("content_type"),"score":h.get("_score"),
                     "snippet":" ... ".join(h.get("highlight",{}).get("text", src.get("text","")[:200:])) if h.get("highlight") else None})
    return {"count": len(hits), "hits": hits}
# Share links
@app.post("/shares")
def create_share(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    doc_id=body.get("document_id"); hours=int(body.get("hours") or 24)
    if not doc_id:
        raise HTTPException(400, "document_id required")
    doc=db.get(Document, _parse_uuid(doc_id))
    if not doc:
        raise HTTPException(404,"document not found")
    if hours < 1:
        hours = 1
    if hours > 168:
        hours = 168
    password = body.get("password")
    password_hash = None
    if password:
        password = password.strip()
        if len(password) < 4 or len(password) > 128:
            raise HTTPException(400, "password length must be between 4 and 128 characters")
        password_hash = hash_password(password)
    token=uuid.uuid4().hex; expires=datetime.utcnow() + timedelta(hours=hours)
    share=ShareLink(token=token, document_id=doc.id, created_by=user.id, expires_at=expires, password_hash=password_hash); db.add(share); db.commit()
    return {"token": token, "expires_at": expires, "requires_password": bool(password_hash)}
@app.get("/shares/{token}")
def resolve_share(token: str, password: Optional[str] = Query(default=None), watermark: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    now=datetime.utcnow()
    share=db.query(ShareLink).options(joinedload(ShareLink.document)).filter(ShareLink.token==token, ShareLink.expires_at>now).first()
    if not share: raise HTTPException(404,"invalid or expired")
    if share.password_hash:
        if not password or not verify_password(password, share.password_hash):
            raise HTTPException(401,"password required")
    document = share.document
    if not document:
        raise HTTPException(500,"document missing")
    if watermark:
        sanitized = normalize_watermark_text(watermark)
        if not sanitized:
            raise HTTPException(400,"watermark must contain printable characters")
        content_type = (document.content_type or "").lower()
        filename = (document.filename or "")
        if "pdf" not in content_type and not filename.lower().endswith(".pdf"):
            raise HTTPException(400,"watermark supported for PDFs only")
        try:
            original_bytes = get_object(document.s3_key)
            stamped = build_watermarked_pdf(original_bytes, sanitized)
            temp_key = f"shares/{token}/watermarked/{uuid4()}.pdf"
            put_object(temp_key, stamped, "application/pdf")
            url = presign_get(temp_key, 300)
            return {"url": url, "filename": filename, "content_type": "application/pdf"}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Failed to create watermarked PDF for share %s", token)
            raise HTTPException(500,"unable to generate watermark") from exc
    url=presign_get(document.s3_key, 300)
    return {"url": url, "filename": document.filename, "content_type": document.content_type}

# Folder Management
from .folders import validate_folder_path, get_parent_path, get_folder_name, create_folder_record, rename_folder_and_docs, delete_folder_and_docs

class FolderInfo(BaseModel):
    path: str
    name: str
    parent_path: Optional[str] = None
    is_empty: bool
    document_count: int
    created_at: Optional[datetime] = None

class FolderListResponse(BaseModel):
    folders: List[FolderInfo]

@app.post("/folders")
def create_folder(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Create a new empty folder"""
    path = body.get("path", "").strip()
    path = validate_folder_path(path)
    folder = create_folder_record(db, path, user.id)
    db.commit()
    db.refresh(folder)
    return {"path": folder.path, "name": folder.name, "parent_path": folder.parent_path, "created": True, "created_at": folder.created_at}

@app.patch("/folders")
def rename_folder(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Rename a folder and update all document paths"""
    old_path = body.get("old_path", "").strip()
    new_path = body.get("new_path", "").strip()
    
    # Support both new_name (for simple rename) and new_path (for full path change)
    if not old_path:
        raise HTTPException(400, "old_path is required")
    
    if not new_path:
        new_name = body.get("new_name", "").strip()
        if not new_name:
            raise HTTPException(400, "either new_path or new_name is required")
        parent = get_parent_path(old_path)
        new_path = f"{parent}/{new_name}" if parent else new_name
    
    old_path = validate_folder_path(old_path)
    new_path = validate_folder_path(new_path)
    
    try:
        documents_updated = rename_folder_and_docs(db, user.id, old_path, new_path.split('/')[-1])
        db.commit()
        return {"old_path": old_path, "new_path": new_path, "documents_updated": documents_updated, "success": True}
    except Exception as e:
        db.rollback()
        logger.exception("Failed to rename folder")
        raise HTTPException(500, f"failed to rename folder: {str(e)}")

@app.delete("/folders")
def delete_folder(body: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Delete a folder and optionally its contents"""
    path = body.get("path", "").strip()
    recursive = body.get("recursive", False)
    if not path: raise HTTPException(400, "path is required")
    path = validate_folder_path(path)
    try:
        documents_deleted, files_removed = delete_folder_and_docs(db, user.id, path, recursive, delete_object, os_delete, logger)
        db.commit()
        return {"deleted": True, "path": path, "documents_deleted": documents_deleted, "files_removed": files_removed}
    except Exception as e:
        db.rollback()
        logger.exception("Failed to delete folder")
        raise HTTPException(500, f"failed to delete folder: {str(e)}")

@app.get("/folders", response_model=FolderListResponse)
def list_folders(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """List all folders with metadata including document counts"""
    from .models import UserRole
    
    # Admin sees all folders except other users' private folders
    if user.role == UserRole.ADMIN:
        # Get all document paths
        doc_paths = db.query(Document.path, Document.owner_user_id).filter(Document.path.isnot(None)).distinct().all()
        # Filter out private folders from other users
        doc_paths = [(path, owner_id) for path, owner_id in doc_paths 
                     if not path.startswith('private/') or owner_id == user.id]
        # Convert back to tuple format
        doc_paths = [(path,) for path, _ in doc_paths]
        
        # Get all empty folders
        empty_folders = db.query(Folder).all()
        # Filter out private folders from other users
        empty_folders = [f for f in empty_folders 
                        if not f.path.startswith('private/') or f.owner_user_id == user.id]
    else:
        # Regular users see only their own folders
        doc_paths = db.query(Document.path).filter(Document.owner_user_id == user.id, Document.path.isnot(None)).distinct().all()
        empty_folders = db.query(Folder).filter(Folder.owner_user_id == user.id).all()
    folder_map = {}
    for (path,) in doc_paths:
        if not path: continue
        parts = path.split("/")
        for i in range(len(parts)):
            folder_path = "/".join(parts[:i+1])
            if folder_path not in folder_map:
                folder_map[folder_path] = {"path": folder_path, "name": get_folder_name(folder_path), "parent_path": get_parent_path(folder_path), "document_count": 0, "is_empty": False, "created_at": None}
    for (path,) in doc_paths:
        if path and path in folder_map: folder_map[path]["document_count"] += 1
    for folder in empty_folders:
        if folder.path not in folder_map:
            folder_map[folder.path] = {"path": folder.path, "name": folder.name, "parent_path": folder.parent_path, "document_count": 0, "is_empty": True, "created_at": folder.created_at}
        else:
            folder_map[folder.path]["created_at"] = folder.created_at
    for folder_path in folder_map:
        if folder_map[folder_path]["document_count"] == 0: folder_map[folder_path]["is_empty"] = True
    folders = [FolderInfo(**f) for f in folder_map.values()]
    folders.sort(key=lambda f: f.path)
    return FolderListResponse(folders=folders)
