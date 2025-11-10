"""Folder management functions and endpoints"""
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .models import Folder, Document


def validate_folder_path(path: str) -> str:
    """Validate and normalize a folder path"""
    try:
        if not path:
            raise HTTPException(400, "path is required")
        
        # Strip leading/trailing slashes and whitespace
        path = path.strip().strip("/")
    except (AttributeError, TypeError) as e:
        raise HTTPException(400, f"invalid path type: {e}")
    
    try:
        if not path:
            raise HTTPException(400, "path cannot be empty after normalization")
        
        # Check for path traversal attempts
        if ".." in path or path.startswith("/") or "\\" in path:
            raise HTTPException(400, "invalid path: path traversal not allowed")
    except (AttributeError, TypeError) as e:
        raise HTTPException(400, f"path validation error: {e}")
    
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
    try:
        if not owner_user_id:
            raise HTTPException(400, "owner_user_id is required")
        
        # Check if folder already exists (parameterized query via SQLAlchemy ORM)
        existing_folder = db.query(Folder).filter(
            Folder.owner_user_id == owner_user_id,
            Folder.path == path
        ).first()
        
        if existing_folder:
            raise HTTPException(409, "folder already exists")
        
        # Check if documents exist at this path (parameterized query via SQLAlchemy ORM)
        doc_count = db.query(Document).filter(
            Document.owner_user_id == owner_user_id,
            Document.path == path
        ).count()
        
        if doc_count > 0:
            raise HTTPException(409, "path already contains documents")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"database error: {e}")
    
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
    try:
        if "/" in new_name or "\\" in new_name:
            raise HTTPException(400, "new_name cannot contain path separators")
        
        parent = get_parent_path(old_path)
        new_path = f"{parent}/{new_name}" if parent else new_name
        new_path = validate_folder_path(new_path)
        
        # Check if new path already exists (parameterized query via SQLAlchemy ORM)
        existing = db.query(Folder).filter(
            Folder.owner_user_id == owner_user_id,
            Folder.path == new_path
        ).first()
        
        if existing:
            raise HTTPException(409, "destination folder already exists")
        
        # Check if documents exist at new path (parameterized query via SQLAlchemy ORM)
        doc_count = db.query(Document).filter(
            Document.owner_user_id == owner_user_id,
            Document.path == new_path
        ).count()
        
        if doc_count > 0:
            raise HTTPException(409, "destination path already contains documents")
        
        # Update the folder record if it exists (parameterized query via SQLAlchemy ORM)
        folder = db.query(Folder).filter(
            Folder.owner_user_id == owner_user_id,
            Folder.path == old_path
        ).first()
        
        old_prefix = f"{old_path}/"
        documents_updated = 0
        
        # Batch update all documents at this exact path (parameterized query via SQLAlchemy ORM)
        docs = db.query(Document).filter(
            Document.owner_user_id == owner_user_id,
            Document.path == old_path
        ).all()
        
        for doc in docs:
            doc.path = new_path
            documents_updated += 1
        
        # Batch update all documents in subfolders (parameterized query via SQLAlchemy ORM)
        subdocs = db.query(Document).filter(
            Document.owner_user_id == owner_user_id,
            Document.path.like(f"{old_prefix}%")
        ).all()
        
        old_path_len = len(old_path)
        for doc in subdocs:
            if doc.path and doc.path.startswith(old_prefix):
                doc.path = new_path + doc.path[old_path_len:]
                documents_updated += 1
        
        if folder:
            folder.path = new_path
            folder.name = new_name
            folder.parent_path = parent
        
        # Batch update any empty subfolders (parameterized query via SQLAlchemy ORM)
        subfolders = db.query(Folder).filter(
            Folder.owner_user_id == owner_user_id,
            Folder.path.like(f"{old_prefix}%")
        ).all()
        
        for subfolder in subfolders:
            if subfolder.path.startswith(old_prefix):
                subfolder.path = new_path + subfolder.path[old_path_len:]
                subfolder.parent_path = get_parent_path(subfolder.path)
        
        return documents_updated
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"rename operation failed: {e}")


def delete_folder_and_docs(db: Session, owner_user_id: str, path: str, recursive: bool, delete_object_func, os_delete_func, logger) -> tuple:
    """Delete a folder and optionally its contents"""
    try:
        # Count documents at this path (parameterized query via SQLAlchemy ORM)
        doc_count = db.query(Document).filter(
            Document.owner_user_id == owner_user_id,
            Document.path == path
        ).count()
        
        # Count documents in subfolders (parameterized query via SQLAlchemy ORM)
        subdoc_count = db.query(Document).filter(
            Document.owner_user_id == owner_user_id,
            Document.path.like(f"{path}/%")
        ).count()
        
        total_docs = doc_count + subdoc_count
        
        if total_docs > 0 and not recursive:
            raise HTTPException(400, f"folder contains {total_docs} document(s). Use recursive=true to delete with contents")
        
        documents_deleted = 0
        files_removed = 0
        
        if recursive and total_docs > 0:
            # Batch fetch documents at this path (parameterized query via SQLAlchemy ORM)
            docs = db.query(Document).filter(
                Document.owner_user_id == owner_user_id,
                Document.path == path
            ).all()
            
            for doc in docs:
                try:
                    delete_object_func(doc.s3_key)
                    files_removed += 1
                except Exception as e:
                    logger.error(f"Failed to delete object {doc.s3_key}: {e}")
                
                try:
                    os_delete_func(str(doc.id))
                except Exception as e:
                    logger.error(f"Failed to delete from search {doc.id}: {e}")
                
                db.delete(doc)
                documents_deleted += 1
            
            # Batch fetch documents in subfolders (parameterized query via SQLAlchemy ORM)
            subdocs = db.query(Document).filter(
                Document.owner_user_id == owner_user_id,
                Document.path.like(f"{path}/%")
            ).all()
            
            for doc in subdocs:
                try:
                    delete_object_func(doc.s3_key)
                    files_removed += 1
                except Exception as e:
                    logger.error(f"Failed to delete object {doc.s3_key}: {e}")
                
                try:
                    os_delete_func(str(doc.id))
                except Exception as e:
                    logger.error(f"Failed to delete from search {doc.id}: {e}")
                
                db.delete(doc)
                documents_deleted += 1
        
        # Delete empty folder record (parameterized query via SQLAlchemy ORM)
        folder = db.query(Folder).filter(
            Folder.owner_user_id == owner_user_id,
            Folder.path == path
        ).first()
        
        if folder:
            db.delete(folder)
        
        # Batch delete empty subfolders (parameterized query via SQLAlchemy ORM)
        subfolders = db.query(Folder).filter(
            Folder.owner_user_id == owner_user_id,
            Folder.path.like(f"{path}/%")
        ).all()
        
        for subfolder in subfolders:
            db.delete(subfolder)
        
        return documents_deleted, files_removed
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"delete operation failed: {e}")
