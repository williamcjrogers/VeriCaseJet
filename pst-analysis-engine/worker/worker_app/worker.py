import io, os, tempfile
from celery import Celery
import boto3
from botocore.client import Config
from sqlalchemy import create_engine, text
from opensearchpy import OpenSearch, RequestsHttpConnection
import requests, subprocess, pytesseract
from PIL import Image
from .config import settings

celery_app = Celery("vericase-docs", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

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
        endpoint_url=settings.MINIO_ENDPOINT,
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
    os_client.index(index=settings.OPENSEARCH_INDEX, id=doc_id, body=body, refresh=True)
def _tika_extract(file_bytes: bytes) -> str:
    try:
        r = requests.put(f"{settings.TIKA_URL}/tika", data=file_bytes, headers={"Accept":"text/plain"}, timeout=60)
        if r.status_code==200 and r.text: return r.text
    except Exception: pass
    return ""
def _ocr_pdf_sidecar(in_path: str) -> str:
    sidecar = in_path + ".txt"
    try:
        subprocess.run(["ocrmypdf","--sidecar", sidecar,"--force-ocr", in_path, in_path + ".ocr.pdf"], check=True, capture_output=True)
        with open(sidecar,"r",encoding="utf-8",errors="ignore") as f: return f.read()
    except subprocess.CalledProcessError: return ""
    finally:
        try: os.remove(sidecar)
        except Exception: pass
def _ocr_image_bytes(file_bytes: bytes) -> str:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(file_bytes)) as im: return pytesseract.image_to_string(im)
    except Exception: return ""
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
                text=_ocr_pdf_sidecar(tmp.name) or ""
                try: os.remove(tmp.name + ".ocr.pdf")
                except Exception: pass
                os.remove(tmp.name)
        else:
            text=_ocr_image_bytes(fb) or ""
    excerpt=(text.strip()[:1000]) if text else ""
    _index_document(doc_id, doc["filename"], doc["created_at"], doc.get("content_type") or "application/octet-stream", doc.get("metadata"), text or "", doc.get("path"), doc.get("owner_user_id"))
    _update_status(doc_id,"READY",excerpt)
    return {"id": doc_id, "chars": len(text or "")}


@celery_app.task(name="worker_app.worker.process_pst_file", queue=settings.CELERY_QUEUE)
def process_pst_file(doc_id: str, case_id: str, company_id: str):
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
        from app.pst_processor import UltimatePSTProcessor
        from app.models import Document
        
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
            
            # Process PST
            stats = processor.process_pst(
                pst_s3_key=doc["s3_key"],
                document_id=doc_id,
                case_id=case_id,
                company_id=company_id
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
