"""
FORENSIC-GRADE PST PROCESSOR
Enterprise PST extraction for dispute intelligence and legal discovery

This is the core differentiation - exceptional PST parsing with forensic integrity
"""

import pypff  # type: ignore[import-not-found]
import hashlib
import uuid
import logging
import tempfile
import os
import re
import shutil
from pathlib import Path
from typing import Any
from email.utils import parseaddr, getaddresses
from sqlalchemy.orm import Session
from sqlalchemy import func
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import (
    PSTFile,
    EmailMessage,
    EmailAttachment,
    Stakeholder,
    Keyword,
    MessageRaw,
    MessageOccurrence,
    MessageDerived,
)
from .email_threading import build_email_threads, ThreadingStats
from .email_dedupe import dedupe_emails
from .storage import put_object, download_file_streaming
from .config import settings
from .search import index_email_in_opensearch
from .email_normalizer import (
    NORMALIZER_RULESET_HASH,
    NORMALIZER_VERSION,
    build_content_hash,
    clean_body_text,
    strip_footer_noise,
)
from .ai_spam_filter import classify_email_ai_sync
from .project_scoping import ScopeMatcher, build_scope_matcher

try:
    from .email_normalizer import build_source_hash
except (ImportError, AttributeError):

    def build_source_hash(payload: dict[str, object]) -> str:
        serialized = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


from .tasks import celery_app  # Import Celery app for task registration

import json
import time

logger = logging.getLogger(__name__)
_AGENT_LOG_ENABLED = bool(getattr(settings, "PST_AGENT_LOG_ENABLED", False))


