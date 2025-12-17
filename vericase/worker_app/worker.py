import io
import os
import sys
import tempfile
from celery import Celery
import boto3
from botocore.client import Config
from sqlalchemy import create_engine, text
from opensearchpy import OpenSearch, RequestsHttpConnection
import requests
import subprocess
import pytesseract
import logging
from .config import settings

logger = logging.getLogger(__name__)


def _running_under_celery_cli() -> bool:
    argv = " ".join(sys.argv).lower()
    return "celery" in argv and any(
        cmd in argv for cmd in (" worker", " beat", " flower")
    )


_TRACING_ON = False
if _running_under_celery_cli():
    try:
        from app.tracing import setup_tracing, instrument_celery, instrument_requests

        _TRACING_ON = setup_tracing("vericase-worker")
        if _TRACING_ON:
            instrument_celery()
            instrument_requests()
    except Exception:
        _TRACING_ON = False

celery_app = Celery(
    "vericase-docs", broker=settings.REDIS_URL, backend=settings.REDIS_URL
)


# Helper to normalize endpoint URLs
def _normalize_endpoint(url: str | None) -> str | None:
    """Ensure endpoints include a scheme so boto3 accepts them."""
    if not url:
        return url
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
if _TRACING_ON:
    try:
        from app.tracing import instrument_sqlalchemy

        instrument_sqlalchemy(engine)
    except Exception:
        pass


def _get_setting_from_db(key: str, default_value: str) -> str:
    """Get setting value from database with fallback to default"""
    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT value FROM app_settings WHERE key = :key"), {"key": key}
            ).scalar()
            if result:
                return str(result)
    except Exception as e:
        logger.debug(f"Failed to get setting '{key}' from DB: {e}")
    return default_value


# Initialize AWS Textract client
if settings.USE_TEXTRACT and use_aws:
    try:
        textract = boto3.client(
            "textract",
            region_name=getattr(
                settings, "AWS_REGION_FOR_TEXTRACT", settings.AWS_REGION
            ),
        )
    except Exception as e:
        logger.warning(f"Failed to initialize Textract client: {e}")
        textract = None
else:
    textract = None

# Initialize OpenSearch client with TLS support
os_client = OpenSearch(
    hosts=[{"host": settings.OPENSEARCH_HOST, "port": settings.OPENSEARCH_PORT}],
    http_compress=True,
    use_ssl=settings.OPENSEARCH_USE_SSL,
    verify_certs=settings.OPENSEARCH_VERIFY_CERTS,
    connection_class=RequestsHttpConnection,
)


def _update_status(doc_id: str, status: str, excerpt: str | None = None):
    with engine.begin() as conn:
        if excerpt is not None:
            conn.execute(
                text(
                    "UPDATE documents SET status=:s, text_excerpt=:e WHERE id::text=:i"
                ),
                {"s": status, "e": excerpt, "i": doc_id},
            )
        else:
            conn.execute(
                text("UPDATE documents SET status=:s WHERE id::text=:i"),
                {"s": status, "i": doc_id},
            )


def _fetch_doc(doc_id: str):
    import json

    with engine.begin() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id::text, filename, content_type, bucket, s3_key, path, created_at, metadata, owner_user_id FROM documents WHERE id::text=:i"
                ),
                {"i": doc_id},
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        doc = dict(row)
        # Ensure metadata is a dict (handle both JSONB and JSON string from database)
        if doc.get("metadata") and isinstance(doc["metadata"], str):
            try:
                doc["metadata"] = json.loads(doc["metadata"])
            except (json.JSONDecodeError, TypeError):
                doc["metadata"] = {}
        elif not doc.get("metadata"):
            doc["metadata"] = {}
        return doc


