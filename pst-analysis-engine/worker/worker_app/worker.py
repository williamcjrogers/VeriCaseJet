# cspell:ignore opensearchpy vericase sessionmaker tika ocrmypdf pypff hset hincrby
import io, os, tempfile, json
from celery import Celery
import boto3
from botocore.client import Config
from sqlalchemy import create_engine, text, func
from opensearchpy import OpenSearch, RequestsHttpConnection  # type: ignore[import-not-found]
import requests, subprocess, pytesseract  # type: ignore[import-not-found]
from PIL import Image  # type: ignore[import-not-found]
from .config import settings
import redis  # type: ignore[import-not-found]
from celery.utils.log import get_task_logger
from .logging_utils import install_log_sanitizer

logger = get_task_logger(__name__)
install_log_sanitizer()

celery_app = Celery("vericase-docs", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

# Database session factory
from sqlalchemy.orm import sessionmaker
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Helper to normalize endpoint URLs
def _normalize_endpoint(url: str | None) -> str | None:
    """Ensure endpoints include a scheme so boto3 accepts them."""
    if not url:
        return url
    # Sanitize URL to prevent injection
    url = str(url).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"http://{url}"

# Initialize S3 client based on AWS mode
use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT
if use_aws:
    # AWS S3 mode: use IRSA for credentials (no endpoint_url, no explicit keys)
    s3 = boto3.client(
        "s3",
        config=Config(signature_version="s3v4"),
        region_name=settings.AWS_REGION,
    )
else:
    # MinIO mode: use explicit endpoint and credentials
    s3 = boto3.client(
        "s3",
        endpoint_url=_normalize_endpoint(settings.MINIO_ENDPOINT),
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name=settings.AWS_REGION,
    )

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# Initialize OpenSearch client with TLS support
os_client = OpenSearch(
    hosts=[{"host": settings.OPENSEARCH_HOST, "port": settings.OPENSEARCH_PORT}],
    http_compress=True,
    use_ssl=settings.OPENSEARCH_USE_SSL,
    verify_certs=settings.OPENSEARCH_VERIFY_CERTS,
    connection_class=RequestsHttpConnection
)
def _update_status(doc_id: str, status: str, excerpt: str|None=None):
    with engine.begin() as conn:
        if excerpt is not None:
            conn.execute(text("UPDATE documents SET status=:s, text_excerpt=:e WHERE id::text=:i"),
                         {"s":status,"e":excerpt,"i":doc_id})
        else:
            conn.execute(text("UPDATE documents SET status=:s WHERE id::text=:i"), {"s":status,"i":doc_id})
def _fetch_doc(doc_id: str):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id::text, filename, content_type, bucket, s3_key, path, created_at, metadata, owner_user_id FROM documents WHERE id::text=:i"),
                           {"i": doc_id}).mappings().first()
        return dict(row) if row else None
def _index_document(doc_id: str, filename: str, created_at, content_type: str, metadata: dict, text: str, path: str|None, owner_user_id: str|None):
    body = {"id": doc_id, "filename": filename, "title": None, "path": path, "owner": owner_user_id,
            "content_type": content_type, "uploaded_at": created_at, "metadata": metadata or {}, "text": text}
    os_client.index(index=settings.OPENSEARCH_INDEX, id=doc_id, body=body)
    os_client.indices.refresh(index=settings.OPENSEARCH_INDEX)
def _tika_extract(file_bytes: bytes) -> str:
    try:
        r = requests.put(f"{settings.TIKA_URL}/tika", data=file_bytes, headers={"Accept":"text/plain"}, timeout=60)
        if r.status_code==200 and r.text: return r.text
    except (requests.RequestException, ConnectionError, TimeoutError) as e:
        logger.warning(f"Tika extraction failed: {e}")
    return ""
def _ocr_pdf_sidecar(in_path: str) -> str:
    # Validate path to prevent path traversal
    if not os.path.isabs(in_path) or ".." in in_path:
        logger.error(f"Invalid path for OCR: {in_path}")
        return ""
    
    sidecar = in_path + ".txt"
    try:
        # Use absolute path for ocrmypdf command
        subprocess.run(["/usr/bin/ocrmypdf","--sidecar", sidecar,"--force-ocr", in_path, in_path + ".ocr.pdf"], check=True, capture_output=True)
        with open(sidecar,"r",encoding="utf-8",errors="ignore") as f: return f.read()
    except subprocess.CalledProcessError as e:
        logger.warning(f"OCR failed: {e}")
        return ""
    except (IOError, OSError) as e:
        logger.error(f"File operation failed during OCR: {e}")
        return ""
    finally:
        try: os.remove(sidecar)
        except (IOError, OSError) as e:
            logger.debug(f"Failed to remove sidecar file: {e}")
