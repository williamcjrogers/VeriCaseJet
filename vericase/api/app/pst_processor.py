"""
THE ULTIMATE PST PROCESSING MACHINE
Enterprise-grade PST extraction with AWS integration

Features:
- Smart extraction: Index content without storing individual email files (saves 90% storage)
- Full attachment extraction with deduplication
- Advanced email threading (Message-ID, In-Reply-To, References, Conversation-Index)
- OpenSearch indexing with semantic embeddings
- Parallel processing across multiple workers
- Progress tracking and error recovery
"""

# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportAny=false

from __future__ import annotations

import hashlib
import json
import os
import logging
import re
import tempfile
import uuid
import time
import io
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import getaddresses

import pypff  # type: ignore  # pypff is installed in Docker container

from sqlalchemy import text
from sqlalchemy.orm import Session
from .models import (
    Document,
    EmailMessage,
    EmailAttachment,
    DocStatus,
    PSTFile,
    EvidenceItem,
    Stakeholder,
    Keyword,
    MessageRaw,
    MessageOccurrence,
    MessageDerived,
)
from .config import settings
from .spam_filter import classify_email, extract_other_project, SpamResult
from .project_scoping import ScopeMatcher, build_scope_matcher
from .email_threading import build_email_threads, ThreadingStats
from .email_dedupe import dedupe_emails
from .email_normalizer import (
    NORMALIZER_RULESET_HASH,
    NORMALIZER_VERSION,
    build_content_hash,
    clean_body_text,
    strip_footer_noise,
)
from .email_headers import (
    decode_header_blob,
    parse_date_header,
    parse_received_headers,
    received_time_bounds,
    sha256_text,
)
from .email_content import decode_maybe_bytes, select_best_body

try:
    from .email_normalizer import build_source_hash
except (ImportError, AttributeError):

    def build_source_hash(payload: dict[str, object]) -> str:
        serialized = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ThreadInfo(TypedDict, total=False):
    """Type definition for thread tracking info.

    MEMORY OPTIMIZATION: Only store fields needed for threading.
    - email_message: Reference to the EmailMessage ORM object
    - in_reply_to: For RFC 2822 threading
    - references: For RFC 2822 threading
    - date: For thread ordering
    - subject: For subject-based fallback threading
    """

    email_message: EmailMessage
    in_reply_to: str | None
    references: str | None
    date: datetime | None
    subject: str


class ProcessingStats(TypedDict):
    total_emails: int
    total_attachments: int
    unique_attachments: int
    threads_identified: int
    size_saved: int
    processing_time: float
    errors: list[str]


# Semantic processing for deep research acceleration
_semantic_available = False
_SemanticIngestionService: type | None = None
try:
    from .semantic_engine import SemanticIngestionService as _SIS

    _SemanticIngestionService = _SIS
    _semantic_available = True
except ImportError:
    pass

logger = logging.getLogger(__name__)
_AGENT_LOG_ENABLED = bool(getattr(settings, "PST_AGENT_LOG_ENABLED", False))


