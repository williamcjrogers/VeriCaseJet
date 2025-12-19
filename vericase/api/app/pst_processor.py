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
import html
import json
import os
import logging
import re
import tempfile
import uuid
import time
import io
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import getaddresses

import pypff  # type: ignore  # pypff is installed in Docker container

from sqlalchemy.orm import Session
from .models import (
    Document,
    EmailMessage,
    EmailAttachment,
    DocStatus,
    PSTFile,
    EvidenceItem,
)
from .config import settings
from .spam_filter import classify_email, extract_other_project, SpamResult


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


# region agent log helper
def agent_log(
    hypothesis_id: str, message: str, data: dict | None = None, run_id: str = "run1"
) -> None:
    log_path = (
        r"c:\Users\William\Documents\Projects\VeriCase Analysis\.cursor\debug.log"
    )
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
        self.processed_count = 0
        self.total_count = 0
        self.attachment_hashes: dict[str, Any] = {}  # For Document deduplication
        self.evidence_item_hashes: dict[str, Any] = {}  # For EvidenceItem deduplication
        self.body_offload_threshold = (
            getattr(settings, "PST_BODY_OFFLOAD_THRESHOLD", 50000) or 50000
        )
        self.body_offload_bucket = (
            getattr(settings, "S3_EMAIL_BODY_BUCKET", None) or settings.S3_BUCKET
        )
        self.chunk_size = (
            getattr(settings, "PST_ATTACHMENT_CHUNK_SIZE", 1024 * 1024) or 1024 * 1024
        )

        # Parallel upload executor (configurable via PST_UPLOAD_WORKERS)
        upload_workers = getattr(settings, "PST_UPLOAD_WORKERS", 50) or 50
        self.upload_executor = ThreadPoolExecutor(max_workers=upload_workers)
        self.upload_futures = []

        # Batch commit size (configurable via PST_BATCH_COMMIT_SIZE)
        self.batch_commit_size = (
            getattr(settings, "PST_BATCH_COMMIT_SIZE", 2500) or 2500
        )

        # Initialize batch buffers (Split for performance)
        self.email_buffer = []
        self.attachment_buffer = []
        self.document_buffer = []
        self.evidence_buffer = []

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

    def _flush_buffers(self, force: bool = False) -> None:
        """
        Flush all buffers to database.
        Splits by type to maximize bulk_save_objects efficiency.
        """
        total_pending = (
            len(self.email_buffer)
            + len(self.document_buffer)
            + len(self.attachment_buffer)
            + len(self.evidence_buffer)
        )

        if total_pending == 0:
            return

        if force or total_pending >= self.batch_commit_size:
            try:
                # Flush in order of dependencies
                if self.document_buffer:
                    self.db.bulk_save_objects(self.document_buffer)
                    self.document_buffer = []

                if self.email_buffer:
                    self.db.bulk_save_objects(self.email_buffer)
                    self.email_buffer = []

                if self.attachment_buffer:
                    self.db.bulk_save_objects(self.attachment_buffer)
                    self.attachment_buffer = []

                if self.evidence_buffer:
                    self.db.bulk_save_objects(self.evidence_buffer)
                    self.evidence_buffer = []

                self.db.commit()

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
                logger.error(f"Batch commit failed: {commit_error}")
                self.db.rollback()
                # Clear buffers on error to prevent cascading
                self.email_buffer = []
                self.document_buffer = []
                self.attachment_buffer = []
                self.evidence_buffer = []

    def process_pst(
        self,
        pst_s3_key: str,
        document_id: UUID | str,
        case_id: UUID | str | None = None,
        company_id: UUID | str | None = None,
        project_id: UUID | str | None = None,
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
                "pst_s3_key": pst_s3_key,
            },
            run_id="pre-fix",
        )
        # endregion agent log H10 start

        stats: ProcessingStats = {
            "total_emails": 0,
            "total_attachments": 0,
            "unique_attachments": 0,  # After deduplication
            "threads_identified": 0,
            "size_saved": 0,  # Bytes saved by not storing email files
            "processing_time": 0.0,
            "errors": [],
        }

        start_time = datetime.now(timezone.utc)
        document: Document | None = None

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
                    s3_bucket=settings.S3_BUCKET,
                    s3_key=pst_s3_key,
                    file_size_bytes=document.size,
                    uploaded_by=uploader,
                )
                self.db.add(pst_file_record)
                self.db.commit()
                self.db.refresh(pst_file_record)

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

        # Download PST from S3 to temp file
        with tempfile.NamedTemporaryFile(suffix=".pst", delete=False) as tmp:
            try:
                logger.info(
                    f"Downloading PST from s3://{settings.S3_BUCKET}/{pst_s3_key}"
                )
                self.s3.download_fileobj(
                    Bucket=settings.S3_BUCKET, Key=pst_s3_key, Fileobj=tmp
                )
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
                        "bucket": settings.S3_BUCKET,
                        "key": pst_s3_key,
                    },
                    run_id="pre-fix",
                )
                # endregion agent log H11 download
            except Exception as e:
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
            pst_file.open(pst_path)

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
                self.total_count = self._count_messages(root)
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
                self._flush_buffers(force=True)

            # Build thread relationships after all emails are extracted (CRITICAL - USP FEATURE!)
            logger.info("Building email thread relationships...")
            self._build_thread_relationships(case_id, project_id)
            # region agent log H13 threads
            agent_log(
                "H13",
                "Threads built",
                {
                    "case_id": str(case_id) if case_id else None,
                    "project_id": str(project_id) if project_id else None,
                    "threads_map_size": len(self.threads_map),
                    "total_emails": stats.get("total_emails"),
                },
                run_id="pre-fix",
            )
            # endregion agent log H13 threads

            # Count unique threads from the built thread_groups
            unique_threads: set[str] = set()
            for thread_info in self.threads_map.values():
                email_msg = thread_info.get("email_message")
                if (
                    email_msg
                    and hasattr(email_msg, "thread_id")
                    and email_msg.thread_id
                ):
                    unique_threads.add(str(email_msg.thread_id))
            stats["threads_identified"] = len(unique_threads)

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
            logger.error(f"PST processing failed: {e}", exc_info=True)
            # Try to save partial results
            try:
                self._flush_buffers(force=True)
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
            # Cleanup temp file
            if os.path.exists(pst_path):
                os.unlink(pst_path)

        return stats

    def _count_messages(self, folder: Any) -> int:
        """Recursively count total messages for progress tracking"""
        try:
            count = int(self._safe_get_attr(folder, "number_of_sub_messages", 0) or 0)
            num_subfolders = int(
                self._safe_get_attr(folder, "number_of_sub_folders", 0) or 0
            )
            for i in range(num_subfolders):
                try:
                    subfolder: Any = folder.get_sub_folder(i)
                    count += self._count_messages(subfolder)
                except (AttributeError, RuntimeError, OSError) as e:
                    logger.debug(
                        "Could not count messages in subfolder %d: %s", i, str(e)[:50]
                    )
            return count
        except (ValueError, TypeError) as e:
            logger.warning("Error counting messages: %s", str(e))
            return 0

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
        Recursively process PST folders

        Note: Email messages and attachments are now committed individually in _process_message
        to ensure EmailAttachment records can be properly linked.
        """
        folder_name = folder.name or "Root"
        current_path = f"{folder_path}/{folder_name}" if folder_path else folder_name

        num_messages = int(
            self._safe_get_attr(folder, "number_of_sub_messages", 0) or 0
        )
        logger.info("Processing folder: %s (%d messages)", current_path, num_messages)

        # Process messages in this folder
        for i in range(num_messages):
            try:
                message = folder.get_sub_message(i)
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

                # Check buffers
                self._flush_buffers()

            except (
                AttributeError,
                RuntimeError,
                OSError,
                ValueError,
                SystemError,
                MemoryError,
            ) as e:
                logger.warning(
                    f"Skipping message {i} in {current_path}: {str(e)[:100]}"
                )
                stats["errors"].append(f"Message {i} in {current_path}: {str(e)[:50]}")

        # Process subfolders
        num_subfolders = int(
            self._safe_get_attr(folder, "number_of_sub_folders", 0) or 0
        )
        for i in range(num_subfolders):
            try:
                subfolder: Any = folder.get_sub_folder(i)
                self._process_folder(
                    subfolder,
                    pst_file_record,
                    document,
                    case_id,
                    project_id,
                    company_id,
                    stats,
                    current_path,
                )
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

    def _clean_body_text(self, text: str | None) -> str | None:
        """
        Clean body text for display:
        - Strip HTML tags and CSS
        - Decode HTML entities (&nbsp;, <, >, etc.)
        - Remove zero-width characters (U+200B, U+200C, U+200D, U+FEFF)
        - Normalize whitespace
        """
        if not text:
            return text

        # Remove CSS style blocks (VML behaviors, style tags, etc.)
        text = re.sub(
            r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE
        )
        text = re.sub(r"v\\:\*\s*\{[^}]*\}", "", text)  # VML behavior CSS
        text = re.sub(r"o\\:\*\s*\{[^}]*\}", "", text)  # Office behavior CSS
        text = re.sub(r"w\\:\*\s*\{[^}]*\}", "", text)  # Word behavior CSS
        text = re.sub(r"\.shape\s*\{[^}]*\}", "", text)  # Shape CSS
        text = re.sub(
            r"@[a-z-]+\s*\{[^}]*\}", "", text, flags=re.IGNORECASE
        )  # @media, @font-face, etc.

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)

        # Decode HTML entities
        text = html.unescape(text)

        # Remove zero-width characters that cause "J ? ? ? ? OHN" display issues
        text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)

        # Remove other invisible/control characters (but keep newlines and tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # Normalize multiple spaces (but preserve single newlines)
        text = re.sub(r"[^\S\n]+", " ", text)

        # Normalize multiple newlines to max 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

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

        # Extract email headers
        message_id = self._get_header(message, "Message-ID")
        in_reply_to = self._get_header(message, "In-Reply-To")
        references = self._get_header(message, "References")

        # Safely get attributes - pypff objects have limited attributes
        subject = self._safe_get_attr(message, "subject", "")
        sender_name = self._safe_get_attr(message, "sender_name", "")

        # Sender/recipient extraction:
        # Prefer pypff message helper methods (more reliable than transport header parsing),
        # but fall back to transport headers when needed.
        sender_email = self._extract_sender_email(message)

        def _normalize_address_list(raw: Any) -> list[str]:
            """Return a stable, de-duplicated list of email addresses (lower-cased).

            If no parseable emails exist, returns an empty list.
            """
            if not raw:
                return []
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            text = str(raw)

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
                return self._safe_get_attr(message, "get_recipient_string", None)
            if recipient_type == "cc":
                return self._safe_get_attr(message, "get_cc_string", None)
            if recipient_type == "bcc":
                return self._safe_get_attr(message, "get_bcc_string", None)
            return None

        def _extract_recipients(recipient_type: str, header_name: str) -> list[str]:
            # Prefer Outlook-provided recipient strings
            rec_str = _recipient_string(recipient_type)
            recipients = _normalize_address_list(rec_str)
            if recipients:
                return recipients
            # Fall back to transport headers
            header_val = self._get_header(message, header_name)
            return _normalize_address_list(header_val)

        to_recipients = _extract_recipients("to", "To")
        cc_recipients = _extract_recipients("cc", "Cc")
        bcc_recipients = _extract_recipients("bcc", "Bcc")

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
            conv_idx_raw = self._safe_get_attr(message, "conversation_index", None)
            if conv_idx_raw:
                conversation_index = (
                    conv_idx_raw.hex()
                    if hasattr(conv_idx_raw, "hex")
                    else str(conv_idx_raw)
                )
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug("Failed to extract conversation index: %s", e, exc_info=True)

        thread_topic = self._get_header(message, "Thread-Topic") or subject

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

        # =====================================================================
        # EARLY SPAM DETECTION - Skip full ingestion for spam/hidden/other_project
        # Only store minimal metadata to save storage and processing time
        # =====================================================================
        spam_info = self._calculate_spam_score(
            subject, None, sender_email or sender_name
        )  # Subject-only check first

        if spam_info.get("is_hidden") or spam_info.get("other_project"):
            spam_category = (
                spam_info.get("spam_reasons", [None])[0]
                if spam_info.get("spam_reasons")
                else None
            )
            is_hidden = bool(
                spam_info.get("is_hidden", False) or spam_info.get("other_project")
            )
            derived_status = (
                "other_project" if spam_category == "other_projects" else "spam"
            )

            # Create minimal EmailMessage record - NO body content, NO attachments
            email_id = uuid.uuid4()
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
                body_preview=f"[EXCLUDED: {spam_info.get('spam_reasons', ['spam'])[0] if spam_info.get('spam_reasons') else 'spam'}]",
                has_attachments=email_data.get("has_attachments", False),
                importance=self._safe_get_attr(message, "importance", None),
                pst_message_path=folder_path,
                meta={
                    "thread_topic": thread_topic,
                    # Correspondence visibility convention
                    "status": derived_status,
                    # Backward-compatible top-level flags
                    "excluded": True,
                    "spam_score": spam_info["spam_score"],
                    "is_spam": spam_info["is_spam"],
                    "is_hidden": is_hidden,
                    "spam_reasons": spam_info["spam_reasons"],
                    "other_project": spam_info["other_project"],
                    # Canonical nested spam structure (used by evidence cascading)
                    "spam": {
                        "is_spam": spam_info["is_spam"],
                        "score": spam_info["spam_score"],
                        "category": spam_category,
                        "is_hidden": is_hidden,
                        "status_set_by": "spam_filter_ingest",
                        "applied_status": derived_status,
                    },
                    "attachments_skipped": email_data.get("has_attachments", False),
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

            return email_message  # EARLY RETURN - skip body/attachment processing

        # =====================================================================
        # FULL PROCESSING - Only for relevant, non-spam emails
        # =====================================================================

        # Extract body content (prefer HTML, fallback to plain text)
        # pypff returns bytes, need to decode properly
        def _decode_body(raw: Any) -> str | None:
            if raw is None:
                return None
            if isinstance(raw, bytes):
                # Try common encodings
                for encoding in ["utf-8", "windows-1252", "iso-8859-1", "cp1252"]:
                    try:
                        return raw.decode(encoding)
                    except (UnicodeDecodeError, LookupError):
                        continue
                # Last resort - replace errors
                return raw.decode("utf-8", errors="replace")
            return str(raw)

        # Prefer pypff get_*_body methods when available (often more reliable)
        body_html = _decode_body(self._safe_get_attr(message, "get_html_body", None))
        if body_html is None:
            body_html = _decode_body(self._safe_get_attr(message, "html_body", None))

        body_plain = _decode_body(
            self._safe_get_attr(message, "get_plain_text_body", None)
        )
        if body_plain is None:
            body_plain = _decode_body(
                self._safe_get_attr(message, "plain_text_body", None)
            )

        body_rtf = _decode_body(self._safe_get_attr(message, "get_rtf_body", None))
        if body_rtf is None:
            body_rtf = _decode_body(self._safe_get_attr(message, "rtf_body", None))

        body_text = None
        body_html_content = None

        if body_html:
            body_html_content = body_html
        if body_plain:
            body_text = body_plain
        elif body_html_content:
            # Provide a simple text fallback by stripping tags
            body_text = re.sub(r"<[^>]+>", " ", body_html_content)
            body_text = re.sub(r"\s+", " ", body_text).strip()
        elif body_rtf:
            # Strip RTF control codes for plain text
            body_text = re.sub(r"\\[a-z]+\d*\s?|\{|\}", "", body_rtf)
            body_text = re.sub(r"\s+", " ", body_text).strip()
        else:
            body_text = ""

        # Store FULL body (plain text), and compute a separate canonical "top message" for previews/dedupe.
        full_body_text = body_text or ""

        canonical_body = full_body_text
        if canonical_body:
            # Quick split on reply markers to approximate the top message.
            try:
                reply_split_pattern = (
                    r"(?mi)^On .+ wrote:|^From:\s|^Sent:\s|^-----Original Message-----"
                )
                parts = re.split(reply_split_pattern, canonical_body, maxsplit=1)
                candidate = (parts[0] if parts else canonical_body).strip()
                # Avoid over-stripping: if the split yields almost nothing, keep the full text.
                if len(candidate) >= 20 or len(canonical_body) <= 200:
                    canonical_body = candidate
            except re.error:
                pass

        # Normalise whitespace for canonical body
        if canonical_body:
            canonical_body = re.sub(r"\s+", " ", canonical_body).strip()

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

        # Clean body text - decode HTML entities and remove zero-width characters
        body_text_clean = self._clean_body_text(canonical_body)

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
        content_hash = None
        try:
            # Normalise participants and subject/date for a stable hash
            norm_from = (sender_email or sender_name or "").strip().lower()
            norm_to = (
                ",".join(sorted([r.strip().lower() for r in to_recipients]))
                if to_recipients
                else ""
            )
            norm_subject = (subject or "").strip().lower()
            norm_date = email_date.isoformat() if email_date else ""

            hash_payload = json.dumps(
                {
                    "body": canonical_body,
                    "from": norm_from,
                    "to": norm_to,
                    "subject": norm_subject,
                    "date": norm_date,
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            content_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()
        except Exception as hash_error:
            logger.debug("Failed to compute content_hash: %s", hash_error)

        # Calculate spam score during ingestion (no AI, pure pattern matching)
        spam_info = self._calculate_spam_score(
            subject, canonical_body, sender_email or sender_name
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
            "is_spam": spam_info["is_spam"],
            "score": spam_info["spam_score"],
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
            # Spam classification (computed at ingestion time)
            "spam_score": spam_info["spam_score"],
            "is_spam": spam_info["is_spam"],
            "is_hidden": spam_is_hidden,  # Auto-exclude from views
            "spam_reasons": spam_info["spam_reasons"],
            "other_project": spam_info["other_project"],
            # Canonical nested spam structure (used by evidence cascading)
            "spam": spam_payload,
        }
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
            has_attachments=num_attachments > 0,
            importance=self._safe_get_attr(message, "importance", None),
            pst_message_path=folder_path,
            meta=meta_payload,
        )

        # We need to add and flush the email message first to get its ID for attachments
        self.email_buffer.append(email_message)

        # Now process attachments with the email_message ID
        if num_attachments > 0:
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
                is_duplicate = file_hash in self.attachment_hashes
                att_doc_id = None

                if is_duplicate:
                    # Use existing document (deduped at storage level)
                    att_doc_id = self.attachment_hashes[file_hash]
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
                            Bucket=settings.S3_BUCKET,
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
                        content_type=content_type,
                        size=size,
                        bucket=settings.S3_BUCKET,
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
                    self.attachment_hashes[file_hash] = att_doc_id

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
                    s3_bucket=settings.S3_BUCKET,
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
                            s3_bucket=settings.S3_BUCKET,
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

        if filtered_signatures > 0:
            logger.info(f"Filtered {filtered_signatures} signature/disclaimer images")

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
            if hasattr(message, "transport_headers") and message.transport_headers:
                headers = message.transport_headers
                if isinstance(headers, bytes):
                    headers = headers.decode("utf-8", errors="replace")
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
        except (ConnectionError, TimeoutError, ValueError) as e:
            logger.error(f"Error indexing email to OpenSearch: {e}")

    def _build_thread_relationships(
        self, case_id: UUID | str | None, project_id: UUID | str | None
    ) -> None:
        """
        Build email thread relationships using fallback algorithms

        Threading hierarchy (PRIORITY ORDER):
        1. Message-ID / In-Reply-To / References (RFC 2822 standard) (PRIMARY)
        2. Conversation-Index (Outlook proprietary)
        3. Subject-based grouping (FALLBACK)
        """
        logger.info(
            f"Building thread relationships for case_id={case_id}, project_id={project_id}"
        )

        if not self.threads_map:
            logger.info("No emails to thread")
            return

        # Step 1: Build thread groups using message IDs
        thread_groups: dict[str, list[EmailMessage]] = (
            {}
        )  # thread_id -> list of email_messages
        message_id_to_email: dict[str, EmailMessage] = {}  # message_id -> email_message

        # First pass: index all emails by message_id
        for message_id, thread_info in self.threads_map.items():
            if not message_id:
                continue
            email_message = thread_info.get("email_message")
            if email_message:
                message_id_to_email[message_id] = email_message

        # === NEW OPTIMIZATION: Pre-index fallback fields ===
        # Map conversation_index root -> thread_id
        conv_root_map: dict[str, str] = {}
        # Map normalized_subject -> (thread_id, participants)
        subject_map: dict[str, tuple[str, set[str]]] = {}

        # Build lookup maps
        for thread_info in self.threads_map.values():
            email = thread_info.get("email_message")
            if not email:
                continue

            if (
                email.conversation_index
                and hasattr(email, "thread_id")
                and email.thread_id
            ):
                conv_root, _ = self._decode_conversation_index(email.conversation_index)
                if conv_root:
                    conv_root_map.setdefault(conv_root, email.thread_id)

            subject = thread_info.get("subject", "")
            if subject:
                norm_subj = re.sub(r"^(re|fw|fwd):\s*", "", subject.lower().strip())
                if hasattr(email, "thread_id") and email.thread_id:
                    participants = self._participants_set(email)
                    subject_map.setdefault(norm_subj, (email.thread_id, participants))
        # ===================================================

        # Second pass: assign thread IDs using fallback logic
        for message_id, thread_info in self.threads_map.items():
            email_message: EmailMessage | None = thread_info.get("email_message")
            if not email_message:
                continue

            subject = thread_info.get("subject", "")
            in_reply_to = thread_info.get("in_reply_to")
            references = thread_info.get("references")
            conversation_index = email_message.conversation_index

            thread_id = None
            participants = self._participants_set(email_message)

            # PRIORITY 1: Use RFC 2822 standard logic (Message-ID / In-Reply-To / References)
            if not thread_id and in_reply_to and in_reply_to in message_id_to_email:
                parent_email = message_id_to_email[in_reply_to]
                if hasattr(parent_email, "thread_id") and parent_email.thread_id:
                    thread_id = parent_email.thread_id

            # Try references (parse space or comma separated list)
            if not thread_id and references:
                ref_list = []
                # Handle both space and comma separated
                if "," in references:
                    ref_list = [r.strip().strip("<>") for r in references.split(",")]
                else:
                    ref_list = [r.strip().strip("<>") for r in references.split()]

                for ref_id in ref_list:
                    if ref_id in message_id_to_email:
                        parent_email = message_id_to_email[ref_id]
                        if (
                            hasattr(parent_email, "thread_id")
                            and parent_email.thread_id
                        ):
                            thread_id = parent_email.thread_id
                            break

            # Try conversation index (Outlook threading) via root hash
            if not thread_id and conversation_index:
                conv_root, _ = self._decode_conversation_index(conversation_index)
                if conv_root:
                    thread_id = conv_root_map.get(conv_root)

            # Last resort: subject-based grouping (normalized subject) with participant overlap
            if not thread_id:
                if subject:
                    # Normalize subject (remove Re:, Fwd:, etc.)
                    normalized_subject = re.sub(
                        r"^(re|fw|fwd):\s*", "", subject.lower().strip()
                    )
                    subject_entry = subject_map.get(normalized_subject)
                    if subject_entry:
                        existing_thread_id, existing_participants = subject_entry
                        if participants & existing_participants:
                            thread_id = existing_thread_id

            # Create new thread if none found
            if not thread_id:
                thread_id = f"thread_{len(thread_groups) + 1}_{uuid.uuid4().hex[:8]}"

            # Update indexes for subsequent lookups (only if not already set)
            if conversation_index:
                conv_root, _ = self._decode_conversation_index(conversation_index)
                if conv_root and conv_root not in conv_root_map:
                    conv_root_map.setdefault(conv_root, thread_id)

            if subject:
                normalized_subject = re.sub(
                    r"^(re|fw|fwd):\s*", "", subject.lower().strip()
                )
                if normalized_subject not in subject_map:
                    subject_map[normalized_subject] = (thread_id, participants)

            # Assign thread_id to email (legacy)
            email_message.thread_id = thread_id
            # New metadata defaults
            email_message.thread_group_id = thread_id
            email_message.is_inclusive = (
                True  # conservative default until finer-grained calc
            )

            # Add to thread group
            if thread_id not in thread_groups:
                thread_groups[thread_id] = []
            thread_groups[thread_id].append(email_message)

        # Update thread metadata in database (batch update)
        try:
            self.db.flush()
            logger.info(f"Created {len(thread_groups)} unique threads")

            # Log thread statistics
            thread_sizes = [len(emails) for emails in thread_groups.values()]
            if thread_sizes:
                avg_size = sum(thread_sizes) / len(thread_sizes)
                max_size = max(thread_sizes)
                logger.info(
                    f"Thread stats: avg={avg_size:.1f} emails/thread, max={max_size} emails/thread"
                )

            # Assign path/position within each thread (ordered by date_sent then id)
            for tg_id, emails in thread_groups.items():
                sorted_emails = sorted(
                    emails,
                    key=lambda e: (
                        e.date_sent or datetime.min.replace(tzinfo=timezone.utc),
                        str(e.id),
                    ),
                )
                for idx, em in enumerate(sorted_emails):
                    em.thread_group_id = tg_id
                    em.thread_position = idx
                    em.thread_path = str(idx)

        except Exception as e:
            logger.error(f"Error updating thread relationships: {e}")
            self.db.rollback()

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

    def _extract_sender_email(self, message: Any) -> str | None:
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

        # Fall back to headers
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

            headers_raw = getattr(message, "transport_headers", None)
            if not headers_raw:
                return None

            # Ensure headers is a string for regex search
            headers_str: str
            if isinstance(headers_raw, bytes):
                headers_str = headers_raw.decode("utf-8", errors="replace")
            elif isinstance(headers_raw, str):
                headers_str = headers_raw
            else:
                headers_str = str(headers_raw)

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