def _fetch_pst_file(pst_id: str):
    """Fetch PST file info from pst_files table."""
    with engine.begin() as conn:
        row = (
            conn.execute(
                text(
                    """
            SELECT id::text, filename, s3_bucket as bucket, s3_key, case_id::text, project_id::text,
                   file_size_bytes as file_size, processing_status, uploaded_by::text
            FROM pst_files WHERE id::text=:i
        """
                ),
                {"i": pst_id},
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        return dict(row)


def _update_pst_status(
    pst_id: str,
    status: str,
    error_msg: str | None = None,
    total_emails: int | None = None,
    processed_emails: int | None = None,
):
    """Update PST file processing status."""
    with engine.begin() as conn:
        if error_msg is not None:
            conn.execute(
                text(
                    """
                UPDATE pst_files SET processing_status=:s, error_message=:e,
                processing_completed_at=CURRENT_TIMESTAMP WHERE id::text=:i
            """
                ),
                {"s": status, "e": error_msg, "i": pst_id},
            )
        elif total_emails is not None:
            conn.execute(
                text(
                    """
                UPDATE pst_files SET processing_status=:s, total_emails=:t, processed_emails=:p,
                processing_completed_at=CURRENT_TIMESTAMP WHERE id::text=:i
            """
                ),
                {
                    "s": status,
                    "t": total_emails,
                    "p": processed_emails or total_emails,
                    "i": pst_id,
                },
            )
        else:
            conn.execute(
                text(
                    """
                UPDATE pst_files SET processing_status=:s, processing_started_at=CURRENT_TIMESTAMP
                WHERE id::text=:i
            """
                ),
                {"s": status, "i": pst_id},
            )


def _index_document(
    doc_id: str,
    filename: str,
    created_at,
    content_type: str,
    metadata: dict,
    text: str,
    path: str | None,
    owner_user_id: str | None,
):
    body = {
        "id": doc_id,
        "filename": filename,
        "title": None,
        "path": path,
        "owner": owner_user_id,
        "content_type": content_type,
        "uploaded_at": created_at,
        "metadata": metadata or {},
        "text": text,
    }
    os_client.index(index=settings.OPENSEARCH_INDEX, id=doc_id, body=body, refresh=True)


def _count_pdf_pages(file_bytes: bytes) -> int:
    """Count pages in a PDF file."""
    try:
        import PyPDF2

        pdf_file = io.BytesIO(file_bytes)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        return len(pdf_reader.pages)
    except Exception:
        try:
            # Fallback: try pdfplumber
            import pdfplumber

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                return len(pdf.pages)
        except Exception:
            return 0


def _textract_extract(file_bytes: bytes, filename: str = "") -> str:
    """
    Extract text using AWS Textract.
    Returns empty string if Textract fails, file is too large, or has too many pages.
    Falls back to Tika for large documents (e.g., 1000+ page PDFs).
    """
    if not textract:
        return ""

    # Check if it's a supported format (PDF, PNG, JPEG, TIFF)
    filename_lower = filename.lower()
    if not any(
        filename_lower.endswith(ext)
        for ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"]
    ):
        logger.debug(f"File {filename} format not supported by Textract, will use Tika")
        return ""

    # For PDFs, check page count first (Textract limit is 500 pages, but use Tika for large docs)
    # Get threshold from database (admin-configurable) with fallback to config
    max_pages = int(
        _get_setting_from_db(
            "textract_max_pages", str(getattr(settings, "TEXTRACT_MAX_PAGES", 500))
        )
    )
    page_threshold = int(
        _get_setting_from_db(
            "textract_page_threshold",
            str(getattr(settings, "TEXTRACT_PAGE_THRESHOLD", 100)),
        )
    )
    if filename_lower.endswith(".pdf"):
        page_count = _count_pdf_pages(file_bytes)
        if page_count > max_pages:
            logger.info(
                f"PDF {filename} has {page_count} pages, exceeds Textract limit ({max_pages} pages), will use Tika"
            )
            return ""
        elif (
            page_count > page_threshold
        ):  # Use Tika for documents over threshold (cost/speed optimization)
            logger.info(
                f"PDF {filename} has {page_count} pages, exceeds threshold ({page_threshold} pages), using Tika for better performance"
            )
            return ""

    file_size_mb = len(file_bytes) / (1024 * 1024)
    max_size_mb = getattr(settings, "TEXTRACT_MAX_FILE_SIZE_MB", 500)

    # Check if file is too large for Textract
    if file_size_mb > max_size_mb:
        logger.info(
            f"File {filename} ({file_size_mb:.2f}MB) exceeds Textract limit ({max_size_mb}MB), will use Tika"
        )
        return ""

    try:
        # Use detect_document_text for simple text extraction
        response = textract.detect_document_text(Document={"Bytes": file_bytes})

        # Extract text from blocks
        text_lines = []
        for block in response.get("Blocks", []):
            if block.get("BlockType") == "LINE":
                text_lines.append(block.get("Text", ""))

        extracted_text = "\n".join(text_lines)

        if extracted_text and len(extracted_text.strip()) > 50:
            logger.info(
                f"Textract extracted {len(extracted_text)} characters from {filename}"
            )
            return extracted_text
        else:
            logger.debug(
                f"Textract returned insufficient text for {filename}, will try Tika"
            )
            return ""

    except Exception as e:
        error_str = str(e)
        if "InvalidParameterException" in error_str or "InvalidParameter" in error_str:
            logger.warning(f"Textract invalid parameter for {filename}: {e}")
        elif (
            "DocumentTooLargeException" in error_str or "DocumentTooLarge" in error_str
        ):
            logger.info(
                f"Document {filename} too large for Textract: {e}, will use Tika"
            )
        else:
            logger.warning(
                f"Textract extraction failed for {filename}: {e}, will try Tika"
            )
        return ""


def _tika_extract(file_bytes: bytes) -> str:
    try:
        r = requests.put(
            f"{settings.TIKA_URL}/tika",
            data=file_bytes,
            headers={"Accept": "text/plain"},
            timeout=60,
        )
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass
    return ""


def _ocr_pdf_sidecar(in_path: str) -> str:
    sidecar = in_path + ".txt"
    try:
        subprocess.run(
            [
                "ocrmypdf",
                "--sidecar",
                sidecar,
                "--force-ocr",
                in_path,
                in_path + ".ocr.pdf",
            ],
            check=True,
            capture_output=True,
        )
        with open(sidecar, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except subprocess.CalledProcessError:
        return ""
    finally:
        try:
            os.remove(sidecar)
        except Exception:
            pass


def _ocr_image_bytes(file_bytes: bytes) -> str:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(file_bytes)) as im:
            return pytesseract.image_to_string(im)
    except Exception:
        return ""


@celery_app.task(name="worker_app.worker.ocr_and_index", queue=settings.CELERY_QUEUE)
def ocr_and_index(doc_id: str):
    doc = _fetch_doc(doc_id)
    if not doc:
        return
    _update_status(doc_id, "PROCESSING", None)
    obj = s3.get_object(Bucket=doc["bucket"], Key=doc["s3_key"])
    fb = obj["Body"].read()

    # Try Textract first (for small/medium documents)
    filename = doc.get("filename") or ""
    text = ""
    if settings.USE_TEXTRACT:
        text = _textract_extract(fb, filename)

    # Fall back to Tika if Textract didn't work (large files, unsupported formats, or failed)
    if not text or len(text.strip()) < 50:
        logger.info(
            f"Textract didn't extract sufficient text for {filename}, trying Tika"
        )
        text = _tika_extract(fb)

    # Final fallback: OCR for PDFs/images if both Textract and Tika failed
    if not text or len(text.strip()) < 50:
        name = filename.lower()
        if name.endswith(".pdf"):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(fb)
                tmp.flush()
                text = _ocr_pdf_sidecar(tmp.name) or ""
                try:
                    os.remove(tmp.name + ".ocr.pdf")
                except Exception:
                    pass
                os.remove(tmp.name)
        else:
            text = _ocr_image_bytes(fb) or ""

    excerpt = (text.strip()[:1000]) if text else ""
    _index_document(
        doc_id,
        doc["filename"],
        doc["created_at"],
        doc.get("content_type") or "application/octet-stream",
        doc.get("metadata"),
        text or "",
        doc.get("path"),
        doc.get("owner_user_id"),
    )
    _update_status(doc_id, "READY", excerpt)
    return {"id": doc_id, "chars": len(text or "")}


@celery_app.task(
    name="worker_app.worker.process_pst_file", queue=settings.CELERY_PST_QUEUE
)
def process_pst_file(
    doc_id: str, case_id: str | None = None, company_id: str | None = None
):
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
    from sqlalchemy.orm import sessionmaker

    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    logger.info(f"Starting PST processing for PST file {doc_id}")

    try:
        # Import PST processor (import here to avoid loading pypff in main process)
        # The pst_processor module is in /code/api/app/
        sys.path.insert(0, "/code/api")
        from app.pst_processor import UltimatePSTProcessor

        # Create DB session
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            # Get PST file info from pst_files table
            pst_file = _fetch_pst_file(doc_id)
            if not pst_file:
                logger.error(f"PST file {doc_id} not found in pst_files table")
                return {"error": "PST file not found"}

            # Update status to processing
            _update_pst_status(doc_id, "processing")

            logger.info(
                f"Processing PST: {pst_file['filename']} from {pst_file['bucket']}/{pst_file['s3_key']}"
            )

            # Initialize processor
            processor = UltimatePSTProcessor(
                db=db, s3_client=s3, opensearch_client=os_client
            )

            # Process PST - use case_id and project_id from the pst_file record
            stats = processor.process_pst(
                pst_s3_key=pst_file["s3_key"],
                pst_s3_bucket=pst_file.get("bucket"),
                document_id=doc_id,
                case_id=pst_file.get("case_id"),
                company_id=pst_file.get(
                    "project_id"
                ),  # project_id maps to company_id in processor
            )

            # Update PST file status with stats
            _update_pst_status(
                doc_id,
                "completed",
                total_emails=stats.get("total_emails", 0),
                processed_emails=stats.get(
                    "processed_emails", stats.get("total_emails", 0)
                ),
            )

            logger.info(f"PST processing completed: {stats}")

            return stats

        finally:
            db.close()

    except Exception as e:
        logger.error(f"PST processing failed: {e}", exc_info=True)
        _update_pst_status(doc_id, "failed", error_msg=str(e))
        raise


# Import forensic processor to register its Celery task (optional)
# Path is /code/app in Docker container

sys.path.insert(0, "/code")

try:
    from app.pst_forensic_processor import process_pst_forensic

    print("Forensic PST task module imported in worker - ready for execution")
except ImportError as e:
    print(f"Forensic PST processor not available: {e}")
    process_pst_forensic = None


def s3_key_from_db(doc_id: str) -> str:
    """Helper to get s3_key from pst_files for fallback"""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT s3_key FROM pst_files WHERE id::text=:i"), {"i": doc_id}
        ).scalar()
        return row if row else ""