# region agent log helper
def agent_log(
    hypothesis_id: str, message: str, data: dict | None = None, run_id: str = "run1"
) -> None:
    if not _AGENT_LOG_ENABLED:
        return
    log_path = (
        os.getenv("PST_AGENT_LOG_PATH")
        or getattr(settings, "PST_AGENT_LOG_PATH", None)
        or os.getenv("VERICASE_DEBUG_LOG_PATH")
        or str(Path(".cursor") / "debug.log")
    )
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    payload = {
        "id": f"log_{int(time.time() * 1000)}_{hash(message) % 10000}",
        "timestamp": int(time.time() * 1000),
        "location": "pst_processor.py",
        "message": message,
        "data": data or {},
        "sessionId": "debug-session",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    # Try local file first
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
            return
    except Exception:
        pass
    # Fallback to ingest endpoint so the server writes to the log file
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://host.docker.internal:7242/ingest/a36b627f-6fe2-4392-af4c-6145b197bf06",
            data=line.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


# endregion agent log helper


class UltimatePSTProcessor:
    """
    THE ULTIMATE PST PROCESSING MACHINE

    Processes PST files with best-in-class fidelity and performance:
    - Extracts all emails without storing individual files (smart indexing)
    - Extracts ALL attachments (including inline images)
    - Builds perfect email threads using multiple algorithms
    - Indexes to OpenSearch for instant search
    - Handles corrupted/password-protected PSTs
    """

    def __init__(self, db: Session, s3_client: Any, opensearch_client: Any = None):
        self.db = db
        self.s3 = s3_client
        self.opensearch = opensearch_client
        self.threads_map: dict[str, ThreadInfo] = {}
        self.scope_matcher: ScopeMatcher | None = None
        self.processed_count = 0
        self.total_count = 0
        self._last_progress_update = 0.0
        self._last_progress_count = 0
        self.attachment_hashes: dict[str, dict[str, Any]] = {}  # For attachment dedup
        self.evidence_item_hashes: dict[str, Any] = {}  # For EvidenceItem deduplication
        self.body_offload_threshold = (
            getattr(settings, "PST_BODY_OFFLOAD_THRESHOLD", 50000) or 50000
        )
        self.body_offload_bucket = (
            getattr(settings, "S3_EMAIL_BODY_BUCKET", None) or settings.S3_BUCKET
        )
        self.attach_bucket = (
            getattr(settings, "S3_ATTACHMENTS_BUCKET", None) or settings.S3_BUCKET
        )
        self.chunk_size = (
            getattr(settings, "PST_ATTACHMENT_CHUNK_SIZE", 1024 * 1024) or 1024 * 1024
        )

        # Parallel upload executor (configurable via PST_UPLOAD_WORKERS)
        cpu_based_default = max(8, (os.cpu_count() or 4) * 4)
        upload_workers = (
            getattr(settings, "PST_UPLOAD_WORKERS", cpu_based_default)
            or cpu_based_default
        )
        try:
            upload_workers = min(int(upload_workers), 64)
        except Exception:
            upload_workers = cpu_based_default
        self.upload_executor = ThreadPoolExecutor(max_workers=upload_workers)
        self.upload_futures = []

        # Batch commit size (configurable via PST_BATCH_COMMIT_SIZE)
        self.batch_commit_size = (
            getattr(settings, "PST_BATCH_COMMIT_SIZE", 2500) or 2500
        )
        self._progress_update_interval = 5.0
        self._progress_update_batch = max(100, min(1000, self.batch_commit_size // 5))

        # Initialize batch buffers (Split for performance)
        self.email_buffer = []
        self.attachment_buffer = []
        self.document_buffer = []
        self.evidence_buffer = []
        self.message_raw_buffer = []
        self.message_occurrence_buffer = []
        self.message_derived_buffer = []
        self.ingest_run_id: str | None = None
        self._stakeholders: list[Stakeholder] = []
        self._keywords: list[Keyword] = []
        self._keyword_plain_terms_cache: dict[str, list[str]] = {}
        self._keyword_regex_terms_cache: dict[str, list[str]] = {}
        self._keyword_regex_cache: dict[tuple[str, str], re.Pattern[str]] = {}
        self._invalid_keyword_regex: set[tuple[str, str]] = set()
        self._timings: dict[str, float] = {
            "download_s": 0.0,
            "open_s": 0.0,
            "precount_s": 0.0,
            "headers_s": 0.0,
            "body_s": 0.0,
            "attachments_s": 0.0,
            "flush_s": 0.0,
            "threading_s": 0.0,
            "dedupe_s": 0.0,
        }
        self._counts: dict[str, int] = {
            "messages_seen": 0,
            "messages_skipped": 0,
            "attachments_seen": 0,
        }
        self._start_monotonic: float | None = None
        self._last_rate_log: float = 0.0

        # Initialize semantic processing for deep research acceleration
        self.semantic_service: Any = None
        if _semantic_available and _SemanticIngestionService is not None:
            try:
                self.semantic_service = _SemanticIngestionService(opensearch_client)
                logger.info("Semantic ingestion service initialized for deep research")
            except Exception as e:
                logger.warning(
                    f"Semantic service initialization failed (non-fatal): {e}"
                )

    def _flush_buffers(
        self, force: bool = False, stats: ProcessingStats | None = None
    ) -> None:
        """
        Flush all buffers to database.
        Splits by type to maximize bulk_save_objects efficiency.

        NOTE: This method is intentionally **fail-fast**.
        If a batch commit fails, we raise to avoid marking PST processing as
        completed when nothing was persisted (a prior bug).
        """
        total_pending = (
            len(self.email_buffer)
            + len(self.document_buffer)
            + len(self.attachment_buffer)
            + len(self.evidence_buffer)
            + len(self.message_raw_buffer)
            + len(self.message_occurrence_buffer)
            + len(self.message_derived_buffer)
        )

        if total_pending == 0:
            return

        if not (force or total_pending >= self.batch_commit_size):
            return

        # Snapshot current buffers so we can safely clear only on successful commit.
        docs = list(self.document_buffer)
        emails = list(self.email_buffer)
        atts = list(self.attachment_buffer)
        evidence = list(self.evidence_buffer)
        raw_messages = list(self.message_raw_buffer)
        occurrences = list(self.message_occurrence_buffer)
        derived_messages = list(self.message_derived_buffer)

        t0 = time.monotonic()
        try:
            # Flush in order of dependencies
            if raw_messages:
                self.db.bulk_save_objects(raw_messages)
            if occurrences:
                self.db.bulk_save_objects(occurrences)
            if derived_messages:
                self.db.bulk_save_objects(derived_messages)
            if docs:
                self.db.bulk_save_objects(docs)
            if emails:
                self.db.bulk_save_objects(emails)
            if atts:
                self.db.bulk_save_objects(atts)
            if evidence:
                self.db.bulk_save_objects(evidence)

            self.db.commit()

            # Only clear buffers after successful commit.
            if docs:
                self.document_buffer = []
            if emails:
                self.email_buffer = []
            if atts:
                self.attachment_buffer = []
            if evidence:
                self.evidence_buffer = []
            if raw_messages:
                self.message_raw_buffer = []
            if occurrences:
                self.message_occurrence_buffer = []
            if derived_messages:
                self.message_derived_buffer = []

            # Log progress
            if self.processed_count > 0 and self.processed_count % 500 == 0:
                if self.total_count > 0:
                    progress = (self.processed_count / self.total_count) * 100
                    logger.info(
                        "Progress: %d/%d (%.1f%%)",
                        self.processed_count,
                        self.total_count,
                        progress,
                    )
                else:
                    logger.info(
                        "Progress: %d emails processed",
                        self.processed_count,
                    )

        except Exception as commit_error:
            msg = (
                "Batch commit failed "
                f"(pending={total_pending}, emails={len(self.email_buffer)}, "
                f"docs={len(self.document_buffer)}, atts={len(self.attachment_buffer)}, "
                f"evidence={len(self.evidence_buffer)}): {commit_error}"
            )
            logger.error(msg, exc_info=True)
            try:
                self.db.rollback()
            except Exception:
                # Best-effort rollback; original exception is more important.
                pass

            if stats is not None:
                stats["errors"].append(msg)

            # Clear buffers on error to prevent cascading.
            self.email_buffer = []
            self.document_buffer = []
            self.attachment_buffer = []
            self.evidence_buffer = []

            raise
        finally:
            self._timings["flush_s"] += time.monotonic() - t0

    @staticmethod
    def _parse_transport_headers_map(
        headers_text: str | None, wanted: set[str] | None = None
    ) -> dict[str, list[str]]:
        """Parse RFC822 headers into a lower-cased multimap.

        This is intentionally faster than `email.parser.HeaderParser` and supports
        folded headers (continuation lines start with whitespace).
        """
        if not headers_text:
            return {}
        wanted_lc = {w.lower() for w in wanted} if wanted else None
        header_map: dict[str, list[str]] = {}
        current_name: str | None = None
        current_value: list[str] = []

        def flush() -> None:
            nonlocal current_name, current_value
            if not current_name:
                current_value = []
                return
            value = " ".join(current_value).strip()
            if value:
                header_map.setdefault(current_name, []).append(value)
            current_name = None
            current_value = []

        for raw_line in str(headers_text).splitlines():
            if not raw_line:
                continue
            if raw_line.startswith((" ", "\t")):
                if current_name:
                    current_value.append(raw_line.strip())
                continue
            if ":" not in raw_line:
                continue
            flush()
            name, rest = raw_line.split(":", 1)
            name_lc = name.strip().lower()
            if wanted_lc is not None and name_lc not in wanted_lc:
                current_name = None
                current_value = []
                continue
            current_name = name_lc
            current_value = [rest.strip()]
        flush()
        return header_map

    @staticmethod
    def _header_first(header_map: dict[str, list[str]], name: str) -> str | None:
        values = header_map.get(name.lower())
        if not values:
            return None
        value = values[0].strip()
        return value or None

    def _report_progress(
        self, pst_file_record: PSTFile | None, force: bool = False
    ) -> None:
        if pst_file_record is None:
            return
        now = time.monotonic()
        if not force:
            if self.processed_count <= self._last_progress_count:
                return
            if (
                self.processed_count - self._last_progress_count
            ) < self._progress_update_batch and (
                now - self._last_progress_update
            ) < self._progress_update_interval:
                return

        total_emails = (
            self.total_count if self.total_count and self.total_count > 0 else None
        )
        try:
            engine = self.db.get_bind()
            if engine is None:
                return
            if total_emails is not None:
                stmt = text(
                    "UPDATE pst_files "
                    "SET processed_emails = :processed, total_emails = :total, processing_status = 'processing' "
                    "WHERE id::text = :id"
                )
                params = {
                    "processed": self.processed_count,
                    "total": total_emails,
                    "id": str(pst_file_record.id),
                }
            else:
                stmt = text(
                    "UPDATE pst_files "
                    "SET processed_emails = :processed, processing_status = 'processing' "
                    "WHERE id::text = :id"
                )
                params = {
                    "processed": self.processed_count,
                    "id": str(pst_file_record.id),
                }
            with engine.begin() as conn:
                conn.execute(stmt, params)
            self._last_progress_update = now
            self._last_progress_count = self.processed_count

            # Periodic throughput/timing log (helps diagnose "stuck/slow" PSTs in prod).
            if self._start_monotonic is not None:
                if (now - self._last_rate_log) >= 30.0:
                    elapsed = max(now - self._start_monotonic, 0.0001)
                    rate = self.processed_count / elapsed
                    logger.info(
                        "PST progress: processed=%d/%s rate=%.2f msg/s headers=%.1fs body=%.1fs atts=%.1fs flush=%.1fs",
                        self.processed_count,
                        total_emails if total_emails is not None else "?",
                        rate,
                        self._timings.get("headers_s", 0.0),
                        self._timings.get("body_s", 0.0),
                        self._timings.get("attachments_s", 0.0),
                        self._timings.get("flush_s", 0.0),
                    )
                    self._last_rate_log = now
        except Exception as exc:
            logger.debug(
                "Failed to update PST progress for %s: %s", pst_file_record.id, exc
            )

    def process_pst(
        self,
        pst_s3_key: str,
        document_id: UUID | str,
        case_id: UUID | str | None = None,
        company_id: UUID | str | None = None,
        project_id: UUID | str | None = None,
        pst_s3_bucket: str | None = None,
    ) -> ProcessingStats:
        """
        Main entry point - process PST from S3

        Returns statistics about processed emails and attachments
        """
        logger.info(
            f"Starting PST processing for document_id={document_id}, case_id={case_id}, project_id={project_id}"
        )
        # region agent log H10 start
        agent_log(
            "H10",
            "Ultimate processor start",
            {
                "document_id": str(document_id),
                "case_id": str(case_id) if case_id else None,
                "project_id": str(project_id) if project_id else None,
                "pst_s3_bucket": pst_s3_bucket,
                "pst_s3_key": pst_s3_key,
            },
            run_id="pre-fix",
        )
        # endregion agent log H10 start

        stats: ProcessingStats = {
            "total_emails": 0,
            "total_attachments": 0,
            "unique_attachments": 0,  # After deduplication
            "skipped_inline_attachments": 0,
            "threads_identified": 0,
            "size_saved": 0,  # Bytes saved by not storing email files
            "processing_time": 0.0,
            "errors": [],
        }

        self.ingest_run_id = f"pst:{document_id}:{uuid.uuid4().hex}"

        start_time = datetime.now(timezone.utc)
        start_monotonic = time.monotonic()
        self._start_monotonic = start_monotonic
        self._last_rate_log = start_monotonic
        document: Document | None = None
        pst_path: str | None = None
        had_error = False

        # Try to find PST file record first (new upload flow creates this directly)
        pst_file_record = self.db.query(PSTFile).filter_by(id=document_id).first()

        if pst_file_record:
            # PST file record exists (new upload flow)
            logger.info(f"Found existing PSTFile record: {pst_file_record.id}")
            # Use case_id/project_id from the record if not provided
            # Note: pst_file_record IDs are UUIDs, cast to str for compatibility
            if not case_id and pst_file_record.case_id:
                case_id = str(pst_file_record.case_id)
            if not project_id and pst_file_record.project_id:
                project_id = str(pst_file_record.project_id)
        else:
            # Try legacy flow - look for Document record
            document = self.db.query(Document).filter_by(id=document_id).first()
            if not document:
                raise ValueError(
                    f"Neither PSTFile nor Document found for id={document_id}"
                )

            # Create PSTFile record from Document (legacy flow)
            pst_file_record = (
                self.db.query(PSTFile)
                .filter_by(
                    filename=document.filename, case_id=case_id, project_id=project_id
                )
                .first()
            )

            if not pst_file_record:
                # Resolve uploader from document metadata or owner
                meta_dict: dict[str, Any] = {}
                try:
                    if isinstance(document.meta, dict):
                        meta_dict = document.meta.copy()
                except Exception:
                    meta_dict = {}
                uploader = meta_dict.get("uploaded_by")
                if not uploader:
                    uploader = (
                        str(document.owner_user_id)
                        if getattr(document, "owner_user_id", None)
                        else "00000000-0000-0000-0000-000000000000"
                    )
                pst_file_record = PSTFile(
                    filename=document.filename,
                    case_id=case_id,
                    project_id=project_id,
                    s3_bucket=document.bucket or settings.S3_BUCKET,
                    s3_key=pst_s3_key,
                    file_size_bytes=document.size,
                    uploaded_by=uploader,
                )
                self.db.add(pst_file_record)
                self.db.commit()
                self.db.refresh(pst_file_record)

        # Build a per-run project/case scoping matcher to exclude other projects early.
        try:
            self.scope_matcher = build_scope_matcher(
                self.db, case_id=case_id, project_id=project_id
            )
        except Exception as exc:
            logger.warning("Failed to build scope matcher (continuing): %s", exc)
            self.scope_matcher = None

        if pst_file_record is not None:
            self._stakeholders, self._keywords = self._load_tagging_assets(
                pst_file_record
            )

        def set_processing_meta(status: str, **extra: Any) -> None:
            if document is not None:
                meta: dict[str, Any] = (
                    document.meta if isinstance(document.meta, dict) else {}
                )
                pst_meta_value = meta.get("pst_processing")
                pst_meta: dict[str, Any] = (
                    pst_meta_value if isinstance(pst_meta_value, dict) else {}
                )
                pst_meta.update(extra)
                pst_meta["status"] = status
                meta["pst_processing"] = pst_meta
                setattr(document, "meta", meta)

        # Update status - either document or pst_file_record
        if document is not None:
            setattr(document, "status", DocStatus.PROCESSING)
            set_processing_meta("processing", started_at=start_time.isoformat())
        else:
            # Update pst_file_record status
            pst_file_record.processing_status = "processing"
            pst_file_record.processing_started_at = start_time
        self.db.commit()

        # Download PST from S3 to a local temp file (pypff requires a filesystem path).
        temp_dir = getattr(settings, "PST_TEMP_DIR", None) or None
        keep_temp_on_error = bool(getattr(settings, "PST_KEEP_TEMP_ON_ERROR", False))
        if temp_dir:
            try:
                os.makedirs(temp_dir, exist_ok=True)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to create PST_TEMP_DIR={temp_dir}: {e}"
                ) from e

        # Preflight: ensure enough free disk for the download (large PSTs can be multi-GB).
        try:
            expected_size = int(getattr(pst_file_record, "file_size_bytes", 0) or 0)
            usage = shutil.disk_usage(temp_dir or tempfile.gettempdir())
            free_bytes = int(usage.free)
            if expected_size and free_bytes < int(expected_size * 1.15):
                raise RuntimeError(
                    "Insufficient temp disk space for PST download. "
                    f"Need ~{expected_size / (1024**3):.2f} GB, "
                    f"free {free_bytes / (1024**3):.2f} GB "
                    f"in {(temp_dir or tempfile.gettempdir())}. "
                    "Set PST_TEMP_DIR to a larger writable volume."
                )
        except Exception as e:
            had_error = True
            logger.error("PST temp disk preflight failed: %s", e)
            if document is not None:
                setattr(document, "status", DocStatus.FAILED)
                set_processing_meta(
                    "failed",
                    error=str(e),
                    failed_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                pst_file_record.processing_status = "failed"
                pst_file_record.error_message = str(e)
                pst_file_record.processing_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            raise

        with tempfile.NamedTemporaryFile(
            suffix=".pst", delete=False, dir=temp_dir
        ) as tmp:
            try:
                t_dl = time.monotonic()
                bucket_to_use = (
                    pst_s3_bucket
                    or (
                        str(getattr(pst_file_record, "s3_bucket", ""))
                        if pst_file_record is not None
                        else ""
                    )
                    or getattr(settings, "S3_PST_BUCKET", "")
                    or settings.S3_BUCKET
                )
                logger.info(f"Downloading PST from s3://{bucket_to_use}/{pst_s3_key}")
                self.s3.download_fileobj(
                    Bucket=bucket_to_use, Key=pst_s3_key, Fileobj=tmp
                )
                self._timings["download_s"] += time.monotonic() - t_dl
                pst_path = tmp.name
                # region agent log H11 download
                size_bytes = (
                    os.path.getsize(pst_path) if os.path.exists(pst_path) else None
                )
                agent_log(
                    "H11",
                    "PST downloaded to temp",
                    {
                        "path": pst_path,
                        "size_bytes": size_bytes,
                        "bucket": bucket_to_use,
                        "key": pst_s3_key,
                    },
                    run_id="pre-fix",
                )
                # endregion agent log H11 download
            except Exception as e:
                had_error = True
                logger.error(f"Failed to download PST: {e}")
                if document is not None:
                    setattr(document, "status", DocStatus.FAILED)
                    set_processing_meta(
                        "failed",
                        error=str(e),
                        failed_at=datetime.now(timezone.utc).isoformat(),
                    )
                else:
                    pst_file_record.processing_status = "failed"
                    pst_file_record.error_message = str(e)
                    pst_file_record.processing_completed_at = datetime.now(timezone.utc)
                self.db.commit()
                raise

        try:
            # Open PST with pypff
            pst_file = pypff.file()
            if not pst_path:
                raise RuntimeError("PST temp path was not created")
            t_open = time.monotonic()
            pst_file.open(pst_path)
            self._timings["open_s"] += time.monotonic() - t_open

            logger.info("PST opened successfully, processing folders...")
            # region agent log H12 open
            agent_log(
                "H12",
                "PST opened with pypff",
                {"path": pst_path},
                run_id="pre-fix",
            )
            # endregion agent log H12 open

            # Get root folder and (optionally) count total messages first
            root: Any = pst_file.get_root_folder()
            if getattr(settings, "PST_PRECOUNT_MESSAGES", False):
                t_count = time.monotonic()
                self.total_count = self._count_messages(root)
                self._timings["precount_s"] += time.monotonic() - t_count
                logger.info(f"Found {self.total_count} total messages to process")
                # region agent log H12 count
                agent_log(
                    "H12",
                    "Total messages counted",
                    {"total_count": self.total_count},
                    run_id="pre-fix",
                )
                # endregion agent log H12 count
            else:
                self.total_count = 0
                logger.info(
                    "Skipping PST pre-count for speed (PST_PRECOUNT_MESSAGES=false)"
                )
                # region agent log H12 count skipped
                agent_log(
                    "H12",
                    "Total messages pre-count skipped",
                    {"total_count": None},
                    run_id="pre-fix",
                )
                # endregion agent log H12 count skipped

            self._report_progress(pst_file_record, force=True)

            # Initialize batch buffers
            self.email_buffer = []
            self.attachment_buffer = []
            self.document_buffer = []
            self.evidence_buffer = []

            # Disable autoflush for maximum speed
            with self.db.no_autoflush:
                # Process all folders recursively
                self._process_folder(
                    root,
                    pst_file_record,
                    document,
                    case_id,
                    project_id,
                    company_id,
                    stats,
                )

                # Flush remaining buffers
                self._flush_buffers(force=True, stats=stats)

            # Build thread relationships after all emails are extracted (CRITICAL - USP FEATURE!)
            logger.info("Building email thread relationships...")
            t_thread = time.monotonic()
            thread_scope = (
                str(getattr(settings, "PST_THREADING_SCOPE", "pst") or "pst")
                .strip()
                .lower()
            )
            thread_pst_id = pst_file_record.id if thread_scope == "pst" else None
            thread_stats = self._build_thread_relationships(
                case_id, project_id, pst_file_id=thread_pst_id
            )
            self._timings["threading_s"] += time.monotonic() - t_thread
            # region agent log H13 threads
            agent_log(
                "H13",
                "Threads built",
                {
                    "case_id": str(case_id) if case_id else None,
                    "project_id": str(project_id) if project_id else None,
                    "thread_scope": thread_scope,
                    "threads_identified": thread_stats.threads_identified,
                    "links_created": thread_stats.links_created,
                    "total_emails": stats.get("total_emails"),
                },
                run_id="pre-fix",
            )
            # endregion agent log H13 threads

            stats["threads_identified"] = thread_stats.threads_identified

            # Deduplicate emails after threading (deterministic, evidence-logged)
            logger.info("Deduplicating emails...")
            t_dedupe = time.monotonic()
            dedupe_scope = (
                str(getattr(settings, "PST_DEDUPE_SCOPE", "pst") or "pst")
                .strip()
                .lower()
            )
            dedupe_pst_id = pst_file_record.id if dedupe_scope == "pst" else None
            dedupe_stats = dedupe_emails(
                self.db,
                case_id=case_id,
                project_id=project_id,
                pst_file_id=dedupe_pst_id,
                run_id="pst_processor",
            )
            self._timings["dedupe_s"] += time.monotonic() - t_dedupe
            stats["dedupe_duplicates"] = dedupe_stats.duplicates_found

            # Wait for any pending S3 uploads
            if self.upload_futures:
                logger.info(
                    f"Waiting for {len(self.upload_futures)} attachment uploads to complete..."
                )
                for future in as_completed(self.upload_futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Async upload failed: {e}")
                        stats["errors"].append(f"Async upload failed: {e}")
                logger.info("All attachment uploads completed")
                self.upload_futures = []  # Clear for next run

            # Calculate stats
            stats["unique_attachments"] = len(self.attachment_hashes)
            stats["processing_time"] = (
                datetime.now(timezone.utc) - start_time
            ).total_seconds()

            # Update status with success
            if document is not None:
                setattr(document, "status", DocStatus.READY)
                set_processing_meta(
                    "completed",
                    processed_at=datetime.now(timezone.utc).isoformat(),
                    stats=stats,
                )
            else:
                pst_file_record.processing_status = "completed"
                pst_file_record.total_emails = stats.get("total_emails", 0)
                pst_file_record.processed_emails = stats.get("total_emails", 0)
                pst_file_record.processing_completed_at = datetime.now(timezone.utc)
            self.db.commit()

            # Trigger background tasks after successful completion
            try:
                from .tasks import (
                    index_project_emails_semantic,
                    index_case_emails_semantic,
                    apply_spam_filter_batch,
                )

                if project_id:
                    logger.info(f"Queueing semantic indexing for project {project_id}")
                    index_project_emails_semantic.delay(str(project_id))
                    logger.info(f"Queueing spam filter for project {project_id}")
                    apply_spam_filter_batch.delay(project_id=str(project_id))
                elif case_id:
                    logger.info(f"Queueing semantic indexing for case {case_id}")
                    index_case_emails_semantic.delay(str(case_id))
                    logger.info(f"Queueing spam filter for case {case_id}")
                    apply_spam_filter_batch.delay(case_id=str(case_id))
            except Exception as task_error:
                logger.warning(f"Failed to queue post-processing tasks: {task_error}")

            pst_file.close()

            logger.info(f"PST processing completed: {stats}")

        except Exception as e:
            had_error = True
            logger.error(f"PST processing failed: {e}", exc_info=True)
            try:
                self.db.rollback()
            except Exception:
                pass
            # Try to save partial results
            try:
                self._flush_buffers(force=True, stats=stats)
            except Exception as save_err:
                logger.error(f"Failed to save remaining buffer on error: {save_err}")

            if document is not None:
                setattr(document, "status", DocStatus.FAILED)
                set_processing_meta(
                    "failed",
                    error=str(e),
                    failed_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                pst_file_record.processing_status = "failed"
                pst_file_record.error_message = str(e)
                pst_file_record.processing_completed_at = datetime.now(timezone.utc)
            self.db.commit()
            stats["errors"].append(str(e))
            raise

        finally:
            total_s = time.monotonic() - start_monotonic
            try:
                logger.info(
                    "PST timing: total=%.2fs download=%.2fs open=%.2fs precount=%.2fs headers=%.2fs body=%.2fs attachments=%.2fs flush=%.2fs threading=%.2fs dedupe=%.2fs msgs_seen=%d msgs_skipped=%d atts_seen=%d",
                    total_s,
                    self._timings.get("download_s", 0.0),
                    self._timings.get("open_s", 0.0),
                    self._timings.get("precount_s", 0.0),
                    self._timings.get("headers_s", 0.0),
                    self._timings.get("body_s", 0.0),
                    self._timings.get("attachments_s", 0.0),
                    self._timings.get("flush_s", 0.0),
                    self._timings.get("threading_s", 0.0),
                    self._timings.get("dedupe_s", 0.0),
                    int(self._counts.get("messages_seen", 0)),
                    int(self._counts.get("messages_skipped", 0)),
                    int(self._counts.get("attachments_seen", 0)),
                )
            except Exception:
                pass
            # Cleanup temp file
            try:
                if pst_path and os.path.exists(pst_path):
                    if keep_temp_on_error and had_error:
                        logger.warning(
                            "Keeping PST temp file for debugging: %s", pst_path
                        )
                    else:
                        os.unlink(pst_path)
            except Exception as cleanup_err:
                logger.warning(
                    "Failed to cleanup PST temp file %s: %s", pst_path, cleanup_err
                )

        return stats

    def _count_messages(self, folder: Any) -> int:
        """Iteratively count total messages for progress tracking."""
        count = 0
        stack = [folder]
        while stack:
            current = stack.pop()
            try:
                count += int(
                    self._safe_get_attr(current, "number_of_sub_messages", 0) or 0
                )
                num_subfolders = int(
                    self._safe_get_attr(current, "number_of_sub_folders", 0) or 0
                )
                for i in range(num_subfolders):
                    try:
                        subfolder: Any = current.get_sub_folder(i)
                        stack.append(subfolder)
                    except (AttributeError, RuntimeError, OSError) as e:
                        logger.debug(
                            "Could not count messages in subfolder %d: %s",
                            i,
                            str(e)[:50],
                        )
            except (ValueError, TypeError) as e:
                logger.warning("Error counting messages: %s", str(e))
                return count
        return count

    def _process_folder(
        self,
        folder: Any,
        pst_file_record: PSTFile,
        document: Document | None,
        case_id: UUID | str | None,
        project_id: UUID | str | None,
        company_id: UUID | str | None,
        stats: ProcessingStats,
        folder_path: str = "",
    ) -> None:
        """
        Iteratively process PST folders to avoid deep recursion limits.

        Note: Email messages and attachments are now committed individually in _process_message
        to ensure EmailAttachment records can be properly linked.
        """
        stack: list[tuple[Any, str]] = [(folder, folder_path)]

        while stack:
            current_folder, parent_path = stack.pop()
            folder_name = current_folder.name or "Root"
            current_path = (
                f"{parent_path}/{folder_name}" if parent_path else folder_name
            )

            num_messages = int(
                self._safe_get_attr(current_folder, "number_of_sub_messages", 0) or 0
            )
            logger.info(
                "Processing folder: %s (%d messages)", current_path, num_messages
            )

            # Process messages in this folder
            for i in range(num_messages):
                try:
                    message = current_folder.get_sub_message(i)

                    # Early filter: skip non-email MAPI items unless explicitly enabled.
                    # This avoids wasting time ingesting IPM.Task/IPM.Appointment/etc as emails.
                    if bool(getattr(settings, "PST_SKIP_NON_EMAIL_ITEMS", True)):
                        message_class = self._safe_get_attr(
                            message, "message_class", None
                        )
                        if message_class is None:
                            message_class = self._safe_get_value(
                                message, "get_message_class", None
                            )
                        message_class_text = decode_maybe_bytes(message_class)
                        if message_class_text:
                            mc_upper = str(message_class_text).upper()
                            if "IPM.NOTE" not in mc_upper:
                                self._counts["messages_skipped"] += 1
                                try:
                                    stats["skipped_non_email"] = (
                                        int(stats.get("skipped_non_email", 0) or 0) + 1
                                    )
                                except Exception:
                                    pass
                                continue

                    _ = self._process_message(
                        message,
                        pst_file_record,
                        document,
                        case_id,
                        project_id,
                        company_id,
                        stats,
                        current_path,
                    )

                    stats["total_emails"] += 1
                    self.processed_count += 1
                    self._report_progress(pst_file_record)

                    # Check buffers
                    self._flush_buffers(stats=stats)

                except (
                    AttributeError,
                    RuntimeError,
                    OSError,
                    ValueError,
                    SystemError,
                    MemoryError,
                ) as e:
                    self._counts["messages_skipped"] += 1
                    logger.warning(
                        f"Skipping message {i} in {current_path}: {str(e)[:100]}"
                    )
                    stats["errors"].append(
                        f"Message {i} in {current_path}: {str(e)[:50]}"
                    )

            # Queue subfolders (reverse order to preserve traversal order)
            num_subfolders = int(
                self._safe_get_attr(current_folder, "number_of_sub_folders", 0) or 0
            )
            subfolders: list[Any] = []
            for i in range(num_subfolders):
                try:
                    subfolder = current_folder.get_sub_folder(i)
                    subfolders.append(subfolder)
                except (
                    AttributeError,
                    RuntimeError,
                    OSError,
                    SystemError,
                    MemoryError,
                ) as e:
                    logger.warning(
                        f"Skipping subfolder {i} in {current_path}: {str(e)[:100]}"
                    )
                    stats["errors"].append(
                        f"Subfolder {i} in {current_path}: {str(e)[:50]}"
                    )

            for subfolder in reversed(subfolders):
                stack.append((subfolder, current_path))

    def _strip_footer_noise(self, text: str | None) -> str:
        """
        Remove boilerplate banners and disclaimers (e.g., CAUTION EXTERNAL EMAIL,
        confidentiality notices, office addresses) while keeping the core message.
        """
        return strip_footer_noise(text)

    def _sanitize_text(self, value: str | None) -> str | None:
        """Remove NUL/control bytes that Postgres cannot store."""
        if value is None:
            return None
        text = str(value)
        if not text:
            return text
        return text.replace("\x00", "").replace("\u0000", "")

    def _clean_body_text(self, text: str | None) -> str | None:
        """
        Clean body text for display:
        - Strip HTML tags and CSS
        - Decode HTML entities (&nbsp;, <, >, etc.)
        - Remove zero-width characters (U+200B, U+200C, U+200D, U+FEFF)
        - Normalize whitespace
        """
        return clean_body_text(text)

    def _calculate_spam_score(
        self,
        subject: str | None,
        body: str | None,
        sender_email: str | None,
    ) -> dict[str, Any]:
        """
        Calculate spam score for an email during ingestion.

        Uses the SpamClassifier from spam_filter module for pattern-based detection.

        Returns a dict with:
        - spam_score: int (0-100, higher = more likely spam)
        - is_spam: bool (True if spam detected)
        - spam_reasons: list[str] (detected categories)
        - other_project: str | None (detected project name if category is other_projects)
        - is_hidden: bool (should be hidden from correspondence view)
        """
        # Use the centralized spam classifier
        result: SpamResult = classify_email(subject, sender_email, body)

        # Extract other_project name if this is an other_projects match
        other_project: str | None = None
        if result["category"] == "other_projects":
            other_project = extract_other_project(subject)

        return {
            "spam_score": result["score"],
            "is_spam": result["is_spam"],
            "spam_reasons": [result["category"]] if result["category"] else [],
            "other_project": other_project,
            "is_hidden": result["is_hidden"],
        }

    def _safe_get_attr(
        self, obj: Any, attr_name: str, default: Any | None = None
    ) -> Any:
        """Safely get attribute from pypff object

        Handles pypff errors that occur when accessing corrupted PST data.
        """
        try:
            # First check if the attribute exists - wrap in try/except too
            try:
                has_attr = hasattr(obj, attr_name)
            except (SystemError, Exception):
                return default

            if not has_attr:
                return default

            # Try to get the value
            value = getattr(obj, attr_name)

            # If it's a callable (method), call it
            if callable(value):
                return value()
            else:
                return value
        except (AttributeError, RuntimeError, OSError) as e:
            # Log only if it's not a common corruption error
            error_str = str(e)
            if not any(
                x in error_str
                for x in ["unable to retrieve", "invalid local descriptors", "libpff"]
            ):
                logger.debug("Error accessing %s: %s", attr_name, error_str[:100])
            return default
        except (ValueError, TypeError, MemoryError, SystemError) as e:
            # SystemError can occur with corrupted Unicode data in pypff
            logger.warning("Unexpected error accessing %s: %s", attr_name, str(e)[:100])
            return default
        except Exception as e:
            # Catch-all for any other pypff errors
            logger.debug("Generic error accessing %s: %s", attr_name, str(e)[:50])
            return default

    def _safe_get_value(
        self, obj: Any, attr_name: str, default: Any | None = None
    ) -> Any:
        """
        Safely get an attribute value from a pypff object.

        If the attribute is callable (e.g. `get_transport_headers()`), calls it
        without arguments and returns the result.
        """
        value = self._safe_get_attr(obj, attr_name, None)
        if value is None:
            return default
        if callable(value):
            try:
                return value()
            except (TypeError, AttributeError, RuntimeError, OSError, ValueError):
                return default
        return value

    def _get_transport_headers_text(self, message: Any) -> str | None:
        """Best-effort extraction of RFC822 transport headers from a PST message."""
        headers = self._safe_get_attr(message, "transport_headers", None)
        if headers is None:
            headers = self._safe_get_value(message, "get_transport_headers", None)
        headers = decode_header_blob(headers)
        return headers

    def _build_canonical_participants(
        self,
        sender_email: str | None,
        recipients_to: list[str] | None,
        recipients_cc: list[str] | None,
        recipients_bcc: list[str] | None,
    ) -> list[str] | None:
        participants: list[str] = []
        for addr in [
            sender_email,
            *(recipients_to or []),
            *(recipients_cc or []),
            *(recipients_bcc or []),
        ]:
            if not addr:
                continue
            cleaned = addr.strip().lower()
            if cleaned:
                participants.append(cleaned)
        unique = sorted(set(participants))
        return unique or None

    def _load_tagging_assets(
        self, pst_file: PSTFile
    ) -> tuple[list[Stakeholder], list[Keyword]]:
        try:
            stakeholders: list[Stakeholder] = []
            keywords: list[Keyword] = []

            if pst_file.case_id:
                stakeholders.extend(
                    self.db.query(Stakeholder)
                    .filter(Stakeholder.case_id == pst_file.case_id)
                    .all()
                )
                keywords.extend(
                    self.db.query(Keyword)
                    .filter(Keyword.case_id == pst_file.case_id)
                    .all()
                )

            if pst_file.project_id:
                # Include project-level defaults even when processing a case-level PST.
                # Convention: project-level assets set `project_id` and leave `case_id` NULL.
                stakeholders.extend(
                    self.db.query(Stakeholder)
                    .filter(
                        Stakeholder.project_id == pst_file.project_id,
                        Stakeholder.case_id.is_(None),
                    )
                    .all()
                )
                keywords.extend(
                    self.db.query(Keyword)
                    .filter(
                        Keyword.project_id == pst_file.project_id,
                        Keyword.case_id.is_(None),
                    )
                    .all()
                )

            unique_stakeholders = {str(item.id): item for item in stakeholders}
            unique_keywords = {str(item.id): item for item in keywords}
            logger.info(
                "Loaded tagging assets (pst_file_id=%s case_id=%s project_id=%s): stakeholders=%s keywords=%s",
                getattr(pst_file, "id", None),
                pst_file.case_id,
                pst_file.project_id,
                len(unique_stakeholders),
                len(unique_keywords),
            )
            return list(unique_stakeholders.values()), list(unique_keywords.values())
        except Exception as exc:
            logger.error(
                "Failed to load tagging assets (pst_file_id=%s): %s",
                getattr(pst_file, "id", None),
                exc,
            )
            return [], []

    def _match_stakeholders(
        self,
        sender_email: str,
        sender_name: str,
        all_recipients: list[Any],
        stakeholders: list[Stakeholder],
        subject: str | None = None,
        body_text: str | None = None,
    ) -> list[Stakeholder]:
        """Auto-tag email with matching stakeholders."""
        matched: list[Stakeholder] = []
        search_text = f"{subject or ''} {body_text or ''}".lower()

        emails: list[str] = []
        names: list[str] = []

        if sender_email:
            emails.append(sender_email)
        if sender_name:
            names.append(sender_name)

        for recipient in all_recipients or []:
            if isinstance(recipient, dict):
                email = (recipient.get("email") or "").strip()
                name = (recipient.get("name") or "").strip()
                if email:
                    emails.append(email)
                if name:
                    names.append(name)
            else:
                try:
                    email = str(recipient).strip()
                except Exception:
                    email = ""
                if email:
                    emails.append(email)

        all_emails: list[str] = []
        seen_emails: set[str] = set()
        for email in emails:
            if not email:
                continue
            lowered = email.lower()
            if lowered in seen_emails:
                continue
            seen_emails.add(lowered)
            all_emails.append(email)

        all_names = [name for name in names if name]
        all_emails_lower = {email.lower() for email in all_emails if email}

        for stakeholder in stakeholders:
            if stakeholder.email and stakeholder.email.lower() in all_emails_lower:
                matched.append(stakeholder)
                continue

            if stakeholder.email_domain:
                for email in all_emails:
                    if email and "@" in email:
                        domain = email.split("@", 1)[1].lower()
                        if domain == stakeholder.email_domain.lower():
                            matched.append(stakeholder)
                            break

            if stakeholder.name:
                stakeholder_name_lower = stakeholder.name.lower()
                for name in all_names:
                    if name and stakeholder_name_lower in name.lower():
                        matched.append(stakeholder)
                        break
                else:
                    if stakeholder_name_lower and stakeholder_name_lower in search_text:
                        matched.append(stakeholder)

        unique: dict[str, Stakeholder] = {}
        for stakeholder in matched:
            key = str(stakeholder.id)
            if key not in unique:
                unique[key] = stakeholder
        return list(unique.values())

    def _match_keywords(
        self, subject: str, body_text: str, keywords: list[Keyword]
    ) -> list[Keyword]:
        """Auto-tag email with matching keywords."""
        matched: list[Keyword] = []
        search_text = f"{subject or ''} {body_text or ''}"
        search_text_lower = search_text.lower()

        for keyword in keywords:
            keyword_id = str(keyword.id)
            keyword_name = (keyword.keyword_name or "").strip()
            if not keyword_name:
                continue
            if keyword.is_regex:
                search_terms = self._keyword_regex_terms_cache.get(keyword_id)
                if search_terms is None:
                    search_terms = [keyword_name]
                    if keyword.variations:
                        variations = [
                            v.strip()
                            for v in keyword.variations.split(",")
                            if v and v.strip()
                        ]
                        search_terms.extend(variations)
                    self._keyword_regex_terms_cache[keyword_id] = search_terms

                for term in search_terms:
                    cache_key = (str(keyword.id), term)
                    if cache_key in self._invalid_keyword_regex:
                        continue

                    compiled = self._keyword_regex_cache.get(cache_key)
                    if compiled is None:
                        try:
                            compiled = re.compile(term, re.IGNORECASE)
                        except (re.error, TypeError) as exc:
                            self._invalid_keyword_regex.add(cache_key)
                            logger.warning(
                                "Invalid keyword regex skipped (keyword_id=%s, term=%s): %s",
                                keyword.id,
                                term[:200],
                                exc,
                            )
                            continue
                        self._keyword_regex_cache[cache_key] = compiled

                    if compiled.search(search_text):
                        matched.append(keyword)
                        break
            else:
                search_terms = self._keyword_plain_terms_cache.get(keyword_id)
                if search_terms is None:
                    search_terms = [keyword_name.lower()]
                    if keyword.variations:
                        variations = [
                            v.strip().lower()
                            for v in keyword.variations.split(",")
                            if v and v.strip()
                        ]
                        search_terms.extend(variations)
                    self._keyword_plain_terms_cache[keyword_id] = search_terms

                for term in search_terms:
                    if term in search_text_lower:
                        matched.append(keyword)
                        break

        unique: dict[str, Keyword] = {}
        for keyword in matched:
            key = str(keyword.id)
            if key not in unique:
                unique[key] = keyword
        return list(unique.values())

    def _process_message(
        self,
        message: Any,
        pst_file_record: PSTFile,
        document: Document | None,
        case_id: UUID | str | None,
        project_id: UUID | str | None,
        company_id: UUID | str | None,
        stats: ProcessingStats,
        folder_path: str,
    ) -> EmailMessage:
        """
        Process individual email message

        KEY INSIGHT: We DON'T save the email as a file - we extract and index content directly!
        This saves ~90% storage compared to traditional PST extraction
        """

        self._counts["messages_seen"] += 1

        # Extract email headers (single pass, fast path)
        t_headers = time.monotonic()
        transport_headers_text = self._get_transport_headers_text(message)
        header_map = self._parse_transport_headers_map(
            transport_headers_text,
            wanted={
                "message-id",
                "in-reply-to",
                "references",
                "date",
                "received",
                "thread-topic",
                "from",
                "to",
                "cc",
                "bcc",
            },
        )

        def _strip_angles(value: str | None) -> str | None:
            if not value:
                return None
            cleaned = value.strip()
            if cleaned.startswith("<") and cleaned.endswith(">"):
                cleaned = cleaned[1:-1].strip()
            return cleaned or None

        message_id = _strip_angles(self._header_first(header_map, "message-id"))
        in_reply_to = _strip_angles(self._header_first(header_map, "in-reply-to"))
        references = self._header_first(header_map, "references")

        message_id = self._sanitize_text(message_id)
        in_reply_to = self._sanitize_text(in_reply_to)
        references = self._sanitize_text(references)
        folder_path = self._sanitize_text(folder_path) or folder_path

        header_date = parse_date_header(self._header_first(header_map, "date"))
        received_values = header_map.get("received", [])
        received_hops = (
            parse_received_headers(received_values) if received_values else []
        )
        received_first, received_last = received_time_bounds(received_hops)
        transport_headers_hash = sha256_text(transport_headers_text)
        self._timings["headers_s"] += time.monotonic() - t_headers

        # Safely get attributes - pypff objects have limited attributes
        subject = self._sanitize_text(self._safe_get_attr(message, "subject", ""))
        sender_name = self._sanitize_text(
            self._safe_get_attr(message, "sender_name", "")
        )

        # Sender/recipient extraction:
        # Prefer pypff message helper methods (more reliable than transport header parsing),
        # but fall back to transport headers when needed.
        sender_email = self._sanitize_text(
            self._extract_sender_email(
                message,
                transport_headers_text=transport_headers_text,
                header_map=header_map,
            )
        )

        def _normalize_address_list(raw: Any) -> list[str]:
            """Return a stable, de-duplicated list of email addresses (lower-cased).

            If no parseable emails exist, returns an empty list.
            """
            if not raw:
                return []
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            text = str(raw)
            text = text.replace("\x00", "").replace("\u0000", "")

            # Primary: RFC 2822 parsing (handles display names)
            parsed = [addr.strip() for _, addr in getaddresses([text]) if addr]
            parsed = [a for a in parsed if "@" in a]

            # Fallback: simple regex extraction (handles malformed headers)
            if not parsed:
                parsed = re.findall(
                    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text
                )

            # De-dup / normalize
            uniq: list[str] = []
            seen: set[str] = set()
            for a in parsed:
                a2 = a.strip().lower()
                if a2 and a2 not in seen:
                    seen.add(a2)
                    uniq.append(a2)
            return uniq

        def _recipient_string(recipient_type: str) -> str | None:
            if recipient_type == "to":
                return self._safe_get_value(message, "get_recipient_string", None)
            if recipient_type == "cc":
                return self._safe_get_value(message, "get_cc_string", None)
            if recipient_type == "bcc":
                return self._safe_get_value(message, "get_bcc_string", None)
            return None

        def _extract_recipients(recipient_type: str, header_name: str) -> list[str]:
            # Prefer Outlook-provided recipient strings
            rec_str = _recipient_string(recipient_type)
            recipients = _normalize_address_list(rec_str)
            if recipients:
                return recipients
            # Fall back to transport headers (already parsed)
            header_val = self._header_first(header_map, header_name)
            return _normalize_address_list(header_val)

        to_recipients = _extract_recipients("to", "To")
        cc_recipients = _extract_recipients("cc", "Cc")
        bcc_recipients = _extract_recipients("bcc", "Bcc")

        # Preserve a UI-friendly recipient display fallback (names-only Exchange messages are common).
        # We keep recipients_to/cc/bcc as *SMTP addresses only* for hashing/dedupe, but store the
        # raw/display strings in metadata so the correspondence grid can show something even when
        # no parseable emails exist.
        def _recipient_display_string(
            recipient_type: str, header_name: str
        ) -> str | None:
            raw_val = _recipient_string(recipient_type) or self._header_first(
                header_map, header_name
            )
            raw_val = self._sanitize_text(raw_val)
            if not raw_val:
                return None
            raw_val = raw_val.strip()
            return raw_val[:2000] if raw_val else None

        recipients_display: dict[str, str] = {}
        for _k, _hn in (("to", "To"), ("cc", "Cc"), ("bcc", "Bcc")):
            _v = _recipient_display_string(_k, _hn)
            if _v:
                recipients_display[_k] = _v

        # Get dates - pypff has delivery_time (Received) and client_submit_time (Sent)
        # For forensic accuracy, we must map these correctly to date_sent and date_received
        date_sent_raw = self._safe_get_attr(message, "client_submit_time", None)
        date_received_raw = self._safe_get_attr(message, "delivery_time", None)

        # Fallbacks for missing dates
        if not date_sent_raw and date_received_raw:
            date_sent_raw = date_received_raw
        if not date_received_raw and date_sent_raw:
            date_received_raw = date_sent_raw

        # Final fallback to creation time
        if not date_sent_raw:
            date_sent_raw = self._safe_get_attr(message, "creation_time", None)
            if not date_received_raw:
                date_received_raw = date_sent_raw

        # Ensure timezone awareness (UTC)
        if date_sent_raw and date_sent_raw.tzinfo is None:
            date_sent_raw = date_sent_raw.replace(tzinfo=timezone.utc)
        if date_received_raw and date_received_raw.tzinfo is None:
            date_received_raw = date_received_raw.replace(tzinfo=timezone.utc)

        # Standardize variable name for threading/hashing logic downstream
        email_date = date_sent_raw

        # Get Outlook conversation index (binary data, convert to hex)
        conversation_index = None
        try:
            conv_idx_raw = self._safe_get_value(message, "get_conversation_index", None)
            if conv_idx_raw is None:
                conv_idx_raw = self._safe_get_attr(message, "conversation_index", None)
            if conv_idx_raw:
                conversation_index = (
                    conv_idx_raw.hex()
                    if hasattr(conv_idx_raw, "hex")
                    else str(conv_idx_raw)
                )
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug("Failed to extract conversation index: %s", e, exc_info=True)

        thread_topic = self._header_first(header_map, "thread-topic") or subject
        thread_topic = self._sanitize_text(thread_topic)

        # Extract email data
        email_data = {
            "message_id": message_id,
            "in_reply_to": in_reply_to,
            "references": references,
            "conversation_index": conversation_index,
            "thread_topic": thread_topic,
            "from": sender_email or sender_name,
            "to": to_recipients,
            "cc": cc_recipients,
            "bcc": bcc_recipients,
            "subject": subject,
            "date": email_date,
            "folder_path": folder_path,
            "importance": self._safe_get_attr(message, "importance", None),
            "has_attachments": int(
                self._safe_get_attr(message, "number_of_attachments", 0) or 0
            )
            > 0,
        }

        ingest_run_id = (
            self.ingest_run_id or f"pst:{pst_file_record.id}:{uuid.uuid4().hex}"
        )
        self.ingest_run_id = ingest_run_id
        raw_payload = {
            "source_type": "pst",
            "pst_file_id": str(pst_file_record.id),
            "pst_s3_bucket": pst_file_record.s3_bucket,
            "pst_s3_key": pst_file_record.s3_key,
            "folder_path": folder_path,
            "message_id": message_id,
            "conversation_index": conversation_index,
            "subject": subject,
            "date_sent": email_date.isoformat() if email_date else None,
        }
        raw_hash = build_source_hash(raw_payload)
        raw_metadata = dict(raw_payload)
        if transport_headers_hash:
            raw_metadata["transport_headers_sha256"] = transport_headers_hash
        if header_date:
            raw_metadata["header_date_utc"] = header_date
        if received_values:
            raw_metadata["received_count"] = len(received_values)
        storage_uri = None
        if pst_file_record.s3_bucket and pst_file_record.s3_key:
            storage_uri = f"s3://{pst_file_record.s3_bucket}/{pst_file_record.s3_key}"
        raw_id = uuid.uuid4()
        self.message_raw_buffer.append(
            MessageRaw(
                id=raw_id,
                source_hash=raw_hash,
                storage_uri=storage_uri,
                source_type="pst",
                extraction_tool_version="pypff",
                extracted_at=email_date,
                raw_metadata=raw_metadata,
            )
        )
        self.message_occurrence_buffer.append(
            MessageOccurrence(
                raw_id=raw_id,
                ingest_run_id=ingest_run_id,
                source_location=folder_path,
                case_id=case_id if case_id else None,
                project_id=project_id if project_id else None,
            )
        )

        # =====================================================================
        # EARLY EXCLUSION GATE
        # - Skip full ingestion for spam + other-project emails
        # - Store minimal metadata only
        # - Never extract attachments/evidence for excluded emails
        # =====================================================================
        scope_allow_current = not bool(getattr(settings, "PST_SCOPE_STRICT", False))

        def _detect_other_project(body_preview: str | None = None) -> str | None:
            if self.scope_matcher is None:
                return None
            try:
                return self.scope_matcher.detect_other_project(
                    subject,
                    folder_path,
                    body_preview,
                    allow_current_terms=scope_allow_current,
                )
            except Exception:
                return None

        def _buffer_excluded_email(
            spam_info: dict[str, Any], other_project_value: str | None
        ) -> EmailMessage:
            spam_category = None
            if other_project_value:
                spam_category = "other_project"
            elif spam_info.get("spam_reasons"):
                spam_category = spam_info.get("spam_reasons", [None])[0]

            spam_reasons = (
                [spam_category]
                if spam_category
                else [r for r in (spam_info.get("spam_reasons") or []) if r]
            )

            # If we are excluding during ingest, treat as hidden so downstream
            # subsystems (evidence, AI, search) cannot accidentally surface it.
            is_hidden = True
            derived_status = "other_project" if other_project_value else "spam"
            body_label = spam_category or derived_status or "spam"

            # Create minimal EmailMessage record - NO body content, NO attachments
            email_id = uuid.uuid4()
            participants = self._build_canonical_participants(
                sender_email, to_recipients, cc_recipients, bcc_recipients
            )
            derived_hash = build_content_hash(
                None,
                sender_email,
                sender_name,
                to_recipients,
                subject,
                email_date,
            )
            self.message_derived_buffer.append(
                MessageDerived(
                    raw_id=raw_id,
                    normalizer_version=NORMALIZER_VERSION,
                    normalizer_ruleset_hash=NORMALIZER_RULESET_HASH,
                    parser_version="pypff",
                    canonical_subject=subject,
                    canonical_participants=participants,
                    canonical_body_preview=None,
                    canonical_body_full=None,
                    banner_stripped_body=None,
                    content_hash_phase1=derived_hash,
                    thread_id_header=message_id,
                    thread_confidence="header" if message_id else None,
                    qc_flags={"excluded": True, "reason": derived_status},
                )
            )
            email_message = EmailMessage(
                id=email_id,
                pst_file_id=pst_file_record.id,
                case_id=case_id,
                project_id=project_id,
                message_id=message_id,
                in_reply_to=in_reply_to,
                email_references=references,
                conversation_index=conversation_index,
                subject=subject,
                sender_email=sender_email,
                sender_name=sender_name,
                recipients_to=to_recipients if to_recipients else None,
                recipients_cc=cc_recipients if cc_recipients else None,
                recipients_bcc=bcc_recipients if bcc_recipients else None,
                date_sent=date_sent_raw,
                date_received=date_received_raw,
                body_text=None,  # Skip body - not needed for excluded emails
                body_html=None,
                body_text_clean=None,
                body_preview=f"[EXCLUDED: {body_label}]",
                has_attachments=email_data.get("has_attachments", False),
                importance=self._safe_get_attr(message, "importance", None),
                pst_message_path=folder_path,
                meta={
                    "thread_topic": thread_topic,
                    "recipients_display": recipients_display or None,
                    "normalizer_version": NORMALIZER_VERSION,
                    "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
                    "transport_headers_sha256": transport_headers_hash,
                    "transport_headers_present": bool(transport_headers_text),
                    "header_date_utc": header_date,
                    "received_count": len(received_hops),
                    "received_bounds": (
                        {
                            "first": received_first,
                            "last": received_last,
                        }
                        if received_first or received_last
                        else None
                    ),
                    "received_chain": (
                        [hop.to_dict() for hop in received_hops]
                        if received_hops
                        else []
                    ),
                    # Correspondence visibility convention
                    "status": derived_status,
                    # Backward-compatible top-level flags
                    "excluded": True,
                    "spam_score": int(spam_info.get("spam_score") or 0),
                    "is_spam": bool(spam_info.get("is_spam")),
                    "is_hidden": is_hidden,
                    "spam_reasons": spam_reasons,
                    "other_project": other_project_value,
                    # Canonical nested spam structure (used by evidence cascading)
                    "spam": {
                        "is_spam": bool(spam_info.get("is_spam")),
                        "score": int(spam_info.get("spam_score") or 0),
                        "category": spam_category,
                        "is_hidden": True,
                        "status_set_by": "spam_filter_ingest",
                        "applied_status": derived_status,
                    },
                    "attachments_skipped": email_data.get("has_attachments", False),
                    "attachments_skipped_reason": derived_status,
                },
            )
            # Add to buffer instead of immediate commit
            self.email_buffer.append(email_message)

            # Track for threading (still needed for reference)
            if message_id:
                thread_info: ThreadInfo = {
                    "email_message": email_message,
                    "in_reply_to": in_reply_to,
                    "references": references,
                    "date": email_date,
                    "subject": subject or "",
                }
                self.threads_map[message_id] = thread_info

            return email_message

        other_project_label = _detect_other_project()
        spam_info = self._calculate_spam_score(
            subject, None, sender_email or sender_name
        )  # Subject-only check first

        other_project_value = other_project_label or spam_info.get("other_project")
        # Only short-circuit ingestion for *hidden* spam (high-confidence) and other-project matches.
        # Medium/low-confidence "spam" categories (e.g. out-of-office) should still be ingested so
        # evidence/attachments aren't lost.
        if (
            spam_info.get("is_spam") and spam_info.get("is_hidden")
        ) or other_project_value:
            return _buffer_excluded_email(spam_info, other_project_value)

        # =====================================================================
        # FULL PROCESSING - Only for relevant, non-spam emails
        # =====================================================================

        # Extract body content deterministically; select the most complete top message.
        t_body = time.monotonic()
        body_html = decode_maybe_bytes(
            self._safe_get_value(message, "get_html_body", None)
        )
        if body_html is None:
            body_html = decode_maybe_bytes(
                self._safe_get_attr(message, "html_body", None)
            )

        body_plain = decode_maybe_bytes(
            self._safe_get_value(message, "get_plain_text_body", None)
        )
        if body_plain is None:
            body_plain = decode_maybe_bytes(
                self._safe_get_attr(message, "plain_text_body", None)
            )

        # RTF extraction is comparatively expensive and can exacerbate libpff edge cases.
        # Only attempt RTF when no plain/html body is available.
        body_rtf = None
        if not body_plain and not body_html:
            body_rtf = decode_maybe_bytes(
                self._safe_get_value(message, "get_rtf_body", None)
            )
            if body_rtf is None:
                body_rtf = decode_maybe_bytes(
                    self._safe_get_attr(message, "rtf_body", None)
                )

        body_selection = select_best_body(
            plain_text=body_plain, html_body=body_html, rtf_body=body_rtf
        )

        body_html_content = body_html or None
        full_body_text = body_selection.full_text or ""
        body_text = full_body_text

        canonical_body = body_selection.top_text or ""
        if canonical_body and len(canonical_body) < 20 and len(full_body_text) <= 200:
            canonical_body = full_body_text
        elif not canonical_body and full_body_text and len(full_body_text) > 200:
            canonical_body = full_body_text

        # Clean body text - decode HTML entities and remove zero-width characters
        body_text_clean = self._clean_body_text(canonical_body)
        if body_text_clean is not None:
            canonical_body = body_text_clean

        # Normalise whitespace for canonical body (hashing/spam)
        if canonical_body:
            canonical_body = re.sub(r"\s+", " ", canonical_body).strip()

        scope_preview = (body_text_clean or canonical_body or full_body_text).strip()
        scope_preview = scope_preview[:4000] if scope_preview else None
        self._timings["body_s"] += time.monotonic() - t_body

        # Calculate spam score during ingestion (no AI, pure pattern matching)
        spam_info = self._calculate_spam_score(
            subject, canonical_body, sender_email or sender_name
        )
        other_project_label = _detect_other_project(scope_preview)
        other_project_value = other_project_label or spam_info.get("other_project")
        if (
            spam_info.get("is_spam") and spam_info.get("is_hidden")
        ) or other_project_value:
            return _buffer_excluded_email(spam_info, other_project_value)

        matched_stakeholders: list[Stakeholder] = []
        matched_keywords: list[Keyword] = []
        if self._stakeholders:
            recipients_all = (
                (to_recipients or []) + (cc_recipients or []) + (bcc_recipients or [])
            )
            matched_stakeholders = self._match_stakeholders(
                sender_email or "",
                sender_name or "",
                recipients_all,
                self._stakeholders,
                subject=subject,
                body_text=full_body_text,
            )
        if self._keywords:
            keyword_body = full_body_text or body_text_clean or canonical_body or ""
            matched_keywords = self._match_keywords(
                subject or "", keyword_body, self._keywords
            )

        # Calculate size saved by NOT storing the email as a file
        combined_content = (body_html_content or "") + (body_text or "")
        stats["size_saved"] += len(combined_content) + len(str(email_data))

        # Process attachments (THESE we DO save!)
        # Note: Attachments are processed AFTER creating the EmailMessage so we can link them
        attachments_info: list[dict[str, Any]] = []
        num_attachments = 0
        try:
            num_attachments = message.number_of_attachments
        except (AttributeError, RuntimeError, OSError) as e:
            logger.warning(
                f"Could not get attachment count for message in {folder_path}: {e}"
            )

        preview_source = full_body_text or body_html_content or ""
        body_preview = preview_source[:10000] if preview_source else None

        # Optional offload of very large FULL bodies to S3 to keep DB lean
        offloaded_body_key = None
        if (
            full_body_text
            and len(full_body_text) > self.body_offload_threshold
            and self.s3 is not None
            and self.body_offload_bucket
        ):
            try:
                entity_folder = (
                    f"case_{case_id}"
                    if case_id
                    else f"project_{project_id}" if project_id else "no_entity"
                )
                offloaded_body_key = f"email-bodies/{entity_folder}/{email_date.isoformat() if email_date else 'no_date'}_{uuid.uuid4().hex}.txt"
                body_bytes = full_body_text.encode("utf-8")
                self.s3.upload_fileobj(
                    io.BytesIO(body_bytes), self.body_offload_bucket, offloaded_body_key
                )
                # Keep only preview in DB; canonical body remains for dedupe/search preview
                full_body_text = ""
            except Exception as e:
                logger.warning(f"Body offload failed, keeping inline: {e}")

        # Compute content hash for deduplication (canonical body + key metadata)
        content_hash = build_content_hash(
            canonical_body,
            sender_email,
            sender_name,
            to_recipients,
            subject,
            email_date,
        )

        participants = self._build_canonical_participants(
            sender_email, to_recipients, cc_recipients, bcc_recipients
        )
        preview_text = (body_text_clean or canonical_body or "").strip()
        self.message_derived_buffer.append(
            MessageDerived(
                raw_id=raw_id,
                normalizer_version=NORMALIZER_VERSION,
                normalizer_ruleset_hash=NORMALIZER_RULESET_HASH,
                parser_version="pypff",
                canonical_subject=subject,
                canonical_participants=participants,
                canonical_body_preview=preview_text[:8000] if preview_text else None,
                canonical_body_full=None,
                banner_stripped_body=body_text_clean or None,
                content_hash_phase1=content_hash,
                thread_id_header=message_id,
                thread_confidence="header" if message_id else None,
                qc_flags={
                    "body_source": body_selection.selected_source,
                    "body_quoted_len": len(body_selection.quoted_text or ""),
                    "body_signature_len": len(body_selection.signature_text or ""),
                },
            )
        )

        spam_category = (
            spam_info.get("spam_reasons", [None])[0]
            if spam_info.get("spam_reasons")
            else None
        )
        spam_is_hidden = bool(spam_info.get("is_hidden", False))
        derived_status = (
            "other_project" if spam_category == "other_projects" else "spam"
        )
        spam_payload: dict[str, Any] = {
            "is_spam": bool(spam_info.get("is_spam")),
            "score": int(spam_info.get("spam_score") or 0),
            "category": spam_category,
            "is_hidden": spam_is_hidden,
            "status_set_by": "spam_filter_ingest",
        }
        if spam_is_hidden:
            spam_payload["applied_status"] = derived_status

        meta_payload: dict[str, Any] = {
            "thread_topic": thread_topic,
            "attachments": [],  # Will be populated after attachments are processed
            "has_attachments": num_attachments > 0,
            "canonical_hash": content_hash,
            "body_offloaded": bool(offloaded_body_key),
            "body_offload_bucket": (
                self.body_offload_bucket if offloaded_body_key else None
            ),
            "body_offload_key": offloaded_body_key,
            # Backward-compatible hint for consumers expecting the explicit field.
            "body_full_s3_key": offloaded_body_key,
            "normalizer_version": NORMALIZER_VERSION,
            "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
            # Spam classification (computed at ingestion time)
            "spam_score": int(spam_info.get("spam_score") or 0),
            "is_spam": bool(spam_info.get("is_spam")),
            "is_hidden": spam_is_hidden,  # Auto-exclude from views
            "spam_reasons": spam_info.get("spam_reasons", []),
            "other_project": other_project_value,
            # Canonical nested spam structure (used by evidence cascading)
            "spam": spam_payload,
        }
        meta_payload.update(
            {
                "body_source": body_selection.selected_source,
                "body_selection": body_selection.diagnostics,
                "body_quoted_len": len(body_selection.quoted_text or ""),
                "body_signature_len": len(body_selection.signature_text or ""),
                "transport_headers_sha256": transport_headers_hash,
                "transport_headers_present": bool(transport_headers_text),
                "header_date_utc": header_date,
                "received_count": len(received_hops),
                "received_bounds": (
                    {
                        "first": received_first,
                        "last": received_last,
                    }
                    if received_first or received_last
                    else None
                ),
                "received_chain": (
                    [hop.to_dict() for hop in received_hops] if received_hops else []
                ),
            }
        )
        if recipients_display:
            meta_payload["recipients_display"] = recipients_display
        if spam_is_hidden:
            # Correspondence visibility convention
            meta_payload["status"] = derived_status

        # Generate ID explicitly for batch processing
        email_id = uuid.uuid4()

        # Create EmailMessage record
        email_message = EmailMessage(
            id=email_id,
            pst_file_id=pst_file_record.id,
            case_id=case_id,
            project_id=project_id,
            message_id=message_id,
            in_reply_to=in_reply_to,
            email_references=references,
            conversation_index=conversation_index,
            subject=subject,
            sender_email=sender_email,
            sender_name=sender_name,
            recipients_to=to_recipients if to_recipients else None,
            recipients_cc=cc_recipients if cc_recipients else None,
            recipients_bcc=bcc_recipients if bcc_recipients else None,
            date_sent=date_sent_raw,
            date_received=date_received_raw,
            body_text=full_body_text or None,
            body_html=body_html_content,
            body_text_clean=body_text_clean or None,
            content_hash=content_hash,
            body_preview=body_preview,
            body_full_s3_key=offloaded_body_key,
            matched_stakeholders=(
                [str(item.id) for item in matched_stakeholders]
                if matched_stakeholders
                else None
            ),
            matched_keywords=(
                [str(item.id) for item in matched_keywords]
                if matched_keywords
                else None
            ),
            has_attachments=num_attachments > 0,
            importance=self._safe_get_attr(message, "importance", None),
            pst_message_path=folder_path,
            meta=meta_payload,
        )

        # We need to add and flush the email message first to get its ID for attachments
        self.email_buffer.append(email_message)

        # Now process attachments with the email_message ID
        if num_attachments > 0:
            t_atts = time.monotonic()
            try:
                attachments_info = self._process_attachments(
                    message,
                    email_message,
                    pst_file_record,
                    document,
                    case_id,
                    project_id,
                    company_id,
                    stats,
                )
                self._counts["attachments_seen"] += int(num_attachments)
                # Update email meta with attachment info
                email_meta = email_message.meta or {}
                email_meta["attachments"] = attachments_info
                email_message.meta = email_meta
            except (AttributeError, RuntimeError, OSError) as e:
                logger.warning(
                    f"Could not read attachments for message in {folder_path}: {e}"
                )
                stats["errors"].append(
                    f"Attachment error in {folder_path}: {str(e)[:100]}"
                )
            finally:
                self._timings["attachments_s"] += time.monotonic() - t_atts

        # Semantic indexing for deep research acceleration
        # Skip during initial PST processing for speed - can be done in background later
        ENABLE_SEMANTIC_INDEXING = (
            False  # Set to True to enable (slower but better search)
        )
        if ENABLE_SEMANTIC_INDEXING and self.semantic_service is not None:
            try:
                self.semantic_service.process_email(
                    email_id=str(email_message.id),
                    subject=subject,
                    body_text=body_text_clean or canonical_body,
                    sender=sender_email or sender_name,
                    recipients=to_recipients,
                    case_id=str(case_id) if case_id else None,
                    project_id=str(project_id) if project_id else None,
                )
            except Exception as sem_err:
                # Non-fatal - semantic indexing failure shouldn't stop ingestion
                logger.debug(f"Semantic indexing failed for email: {sem_err}")

        # Track for threading (use temporary ID)
        if message_id:
            thread_info: ThreadInfo = {
                "email_message": email_message,
                "in_reply_to": in_reply_to,
                "references": references,
                "date": email_date,
                "subject": subject or "",
            }
            self.threads_map[message_id] = thread_info

        return email_message

    def _get_attachment_property(self, attachment: Any, property_id: int) -> str | None:
        """Extract a string property from attachment record sets using MAPI property ID"""
        try:
            if hasattr(attachment, "record_sets"):
                for record_set in attachment.record_sets:
                    for entry_idx in range(record_set.number_of_entries):
                        try:
                            entry = record_set.get_entry(entry_idx)
                            if entry.entry_type == property_id:
                                return entry.data_as_string
                        except Exception:
                            continue
            # Also try get_record_set method
            if hasattr(attachment, "get_number_of_record_sets"):
                for rs_idx in range(attachment.get_number_of_record_sets()):
                    try:
                        record_set = attachment.get_record_set(rs_idx)
                        for entry_idx in range(record_set.number_of_entries):
                            try:
                                entry = record_set.get_entry(entry_idx)
                                if entry.entry_type == property_id:
                                    return entry.data_as_string
                            except Exception:
                                continue
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Could not get property {hex(property_id)}: {e}")
        return None

    def _get_attachment_filename(self, attachment: Any, index: int) -> str:
        """Extract attachment filename from MAPI properties"""
        # MAPI Property IDs for attachment filenames:
        # 0x3707 = PR_ATTACH_LONG_FILENAME (preferred)
        # 0x3704 = PR_ATTACH_FILENAME (8.3 short name)
        # 0x3001 = PR_DISPLAY_NAME
        # 0x370E = PR_ATTACH_EXTENSION

        # Try long filename first
        filename = self._get_attachment_property(attachment, 0x3707)
        if filename:
            return filename

        # Try short filename
        filename = self._get_attachment_property(attachment, 0x3704)
        if filename:
            return filename

        # Try display name
        filename = self._get_attachment_property(attachment, 0x3001)
        if filename:
            return filename

        # Try direct attributes (some pypff versions)
        filename = (
            self._safe_get_attr(attachment, "name", None)
            or self._safe_get_attr(attachment, "long_filename", None)
            or self._safe_get_attr(attachment, "short_filename", None)
            or self._safe_get_attr(attachment, "filename", None)
        )
        if filename:
            return filename

        # Fallback to generic name with extension if available
        ext = self._get_attachment_property(attachment, 0x370E)  # PR_ATTACH_EXTENSION
        if ext:
            return f"attachment_{index}{ext}"

        return f"attachment_{index}"

    def _get_attachment_content_type(self, attachment: Any, filename: str) -> str:
        """Get attachment content type from MAPI properties or guess from filename"""
        import mimetypes

        # Try MAPI property 0x370E for MIME type
        mime_type = self._get_attachment_property(attachment, 0x370E)
        if mime_type and "/" in mime_type:
            return mime_type

        # Try direct attribute
        content_type = self._safe_get_attr(
            attachment, "mime_type", None
        ) or self._safe_get_attr(attachment, "content_type", None)
        if content_type:
            return content_type

        # Guess from filename extension
        guessed_type, _ = mimetypes.guess_type(filename)
        return guessed_type or "application/octet-stream"

    def _is_signature_image(
        self, filename: str, size: int, content_id: str | None, content_type: str | None
    ) -> bool:
        """
        Intelligent detection of signature logos and email disclaimers

        Filters out:
        - Email signature logos (logo.png, signature.jpg, etc.)
        - Embedded disclaimer images
        - Outlook auto-generated images (image001.png, etc.)
        - Small inline images under 50KB

        Returns True if this is a signature/disclaimer image that should be filtered
        """
        filename_lower = filename.lower() if filename else ""

        # Pattern-based detection for common signature image names
        signature_patterns = [
            r"^logo\d*\.(?:png|jpg|jpeg|gif|bmp)$",  # logo.png, logo1.png
            r"^signature\d*\.(?:png|jpg|jpeg|gif|bmp)$",  # signature.jpg
            r"^image\d{3,}\.(?:png|jpg|jpeg|gif|bmp)$",  # image001.png (Outlook default)
            r"^~wrd\d+\.(?:png|jpg|jpeg|gif|bmp)$",  # ~WRD0001.png (Word embedded)
            r"^banner\.(?:png|jpg|jpeg|gif|bmp)$",  # banner.png
            r"^icon\.(?:png|jpg|jpeg|gif|bmp)$",  # icon.png
            r"^header\.(?:png|jpg|jpeg|gif|bmp)$",  # header.png
            r"^footer\.(?:png|jpg|jpeg|gif|bmp)$",  # footer.png
            r"^disclaimer\.(?:png|jpg|jpeg|gif|bmp)$",  # disclaimer.png
            r"^external.*\.(?:png|jpg|jpeg|gif|bmp)$",  # external warning images
            r"^caution.*\.(?:png|jpg|jpeg|gif|bmp)$",  # caution images
            r"^warning.*\.(?:png|jpg|jpeg|gif|bmp)$",  # warning images
        ]

        for pattern in signature_patterns:
            if re.match(pattern, filename_lower):
                logger.debug(f"Filtering signature image (pattern match): {filename}")
                return True

        # Size-based filtering: signatures and disclaimers are typically small
        # Most signature logos are under 50KB
        if size and size < 50000:  # 50KB threshold
            # Check if it's an image type
            if content_type and content_type.startswith("image/"):
                # If it has a content_id, it's embedded (likely signature)
                if content_id:
                    logger.debug(
                        f"Filtering small embedded image: {filename} ({size} bytes)"
                    )
                    return True

                # Very small images are usually icons/logos
                if size < 10000:  # 10KB
                    logger.debug(
                        f"Filtering very small image: {filename} ({size} bytes)"
                    )
                    return True

        # Inline images with content_id are usually embedded in email body (signatures)
        # BUT: Only filter if they're also small (to preserve genuine embedded diagrams)
        if content_id and size and size < 100000:  # 100KB threshold for cid: images
            if content_type and content_type.startswith("image/"):
                logger.debug(f"Filtering inline image: {filename} (cid:{content_id})")
                return True

        return False

    def _process_attachments(
        self,
        message: Any,
        email_message: EmailMessage,
        pst_file_record: PSTFile,
        parent_document: Document | None,
        case_id: UUID | str | None,
        project_id: UUID | str | None,
        company_id: UUID | str | None,
        stats: ProcessingStats,
    ) -> list[dict[str, Any]]:
        """
        Extract and save ONLY real attachments (FILTERS OUT signature logos and disclaimers)

        Creates both:
        1. Document records for the attachment files (for OCR/search)
        2. EmailAttachment records linking to the parent email

        Signature Detection:
        - Filters signature logos, disclaimers, and embedded images
        - Preserves whitespace in email (filters don't affect email body)
        - Only genuine document attachments are saved

        Returns list of attachment metadata dicts
        """
        attachments_info: list[dict[str, Any]] = []
        filtered_signatures = 0
        skipped_inline = 0

        for i in range(message.number_of_attachments):
            try:
                attachment = message.get_attachment(i)

                # Get attachment filename from MAPI properties in record sets
                # Property IDs: 0x3707 = Long filename, 0x3704 = Short filename, 0x3001 = Display name
                filename = self._get_attachment_filename(attachment, i)
                size = self._safe_get_attr(attachment, "size", 0)

                # Try to get content type from MAPI properties or guess from filename
                content_type = self._get_attachment_content_type(attachment, filename)

                # Special handling for inline images - get content_id from MAPI properties
                content_id = self._get_attachment_property(
                    attachment, 0x3712
                )  # PR_ATTACH_CONTENT_ID

                # SIGNATURE FILTERING: Skip signature logos and disclaimers
                if self._is_signature_image(filename, size, content_id, content_type):
                    filtered_signatures += 1
                    logger.debug(f"Skipped signature/disclaimer image: {filename}")
                    continue  # Skip this attachment - don't save it!

                # Determine if attachment is truly inline (embedded in email body)
                # In Outlook PST files, ALL attachments get a content_id, so we need smarter detection
                # Only mark as inline if:
                # 1. It has a content_id AND
                # 2. It's an image type AND
                # 3. It's small (< 500KB - large images are likely intentional attachments)
                is_image = bool(content_type and content_type.startswith("image/"))
                size_int = int(size) if size else 0
                is_small = size_int > 0 and size_int < 500000  # 500KB threshold
                is_inline = bool(content_id) and is_image and is_small

                # Inline images are overwhelmingly signature noise and very expensive to store/index.
                # Default behaviour is to skip them entirely (configurable).
                include_inline = bool(
                    getattr(settings, "PST_INCLUDE_INLINE_ATTACHMENTS", False)
                )
                if is_inline and not include_inline:
                    skipped_inline += 1
                    try:
                        stats["skipped_inline_attachments"] = (
                            int(stats.get("skipped_inline_attachments", 0)) + 1
                        )
                    except Exception:
                        pass
                    continue

                # Read attachment data - pypff uses read_buffer method
                attachment_data = None
                try:
                    if hasattr(attachment, "read_buffer"):
                        attachment_data = attachment.read_buffer(size)
                    elif hasattr(attachment, "data"):
                        attachment_data = attachment.data
                except Exception as e:
                    logger.warning(
                        f"Could not read attachment {filename}: {e}, skipping"
                    )
                    continue

                if not attachment_data:
                    logger.warning(f"No data for attachment {filename}, skipping")
                    continue

                # Calculate hash for deduplication using chunked hashing to reduce peak allocations
                hasher = hashlib.sha256()
                mv = memoryview(attachment_data)
                for offset in range(0, len(mv), self.chunk_size):
                    hasher.update(mv[offset : offset + self.chunk_size])
                file_hash = hasher.hexdigest()

                # Sanitize filename and generate unique S3 key
                safe_filename = self._sanitize_attachment_filename(
                    filename, f"attachment_{i}"
                )
                hash_prefix = file_hash[:8]
                entity_folder = (
                    f"case_{case_id}" if case_id else f"project_{project_id}"
                )
                company_prefix = company_id if company_id else "no_company"
                s3_key = f"attachments/{company_prefix}/{entity_folder}/{hash_prefix}_{safe_filename}"

                # Check if we've already stored this attachment (deduplication)
                entry = self.attachment_hashes.get(file_hash)
                is_duplicate = entry is not None
                att_doc_id = None

                if is_duplicate:
                    # Use existing document and S3 key (deduped at storage level)
                    if isinstance(entry, dict):
                        att_doc_id = entry.get("document_id")
                        s3_key = entry.get("s3_key", s3_key)
                    else:
                        att_doc_id = entry
                    logger.debug(
                        "Attachment is duplicate (hash=%s), reusing doc %s",
                        file_hash[:8],
                        att_doc_id,
                    )
                else:
                    # Upload to S3 (Parallelized)
                    try:
                        future = self.upload_executor.submit(
                            self.s3.put_object,
                            Bucket=self.attach_bucket,
                            Key=s3_key,
                            Body=attachment_data,
                            ContentType=content_type,
                            Metadata={
                                "original_filename": filename,
                                "file_hash": file_hash,
                                "case_id": str(case_id) if case_id else "",
                            },
                        )
                        self.upload_futures.append(future)
                    except Exception as e:
                        logger.error(
                            f"Failed to queue attachment upload {filename}: {e}"
                        )
                        stats["errors"].append(
                            f"Attachment upload queue failed: {filename}"
                        )
                        continue

                    # Create Document record for attachment
                    att_doc_id = uuid.uuid4()
                    att_doc = Document(
                        id=att_doc_id,
                        filename=safe_filename,
                        title=safe_filename,
                        content_type=content_type,
                        size=size,
                        bucket=self.attach_bucket,
                        s3_key=s3_key,
                        status=DocStatus.NEW,  # Set to NEW so OCR can process it
                        owner_user_id=(
                            getattr(parent_document, "owner_user_id", None)
                            if parent_document
                            else None
                        ),
                        meta={
                            "is_email_attachment": True,
                            "is_inline": is_inline,
                            "content_id": content_id,
                            "file_hash": file_hash,
                            "email_message_id": str(email_message.id),
                            "case_id": str(case_id) if case_id else None,
                            "project_id": str(project_id) if project_id else None,
                            "company_id": str(company_id) if company_id else None,
                        },
                    )
                    # Note: We append to buffer, so flush is delayed.
                    self.document_buffer.append(att_doc)

                    # Store for deduplication
                    self.attachment_hashes[file_hash] = {
                        "document_id": att_doc_id,
                        "s3_key": s3_key,
                    }

                    # ASYNC OCR: Queue OCR task immediately (non-blocking)
                    try:
                        from .tasks import celery_app

                        _ = celery_app.send_task(
                            "worker_app.worker.ocr_and_index",
                            args=[str(att_doc.id)],
                            queue=getattr(settings, "CELERY_QUEUE", "vericase"),
                        )
                        logger.debug(f"Queued OCR task for attachment: {safe_filename}")
                    except Exception as ocr_queue_error:
                        logger.warning(
                            f"Failed to queue OCR for {safe_filename}: {ocr_queue_error}"
                        )

                # CREATE EmailAttachment record - THIS IS THE CRITICAL FIX!
                email_attachment_id = uuid.uuid4()
                email_attachment = EmailAttachment(
                    id=email_attachment_id,
                    email_message_id=email_message.id,
                    filename=safe_filename,
                    content_type=content_type,
                    file_size_bytes=size,
                    s3_bucket=self.attach_bucket,
                    s3_key=s3_key,
                    attachment_hash=file_hash,
                    is_inline=is_inline,
                    content_id=content_id,
                    is_duplicate=is_duplicate,
                )
                self.attachment_buffer.append(email_attachment)

                # CREATE EvidenceItem record - so attachments appear in Evidence Repository!
                # Only create for non-inline attachments (skip embedded images)
                evidence_item_id = None
                if not is_inline:
                    try:
                        # Determine file type from extension
                        # Truncate to 255 chars max for database compatibility
                        raw_ext = (
                            os.path.splitext(safe_filename)[1].lower().lstrip(".")
                            if safe_filename
                            else ""
                        )
                        file_ext = raw_ext[:255] if raw_ext else None

                        # Check if this is a duplicate based on file hash
                        # Note: We don't set duplicate_of_id because the referenced ID may not
                        # exist if a previous batch was rolled back. The is_duplicate flag is sufficient.
                        evidence_is_duplicate = file_hash in self.evidence_item_hashes

                        # Ensure correct categorisation for Evidence Repository (Images vs Documents)
                        evidence_type_category = "email_attachment"
                        if is_image:
                            evidence_type_category = "photo"  # Images go to Media pot

                        evidence_item_id = uuid.uuid4()
                        evidence_item = EvidenceItem(
                            id=evidence_item_id,
                            filename=safe_filename,
                            original_path=f"PST:{pst_file_record.filename if pst_file_record else 'unknown'}/{safe_filename}",
                            file_type=file_ext,
                            mime_type=content_type,
                            file_size=size,
                            file_hash=file_hash,
                            s3_bucket=self.attach_bucket,
                            s3_key=s3_key,
                            evidence_type=evidence_type_category,
                            source_type="pst_extraction",
                            source_email_id=email_message.id,
                            case_id=case_id,
                            project_id=project_id,
                            is_duplicate=evidence_is_duplicate,
                            duplicate_of_id=None,  # Avoid FK issues from rollback scenarios
                            processing_status="pending",
                            auto_tags=["email-attachment", "from-pst"],
                        )
                        self.evidence_buffer.append(evidence_item)
                        evidence_item_id = evidence_item.id

                        # Store for EvidenceItem deduplication (only if not a duplicate)
                        if not evidence_is_duplicate:
                            self.evidence_item_hashes[file_hash] = evidence_item_id
                        logger.debug(
                            f"Created EvidenceItem {evidence_item_id} for attachment: {safe_filename}"
                        )
                    except Exception as ev_err:
                        logger.warning(
                            f"Failed to create EvidenceItem for {safe_filename}: {ev_err}"
                        )

                attachments_info.append(
                    {
                        "attachment_id": str(email_attachment.id),
                        "document_id": str(att_doc_id),
                        "evidence_item_id": (
                            str(evidence_item_id) if evidence_item_id else None
                        ),
                        "filename": safe_filename,
                        "size": size,
                        "content_type": content_type,
                        "is_inline": is_inline,
                        "content_id": content_id,
                        "s3_key": s3_key,
                        "hash": file_hash,
                        "attachment_hash": file_hash,
                        "is_duplicate": is_duplicate,
                    }
                )

                stats["total_attachments"] += 1

            except (AttributeError, RuntimeError, OSError, ValueError) as e:
                logger.error(f"Error processing attachment {i}: {e}", exc_info=True)
                stats["errors"].append(f"Attachment {i}: {str(e)}")

        if filtered_signatures > 0 or skipped_inline > 0:
            logger.debug(
                "Filtered signature images=%d; skipped inline images=%d",
                filtered_signatures,
                skipped_inline,
            )

        return attachments_info

    @staticmethod
    def _sanitize_attachment_filename(filename: str | None, fallback: str) -> str:
        """
        Prevent path traversal and control characters in attachment filenames.
        Returns a safe filename or a fallback value when the provided name is empty.
        """
        if not filename:
            return fallback
        name = os.path.basename(str(filename).strip())
        name = name.replace("\\", "_").replace("/", "_")
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        name = name.strip("._")
        return name or fallback

    def _get_header(self, message: Any, header_name: str) -> str | None:
        """
        Extract specific header from message transport headers
        """
        try:
            headers = self._get_transport_headers_text(message)
            if headers:
                # Parse headers - handle multi-line headers (continuation lines start with whitespace)
                current_header = None
                current_value = []
                for line in headers.split("\n"):
                    if line.startswith((" ", "\t")) and current_header:
                        # Continuation of previous header
                        current_value.append(line.strip())
                    elif ":" in line:
                        # New header - check if we found what we're looking for
                        if (
                            current_header
                            and current_header.lower() == header_name.lower()
                        ):
                            value = " ".join(current_value)
                            if value.startswith("<") and value.endswith(">"):
                                value = value[1:-1]
                            return value
                        # Start new header
                        colon_idx = line.index(":")
                        current_header = line[:colon_idx].strip()
                        current_value = [line[colon_idx + 1 :].strip()]
                # Check last header
                if current_header and current_header.lower() == header_name.lower():
                    value = " ".join(current_value)
                    if value.startswith("<") and value.endswith(">"):
                        value = value[1:-1]
                    return value
        except (AttributeError, ValueError, TypeError) as e:
            logger.debug(f"Could not extract header {header_name}: {e}")
        return None

    def _index_to_opensearch(
        self, email_message: EmailMessage, email_data: dict[str, Any], content: str
    ) -> None:
        """Index email to OpenSearch for full-text search"""
        # cspell:ignore opensearch
        if not self.opensearch:
            return

        attachments_val = email_data.get("attachments", [])
        doc = {
            "id": f"email_{email_message.id}",
            "type": "email",
            "case_id": str(email_message.case_id) if email_message.case_id else None,
            "project_id": (
                str(email_message.project_id) if email_message.project_id else None
            ),
            "pst_file_id": str(email_message.pst_file_id),
            "thread_id": getattr(email_message, "thread_id", None),
            "message_id": email_data["message_id"],
            "in_reply_to": email_data["in_reply_to"],
            "from": email_data["from"],
            "to": email_data["to"],
            "cc": email_data["cc"],
            "subject": email_data["subject"],
            "date": email_data["date"].isoformat() if email_data["date"] else None,
            "content": content[:10000] if content else "",
            "folder_path": email_data["folder_path"],
            "has_attachments": email_data["has_attachments"],
            "attachments_count": len(attachments_val),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

        index_name = "correspondence"
        try:
            if not self.opensearch.indices.exists(index=index_name):  # type: ignore
                self.opensearch.indices.create(  # type: ignore
                    index=index_name,
                    body={
                        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                        "mappings": {
                            "properties": {
                                "date": {"type": "date"},
                                "content": {"type": "text"},
                                "subject": {"type": "text"},
                                "from": {"type": "keyword"},
                                "to": {"type": "keyword"},
                            }
                        },
                    },
                )

            self.opensearch.index(  # type: ignore
                index=index_name,
                body=doc,
                id=f"email_{email_message.id}",
                refresh=False,
            )
        except Exception as e:
            # OpenSearch indexing must never break PST extraction; treat as best-effort.
            logger.warning("Error indexing email to OpenSearch (non-fatal): %s", e)

    def _build_thread_relationships(
        self,
        case_id: UUID | str | None,
        project_id: UUID | str | None,
        *,
        pst_file_id: UUID | str | None = None,
    ) -> ThreadingStats:
        """Build deterministic email thread relationships with evidence."""
        logger.info(
            "Building thread relationships for case_id=%s, project_id=%s, pst_file_id=%s",
            case_id,
            project_id,
            pst_file_id,
        )
        stats = build_email_threads(
            self.db,
            case_id=case_id,
            project_id=project_id,
            pst_file_id=pst_file_id,
            run_id="pst_processor",
        )
        logger.info(
            "Threading complete: threads=%d links=%d",
            stats.threads_identified,
            stats.links_created,
        )
        # Free memory retained during ingest
        self.threads_map = {}
        return stats

    @staticmethod
    def _decode_conversation_index(
        conv_index_hex: str | None,
    ) -> tuple[str | None, int]:
        """Return (root_hash, depth) from Outlook Conversation-Index; tolerant to malformed data."""
        if not conv_index_hex:
            return None, 0
        try:
            data = bytes.fromhex(conv_index_hex)
            if len(data) < 22:
                return None, 0
            root = data[:22].hex()
            depth = max((len(data) - 22) // 5, 0)
            return root, depth
        except (ValueError, TypeError):
            return None, 0

    @staticmethod
    def _participants_set(email_message: EmailMessage) -> set[str]:
        """Lower-cased sender/recipient set for heuristic matching."""
        participants: set[str] = set()
        try:
            sender = (getattr(email_message, "sender_email", None) or "").lower()
            if sender:
                participants.add(sender)
            for field in ("to", "cc", "bcc"):
                vals = getattr(email_message, f"recipients_{field}", None)
                if vals:
                    for v in vals:
                        if v:
                            participants.add(str(v).lower())
        except Exception:
            pass
        return participants

    def _extract_sender_email(
        self,
        message: Any,
        *,
        transport_headers_text: str | None = None,
        header_map: dict[str, list[str]] | None = None,
    ) -> str | None:
        """Best-effort sender email extraction.

        Prefer pypff sender helper methods/fields when available; fall back to transport headers.
        Returns a single email address (lower-cased) or None.
        """

        def _first_email(raw: Any) -> str | None:
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            text = str(raw)
            parsed = [addr.strip() for _, addr in getaddresses([text]) if addr]
            for addr in parsed:
                if "@" in addr:
                    return addr.strip().lower()
            # Fallback: regex search
            match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
            return match.group(0).lower() if match else None

        if not message:
            return None

        # Most reliable: explicit pypff accessor
        candidate = self._safe_get_attr(message, "get_sender_email_address", None)
        email = _first_email(candidate)
        if email:
            return email

        # Common attribute names
        for attr in ("sender_email_address", "sender_email"):
            email = _first_email(self._safe_get_attr(message, attr, None))
            if email:
                return email

        # Fall back to headers (avoid re-decoding if caller already has them)
        try:
            from_header = None
            if header_map is not None:
                vals = header_map.get("from", [])
                from_header = vals[0] if vals else None
            if not from_header and transport_headers_text:
                # Fast regex for common case
                match = re.search(
                    r"(?im)^From:\s*(?:.*?<)?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
                    transport_headers_text,
                )
                if match:
                    return match.group(1).strip().lower()
            if from_header:
                parsed = [
                    addr.strip() for _, addr in getaddresses([from_header]) if addr
                ]
                for addr in parsed:
                    if "@" in addr:
                        return addr.strip().lower()
        except Exception:
            pass

        return self._extract_email_from_headers(message)

    def _extract_email_from_headers(self, message: Any) -> str | None:
        """
        Extract email address from RFC 2822 transport headers
        pypff doesn't expose direct .sender_email_address - parse from headers
        """
        try:
            if not message:
                return None
            from_header = self._get_header(message, "From")
            if from_header:
                parsed = [
                    addr.strip() for _, addr in getaddresses([from_header]) if addr
                ]
                for addr in parsed:
                    if "@" in addr:
                        return addr.strip().lower()

            headers_str = self._get_transport_headers_text(message)
            if not headers_str:
                return None

            # Fallback: search for a From: line then a raw email anywhere
            from_match = re.search(
                r"(?im)^From:\s*(?:.*?<)?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
                headers_str,
            )
            if from_match:
                return from_match.group(1).strip().lower()

            any_match = re.search(
                r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", headers_str
            )
            return any_match.group(0).lower() if any_match else None
        except (AttributeError, TypeError, re.error) as e:
            logger.debug("Could not extract email from headers: %s", str(e))
            return None