def _ocr_image_bytes(file_bytes: bytes) -> str:
    try:
        from PIL import Image  # type: ignore[import-not-found]
        with Image.open(io.BytesIO(file_bytes)) as im: return pytesseract.image_to_string(im)
    except (IOError, ValueError, RuntimeError) as e:
        logger.warning(f"Image OCR failed: {e}")
        return ""
@celery_app.task(name="worker_app.worker.ocr_and_index", queue=settings.CELERY_QUEUE)
def ocr_and_index(doc_id: str):
    doc=_fetch_doc(doc_id)
    if not doc:
        return
    _update_status(doc_id,"PROCESSING",None)
    obj=s3.get_object(Bucket=doc["bucket"], Key=doc["s3_key"]); fb=obj["Body"].read()
    text=_tika_extract(fb)
    if not text or len(text.strip())<50:
        name=(doc["filename"] or "").lower()
        if name.endswith(".pdf"):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(fb); tmp.flush()
                tmp_path = tmp.name
            try:
                text=_ocr_pdf_sidecar(tmp_path) or ""
                try: os.remove(tmp_path + ".ocr.pdf")
                except (IOError, OSError) as e:
                    logger.debug(f"Failed to remove OCR output: {e}")
            finally:
                try: os.remove(tmp_path)
                except (IOError, OSError) as e:
                    logger.warning(f"Failed to remove temp file: {e}")
        else:
            text=_ocr_image_bytes(fb) or ""
    excerpt=(text.strip()[:1000]) if text else ""
    _index_document(doc_id, doc["filename"], doc["created_at"], doc.get("content_type") or "application/octet-stream", doc.get("metadata"), text or "", doc.get("path"), doc.get("owner_user_id"))
    _update_status(doc_id,"READY",excerpt)
    return {"id": doc_id, "chars": len(text or "")}


from typing import Optional

@celery_app.task(name="worker_app.worker.process_pst_file", queue=settings.CELERY_QUEUE)
def process_pst_file(doc_id: str, case_id: Optional[str], company_id: Optional[str]):
    """
    THE ULTIMATE PST PROCESSOR TASK
    
    Processes PST files with enterprise-grade extraction:
    - Extracts all emails without storing individual files (smart indexing)
    - Extracts all attachments with deduplication
    - Builds email threads (Message-ID, In-Reply-To, Conversation-Index)
    - Indexes to OpenSearch for instant search
    """
    import sys
    import logging
    from sqlalchemy.orm import Session, sessionmaker
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    logger.info(f"Starting PST processing for document {doc_id}")
    
    try:
        # Import PST processor (import here to avoid loading pypff in main process)
        sys.path.insert(0, '/code')
        from app.pst_processor import UltimatePSTProcessor  # type: ignore[import-not-found]
        from app.models import Document  # type: ignore[import-not-found]
        
        # Create DB session
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        
        try:
            # Get document info
            doc = _fetch_doc(doc_id)
            if not doc:
                logger.error(f"Document {doc_id} not found")
                return {"error": "Document not found"}
            
            # Update status
            _update_status(doc_id, "PROCESSING", "Extracting PST file...")
            
            # Initialize processor
            processor = UltimatePSTProcessor(
                db=db,
                s3_client=s3,
                opensearch_client=os_client
            )
            
            # Determine if this is for a case or project
            project_id = None
            if case_id == "00000000-0000-0000-0000-000000000000" or not case_id:
                # This is a project upload - extract project_id from document metadata
                doc_meta = doc.get('metadata', {})
                if isinstance(doc_meta, dict):
                    project_id = doc_meta.get('profile_id') if doc_meta.get('profile_type') == 'project' else None
                case_id = None
            
            # Process PST
            stats = processor.process_pst(
                pst_s3_key=doc["s3_key"],
                document_id=doc_id,
                case_id=case_id,
                company_id=company_id,
                project_id=project_id
            )
            
            # Update document status with stats
            excerpt = f"PST processed: {stats['total_emails']} emails, {stats['total_attachments']} attachments, {stats['threads_identified']} threads"
            _update_status(doc_id, "READY", excerpt)
            
            logger.info(f"PST processing completed: {stats}")
            
            return stats
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"PST processing failed: {e}", exc_info=True)
        _update_status(doc_id, "FAILED", f"PST processing error: {str(e)}")
        raise


# ========================================
# FORENSIC PST PROCESSING TASK
# ========================================

