"""Folder management functions and endpoints"""
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from .models import Folder, Document


def validate_folder_path(path: str) -> str:
    """Validate and normalize a folder path"""
    if not path:
        raise HTTPException(400, "path is required")
    
    # Strip leading/trailing slashes and whitespace
    path = path.strip().strip("/")
    
    if not path:
        raise HTTPException(400, "path cannot be empty after normalization")
    
    # Check for path traversal attempts
    if ".." in path or path.startswith("/") or "\\" in path:
        raise HTTPException(400, "invalid path: path traversal not allowed")
    
    # Check for invalid characters
    invalid_chars = ["<", ">", ":", '"', "|", "?", "*"]
    if any(char in path for char in invalid_chars):
        raise HTTPException(400, f"invalid path: contains forbidden characters")
    
    # Check for reserved names (Windows compatibility)
    reserved = ["CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", 
                "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", 
                "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"]
    parts = path.split("/")
    for part in parts:
        if part.upper() in reserved:
            raise HTTPException(400, f"invalid path: '{part}' is a reserved name")
    
    # Check depth (max 10 levels)
    if len(parts) > 10:
        raise HTTPException(400, "path depth exceeds maximum of 10 levels")
    
    # Check length
    if len(path) > 1024:
        raise HTTPException(400, "path exceeds maximum length of 1024 characters")
    
    return path


def get_parent_path(path: str) -> Optional[str]:
    """Get parent path from a path"""
    if not path or "/" not in path:
        return None
    return "/".join(path.split("/")[:-1])


def get_folder_name(path: str) -> str:
    """Extract folder name from path"""
    if not path:
        return ""
    return path.split("/")[-1]


def create_folder_record(db: Session, path: str, owner_user_id: str) -> Folder:
    """Create a folder record in the database"""
    path = validate_folder_path(path)
    
    # Parameterized query via SQLAlchemy select()
    existing_stmt = select(Folder).where(
        Folder.owner_user_id == owner_user_id,
        Folder.path == path
    )
    existing_folder = db.execute(existing_stmt).scalars().first()
    
    if existing_folder:
        raise HTTPException(409, "folder already exists")
    
    # Parameterized query via SQLAlchemy select()
    count_stmt = select(func.count()).select_from(Document).where(
        Document.owner_user_id == owner_user_id,
        Document.path == path
    )
    doc_count = db.execute(count_stmt).scalar() or 0
    
    if doc_count > 0:
        raise HTTPException(409, "path already contains documents")
    
    # Create the folder
    name = get_folder_name(path)
    parent_path = get_parent_path(path)
    
    folder = Folder(
        path=path,
        name=name,
        parent_path=parent_path,
        owner_user_id=owner_user_id
    )
    db.add(folder)
    return folder


def rename_folder_and_docs(db: Session, owner_user_id: str, old_path: str, new_name: str) -> int:
    """Rename a folder and update all document paths"""
    old_path = validate_folder_path(old_path)
    
    if "/" in new_name or "\\" in new_name:
        raise HTTPException(400, "new_name cannot contain path separators")
    
    parent = get_parent_path(old_path)
    new_path = f"{parent}/{new_name}" if parent else new_name
    new_path = validate_folder_path(new_path)
    
    # Parameterized query via SQLAlchemy select()
    existing_stmt = select(Folder).where(
        Folder.owner_user_id == owner_user_id,
        Folder.path == new_path
    )
    existing = db.execute(existing_stmt).scalars().first()
    
    if existing:
        raise HTTPException(409, "destination folder already exists")
    
    # Parameterized query via SQLAlchemy select()
    count_stmt = select(func.count()).select_from(Document).where(
        Document.owner_user_id == owner_user_id,
        Document.path == new_path
    )
    doc_count = db.execute(count_stmt).scalar() or 0
    
    if doc_count > 0:
        raise HTTPException(409, "destination path already contains documents")
    
    # Parameterized query via SQLAlchemy select()
    folder_stmt = select(Folder).where(
        Folder.owner_user_id == owner_user_id,
        Folder.path == old_path
    )
    folder = db.execute(folder_stmt).scalars().first()
    
    documents_updated = 0
    old_prefix = f"{old_path}/"
    
    # Parameterized query via SQLAlchemy select()
    docs_stmt = select(Document).where(
        Document.owner_user_id == owner_user_id,
        Document.path == old_path
    )
    docs = db.execute(docs_stmt).scalars().all()
    
    for doc in docs:
        doc.path = new_path
        documents_updated += 1
    
    # Parameterized query via SQLAlchemy select()
    subdocs_stmt = select(Document).where(
        Document.owner_user_id == owner_user_id,
        Document.path.startswith(old_prefix)
    )
    subdocs = db.execute(subdocs_stmt).scalars().all()
    
    old_path_len = len(old_path)
    for doc in subdocs:
        if doc.path and doc.path.startswith(old_prefix):
            doc.path = new_path + doc.path[old_path_len:]
            documents_updated += 1
    
    if folder:
        folder.path = new_path
        folder.name = new_name
        folder.parent_path = parent
    
    # Parameterized query via SQLAlchemy select()
    subfolders_stmt = select(Folder).where(
        Folder.owner_user_id == owner_user_id,
        Folder.path.startswith(old_prefix)
    )
    subfolders = db.execute(subfolders_stmt).scalars().all()
    
    for subfolder in subfolders:
        if subfolder.path.startswith(old_prefix):
            subfolder.path = new_path + subfolder.path[old_path_len:]
            subfolder.parent_path = get_parent_path(subfolder.path)
    
    return documents_updated