# region agent log helper
def agent_log(
    hypothesis_id: str, message: str, data: dict = None, run_id: str = "run1"
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
        "location": "pst_forensic_processor.py",
        "message": message,
        "data": data or {},
        "sessionId": "debug-session",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    # Try local file first (preferred)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
            return
    except Exception:
        pass
    # Fallback: send to ingest server so it writes to the log file
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


class ForensicPSTProcessor:
    """
    Forensic-grade PST processor - our USP

    Key Features:
    - Preserves PST file immutability (no modifications)
    - Extracts complete forensic metadata (offsets, paths, headers)
    - Perfect email threading using multiple algorithms
    - Intelligent stakeholder/keyword auto-tagging
    - Attachment extraction with S3 storage
    - OpenSearch indexing for full-text search
    - Handles 50GB+ PST files with chunked processing
    """

    def __init__(self, db: Session):
        self.db = db
        self.processed_count = 0
        self.total_count = 0
        self.scope_matcher: ScopeMatcher | None = None
        self.attachment_hashes = {}  # For deduplication
        self.ingest_run_id: str | None = None
        self._keyword_plain_terms_cache: dict[str, list[str]] = {}
        self._keyword_regex_terms_cache: dict[str, list[str]] = {}
        self._keyword_regex_cache: dict[tuple[str, str], re.Pattern[str]] = {}
        self._invalid_keyword_regex: set[tuple[str, str]] = set()
        cpu_based_default = max(8, (os.cpu_count() or 4) * 4)
        max_workers = (
            getattr(settings, "PST_UPLOAD_WORKERS", cpu_based_default)
            or cpu_based_default
        )
        max_workers = min(max_workers, 64)
        self.upload_executor = ThreadPoolExecutor(
            max_workers=max_workers
        )  # Parallel uploads
        self.upload_futures = []
        self.attach_bucket = (
            getattr(settings, "S3_ATTACHMENTS_BUCKET", None) or settings.S3_BUCKET
        )
        self.pst_bucket_fallback = (
            getattr(settings, "S3_PST_BUCKET", None) or settings.S3_BUCKET
        )

    def _strip_footer_noise(self, text: str | None) -> str:
        """
        Remove boilerplates/disclaimers/banners while leaving the message content intact.
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

    def _stream_pst_to_temp(self, s3_bucket: str, s3_key: str) -> str:
        temp_dir = getattr(settings, "PST_TEMP_DIR", None) or None
        if temp_dir:
            try:
                os.makedirs(temp_dir, exist_ok=True)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to create PST_TEMP_DIR={temp_dir}: {e}"
                ) from e

        # Preflight: best-effort free-space check
        try:
            usage = shutil.disk_usage(temp_dir or tempfile.gettempdir())
            free_bytes = int(usage.free)
            # Require at least 2GB free for safety; large PSTs are much larger and will fail anyway.
            if free_bytes < 2 * 1024 * 1024 * 1024:
                raise RuntimeError(
                    "Insufficient temp disk space for PST download. "
                    f"Free {free_bytes / (1024**3):.2f} GB in {(temp_dir or tempfile.gettempdir())}. "
                    "Set PST_TEMP_DIR to a larger writable volume."
                )
        except Exception as e:
            logger.error("PST temp disk preflight failed: %s", e)
            raise

        tmp = tempfile.NamedTemporaryFile(suffix=".pst", delete=False, dir=temp_dir)
        try:
            logger.info("Streaming PST from s3://%s/%s", s3_bucket, s3_key)
            download_file_streaming(s3_bucket or self.pst_bucket_fallback, s3_key, tmp)
            tmp.flush()
            return tmp.name
        except Exception as e:
            logger.error(f"Failed to stream PST: {e}")
            tmp.close()
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
            raise

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

    def _process_pst_path(
        self, pst_path: str, pst_file: PSTFile, stats: dict[str, Any]
    ) -> None:
        pst = pypff.file()
        # region agent log H2 pst open
        try:
            pst.open(pst_path)
            agent_log("H2", "PST opened successfully with pypff", {"path": pst_path})
            root = pst.get_root_folder()
        except Exception as e:
            agent_log(
                "H2",
                "Failed to open PST with pypff",
                {"path": pst_path, "error": str(e)},
            )
            raise
        # endregion agent log H2 pst open

        # Optimization: Skip pre-count if configured (default is False in settings)
        if getattr(settings, "PST_PRECOUNT_MESSAGES", False):
            self.total_count = self._count_emails_recursive(root)
            # region agent log H3 total count
            agent_log("H3", "Total emails counted in PST", {"total": self.total_count})
            # endregion agent log H3 total count
            pst_file.total_emails = self.total_count
            self.db.commit()
            logger.info("PST contains %s total emails", self.total_count)
        else:
            self.total_count = 0
            logger.info("Skipping PST pre-count for performance")

        stakeholders, keywords = self._load_tagging_assets(pst_file)

        # Initialize batch buffer
        self.batch_buffer = []
        self.BATCH_SIZE = getattr(settings, "PST_BATCH_COMMIT_SIZE", 2500)

        try:
            self._process_folder_recursive(
                root, pst_file, stakeholders, keywords, stats
            )

            # Commit any remaining items in buffer
            if self.batch_buffer:
                self.db.bulk_save_objects(self.batch_buffer)
                self.db.commit()
                self.batch_buffer = []
        except Exception as e:
            # If error occurs, try to save what we have so far
            if self.batch_buffer:
                try:
                    self.db.bulk_save_objects(self.batch_buffer)
                    self.db.commit()
                except Exception as save_err:
                    logger.error(
                        f"Failed to save remaining buffer on error: {save_err}"
                    )
            raise e

        pst.close()

        # Wait for any pending attachment uploads
        if self.upload_futures:
            logger.info(f"Waiting for {len(self.upload_futures)} attachment uploads...")
            for future in as_completed(self.upload_futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Async upload failed: {e}")
                    stats["errors"].append(f"Async upload failed: {str(e)}")
            logger.info("All attachment uploads completed")
            self.upload_futures = []

        entity_id = pst_file.case_id or pst_file.project_id
        if entity_id:
            thread_stats = self._build_email_threads(
                str(entity_id), is_project=bool(pst_file.project_id)
            )
            stats["threads_identified"] = thread_stats.threads_identified

            dedupe_stats = dedupe_emails(
                self.db,
                case_id=None if pst_file.project_id else pst_file.case_id,
                project_id=pst_file.project_id,
                run_id="pst_forensic",
            )
            stats["dedupe_duplicates"] = dedupe_stats.duplicates_found

    def process_pst_file(
        self, pst_file_id: str, s3_bucket: str, s3_key: str
    ) -> dict[str, Any]:
        """
        Main entry point for PST processing

        Returns statistics about extraction
        """
        logger.info("Starting forensic PST processing for file_id={pst_file_id}")

        # Get PST file record
        pst_file = self.db.query(PSTFile).filter_by(id=pst_file_id).first()
        if not pst_file:
            raise ValueError("PST file {pst_file_id} not found")

        try:
            self.scope_matcher = build_scope_matcher(
                self.db, case_id=pst_file.case_id, project_id=pst_file.project_id
            )
        except Exception as exc:
            logger.warning("Failed to build scope matcher (continuing): %s", exc)
            self.scope_matcher = None

        # Update status
        pst_file.processing_status = "processing"
        pst_file.processing_started_at = func.now()
        self.db.commit()

        stats = {
            "total_emails": 0,
            "total_attachments": 0,
            "unique_attachments": 0,
            "threads_identified": 0,
            "stakeholders_matched": 0,
            "keywords_matched": 0,
            "errors": [],
        }

        self.ingest_run_id = f"pst_forensic:{pst_file_id}:{uuid.uuid4().hex}"

        pst_path = None
        try:
            pst_path = self._stream_pst_to_temp(s3_bucket, s3_key)
            # region agent log H1 pst streamed
            if pst_path:
                size = os.path.getsize(pst_path)
                agent_log(
                    "H1",
                    "PST file streamed from S3",
                    {
                        "path": pst_path,
                        "size_bytes": size,
                        "s3_bucket": s3_bucket,
                        "s3_key": s3_key,
                    },
                )
            else:
                agent_log("H1", "PST stream failed, path is None")
            # endregion agent log H1 pst streamed
            self._process_pst_path(pst_path, pst_file, stats)

            pst_file.processing_status = "completed"
            pst_file.processing_completed_at = func.now()
            pst_file.processed_emails = self.processed_count
            stats["total_emails"] = self.processed_count
            self.db.commit()

            logger.info("✓ PST processing complete: %s", stats)

            # Trigger background tasks after successful completion
            try:
                from .tasks import (
                    index_project_emails_semantic,
                    index_case_emails_semantic,
                    apply_spam_filter_batch,
                )

                if pst_file.project_id:
                    logger.info(
                        f"Queueing semantic indexing for project {pst_file.project_id}"
                    )
                    index_project_emails_semantic.delay(str(pst_file.project_id))
                    logger.info(
                        f"Queueing spam filter for project {pst_file.project_id}"
                    )
                    apply_spam_filter_batch.delay(project_id=str(pst_file.project_id))
                elif pst_file.case_id:
                    logger.info(
                        f"Queueing semantic indexing for case {pst_file.case_id}"
                    )
                    index_case_emails_semantic.delay(str(pst_file.case_id))
                    logger.info(f"Queueing spam filter for case {pst_file.case_id}")
                    apply_spam_filter_batch.delay(case_id=str(pst_file.case_id))
            except Exception as task_error:
                logger.warning(f"Failed to queue post-processing tasks: {task_error}")

        except Exception as e:
            logger.error(f"Error processing PST: {e}", exc_info=True)
            pst_file.processing_status = "failed"
            pst_file.error_message = str(e)
            self.db.commit()
            stats["errors"].append(str(e))
            raise
        finally:
            if pst_path and os.path.exists(pst_path):
                os.unlink(pst_path)

        return stats

    def _count_emails_recursive(self, folder) -> int:
        """Count total emails in folder tree"""
        count = folder.get_number_of_sub_messages()
        for i in range(folder.get_number_of_sub_folders()):
            sub_folder = folder.get_sub_folder(i)
            count += self._count_emails_recursive(sub_folder)
        return count

    def _process_folder_recursive(
        self,
        folder: Any,
        pst_file: PSTFile,
        stakeholders: list[Stakeholder],
        keywords: list[Keyword],
        stats: dict[str, Any],
        folder_path: str = "Root",
    ) -> None:
        """Process all emails in folder and subfolders"""

        # Process messages in current folder
        num_messages = folder.get_number_of_sub_messages()
        num_sub_folders = folder.get_number_of_sub_folders()
        # region agent log H3 folder start
        agent_log(
            "H3",
            "Starting to process folder",
            {
                "folder_path": folder_path,
                "num_messages": num_messages,
                "num_sub_folders": num_sub_folders,
            },
        )
        # endregion agent log H3 folder start
        processed_messages = 0
        for i in range(num_messages):
            try:
                message = folder.get_sub_message(i)
                self._extract_email_message(
                    message,
                    pst_file,
                    folder_path,
                    i,  # Message offset/index
                    stakeholders,
                    keywords,
                    stats,
                )
                self.processed_count += 1
                processed_messages += 1

                # Batch commit logic
                if len(self.batch_buffer) >= self.BATCH_SIZE:
                    self.db.bulk_save_objects(self.batch_buffer)
                    self.db.commit()
                    self.batch_buffer = []

                    # Update progress
                    pst_file.processed_emails = self.processed_count
                    self.db.commit()  # Commit the progress update

                    total_str = f"/{self.total_count}" if self.total_count > 0 else ""
                    logger.info(f"Progress: {self.processed_count}{total_str} emails")
            except Exception as e:
                logger.error(f"Error extracting email at index {i}: {e}")
                stats["errors"].append(f"Email {i}: {str(e)}")
        # region agent log H4 messages processed
        agent_log(
            "H4",
            "Finished processing messages in folder",
            {
                "folder_path": folder_path,
                "attempted": num_messages,
                "successful": processed_messages,
            },
        )
        # endregion agent log H4 messages processed

        # Process subfolders
        num_folders = folder.get_number_of_sub_folders()
        processed_folders = 0
        for i in range(num_folders):
            try:
                sub_folder = folder.get_sub_folder(i)
                folder_name = sub_folder.get_name() or f"Folder{i}"
                sub_path = f"{folder_path}/{folder_name}"

                self._process_folder_recursive(
                    sub_folder, pst_file, stakeholders, keywords, stats, sub_path
                )
                processed_folders += 1
            except Exception as e:
                logger.error(f"Error processing subfolder {i}: {e}")
                stats["errors"].append(f"Subfolder {i}: {str(e)}")
        # region agent log H3 folder complete
        agent_log(
            "H3",
            "Finished processing folder and subfolders",
            {"folder_path": folder_path, "sub_folders_processed": processed_folders},
        )
        # endregion agent log H3 folder complete

    def _extract_email_message(
        self,
        message: Any,
        pst_file: PSTFile,
        folder_path: str,
        message_offset: int,
        stakeholders: list[Stakeholder],
        keywords: list[Keyword],
        stats: dict[str, Any],
    ) -> None:
        """Extract single email message with forensic metadata"""
        import uuid

        # Extract email headers and content
        try:
            subject = self._sanitize_text(message.get_subject() or "")
            sender_email_addr = self._sanitize_text(
                message.get_sender_email_address() or ""
            )
            sender_name = self._sanitize_text(message.get_sender_name() or "")
            folder_path = self._sanitize_text(folder_path) or folder_path

            # Get RFC822 message headers for threading
            transport_headers = (
                self._sanitize_text(message.get_transport_headers() or "") or ""
            )

            # Fallback: Exchange often returns display names, extract SMTP from headers
            if not sender_email_addr or "@" not in sender_email_addr:
                from_match = re.search(
                    r"From:.*?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
                    transport_headers,
                    re.IGNORECASE | re.DOTALL,
                )
                if from_match:
                    sender_email_addr = (
                        self._sanitize_text(from_match.group(1)) or sender_email_addr
                    )
            message_id = self._sanitize_text(
                self._extract_header(transport_headers, "Message-ID")
            )
            in_reply_to = self._sanitize_text(
                self._extract_header(transport_headers, "In-Reply-To")
            )
            references_header = self._sanitize_text(
                self._extract_header(transport_headers, "References")
            )

            # Get conversation index (Outlook-specific threading)
            conv_index = None
            try:
                conv_index_bytes = message.get_conversation_index()
                if conv_index_bytes:
                    conv_index = conv_index_bytes.hex()
            except (AttributeError, TypeError, ValueError):
                pass

            # Get recipients (with transport headers fallback for Exchange emails)
            recipients_to = self._extract_recipients(message, "to", transport_headers)
            recipients_cc = self._extract_recipients(message, "cc", transport_headers)
            recipients_bcc = self._extract_recipients(message, "bcc", transport_headers)

            # Preserve UI-friendly recipient display fallback (names-only Exchange messages are common).
            # Keep recipients_to/cc/bcc as SMTP addresses only; store raw/display in metadata for UI.
            def _recipient_display(recipient_type: str) -> str | None:
                raw_val: str | None = None
                try:
                    if recipient_type == "to":
                        raw_val = message.get_recipient_string() or None
                    elif recipient_type == "cc":
                        raw_val = message.get_cc_string() or None
                    elif recipient_type == "bcc":
                        raw_val = message.get_bcc_string() or None
                except Exception:
                    raw_val = None

                if not raw_val and transport_headers:
                    header_name = {"to": "To", "cc": "Cc", "bcc": "Bcc"}.get(
                        recipient_type
                    )
                    if header_name:
                        try:
                            raw_val = self._extract_header(
                                transport_headers, header_name
                            )
                        except Exception:
                            raw_val = raw_val

                if not raw_val:
                    return None
                cleaned = str(raw_val).replace("\x00", "").strip()
                return cleaned[:2000] if cleaned else None

            recipients_display: dict[str, str] = {}
            for _k in ("to", "cc", "bcc"):
                _v = _recipient_display(_k)
                if _v:
                    recipients_display[_k] = _v

            # Get dates
            date_sent = message.get_delivery_time()
            date_received = message.get_client_submit_time()

            ingest_run_id = (
                self.ingest_run_id or f"pst_forensic:{pst_file.id}:{uuid.uuid4().hex}"
            )
            self.ingest_run_id = ingest_run_id
            raw_payload = {
                "source_type": "pst",
                "pst_file_id": str(pst_file.id),
                "pst_s3_bucket": pst_file.s3_bucket,
                "pst_s3_key": pst_file.s3_key,
                "folder_path": folder_path,
                "message_id": message_id,
                "conversation_index": conv_index,
                "subject": subject,
                "date_sent": date_sent.isoformat() if date_sent else None,
                "message_offset": message_offset,
            }
            raw_hash = build_source_hash(raw_payload)
            storage_uri = None
            if pst_file.s3_bucket and pst_file.s3_key:
                storage_uri = f"s3://{pst_file.s3_bucket}/{pst_file.s3_key}"
            raw_id = uuid.uuid4()
            self.batch_buffer.append(
                MessageRaw(
                    id=raw_id,
                    source_hash=raw_hash,
                    storage_uri=storage_uri,
                    source_type="pst",
                    extraction_tool_version="pypff",
                    extracted_at=date_sent,
                    raw_metadata=raw_payload,
                )
            )
            self.batch_buffer.append(
                MessageOccurrence(
                    raw_id=raw_id,
                    ingest_run_id=ingest_run_id,
                    source_location=folder_path,
                    case_id=pst_file.case_id,
                    project_id=pst_file.project_id,
                )
            )

            # ============================================================
            # EARLY EXCLUSION GATE (spam + other project)
            # - Store minimal metadata only
            # - Never extract attachments/evidence for excluded emails
            # ============================================================
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
                other_project_value: str | None,
                spam_result: dict[str, Any],
                num_attachments: int,
            ) -> None:
                derived_status = "other_project" if other_project_value else "spam"
                spam_category = (
                    "other_project"
                    if other_project_value
                    else spam_result.get("category")
                )
                body_label = spam_category or derived_status

                participants = self._build_canonical_participants(
                    sender_email_addr, recipients_to, recipients_cc, recipients_bcc
                )
                derived_hash = build_content_hash(
                    None,
                    sender_email_addr,
                    sender_name,
                    recipients_to,
                    subject,
                    date_sent,
                )
                self.batch_buffer.append(
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
                        thread_id_header=message_id[:128] if message_id else None,
                        thread_confidence="header" if message_id else None,
                        qc_flags={"excluded": True, "reason": derived_status},
                    )
                )

                email_msg = EmailMessage(
                    id=uuid.uuid4(),
                    pst_file_id=pst_file.id,
                    case_id=pst_file.case_id,
                    project_id=pst_file.project_id,
                    message_id=message_id,
                    in_reply_to=in_reply_to,
                    email_references=references_header,
                    conversation_index=conv_index,
                    subject=subject,
                    sender_email=sender_email_addr,
                    sender_name=sender_name,
                    recipients_to=recipients_to or None,
                    recipients_cc=recipients_cc or None,
                    recipients_bcc=recipients_bcc or None,
                    date_sent=date_sent,
                    date_received=date_received,
                    body_text=None,
                    body_html=None,
                    body_text_clean=None,
                    body_preview=f"[EXCLUDED: {body_label}]",
                    has_attachments=num_attachments > 0,
                    importance=None,
                    pst_message_path=folder_path,
                    meta={
                        "normalizer_version": NORMALIZER_VERSION,
                        "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
                        "recipients_display": recipients_display or None,
                        "status": derived_status,
                        "excluded": True,
                        "is_hidden": True,
                        "is_spam": bool(spam_result.get("is_spam")),
                        "spam_score": int(spam_result.get("score") or 0),
                        "spam_reasons": [spam_category] if spam_category else [],
                        "other_project": other_project_value,
                        "spam": {
                            "is_spam": bool(spam_result.get("is_spam")),
                            "score": int(spam_result.get("score") or 0),
                            "category": spam_category,
                            "is_hidden": True,
                            "status_set_by": "spam_filter_ingest",
                            "applied_status": derived_status,
                        },
                        "attachments_skipped": num_attachments > 0,
                        "attachments_skipped_reason": derived_status,
                    },
                )
                self.batch_buffer.append(email_msg)

            other_project_label = _detect_other_project()
            spam_result = classify_email_ai_sync(
                subject=subject or "",
                sender=sender_email_addr or sender_name or "",
                body_preview="",
                db=self.db,
            )

            # Use AI detection for generic 'other projects' if ScopeMatcher missed it
            if not other_project_label and spam_result.get("extracted_entity"):
                other_project_label = spam_result.get("extracted_entity")

            # Only short-circuit ingestion for *hidden* spam (high-confidence) and other-project matches.
            # Medium/low-confidence "spam" categories (e.g. out-of-office) should still be ingested so
            # evidence/attachments aren't lost.
            if (
                bool(spam_result.get("is_spam")) and bool(spam_result.get("is_hidden"))
            ) or other_project_label:
                num_attachments = 0
                try:
                    num_attachments = int(message.get_number_of_attachments() or 0)
                except Exception:
                    num_attachments = 0

                _buffer_excluded_email(
                    other_project_label, spam_result, num_attachments
                )
                return

            # Get body text and HTML
            body_text = self._sanitize_text(message.get_plain_text_body() or "") or ""
            body_html = self._sanitize_text(message.get_html_body() or "") or ""

            # Get importance/priority
            importance = "normal"
            try:
                priority = message.get_priority()
                if priority == 1:
                    importance = "high"
                elif priority == 3:
                    importance = "low"
            except (AttributeError, TypeError, ValueError):
                pass

            # Check for attachments
            num_attachments = message.get_number_of_attachments()
            has_attachments = num_attachments > 0
            # region agent log H5 attachments start
            agent_log(
                "H5",
                "Message attachments check",
                {
                    "message_offset": message_offset,
                    "folder_path": folder_path,
                    "num_attachments": num_attachments,
                },
            )
            # endregion agent log H5 attachments start

            # Auto-tag: Match stakeholders and keywords
            matched_stakeholders = self._match_stakeholders(
                sender_email_addr,
                sender_name,
                recipients_to + recipients_cc,
                stakeholders,
            )

            matched_keywords = self._match_keywords(subject, body_text, keywords)

            if matched_stakeholders:
                stats["stakeholders_matched"] += 1
            if matched_keywords:
                stats["keywords_matched"] += 1

            # Build canonical body (top-message only, quotes/signatures stripped)
            # For performance: Only create preview, skip HTML parsing during ingestion
            canonical_body = ""

            # Helper: Check if text is mostly boilerplate (CAUTION banners, signatures, etc.)
            def _is_mostly_boilerplate_text(text: str) -> bool:
                """Heuristic to detect if text is mostly external-email banner/disclaimer."""
                if not text or len(text) < 20:
                    return True
                text_stripped = re.sub(r"[^0-9A-Za-z]+", "", text)
                if len(text_stripped) < 30:
                    return True
                text_lower = text.lower()
                boilerplate_phrases = [
                    "external email",
                    "caution",
                    "do not click",
                    "don't click",
                    "unless you recognise",
                    "unless you recognize",
                    "expected and known to be safe",
                    "message originated outside",
                    "originated from outside",
                    "disclaimer",
                ]
                phrase_count = sum(1 for p in boilerplate_phrases if p in text_lower)
                # If 2+ boilerplate phrases and text is short, it's boilerplate
                if phrase_count >= 2 and len(text_stripped) < 200:
                    return True
                # If the text is primarily the CAUTION banner
                if (
                    "external email" in text_lower
                    and phrase_count >= 1
                    and len(text_stripped) < 250
                ):
                    return True
                return False

            # Extract text from HTML if needed
            html_as_text = None
            if body_html:
                html_as_text = re.sub(
                    r"<style[^>]*>.*?</style>",
                    "",
                    body_html,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                html_as_text = re.sub(r"<[^>]+>", " ", html_as_text)
                html_as_text = re.sub(r"\s+", " ", html_as_text).strip()

            # Choose best source: prefer body_text unless it's mostly boilerplate
            if body_text and not _is_mostly_boilerplate_text(body_text):
                canonical_body = body_text
                # Quick split on reply markers
                try:
                    reply_split_pattern = r"(?mi)^On .+ wrote:|^From:\s|^Sent:\s|^-----Original Message-----"
                    parts = re.split(reply_split_pattern, canonical_body, maxsplit=1)
                    canonical_body = parts[0] if parts else canonical_body
                    canonical_body = re.sub(r"\s+", " ", canonical_body).strip()
                except re.error:
                    pass
            elif html_as_text:
                # Use HTML-derived text (body_text was empty or boilerplate)
                canonical_body = html_as_text
                # Also split replies from HTML-derived text
                try:
                    reply_split_pattern = r"(?mi)^On .+ wrote:|^From:\s|^Sent:\s|^-----Original Message-----"
                    parts = re.split(reply_split_pattern, canonical_body, maxsplit=1)
                    canonical_body = parts[0] if parts else canonical_body
                    canonical_body = re.sub(r"\s+", " ", canonical_body).strip()
                except re.error:
                    pass
            elif body_text:
                # Fallback: use body_text even if boilerplate (better than nothing)
                canonical_body = body_text

            body_text_clean = clean_body_text(canonical_body)
            if body_text_clean is not None:
                canonical_body = body_text_clean

            canonical_body_for_hash = (
                re.sub(r"\s+", " ", canonical_body).strip() if canonical_body else ""
            )
            scope_preview = (
                canonical_body_for_hash[:4000] if canonical_body_for_hash else None
            )
            other_project_label = _detect_other_project(scope_preview)
            if other_project_label:
                _buffer_excluded_email(
                    other_project_label, spam_result, num_attachments
                )
                return

            content_hash = build_content_hash(
                canonical_body_for_hash,
                sender_email_addr,
                sender_name,
                recipients_to,
                subject,
                date_sent,
            )

            participants = self._build_canonical_participants(
                sender_email_addr, recipients_to, recipients_cc, recipients_bcc
            )
            preview_text = canonical_body.strip() if canonical_body else ""
            self.batch_buffer.append(
                MessageDerived(
                    raw_id=raw_id,
                    normalizer_version=NORMALIZER_VERSION,
                    normalizer_ruleset_hash=NORMALIZER_RULESET_HASH,
                    parser_version="pypff",
                    canonical_subject=subject,
                    canonical_participants=participants,
                    canonical_body_preview=(
                        preview_text[:8000] if preview_text else None
                    ),
                    canonical_body_full=None,
                    banner_stripped_body=canonical_body or None,
                    content_hash_phase1=content_hash,
                    thread_id_header=message_id[:128] if message_id else None,
                    thread_confidence="header" if message_id else None,
                )
            )

            # Storage optimization: Large emails go to S3
            body_preview = None
            body_full_s3_key = None
            BODY_SIZE_LIMIT = 10 * 1024  # 10KB limit

            if canonical_body and len(canonical_body) > BODY_SIZE_LIMIT:
                # Store full body in S3
                body_preview = canonical_body[:BODY_SIZE_LIMIT]
                # Support both projects and cases
                if pst_file.project_id:
                    body_full_s3_key = f"project_{pst_file.project_id}/email_bodies/{message_id or message_offset}.txt"
                elif pst_file.case_id:
                    body_full_s3_key = f"case_{pst_file.case_id}/email_bodies/{message_id or message_offset}.txt"
                else:
                    body_full_s3_key = (
                        f"email_bodies/{message_id or message_offset}.txt"
                    )
                try:
                    put_object(
                        body_full_s3_key,
                        canonical_body.encode("utf-8"),
                        "text/plain; charset=utf-8",
                        bucket=self.attach_bucket,
                    )
                    # region agent log H9 body offload success
                    agent_log(
                        "H9",
                        "Body offloaded to S3",
                        {
                            "body_len": len(canonical_body),
                            "body_preview_len": len(body_preview),
                            "s3_key": body_full_s3_key,
                            "project_id": (
                                str(pst_file.project_id)
                                if pst_file.project_id
                                else None
                            ),
                            "case_id": (
                                str(pst_file.case_id) if pst_file.case_id else None
                            ),
                        },
                        run_id="pre-fix",
                    )
                    # endregion agent log H9 body offload success
                    canonical_body_to_store = None
                except Exception as e:
                    # region agent log H9 body offload failure
                    agent_log(
                        "H9",
                        "Body offload failed, keeping inline",
                        {
                            "body_len": len(canonical_body),
                            "s3_key": body_full_s3_key,
                            "error": str(e),
                        },
                        run_id="pre-fix",
                    )
                    # endregion agent log H9 body offload failure
                    logger.warning(f"Failed to store body in S3: {e}")
                    canonical_body_to_store = canonical_body
            else:
                canonical_body_to_store = canonical_body

            # Generate ID locally for batch processing
            import uuid

            email_id = uuid.uuid4()

            # Create email message record
            email_msg = EmailMessage(
                id=email_id,
                pst_file_id=pst_file.id,
                case_id=pst_file.case_id,
                # Threading metadata
                message_id=message_id,
                in_reply_to=in_reply_to,
                email_references=references_header,
                conversation_index=conv_index,
                # Forensic data
                pst_message_offset=message_offset,
                pst_message_path=folder_path,
                # Email content
                subject=subject,
                sender_email=sender_email_addr,
                sender_name=sender_name,
                recipients_to=recipients_to,
                recipients_cc=recipients_cc,
                recipients_bcc=recipients_bcc,
                date_sent=date_sent,
                date_received=date_received,
                body_text=canonical_body_to_store,  # Store only the top message, not the full thread
                body_html=(
                    body_html[:20000] if body_html else None
                ),  # Limit HTML to 20KB
                body_text_clean=body_text_clean or None,
                content_hash=content_hash,
                body_preview=body_preview,
                body_full_s3_key=body_full_s3_key,
                # Flags
                has_attachments=has_attachments,
                importance=importance,
                # Tagging
                matched_stakeholders=[str(s.id) for s in matched_stakeholders],
                matched_keywords=[str(k.id) for k in matched_keywords],
                meta={
                    "normalizer_version": NORMALIZER_VERSION,
                    "normalizer_ruleset_hash": NORMALIZER_RULESET_HASH,
                    "recipients_display": recipients_display or None,
                },
            )

            # Add to batch buffer instead of immediate commit
            self.batch_buffer.append(email_msg)

            # Extract attachments
            if has_attachments:
                processed_attach = 0
                for i in range(num_attachments):
                    try:
                        attachment = message.get_attachment(i)
                        self._extract_attachment(attachment, email_msg, stats)
                        processed_attach += 1
                    except Exception as e:
                        logger.error(f"Error extracting attachment {i}: {e}")
                        stats["errors"].append(f"Attachment {i}: {str(e)}")
                # region agent log H5 attachments complete
                agent_log(
                    "H5",
                    "Finished extracting attachments for message",
                    {
                        "message_offset": message_offset,
                        "attempted": num_attachments,
                        "successful": processed_attach,
                    },
                )
                # endregion agent log H5 attachments complete

            # Skip OpenSearch indexing during ingestion for speed
            # It will be handled by background task later

            stats["total_emails"] += 1

        except Exception as e:
            logger.error(f"Error extracting email message: {e}", exc_info=True)
            raise

    def _extract_attachment(
        self, attachment: Any, email_msg: EmailMessage, stats: dict[str, Any]
    ) -> None:
        """Extract email attachment to S3"""
        import uuid

        try:
            filename = (
                attachment.get_name() or "attachment_{stats['total_attachments']}"
            )
            size = attachment.get_size()

            # Get attachment data
            try:
                data = attachment.read_buffer(size) if size > 0 else b""
            except Exception as e:
                logger.error(f"Failed to read attachment: {e}")
                return

            if not data:
                logger.warning(f"Empty attachment: {filename}")
                return

            # Calculate hash for deduplication
            file_hash = hashlib.sha256(data).hexdigest()
            content_type = (
                self._detect_content_type(filename, data) or "application/octet-stream"
            )

            # Check if we've seen this attachment before
            seen_before = file_hash in self.attachment_hashes
            if seen_before:
                logger.debug(f"Duplicate attachment detected: {filename}")
                # Still create a record, but link to existing S3 file
                s3_key = self.attachment_hashes[file_hash]
                s3_bucket = self.attach_bucket
            else:
                # Upload new attachment to S3
                s3_bucket = self.attach_bucket
                # Support both projects and cases
                if email_msg.project_id:
                    s3_key = f"project_{email_msg.project_id}/attachments/{email_msg.id}/{filename}"
                elif email_msg.case_id:
                    s3_key = f"case_{email_msg.case_id}/attachments/{email_msg.id}/{filename}"
                else:
                    s3_key = f"attachments/{email_msg.id}/{filename}"

                try:
                    # Parallel upload using thread pool executor
                    future = self.upload_executor.submit(
                        put_object,
                        s3_key,
                        data,
                        content_type,
                        bucket=s3_bucket,
                    )
                    self.upload_futures.append(future)
                    self.attachment_hashes[file_hash] = s3_key
                    stats["unique_attachments"] += 1
                except Exception as e:
                    logger.error(f"Failed to queue attachment upload: {e}")
                    raise

            # region agent log H8 attachment dedup
            agent_log(
                "H8",
                "Attachment dedup decision",
                {
                    "hash_prefix": file_hash[:8],
                    "seen_before": seen_before,
                    "is_duplicate_flag": file_hash in self.attachment_hashes,
                    "size": size,
                    "content_type": content_type,
                    "s3_bucket": s3_bucket,
                    "s3_key": s3_key,
                    "unique_attachments": stats.get("unique_attachments"),
                    "total_attachments": stats.get("total_attachments"),
                },
                run_id="pre-fix",
            )
            # endregion agent log H8 attachment dedup

            # Create attachment record
            attachment_record = EmailAttachment(
                id=uuid.uuid4(),
                email_message_id=email_msg.id,
                filename=filename,
                content_type=content_type,
                file_size=size,
                s3_bucket=s3_bucket,
                s3_key=s3_key,
                has_been_ocred=False,
                attachment_hash=file_hash,
                is_inline=False,
                content_id=None,
                is_duplicate=(file_hash in self.attachment_hashes),
            )

            self.batch_buffer.append(attachment_record)
            stats["total_attachments"] += 1

        except Exception as e:
            logger.error(f"Error extracting attachment: {e}", exc_info=True)
            raise

    def _extract_header(self, headers: str, header_name: str) -> str | None:
        """Extract specific header from RFC822 headers"""
        if not headers:
            return None

        pattern = rf"{re.escape(header_name)}:\s*(.+?)(?:\r?\n(?!\s)|$)"
        match = re.search(pattern, headers, re.IGNORECASE | re.MULTILINE)
        value = match.group(1).strip() if match else None
        # region agent log H7 header parse
        value_hash = (
            hashlib.sha1(value.encode("utf-8")).hexdigest()[:8] if value else None
        )
        agent_log(
            "H7",
            "Extract header attempted",
            {
                "header_name": header_name,
                "has_headers": bool(headers),
                "headers_len": len(headers) if headers else 0,
                "value_present": bool(value),
                "value_hash": value_hash,
            },
            run_id="pre-fix",
        )
        # endregion agent log H7 header parse
        return value

    def _extract_recipients(
        self, message: Any, recipient_type: str, transport_headers: str = ""
    ) -> list[str]:
        """Extract recipients as list of email addresses (no display names)."""
        recipients: list[str] = []

        try:
            if recipient_type == "to":
                recipient_str = message.get_recipient_string() or ""
            elif recipient_type == "cc":
                recipient_str = message.get_cc_string() or ""
            elif recipient_type == "bcc":
                recipient_str = message.get_bcc_string() or ""
            else:
                recipient_str = ""

            parsed = [addr for _, addr in getaddresses([recipient_str]) if addr]
            if parsed:
                recipients.extend(parsed)
            else:
                for addr in recipient_str.split(";"):
                    addr = addr.strip()
                    if not addr:
                        continue
                    _, email = parseaddr(addr)
                    if email:
                        recipients.append(email)

            if transport_headers and not recipients:
                header_map = {"to": "To", "cc": "Cc", "bcc": "Bcc"}
                header_name = header_map.get(recipient_type)
                if header_name:
                    pattern = f"{header_name}:\\s*(.+?)(?:\\r?\\n(?!\\s)|$)"
                    match = re.search(
                        pattern, transport_headers, re.IGNORECASE | re.MULTILINE
                    )
                    if match:
                        header_value = match.group(1).strip()
                        parsed_header = [
                            addr for _, addr in getaddresses([header_value]) if addr
                        ]
                        if parsed_header:
                            recipients.extend(parsed_header)
                        else:
                            email_matches = re.findall(
                                r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+)",
                                header_value,
                            )
                            if email_matches:
                                recipients.extend(email_matches)
        except Exception as e:
            logger.warning(f"Error parsing {recipient_type} recipients: {e}")

        # Normalize to lower-case and unique
        unique_emails: list[str] = []
        seen: set[str] = set()
        for email in recipients:
            if not email:
                continue
            email_lower = email.lower()
            if email_lower not in seen:
                seen.add(email_lower)
                unique_emails.append(email_lower)
        return unique_emails

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

    def _match_stakeholders(
        self,
        sender_email: str,
        sender_name: str,
        all_recipients: list[Any],
        stakeholders: list[Stakeholder],
    ) -> list[Stakeholder]:
        """Auto-tag email with matching stakeholders"""
        matched: list[Stakeholder] = []

        # Recipient extraction has existed in multiple formats over time:
        # - list[str] (email addresses)
        # - list[dict] with keys like {"name": ..., "email": ...}
        emails: list[str] = []
        names: list[str] = []

        if sender_email:
            emails.append(sender_email)
        if sender_name:
            names.append(sender_name)

        for r in all_recipients or []:
            if isinstance(r, dict):
                e = (r.get("email") or "").strip()
                n = (r.get("name") or "").strip()
                if e:
                    emails.append(e)
                if n:
                    names.append(n)
            else:
                # Assume string-like.
                try:
                    e = str(r).strip()
                except Exception:
                    e = ""
                if e:
                    emails.append(e)

        # Normalize/unique (case-insensitive)
        all_emails: list[str] = []
        seen_emails: set[str] = set()
        for e in emails:
            if not e:
                continue
            el = e.lower()
            if el in seen_emails:
                continue
            seen_emails.add(el)
            all_emails.append(e)

        all_names = [n for n in names if n]
        all_emails_lower = {e.lower() for e in all_emails if e}

        for stakeholder in stakeholders:
            # Match by email
            if stakeholder.email and stakeholder.email.lower() in all_emails_lower:
                matched.append(stakeholder)
                continue

            # Match by email domain
            if stakeholder.email_domain:
                for email in all_emails:
                    if email and "@" in email:
                        domain = email.split("@")[1].lower()
                        if domain == stakeholder.email_domain.lower():
                            matched.append(stakeholder)
                            break

            # Fuzzy match by name
            if stakeholder.name:
                stakeholder_name_lower = stakeholder.name.lower()
                for name in all_names:
                    if name and stakeholder_name_lower in name.lower():
                        matched.append(stakeholder)
                        break

        return list(set(matched))  # Remove duplicates

    def _match_keywords(
        self, subject: str, body_text: str, keywords: list[Keyword]
    ) -> list[Keyword]:
        """Auto-tag email with matching keywords"""
        matched: list[Keyword] = []

        search_text = f"{subject or ''} {body_text or ''}"
        search_text_lower = search_text.lower()

        for keyword in keywords:
            # Build search terms (keyword + variations)
            keyword_id = str(keyword.id)
            keyword_name = (keyword.keyword_name or "").strip()
            if not keyword_name:
                continue

            # Check if any term matches
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

    def _detect_content_type(self, filename: str, data: bytes) -> str:
        """Detect file content type from filename and magic bytes"""
        # Simple content type detection based on extension
        ext = os.path.splitext(filename)[1].lower()

        content_types = {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".txt": "text/plain",
            ".csv": "text/csv",
            ".zip": "application/zip",
            ".msg": "application/vnd.ms-outlook",
        }

        return content_types.get(ext, "application/octet-stream")

    def _index_email(self, email_msg: EmailMessage):
        """Index email in OpenSearch for full-text search"""
        try:
            from .visibility import is_email_visible_meta

            # Never index excluded/hidden emails into the retrieval index.
            # (Even if the DB layer filters them, indexing them increases the risk
            # of accidental exposure via future code changes.)
            if not is_email_visible_meta(
                email_msg.meta
                if isinstance(getattr(email_msg, "meta", None), dict)
                else None
            ):
                return

            if (email_msg.subject or "").startswith("IPM."):
                return

            index_email_in_opensearch(
                email_id=str(email_msg.id),
                case_id=(
                    str(email_msg.case_id)
                    if getattr(email_msg, "case_id", None)
                    else None
                ),
                project_id=(
                    str(email_msg.project_id)
                    if getattr(email_msg, "project_id", None)
                    else None
                ),
                subject=email_msg.subject or "",
                body_text=email_msg.body_text or "",
                sender_email=email_msg.sender_email or "",
                sender_name=email_msg.sender_name or "",
                recipients=email_msg.recipients_to or [],
                thread_id=getattr(email_msg, "thread_id", None),
                thread_group_id=getattr(email_msg, "thread_group_id", None),
                message_id=getattr(email_msg, "message_id", None),
                date_sent=(
                    email_msg.date_sent.isoformat() if email_msg.date_sent else None
                ),
                has_attachments=email_msg.has_attachments,
                matched_stakeholders=email_msg.matched_stakeholders or [],
                matched_keywords=email_msg.matched_keywords or [],
                body_text_clean=getattr(email_msg, "body_text_clean", None),
                content_hash=getattr(email_msg, "content_hash", None),
            )
        except Exception as e:
            logger.warning(f"Failed to index email {email_msg.id} in OpenSearch: {e}")

    def _build_email_threads(
        self, entity_id: str, is_project: bool = False
    ) -> ThreadingStats:
        """Build deterministic email threads with evidence attribution."""
        # region agent log H6 threading start
        agent_log(
            "H6",
            "Loaded emails for threading",
            {
                "entity_id": entity_id,
                "is_project": is_project,
            },
        )
        # endregion agent log H6 threading start
        stats = build_email_threads(
            self.db,
            case_id=None if is_project else entity_id,
            project_id=entity_id if is_project else None,
            run_id="pst_forensic",
        )
        # region agent log H6 threading complete
        agent_log(
            "H6",
            "Email threads built",
            {
                "entity_id": entity_id,
                "num_threads": stats.threads_identified,
                "total_emails": stats.emails_total,
            },
        )
        # endregion agent log H6 threading complete
        logger.info(
            "Built %d email threads from %d emails",
            stats.threads_identified,
            stats.emails_total,
        )
        return stats

    def _find_thread_root(
        self, email: EmailMessage, message_id_map: dict[str, EmailMessage]
    ) -> str:
        """Find the root message of an email thread"""

        in_reply_to = email.in_reply_to
        if not in_reply_to:
            return email.message_id or str(email.id)

        current = email
        seen: set[str] = set()

        while True:
            parent_ref = current.in_reply_to
            if not parent_ref or parent_ref in seen:
                break

            seen.add(parent_ref)
            parent = message_id_map.get(parent_ref)
            if not parent:
                break

            current = parent

        return current.message_id or str(current.id)


# Helper function for Celery tasks
@celery_app.task(bind=True, name="app.process_pst_forensic")
def process_pst_forensic(
    self,
    pst_file_id: str,
    s3_bucket: str | None = None,
    s3_key: str | None = None,
    case_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Compatibility Celery task wrapper (routes to canonical PST processor).
    """
    # region agent log H11 task start early
    agent_log(
        "H11", "Forensic PST task started - sync entry", {"pst_file_id": pst_file_id}
    )
    # endregion agent log H11 task start early
    from .db import SessionLocal
    import uuid

    db = SessionLocal()
    try:
        # region agent log H19 session created
        agent_log("H19", "DB session created in task", {"pst_file_id": pst_file_id})
        # endregion agent log H19 session created
        from .pst_processor import UltimatePSTProcessor
        from .storage import s3 as s3_client

        try:
            from .opensearch_client import get_opensearch_client
        except Exception:
            get_opensearch_client = None  # type: ignore[assignment]

        opensearch_client = None
        if get_opensearch_client:
            try:
                opensearch_client = get_opensearch_client()
            except Exception:
                opensearch_client = None
        processor = UltimatePSTProcessor(
            db=db, s3_client=s3_client(), opensearch_client=opensearch_client
        )
        # Update PST record with case/project if provided
        pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
        if not pst_file:
            raise ValueError(f"PST file {pst_file_id} not found")
        if case_id:
            pst_file.case_id = uuid.UUID(case_id)
        if project_id:
            pst_file.project_id = uuid.UUID(project_id)
        if s3_bucket:
            pst_file.s3_bucket = s3_bucket
        if s3_key:
            pst_file.s3_key = s3_key
        db.commit()
        pst_s3_bucket = s3_bucket or pst_file.s3_bucket
        pst_s3_key = s3_key or pst_file.s3_key
        if not pst_s3_key:
            raise ValueError(f"PST file {pst_file_id} is missing s3_key")
        result = processor.process_pst(
            pst_s3_key=pst_s3_key,
            document_id=pst_file_id,
            case_id=str(pst_file.case_id) if pst_file.case_id else None,
            project_id=str(pst_file.project_id) if pst_file.project_id else None,
            company_id=None,
            pst_s3_bucket=pst_s3_bucket,
        )
        # region agent log H11 task success
        agent_log(
            "H11",
            "Forensic PST task completed successfully",
            {"pst_file_id": pst_file_id, "stats": result},
        )
        # endregion agent log H11 task success
        return result
    except Exception as e:
        # region agent log H11 task error
        agent_log(
            "H11",
            "Forensic PST task failed",
            {"pst_file_id": pst_file_id, "error": str(e)},
        )
        # endregion agent log H11 task error
        logger.error(f"Forensic PST task failed for {pst_file_id}: {e}", exc_info=True)
        if self.request.retries < 3:
            raise self.retry(countdown=60)
        else:
            raise
    finally:
        db.close()