@celery_app.task(bind=True, name='worker_app.worker.process_pst_forensic_task')
def process_pst_forensic_task(self, pst_file_id: str, s3_bucket: str, s3_key: str):
    """
    Process PST file with forensic-grade extraction
    This is the commercial-grade PST processor
    
    Args:
        pst_file_id: ID of PSTFile record
        s3_bucket: S3 bucket containing the PST
        s3_key: S3 key of the PST file
    """
    logger.info(f"Starting forensic PST processing: {pst_file_id}")
    
    db = SessionLocal()
    
    try:
        # Update task progress
        self.update_state(state='PROCESSING', meta={'status': 'Initializing PST processor'})
        
        # Create processor
        from api.app.pst_forensic_processor import ForensicPSTProcessor  # type: ignore[import-not-found]
        processor = ForensicPSTProcessor(db)
        
        # Process PST file
        stats = processor.process_pst_file(pst_file_id, s3_bucket, s3_key)
        
        logger.info(f"PST processing complete: {stats}")
        
        return {
            'status': 'completed',
            'pst_file_id': pst_file_id,
            'stats': stats
        }
        
    except Exception as e:
        logger.error(f"Forensic PST processing failed: {e}", exc_info=True)
        
        # Update PST file status to failed
        from app.models import PSTFile  # type: ignore[import-not-found]
        pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
        if pst_file:
            pst_file.processing_status = 'failed'
            pst_file.error_message = str(e)
            db.commit()
        
        raise
    
    finally:
        db.close()


# ========================================
# PST PROCESSING COORDINATOR
# ========================================

@celery_app.task(name='worker_app.worker.coordinate_pst_processing')
def coordinate_pst_processing(pst_file_id: str, s3_bucket: str, s3_key: str):
    """
    Coordinate processing of large PST files by splitting work
    """
    import pypff  # type: ignore[import-not-found]
    import tempfile
    # Import from parent directory
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
    from api.app.storage import download_file_streaming
    from api.app.models import PSTFile
    
    logger.info(f"Starting PST coordination for {pst_file_id}")
    
    db = SessionLocal()
    redis_client = redis.from_url(settings.REDIS_URL)
    
    try:
        # Update status
        pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
        if not pst_file:
            raise ValueError(f"PST file {pst_file_id} not found")
        
        pst_file.processing_status = 'analyzing'
        db.commit()
        
        # Download PST to analyze structure
        with tempfile.NamedTemporaryFile(suffix='.pst', delete=False) as tmp:
            pst_path = tmp.name
            logger.info(f"Downloading PST for analysis: s3://{s3_bucket}/{s3_key}")
            download_file_streaming(s3_bucket, s3_key, tmp)
            tmp.flush()
        
        try:
            # Open PST to analyze folder structure
            pst = pypff.file()
            pst.open(pst_path)
            
            root = pst.get_root_folder()
            
            # Build list of work chunks (folder-based)
            work_chunks = []
            _collect_folders(root, "", work_chunks)
            
            logger.info(f"Found {len(work_chunks)} folders to process")
            
            # Store coordination metadata in Redis
            redis_key = f"pst:{pst_file_id}"
            redis_client.hset(redis_key, mapping={
                "total_chunks": len(work_chunks),
                "completed_chunks": 0,
                "failed_chunks": 0,
                "status": "processing"
            })
            
            # Dispatch chunk processing tasks
            chunk_tasks = []
            for idx, (folder_path, message_count) in enumerate(work_chunks):
                task = process_pst_chunk.apply_async(
                    args=[pst_file_id, s3_bucket, s3_key, folder_path, idx],
                    queue=settings.CELERY_QUEUE
                )
                chunk_tasks.append(task.id)
                
                # Update progress
                redis_client.hset(redis_key, f"chunk_{idx}", json.dumps({
                    "folder_path": folder_path,
                    "message_count": message_count,
                    "task_id": task.id,
                    "status": "dispatched"
                }))
            
            pst.close()
            
            # Monitor chunk completion
            _monitor_chunks(pst_file_id, chunk_tasks, redis_client, db)
            
        finally:
            if os.path.exists(pst_path):
                os.unlink(pst_path)
        
        return {"status": "completed", "chunks_processed": len(work_chunks)}
        
    except Exception as e:
        logger.error(f"PST coordination failed: {e}", exc_info=True)
        redis_client.hset(f"pst:{pst_file_id}", "status", "failed")
        
        pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
        if pst_file:
            pst_file.processing_status = 'failed'
            pst_file.error_message = str(e)
            db.commit()
        raise
    finally:
        db.close()


def _collect_folders(folder, path, chunks):
    """Recursively collect folders as work chunks"""
    num_messages = folder.get_number_of_sub_messages()
    
    if num_messages > 0:
        chunks.append((path, num_messages))
    
    num_folders = folder.get_number_of_sub_folders()
    for i in range(num_folders):
        sub_folder = folder.get_sub_folder(i)
        folder_name = sub_folder.get_name() or f"Folder{i}"
        sub_path = f"{path}/{folder_name}" if path else folder_name
        _collect_folders(sub_folder, sub_path, chunks)