def delete_folder_and_docs(db: Session, owner_user_id: str, path: str, recursive: bool, delete_object_func, os_delete_func, logger) -> tuple:
    """Delete a folder and optionally its contents"""
    path = validate_folder_path(path)
    
    # Parameterized query via SQLAlchemy select()
    doc_count_stmt = select(func.count()).select_from(Document).where(
        Document.owner_user_id == owner_user_id,
        Document.path == path
    )
    doc_count = db.execute(doc_count_stmt).scalar() or 0
    
    # Parameterized query via SQLAlchemy select()
    subdoc_count_stmt = select(func.count()).select_from(Document).where(
        Document.owner_user_id == owner_user_id,
        Document.path.startswith(path + "/")
    )
    subdoc_count = db.execute(subdoc_count_stmt).scalar() or 0
    
    total_docs = doc_count + subdoc_count
    
    if total_docs > 0 and not recursive:
        raise HTTPException(400, f"folder contains {total_docs} document(s). Use recursive=true to delete with contents")
    
    documents_deleted = 0
    files_removed = 0
    
    if recursive and total_docs > 0:
        # Parameterized query via SQLAlchemy select()
        docs_stmt = select(Document).where(
            Document.owner_user_id == owner_user_id,
            Document.path == path
        )
        docs = db.execute(docs_stmt).scalars().all()
        
        for doc in docs:
            try:
                delete_object_func(doc.s3_key)
                files_removed += 1
            except Exception:
                logger.exception("Failed to delete object %s", doc.s3_key)
            
            try:
                os_delete_func(str(doc.id))
            except Exception:
                logger.exception("Failed to delete from search %s", doc.id)
            
            db.delete(doc)
            documents_deleted += 1
        
        # Parameterized query via SQLAlchemy select()
        subdocs_stmt = select(Document).where(
            Document.owner_user_id == owner_user_id,
            Document.path.startswith(path + "/")
        )
        subdocs = db.execute(subdocs_stmt).scalars().all()
        
        for doc in subdocs:
            try:
                delete_object_func(doc.s3_key)
                files_removed += 1
            except Exception:
                logger.exception("Failed to delete object %s", doc.s3_key)
            
            try:
                os_delete_func(str(doc.id))
            except Exception:
                logger.exception("Failed to delete from search %s", doc.id)
            
            db.delete(doc)
            documents_deleted += 1
    
    # Parameterized query via SQLAlchemy select()
    folder_stmt = select(Folder).where(
        Folder.owner_user_id == owner_user_id,
        Folder.path == path
    )
    folder = db.execute(folder_stmt).scalars().first()
    
    if folder:
        db.delete(folder)
    
    # Parameterized query via SQLAlchemy select()
    subfolders_stmt = select(Folder).where(
        Folder.owner_user_id == owner_user_id,
        Folder.path.startswith(path + "/")
    )
    subfolders = db.execute(subfolders_stmt).scalars().all()
    
    for subfolder in subfolders:
        db.delete(subfolder)
    
    return documents_deleted, files_removed
