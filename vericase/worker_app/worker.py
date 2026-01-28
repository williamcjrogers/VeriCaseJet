import io
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from celery import Celery
import boto3
from botocore.client import Config
from sqlalchemy import create_engine, text
from opensearchpy import OpenSearch, RequestsHttpConnection
import requests
import subprocess
import pytesseract
import logging
from kombu import Queue
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

# Ensure the worker consumes both the general queue and the PST queue by default.
#
# In some deployments (notably k8s), the worker is started without `-Q ...`.
# Without explicit `task_queues`, Celery will only consume the default queue
# (typically "celery"), causing PST tasks routed to `CELERY_PST_QUEUE` to
# remain stuck indefinitely.
celery_app.conf.update(
    task_default_queue=settings.CELERY_QUEUE,
    task_create_missing_queues=True,
    task_queues=(
        Queue(settings.CELERY_QUEUE),
        Queue(settings.CELERY_PST_QUEUE),
    ),
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
_s3_max_pool = int(os.getenv("S3_MAX_POOL_CONNECTIONS", "64") or "64")
_s3_config = Config(
    signature_version="s3v4",
    max_pool_connections=_s3_max_pool,
    retries={"max_attempts": 10, "mode": "adaptive"},
)

# Log S3 configuration for debugging
logger.info(
    "[WORKER S3 CONFIG] USE_AWS_SERVICES=%s, MINIO_ENDPOINT=%s, use_aws=%s, MINIO_BUCKET=%s",
    settings.USE_AWS_SERVICES,
    settings.MINIO_ENDPOINT,
    use_aws,
    settings.MINIO_BUCKET,
)

if use_aws:
    # AWS S3 mode: use IRSA for credentials (no endpoint_url, no explicit keys)
    logger.info(
        "[WORKER S3] Creating AWS S3 client (IRSA mode), region=%s", settings.AWS_REGION
    )
    s3 = boto3.client(
        "s3",
        config=_s3_config,
        region_name=settings.AWS_REGION,
    )
else:
    # MinIO mode: use explicit endpoint and credentials
    _minio_endpoint = _normalize_endpoint(settings.MINIO_ENDPOINT)
    logger.info(
        "[WORKER S3] Creating MinIO client, endpoint=%s, region=%s",
        _minio_endpoint,
        settings.AWS_REGION,
    )
    s3 = boto3.client(
        "s3",
        endpoint_url=_minio_endpoint,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=_s3_config,
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

# Initialize OpenSearch client with TLS + (optional) AWS SigV4 signing
_os_http_auth = None
try:
    host = settings.OPENSEARCH_HOST
    is_aws_host = host.endswith(".es.amazonaws.com") or host.endswith(
        ".aoss.amazonaws.com"
    )
    if use_aws or is_aws_host:
        try:
            from requests_aws4auth import AWS4Auth

            region = getattr(settings, "AWS_REGION", "us-east-1")
            service = "aoss" if host.endswith(".aoss.amazonaws.com") else "es"
            creds = boto3.Session(region_name=region).get_credentials()
            if creds is not None:
                frozen = creds.get_frozen_credentials()
                _os_http_auth = AWS4Auth(
                    frozen.access_key,
                    frozen.secret_key,
                    region,
                    service,
                    session_token=frozen.token,
                )
        except Exception as e:
            logger.warning("Failed to initialize AWS SigV4 auth for OpenSearch: %s", e)
except Exception:
    # Best-effort only; worker will continue and OpenSearch features may be unavailable.
    pass

os_client = OpenSearch(
    hosts=[{"host": settings.OPENSEARCH_HOST, "port": settings.OPENSEARCH_PORT}],
    http_auth=_os_http_auth,
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


def _merge_document_metadata(doc_id: str, patch: dict) -> None:
    """Merge a small JSON patch into documents.metadata (best-effort)."""
    import json

    try:
        patch_json = json.dumps(patch)
    except Exception:
        return

    with engine.begin() as conn:
        # metadata is stored as JSON in many deployments; merge via jsonb then cast back.
        conn.execute(
            text(
                """
                UPDATE documents
                SET metadata = (COALESCE(metadata::jsonb, '{}'::jsonb) || :patch::jsonb)::json
                WHERE id::text = :i
                """
            ),
            {"patch": patch_json, "i": doc_id},
        )


def _fetch_doc(doc_id: str):
    import json

    with engine.begin() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id::text, filename, content_type, bucket, s3_key, path, created_at, status::text as status, text_excerpt, metadata, owner_user_id FROM documents WHERE id::text=:i"
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


def _put_text_sidecar(
    bucket: str, key: str, text_value: str
) -> tuple[str, str, str, int]:
    import hashlib

    raw = (text_value or "").encode("utf-8", errors="replace")
    sha = hashlib.sha256(raw).hexdigest()
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=raw,
        ContentType="text/plain; charset=utf-8",
    )
    return bucket, key, sha, len(raw)


def _try_parse_json_from_text(text_value: str) -> dict | None:
    import json

    if not text_value:
        return None
    raw = text_value.strip()
    # Try direct JSON first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except Exception:
        pass

    def _extract_balanced_json_object(s: str, start_idx: int) -> tuple[str, int] | None:
        """Return (substring, end_idx_inclusive) for the first balanced {...} starting at start_idx."""

        depth = 0
        in_string = False
        escape = False

        for i in range(start_idx, len(s)):
            ch = s[i]
            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                depth += 1
                continue

            if ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start_idx : i + 1], i
                continue

        return None

    # Try to extract the first JSON object block.
    # Note: We intentionally do NOT use a greedy regex like r"\{[\s\S]*\}" because it will
    # capture from the first "{" to the last "}" and can swallow non-JSON brace content.
    start = 0
    while True:
        start = raw.find("{", start)
        if start < 0:
            return None

        balanced = _extract_balanced_json_object(raw, start)
        if not balanced:
            start += 1
            continue

        candidate, end_idx = balanced
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception:
            # Continue searching in case the first balanced {...} isn't JSON (e.g. "{high}").
            start = end_idx + 1
            continue


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


def _try_claim_pst_for_processing(pst_id: str) -> bool:
    """Best-effort claim to avoid duplicate PST processing tasks.

    Why: the API may re-enqueue a PST that has been "pending" for a long time, and
    Redis retries can also create duplicate deliveries. Without a claim step, two
    workers could process the same PST simultaneously.

    Strategy:
    - Allow claiming when status is pending/queued/uploaded
    - Allow reclaiming when status is processing but *stale* (or started_at is null)
    """

    try:
        stale_hours = float(
            getattr(settings, "PST_PROCESSING_STALE_AFTER_HOURS", 12.0) or 12.0
        )
    except Exception:
        stale_hours = 12.0

    # SECURITY: always use timezone-aware UTC for time calculations.
    stale_before_utc = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    # DB column may be timezone-naive in some deployments; compare against UTC-naive.
    stale_before_db = stale_before_utc.replace(tzinfo=None)

    try:
        with engine.begin() as conn:
            claimed = conn.execute(
                text(
                    """
                    UPDATE pst_files
                    SET processing_status = 'processing',
                        processing_started_at = CURRENT_TIMESTAMP,
                        error_message = NULL
                    WHERE id::text = :i
                      AND (
                        processing_status IN ('pending', 'queued', 'uploaded')
                        OR (
                          processing_status = 'processing'
                          AND (processing_started_at IS NULL OR processing_started_at < :stale_before)
                        )
                      )
                    RETURNING id::text
                    """
                ),
                {"i": pst_id, "stale_before": stale_before_db},
            ).scalar()
            return bool(claimed)
    except Exception as exc:
        logger.warning(
            "Failed to claim PST %s for processing (continuing): %s", pst_id, exc
        )
        return True


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
    try:
        os_client.index(  # type: ignore[union-attr]
            index=settings.OPENSEARCH_INDEX,
            id=doc_id,
            body=body,
            refresh=True,
        )
    except Exception as exc:
        # Best-effort: OCR output should still be persisted to Postgres even if OpenSearch is down.
        logger.warning("OpenSearch index failed for %s (non-fatal): %s", doc_id, exc)


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

    # Non-blocking enrichment (Bedrock / BDA) as an add-on layer
    if getattr(settings, "ENABLE_DOCUMENT_ENRICHMENT", False):
        # Store extracted text sidecar so enrichers can fetch it without OpenSearch dependency.
        # Best-effort only: enrichment can still run using text_excerpt fallback.
        if text and len(text) >= getattr(settings, "BEDROCK_DOC_ENRICH_MIN_CHARS", 500):
            try:
                sidecar_key = f"document-text/{doc_id}.txt"
                b, k, sha, size_bytes = _put_text_sidecar(
                    doc["bucket"], sidecar_key, text
                )
                _merge_document_metadata(
                    doc_id,
                    {
                        "extracted_text": {
                            "bucket": b,
                            "key": k,
                            "sha256": sha,
                            "bytes": size_bytes,
                        }
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to store extracted text sidecar (non-fatal): %s", exc
                )

        # Always enqueue enrichment even if sidecar/metadata writes fail.
        try:
            enrich_document.delay(doc_id)
        except Exception as exc:
            logger.warning("Failed to enqueue document enrichment (non-fatal): %s", exc)
    return {"id": doc_id, "chars": len(text or "")}


@celery_app.task(
    name="worker_app.worker.enrich_document", queue=settings.ENRICHMENT_QUEUE
)
def enrich_document(doc_id: str):
    """Best-effort enrichment: prefer BDA if configured, else use Bedrock LLM."""
    doc = _fetch_doc(doc_id)
    if not doc:
        return

    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    if not isinstance(meta, dict):
        meta = {}

    # Idempotency: if we already have enrichment, don't redo unless explicitly forced later.
    if (
        isinstance(meta.get("enrichment"), dict)
        and meta["enrichment"].get("status") == "ok"
    ):
        return

    # Load extracted text (prefer sidecar)
    extracted = ""
    try:
        ext = (
            meta.get("extracted_text")
            if isinstance(meta.get("extracted_text"), dict)
            else None
        )
        if ext and ext.get("bucket") and ext.get("key"):
            obj = s3.get_object(Bucket=str(ext["bucket"]), Key=str(ext["key"]))
            extracted = obj["Body"].read().decode("utf-8", errors="replace")
    except Exception:
        extracted = ""

    if not extracted:
        extracted = (
            (doc.get("text_excerpt") or "")
            if isinstance(doc.get("text_excerpt"), str)
            else ""
        )

    extracted = (extracted or "").strip()
    if len(extracted) < getattr(settings, "BEDROCK_DOC_ENRICH_MIN_CHARS", 500):
        _merge_document_metadata(
            doc_id,
            {"enrichment": {"status": "skipped", "reason": "insufficient_text"}},
        )
        return

    # Try BDA first if configured
    if getattr(settings, "BDA_DOC_ENRICH_ENABLED", False):
        try:
            result = _enrich_with_bda(doc)
            _merge_document_metadata(
                doc_id, {"enrichment": {"status": "ok", "method": "bda", **result}}
            )
            return
        except Exception as exc:
            _merge_document_metadata(
                doc_id,
                {
                    "enrichment": {
                        "status": "error",
                        "method": "bda",
                        "error": str(exc)[:500],
                    }
                },
            )
            # fall through to Bedrock LLM

    if getattr(settings, "BEDROCK_DOC_ENRICH_ENABLED", False):
        try:
            result = _enrich_with_bedrock_llm(doc, extracted)
            _merge_document_metadata(
                doc_id, {"enrichment": {"status": "ok", "method": "bedrock", **result}}
            )
            return
        except Exception as exc:
            _merge_document_metadata(
                doc_id,
                {
                    "enrichment": {
                        "status": "error",
                        "method": "bedrock",
                        "error": str(exc)[:500],
                    }
                },
            )
            return

    _merge_document_metadata(
        doc_id, {"enrichment": {"status": "skipped", "reason": "disabled"}}
    )


def _enrich_with_bda(doc: dict) -> dict:
    """Invoke Bedrock Data Automation on the original document S3 object (sync API)."""
    import json
    import time

    if not getattr(settings, "BDA_PROJECT_ARN", ""):
        raise RuntimeError("BDA_PROJECT_ARN not set")
    if not getattr(settings, "BDA_PROFILE_ARN", ""):
        raise RuntimeError("BDA_PROFILE_ARN not set")
    if not getattr(settings, "BDA_KMS_KEY_ID", ""):
        raise RuntimeError("BDA_KMS_KEY_ID not set")

    bda = boto3.client(
        "bedrock-data-automation-runtime", region_name=settings.BDA_REGION
    )

    s3_uri = f"s3://{doc['bucket']}/{doc['s3_key']}"
    blueprints = []
    if getattr(settings, "BDA_BLUEPRINT_ARN", ""):
        bp = {
            "blueprintArn": settings.BDA_BLUEPRINT_ARN,
            "stage": settings.BDA_BLUEPRINT_STAGE,
        }
        if getattr(settings, "BDA_BLUEPRINT_VERSION", ""):
            bp["version"] = settings.BDA_BLUEPRINT_VERSION
        blueprints.append(bp)

    started = time.time()
    resp = bda.invoke_data_automation(
        inputConfiguration={"s3Uri": s3_uri},
        dataAutomationConfiguration={
            "dataAutomationProjectArn": settings.BDA_PROJECT_ARN,
            "stage": settings.BDA_STAGE,
        },
        blueprints=blueprints,
        dataAutomationProfileArn=settings.BDA_PROFILE_ARN,
        encryptionConfiguration={"kmsKeyId": settings.BDA_KMS_KEY_ID},
    )
    duration_ms = int((time.time() - started) * 1000)

    # Store small excerpts inline; larger payloads are stored as JSON in metadata (still bounded).
    payload = json.dumps(resp)
    payload_trunc = payload[:100000]

    out_segments = resp.get("outputSegments") or []
    std_excerpt = ""
    cust_excerpt = ""
    if out_segments and isinstance(out_segments, list):
        seg0 = out_segments[0] if isinstance(out_segments[0], dict) else {}
        std_excerpt = str(seg0.get("standardOutput") or "")[:5000]
        cust_excerpt = str(seg0.get("customOutput") or "")[:5000]

    return {
        "model": {"bda_region": settings.BDA_REGION, "stage": settings.BDA_STAGE},
        "timing_ms": duration_ms,
        "bda": {
            "semanticModality": resp.get("semanticModality"),
            "outputSegments": [
                {
                    "customOutputStatus": s.get("customOutputStatus"),
                    "standardOutputExcerpt": str(s.get("standardOutput") or "")[:5000],
                    "customOutputExcerpt": str(s.get("customOutput") or "")[:5000],
                }
                for s in (out_segments[:5] if isinstance(out_segments, list) else [])
                if isinstance(s, dict)
            ],
            "raw_json_trunc": payload_trunc,
        },
        "standard_output_excerpt": std_excerpt,
        "custom_output_excerpt": cust_excerpt,
    }


def _enrich_with_bedrock_llm(doc: dict, extracted_text: str) -> dict:
    """Use Bedrock LLM to produce a compact JSON enrichment payload from extracted text."""
    import asyncio
    import time

    from vericase.api.app.ai_providers.bedrock import BedrockProvider  # type: ignore

    model_id = getattr(settings, "BEDROCK_DOC_ENRICH_MODEL_ID", "")
    max_tokens = int(getattr(settings, "BEDROCK_DOC_ENRICH_MAX_TOKENS", 800) or 800)
    max_chars = int(getattr(settings, "BEDROCK_DOC_ENRICH_MAX_CHARS", 20000) or 20000)

    text_slice = extracted_text[:max_chars]

    system = (
        "You are a forensic-safe document enrichment engine.\n"
        "Return STRICT JSON only. Do not include markdown.\n"
        "Never invent facts; if unknown, use null or empty arrays.\n"
        "Schema:\n"
        "{"
        '"document_type": string|null,'
        '"summary": string|null,'
        '"key_dates": [string],'
        '"entities": [{"type": string, "value": string}],'
        '"actions": [string],'
        '"confidence": number'
        "}"
    )

    prompt = (
        f"Filename: {doc.get('filename')}\n"
        f"Content-Type: {doc.get('content_type')}\n\n"
        "Extracted text:\n"
        "-----\n"
        f"{text_slice}\n"
        "-----\n"
        "Return JSON now."
    )

    provider = BedrockProvider(region=os.getenv("AWS_REGION", "us-east-1"))
    started = time.time()
    raw = asyncio.run(
        provider.invoke(
            model_id=model_id,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.0,
            system_prompt=system,
        )
    )
    duration_ms = int((time.time() - started) * 1000)

    parsed = _try_parse_json_from_text(raw) or {}
    return {
        "model": {
            "model_id": model_id,
            "max_tokens": max_tokens,
            "max_chars": max_chars,
        },
        "timing_ms": duration_ms,
        "bedrock": {"raw_trunc": (raw or "")[:10000], "parsed": parsed},
    }


@celery_app.task(
    name="worker_app.worker.process_pst_file",
    queue=settings.CELERY_PST_QUEUE,
    soft_time_limit=getattr(settings, "PST_TASK_SOFT_TIME_LIMIT_S", 21600),
    time_limit=getattr(settings, "PST_TASK_TIME_LIMIT_S", 22200),
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
        # The pst_processor module is in /code/api/app/ inside Docker.
        api_path = "/code/api"
        if os.path.isdir(api_path):
            sys.path.insert(0, api_path)
        else:
            repo_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            local_api = os.path.join(repo_root, "vericase", "api")
            if os.path.isdir(local_api):
                sys.path.insert(0, local_api)
        from app.pst_processor import UltimatePSTProcessor

        # Import API's S3 client for consistency with upload endpoint
        # This ensures we use the exact same S3 configuration as the API
        from app.storage import s3 as get_api_s3_client
        from app.config import settings as api_settings

        api_s3_client = get_api_s3_client()
        logger.info(
            "[PST S3 CONSISTENCY] Using API's S3 client: USE_AWS_SERVICES=%s, "
            "MINIO_ENDPOINT=%s, S3_BUCKET=%s",
            api_settings.USE_AWS_SERVICES,
            api_settings.MINIO_ENDPOINT,
            api_settings.S3_BUCKET,
        )

        # Create DB session
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            # Get PST file info from pst_files table
            pst_file = _fetch_pst_file(doc_id)
            if not pst_file:
                logger.error(f"PST file {doc_id} not found in pst_files table")
                return {"error": "PST file not found"}

            # Detailed logging for debugging PST file not found issues
            logger.info(
                "[PST DEBUG] Database record: id=%s, bucket=%s (type=%s), s3_key=%s, "
                "case_id=%s, project_id=%s, status=%s",
                pst_file.get("id"),
                pst_file.get("bucket"),
                type(pst_file.get("bucket")),
                pst_file.get("s3_key"),
                pst_file.get("case_id"),
                pst_file.get("project_id"),
                pst_file.get("processing_status"),
            )

            # Pre-verify the file exists in S3 before starting processing
            # Use API's S3 client for consistency with upload endpoint
            bucket_to_check = pst_file.get("bucket") or api_settings.S3_BUCKET
            key_to_check = pst_file.get("s3_key")
            logger.info(
                "[PST DEBUG] Pre-verify: checking s3://%s/%s using API S3 client",
                bucket_to_check,
                key_to_check,
            )
            try:
                head_resp = api_s3_client.head_object(
                    Bucket=bucket_to_check, Key=key_to_check
                )
                logger.info(
                    "[PST DEBUG] Pre-verify SUCCESS: file exists, size=%s bytes",
                    head_resp.get("ContentLength", 0),
                )
            except Exception as pre_verify_err:
                logger.error(
                    "[PST DEBUG] Pre-verify FAILED: file NOT found at s3://%s/%s - error: %s",
                    bucket_to_check,
                    key_to_check,
                    pre_verify_err,
                )
                # Continue anyway to let processor give proper error

            # Claim the PST for processing (prevents duplicate worker execution).
            if not _try_claim_pst_for_processing(doc_id):
                current = _fetch_pst_file(doc_id) or {}
                current_status = str(current.get("processing_status") or "").lower()
                logger.info(
                    "Skipping PST %s: already claimed or completed (status=%s)",
                    doc_id,
                    current_status,
                )
                return {
                    "status": "skipped",
                    "reason": "already_claimed",
                    "processing_status": current_status,
                }

            logger.info(
                f"Processing PST: {pst_file['filename']} from {pst_file['bucket']}/{pst_file['s3_key']}"
            )

            # Initialize processor with API's S3 client for consistency
            processor = UltimatePSTProcessor(
                db=db, s3_client=api_s3_client, opensearch_client=os_client
            )

            # Process PST - use case_id and project_id from the pst_file record
            stats = processor.process_pst(
                pst_s3_key=pst_file["s3_key"],
                document_id=doc_id,
                case_id=pst_file.get("case_id"),
                company_id=company_id,
                project_id=pst_file.get("project_id"),
                pst_s3_bucket=pst_file.get("bucket"),
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


@celery_app.task(name="app.process_pst_forensic", queue=settings.CELERY_PST_QUEUE)
def process_pst_forensic(
    pst_file_id: str,
    s3_bucket: str | None = None,
    s3_key: str | None = None,
    case_id: str | None = None,
    project_id: str | None = None,
):
    """Compatibility alias for legacy forensic task names."""
    return process_pst_file(pst_file_id, case_id=case_id)


@celery_app.task(
    name="link_emails_to_programme_activities", queue=settings.CELERY_QUEUE
)
def link_emails_to_programme_activities(
    project_id: str | None = None,
    case_id: str | None = None,
    overwrite_existing: bool = False,
    batch_size: int = 500,
):
    """Worker task wrapper for linking emails to programme activities.

    The API codebase defines the shared implementation in `app.programme_linking`.
    We register the task here so the deployed worker (Celery app: worker_app.worker)
    can execute tasks enqueued by the API.
    """

    from sqlalchemy.orm import sessionmaker

    try:
        from app.programme_linking import link_emails_to_programme_activities as _impl
    except Exception as exc:
        logger.error(f"Failed to import programme linking implementation: {exc}")
        return {"status": "failed", "error": f"Import error: {exc}"}

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        return _impl(
            db=db,
            project_id=project_id,
            case_id=case_id,
            overwrite_existing=overwrite_existing,
            batch_size=batch_size,
        )
    finally:
        db.close()


def s3_key_from_db(doc_id: str) -> str:
    """Helper to get s3_key from pst_files for fallback"""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT s3_key FROM pst_files WHERE id::text=:i"), {"i": doc_id}
        ).scalar()
        return row if row else ""


@celery_app.task(
    bind=True,
    name="worker_app.worker.analyze_workspace",
    queue=settings.CELERY_QUEUE,
    soft_time_limit=7200,  # 2h
    time_limit=7500,  # 2h05m hard kill
)
def analyze_workspace(
    self,
    workspace_id: str,
    *,
    owner_user_id: str | None = None,
    include_purpose: bool = True,
    include_keywords: bool = True,
    force: bool = True,
    deep: bool = True,
    keyword_mode: str = "overwrite",
    include_emails: bool = True,
    include_evidence: bool = True,
    max_emails: int = 50000,
    max_evidence: int = 50000,
) -> dict:
    """Run a cohesive “workspace analysis” flow with progress updates.

    This is intentionally opinionated:
    - Purpose refresh (deep) builds the brief + deliverables + chronology + contradictions.
    - Keyword rescan updates tags across correspondence + evidence so filtering stays aligned.
    """

    import time
    import uuid as _uuid

    from sqlalchemy.orm import sessionmaker

    # Local helper: run a coroutine safely in Celery worker context.
    def _run_async(coro):
        import asyncio

        try:
            return asyncio.run(coro)
        except RuntimeError:
            # Fallback if a loop is already running in this worker process.
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

    # Resolve workspace UUID early for consistent meta.
    try:
        ws_uuid = _uuid.UUID(str(workspace_id))
    except Exception:
        return {"status": "failed", "error": "invalid workspace_id"}

    base_meta = {
        "workspace_id": str(ws_uuid),
        "owner_user_id": str(owner_user_id) if owner_user_id else None,
        "started_at": int(time.time()),
        "stage": "init",
        "percent": 1,
        "message": "Starting workspace analysis…",
    }
    self.update_state(state="PROGRESS", meta=base_meta)

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        from app.models import Workspace

        ws = db.query(Workspace).filter(Workspace.id == ws_uuid).first()
        if not ws:
            return {"status": "failed", "error": "workspace not found"}

        # Weighting: purpose is the bulk of perceived value.
        purpose_weight = 70 if include_purpose and include_keywords else 100
        keywords_weight = 30 if include_purpose and include_keywords else 100

        purpose_result = None
        keywords_result = None

        if include_purpose:
            try:
                from app.workspaces import _build_workspace_purpose_snapshot

                def _purpose_progress(meta: dict) -> None:
                    try:
                        p = int(meta.get("percent", 0) or 0)
                    except Exception:
                        p = 0
                    if include_keywords:
                        overall = int((p / 100.0) * purpose_weight)
                    else:
                        overall = p
                    payload = {
                        **base_meta,
                        "stage": "purpose",
                        "percent": max(0, min(100, overall)),
                        "message": str(meta.get("message") or "Purpose analysis…"),
                        "detail": meta,
                    }
                    self.update_state(state="PROGRESS", meta=payload)

                _run_async(
                    _build_workspace_purpose_snapshot(
                        db=db,
                        workspace=ws,
                        force=bool(force),
                        deep=bool(deep),
                        progress_cb=_purpose_progress,
                    )
                )
                purpose_result = {"status": "completed"}
            except Exception as exc:
                logger.exception("Workspace purpose analysis failed: %s", exc)
                purpose_result = {"status": "failed", "error": str(exc)[:500]}

        if include_keywords:
            try:
                from app.workspaces import _rescan_workspace_keywords_impl

                def _keywords_progress(meta: dict) -> None:
                    try:
                        p = int(meta.get("percent", 0) or 0)
                    except Exception:
                        p = 0
                    if include_purpose:
                        overall = purpose_weight + int((p / 100.0) * keywords_weight)
                    else:
                        overall = p
                    payload = {
                        **base_meta,
                        "stage": "keywords",
                        "percent": max(0, min(100, overall)),
                        "message": str(meta.get("message") or "Keyword scan…"),
                        "detail": meta,
                    }
                    self.update_state(state="PROGRESS", meta=payload)

                keywords_result = _rescan_workspace_keywords_impl(
                    db=db,
                    workspace=ws,
                    mode=str(keyword_mode or "overwrite"),
                    include_emails=bool(include_emails),
                    include_evidence=bool(include_evidence),
                    max_emails=int(max_emails or 0),
                    max_evidence=int(max_evidence or 0),
                    progress_cb=_keywords_progress,
                )
            except Exception as exc:
                logger.exception("Workspace keyword rescan failed: %s", exc)
                keywords_result = {"status": "failed", "error": str(exc)[:500]}

        overall_status = "completed"
        errors: list[str] = []
        if include_purpose and isinstance(purpose_result, dict):
            if str(purpose_result.get("status") or "").lower() == "failed":
                overall_status = "failed"
                if purpose_result.get("error"):
                    errors.append(f"purpose: {purpose_result.get('error')}")
        if include_keywords and isinstance(keywords_result, dict):
            if str(keywords_result.get("status") or "").lower() == "failed":
                overall_status = "failed"
                if keywords_result.get("error"):
                    errors.append(f"keywords: {keywords_result.get('error')}")

        # Final progress update (Celery SUCCESS will follow immediately after return)
        final_message = (
            "Workspace analysis complete."
            if overall_status == "completed"
            else "Workspace analysis finished with errors."
        )
        self.update_state(
            state="PROGRESS",
            meta={
                **base_meta,
                "stage": "complete",
                "percent": 100,
                "message": final_message,
                "status": overall_status,
                "errors": errors,
                "purpose": purpose_result,
                "keywords": keywords_result,
            },
        )

        return {
            "status": overall_status,
            "workspace_id": str(ws_uuid),
            "owner_user_id": str(owner_user_id) if owner_user_id else None,
            "purpose": purpose_result,
            "keywords": keywords_result,
            "errors": errors,
        }
    finally:
        db.close()