def _monitor_chunks(pst_file_id: str, chunk_tasks: list, redis_client, db):
    """Monitor chunk completion and aggregate results"""
    import time
    from celery.result import AsyncResult
    
    redis_key = f"pst:{pst_file_id}"
    total_chunks = len(chunk_tasks)
    
    while True:
        completed = 0
        failed = 0
        
        for idx, task_id in enumerate(chunk_tasks):
            result = AsyncResult(task_id, app=celery_app)
            
            if result.ready():
                if result.successful():
                    completed += 1
                else:
                    failed += 1
        
        # Update Redis
        redis_client.hset(redis_key, mapping={
            "completed_chunks": completed,
            "failed_chunks": failed
        })
        
        # Check if all done
        if completed + failed >= total_chunks:
            break
        
        time.sleep(2)  # Check every 2 seconds
    
    # Update final status
    from api.app.models import PSTFile
    pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
    
    if pst_file:
        if failed == 0:
            pst_file.processing_status = 'completed'
        else:
            pst_file.processing_status = 'completed_with_errors'
            pst_file.error_message = f"{failed} chunks failed processing"
        
        pst_file.processing_completed_at = func.now()
        db.commit()


# ========================================
# PST CHUNK PROCESSOR
# ========================================

@celery_app.task(bind=True, name='worker_app.worker.process_pst_chunk')
def process_pst_chunk(self, pst_file_id: str, s3_bucket: str, s3_key: str, 
                     folder_path: str, chunk_idx: int):
    """
    Process a specific folder/chunk from PST file
    """
    import pypff  # type: ignore[import-not-found]
    import tempfile
    # Import from parent directory
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
    from api.app.storage import download_file_streaming
    from api.app.pst_forensic_processor import ForensicPSTProcessor
    
    logger.info(f"Processing chunk {chunk_idx}: {folder_path}")
    
    db = SessionLocal()
    redis_client = redis.from_url(settings.REDIS_URL)
    redis_key = f"pst:{pst_file_id}"
    
    try:
        # Update chunk status
        redis_client.hset(redis_key, f"chunk_{chunk_idx}_status", "processing")
        
        # Create processor
        processor = ForensicPSTProcessor(db)
        
        # Download PST (TODO: optimize with shared cache)
        with tempfile.NamedTemporaryFile(suffix='.pst', delete=False) as tmp:
            pst_path = tmp.name
            download_file_streaming(s3_bucket, s3_key, tmp)
            tmp.flush()
        
        try:
            # Open PST and navigate to specific folder
            pst = pypff.file()
            pst.open(pst_path)
            
            root = pst.get_root_folder()
            target_folder = _navigate_to_folder(root, folder_path)
            
            if target_folder:
                # Process only this folder
                from api.app.models import PSTFile, Stakeholder, Keyword  # type: ignore[import-not-found]
                
                pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
                if not pst_file:
                    raise ValueError(f"PST file {pst_file_id} not found")
                stakeholders = db.query(Stakeholder).filter_by(case_id=pst_file.case_id).all()
                keywords = db.query(Keyword).filter_by(case_id=pst_file.case_id).all()
                
                stats = {"total_emails": 0, "total_attachments": 0, "errors": []}
                
                processor._process_folder_recursive(
                    target_folder,
                    pst_file,
                    stakeholders,
                    keywords,
                    stats,
                    folder_path
                )
                
                # Update progress
                redis_client.hincrby(redis_key, "processed_emails", stats["total_emails"])
                
                logger.info(f"Chunk {chunk_idx} processed: {stats['total_emails']} emails")
            
            pst.close()
            
        finally:
            if os.path.exists(pst_path):
                os.unlink(pst_path)
        
        # Mark chunk complete
        redis_client.hset(redis_key, f"chunk_{chunk_idx}_status", "completed")
        
        return {
            "status": "completed",
            "folder_path": folder_path,
            "emails_processed": stats.get("total_emails", 0)
        }
        
    except Exception as e:
        logger.error(f"Chunk processing failed: {e}", exc_info=True)
        redis_client.hset(redis_key, f"chunk_{chunk_idx}_status", "failed")
        raise
    finally:
        db.close()


def _navigate_to_folder(root, folder_path):
    """Navigate PST folder tree to find target folder"""
    if not folder_path:
        return root
    
    parts = folder_path.split('/')
    current = root
    
    for part in parts:
        found = False
        for i in range(current.get_number_of_sub_folders()):
            sub = current.get_sub_folder(i)
            if (sub.get_name() or f"Folder{i}") == part:
                current = sub
                found = True
                break
        
        if not found:
            logger.warning(f"Folder not found: {part} in path {folder_path}")
            return None
    
    return current
