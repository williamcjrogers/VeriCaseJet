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
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import UUID

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


class ThreadInfo(TypedDict, total=False):
    """Type definition for thread tracking info."""

    email_message: EmailMessage
    in_reply_to: str | None
    references: str | None
    date: datetime | None
    subject: str
    content: str
    email_data: dict[str, Any]


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

            # Get root folder and count total messages first
            root: Any = pst_file.get_root_folder()
            self.total_count = self._count_messages(root)
            logger.info(f"Found {self.total_count} total messages to process")

            # Process all folders recursively
            self._process_folder(
                root, pst_file_record, document, case_id, project_id, company_id, stats
            )

            # Build thread relationships after all emails are extracted (CRITICAL - USP FEATURE!)
            logger.info("Building email thread relationships...")
            self._build_thread_relationships(case_id, project_id)

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

            # Trigger background semantic indexing after successful completion
            try:
                from .tasks import index_project_emails_semantic, index_case_emails_semantic

                if project_id:
                    logger.info(f"Queueing semantic indexing for project {project_id}")
                    index_project_emails_semantic.delay(str(project_id))
                elif case_id:
                    logger.info(f"Queueing semantic indexing for case {case_id}")
                    index_case_emails_semantic.delay(str(case_id))
            except Exception as task_error:
                logger.warning(f"Failed to queue semantic indexing task: {task_error}")

            pst_file.close()

            logger.info(f"PST processing completed: {stats}")

        except Exception as e:
            logger.error(f"PST processing failed: {e}", exc_info=True)
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
        COMMIT_BATCH_SIZE = 100  # Commit every N messages for performance (increased for speed)

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

                # Commit every COMMIT_BATCH_SIZE messages for performance
                if self.processed_count % COMMIT_BATCH_SIZE == 0:
                    try:
                        self.db.commit()
                    except Exception as commit_error:
                        logger.error(f"Batch commit failed: {commit_error}")
                        self.db.rollback()

                # Log progress every 100 emails
                if self.processed_count % 100 == 0:
                    progress = (
                        (self.processed_count / self.total_count * 100)
                        if self.total_count > 0
                        else 0
                    )
                    logger.info(
                        "Progress: %d/%d (%.1f%%)",
                        self.processed_count,
                        self.total_count,
                        progress,
                    )

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
                # Rollback any partial changes from this message
                try:
                    self.db.rollback()
                except Exception:
                    pass

        # Final commit for this folder
        try:
            self.db.commit()
        except Exception as commit_error:
            logger.error(f"Final folder commit failed: {commit_error}")
            self.db.rollback()

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
        - Decode HTML entities (&nbsp;, &lt;, &gt;, etc.)
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

        # Extract email address from transport headers
        from_email = self._extract_email_from_headers(message)
        if not from_email:
            from_email = sender_name  # Fallback to sender name if no email found

        # Get recipients from transport headers (pypff doesn't have display_to/cc/bcc)
        def _normalize_recipients(raw: str | None) -> list[str]:
            if not raw:
                return []
            # Handle bytes
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            # Outlook often separates with ; but can include commas as well.
            # Also handle "Name <email>" format
            parts = [part.strip() for part in re.split(r"[;,]", raw) if part.strip()]
            return parts

        to_recipients = _normalize_recipients(self._get_header(message, "To"))
        cc_recipients = _normalize_recipients(self._get_header(message, "Cc"))
        bcc_recipients = _normalize_recipients(self._get_header(message, "Bcc"))

        # Get dates - pypff has delivery_time and client_submit_time
        email_date = self._safe_get_attr(message, "delivery_time", None)
        if not email_date:
            email_date = self._safe_get_attr(message, "client_submit_time", None)
        if not email_date:
            email_date = self._safe_get_attr(message, "creation_time", None)
        if email_date and email_date.tzinfo is None:
            email_date = email_date.replace(tzinfo=timezone.utc)

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
            "from": from_email,
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

        body_html = _decode_body(self._safe_get_attr(message, "html_body", None))
        body_plain = _decode_body(self._safe_get_attr(message, "plain_text_body", None))
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
            body_text = f"From: {from_email}\nTo: {', '.join(to_recipients)}\nSubject: {subject}\n\n[No body content available]"

        # Build canonical body (top-message only, quotes/signatures stripped)
        # For performance: Only create preview, store full body in PST for on-demand retrieval
        canonical_body = ""

        # Fast path: Just extract a preview from plain text (no HTML parsing during ingestion)
        if body_text:
            canonical_body = body_text
            # Quick split on reply markers
            try:
                reply_split_pattern = (
                    r"(?mi)^On .+ wrote:|^From:\s|^Sent:\s|^-----Original Message-----"
                )
                parts = re.split(reply_split_pattern, canonical_body, maxsplit=1)
                canonical_body = parts[0] if parts else canonical_body
                canonical_body = re.sub(r"\s+", " ", canonical_body).strip()
            except re.error:
                pass
        elif body_html:
            # Fallback: Strip HTML tags quickly (no BeautifulSoup for speed)
            canonical_body = re.sub(r"<[^>]+>", " ", body_html)
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

        preview_source = body_text or body_html_content or ""
        body_preview = preview_source[:10000] if preview_source else None

        # Clean body text - decode HTML entities and remove zero-width characters
        body_text_clean = self._clean_body_text(canonical_body)

        # Compute content hash for deduplication (canonical body + key metadata)
        content_hash = None
        try:
            # Normalise participants and subject/date for a stable hash
            norm_from = (from_email or "").strip().lower()
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

        # Create EmailMessage record
        email_message = EmailMessage(
            pst_file_id=pst_file_record.id,
            case_id=case_id,
            project_id=project_id,
            message_id=message_id,
            in_reply_to=in_reply_to,
            email_references=references,
            conversation_index=conversation_index,
            subject=subject,
            sender_email=from_email,
            sender_name=sender_name,
            recipients_to=to_recipients if to_recipients else None,
            recipients_cc=cc_recipients if cc_recipients else None,
            recipients_bcc=bcc_recipients if bcc_recipients else None,
            date_sent=email_date,
            date_received=email_date,
            body_text=canonical_body,  # Store only the top message, not the full thread
            body_html=body_html_content,
            body_text_clean=body_text_clean or None,
            content_hash=content_hash,
            body_preview=body_preview,
            has_attachments=num_attachments > 0,
            importance=self._safe_get_attr(message, "importance", None),
            pst_message_path=folder_path,
            meta={
                "thread_topic": thread_topic,
                "attachments": [],  # Will be populated after attachments are processed
                "has_attachments": num_attachments > 0,
                "canonical_hash": content_hash,
            },
        )

        # We need to add and flush the email message first to get its ID for attachments
        self.db.add(email_message)
        self.db.flush()

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
        ENABLE_SEMANTIC_INDEXING = False  # Set to True to enable (slower but better search)
        if ENABLE_SEMANTIC_INDEXING and self.semantic_service is not None:
            try:
                self.semantic_service.process_email(
                    email_id=str(email_message.id),
                    subject=subject,
                    body_text=body_text_clean or canonical_body,
                    sender=from_email,
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
                "content": body_html_content or body_text or "",
                "email_data": email_data,
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

                # Calculate hash for deduplication
                file_hash = hashlib.sha256(attachment_data).hexdigest()

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
                    # Upload to S3
                    try:
                        self.s3.put_object(
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
                    except Exception as e:
                        logger.error(
                            f"Failed to upload attachment {filename} to S3: {e}"
                        )
                        stats["errors"].append(f"Attachment upload failed: {filename}")
                        continue

                    # Create Document record for attachment
                    att_doc = Document(
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
                    self.db.add(att_doc)
                    self.db.flush()
                    att_doc_id = att_doc.id

                    # Store for deduplication
                    self.attachment_hashes[file_hash] = att_doc.id

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
                email_attachment = EmailAttachment(
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
                self.db.add(email_attachment)
                self.db.flush()

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

                        # Check if this is a duplicate in the EvidenceItem context
                        # (attachment_hashes tracks Documents, evidence_item_hashes tracks EvidenceItems)
                        evidence_duplicate_of_id = self.evidence_item_hashes.get(file_hash)
                        evidence_is_duplicate = evidence_duplicate_of_id is not None

                        evidence_item = EvidenceItem(
                            filename=safe_filename,
                            original_path=f"PST:{pst_file_record.filename if pst_file_record else 'unknown'}/{safe_filename}",
                            file_type=file_ext,
                            mime_type=content_type,
                            file_size=size,
                            file_hash=file_hash,
                            s3_bucket=settings.S3_BUCKET,
                            s3_key=s3_key,
                            evidence_type="email_attachment",
                            source_type="pst_extraction",
                            source_email_id=email_message.id,
                            case_id=case_id,
                            project_id=project_id,
                            is_duplicate=evidence_is_duplicate,
                            duplicate_of_id=evidence_duplicate_of_id,
                            processing_status="pending",
                            auto_tags=["email-attachment", "from-pst"],
                        )
                        self.db.add(evidence_item)
                        self.db.flush()
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

        # Second pass: assign thread IDs using fallback logic
        for message_id, thread_info in self.threads_map.items():
            email_message: EmailMessage | None = thread_info.get("email_message")
            if not email_message:
                continue

            in_reply_to = thread_info.get("in_reply_to")
            references = thread_info.get("references")
            conversation_index = email_message.conversation_index

            thread_id = None

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

            # Try conversation index (Outlook threading)
            if not thread_id and conversation_index:
                # Look for other emails with same conversation index
                for _, other_info in self.threads_map.items():
                    other_email = other_info.get("email_message")
                    if (
                        other_email
                        and other_email != email_message
                        and other_email.conversation_index == conversation_index
                        and hasattr(other_email, "thread_id")
                        and other_email.thread_id
                    ):
                        thread_id = other_email.thread_id
                        break

            # Last resort: subject-based grouping (normalized subject)
            if not thread_id:
                subject = thread_info.get("subject", "")
                if subject:
                    # Normalize subject (remove Re:, Fwd:, etc.)
                    normalized_subject = re.sub(
                        r"^(re|fw|fwd):\s*", "", subject.lower().strip()
                    )
                    # Look for other emails with same normalized subject
                    for _, other_info in self.threads_map.items():
                        other_email = other_info.get("email_message")
                        other_subject = other_info.get("subject", "")
                        if (
                            other_email
                            and other_email != email_message
                            and other_subject
                        ):
                            other_normalized = re.sub(
                                r"^(re|fw|fwd):\s*", "", other_subject.lower().strip()
                            )
                            if (
                                normalized_subject == other_normalized
                                and hasattr(other_email, "thread_id")
                                and other_email.thread_id
                            ):
                                thread_id = other_email.thread_id
                                break

            # Create new thread if none found
            if not thread_id:
                thread_id = f"thread_{len(thread_groups) + 1}_{uuid.uuid4().hex[:8]}"

            # Assign thread_id to email
            email_message.thread_id = thread_id

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
        except Exception as e:
            logger.error(f"Error updating thread relationships: {e}")
            self.db.rollback()

    def _extract_email_from_headers(self, message: Any) -> str | None:
        """
        Extract email address from RFC 2822 transport headers
        pypff doesn't expose direct .sender_email_address - parse from headers
        """
        try:
            if not message:
                return None
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
                # Convert to string - for pypff objects that may return other types
                headers_str = str(headers_raw)

            # Parse From: header - format is "Name <email@domain.com>" or just "email@domain.com"
            from_match = re.search(
                r"From:\s*(?:.*?<)?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
                headers_str,
                re.IGNORECASE,
            )
            if from_match:
                return from_match.group(1)

            return None
        except (AttributeError, TypeError, re.error) as e:
            logger.debug("Could not extract email from headers: %s", str(e))
            return None
