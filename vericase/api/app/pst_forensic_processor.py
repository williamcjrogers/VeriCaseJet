"""
FORENSIC-GRADE PST PROCESSOR
Enterprise PST extraction for dispute intelligence and legal discovery

This is the core differentiation - exceptional PST parsing with forensic integrity
"""

import pypff  # type: ignore[import-not-found]
import hashlib
import logging
import tempfile
import os
import re
from datetime import datetime
from typing import Any
from email.utils import parseaddr, getaddresses
from sqlalchemy.orm import Session
from sqlalchemy import func
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import PSTFile, EmailMessage, EmailAttachment, Stakeholder, Keyword
from .storage import put_object, download_file_streaming
from .config import settings
from .search import index_email_in_opensearch
from .tasks import celery_app  # Import Celery app for task registration

import json
import time

logger = logging.getLogger(__name__)


# region agent log helper
def agent_log(
    hypothesis_id: str, message: str, data: dict = None, run_id: str = "run1"
) -> None:
    log_path = (
        r"c:\Users\William\Documents\Projects\VeriCase Analysis\.cursor\debug.log"
    )
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
        self.attachment_hashes = {}  # For deduplication
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

    def _stream_pst_to_temp(self, s3_bucket: str, s3_key: str) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".pst", delete=False)
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
            stakeholder_query = self.db.query(Stakeholder)
            keyword_query = self.db.query(Keyword)
            if pst_file.case_id:
                stakeholder_query = stakeholder_query.filter_by(
                    case_id=pst_file.case_id
                )
                keyword_query = keyword_query.filter_by(case_id=pst_file.case_id)
            elif pst_file.project_id:
                stakeholder_query = stakeholder_query.filter_by(
                    project_id=pst_file.project_id
                )
                keyword_query = keyword_query.filter_by(project_id=pst_file.project_id)
            try:
                return stakeholder_query.all(), keyword_query.all()
            except Exception as e:
                logger.error(f"Failed to load tagging assets: {e}")
                return [], []
        except Exception:
            logger.error("Failed to load tagging assets: {e}")
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
            threads = self._build_email_threads(
                str(entity_id), is_project=bool(pst_file.project_id)
            )
            stats["threads_identified"] = len(threads)

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
            subject = message.get_subject() or ""
            sender_email_addr = message.get_sender_email_address() or ""
            sender_name = message.get_sender_name() or ""

            # Get RFC822 message headers for threading
            transport_headers = message.get_transport_headers() or ""

            # Fallback: Exchange often returns display names, extract SMTP from headers
            if not sender_email_addr or "@" not in sender_email_addr:
                from_match = re.search(
                    r"From:.*?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
                    transport_headers,
                    re.IGNORECASE | re.DOTALL,
                )
                if from_match:
                    sender_email_addr = from_match.group(1)
            message_id = self._extract_header(transport_headers, "Message-ID")
            in_reply_to = self._extract_header(transport_headers, "In-Reply-To")
            references_header = self._extract_header(transport_headers, "References")

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

            # Get dates
            date_sent = message.get_delivery_time()
            date_received = message.get_client_submit_time()

            # Get body text and HTML
            body_text = message.get_plain_text_body() or ""
            body_html = message.get_html_body() or ""

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

            # Fast path: Just extract a preview from plain text
            if body_text:
                canonical_body = body_text
                # Quick split on reply markers
                try:
                    reply_split_pattern = r"(?mi)^On .+ wrote:|^From:\s|^Sent:\s|^-----Original Message-----"
                    parts = re.split(reply_split_pattern, canonical_body, maxsplit=1)
                    canonical_body = parts[0] if parts else canonical_body
                    canonical_body = re.sub(r"\s+", " ", canonical_body).strip()
                except re.error:
                    pass
            elif body_html:
                # Fallback: Strip HTML tags quickly (no BeautifulSoup for speed)
                canonical_body = re.sub(r"<[^>]+>", " ", body_html)
                canonical_body = re.sub(r"\s+", " ", canonical_body).strip()

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
                body_preview=body_preview,
                body_full_s3_key=body_full_s3_key,
                # Flags
                has_attachments=has_attachments,
                importance=importance,
                # Tagging
                matched_stakeholders=[str(s.id) for s in matched_stakeholders],
                matched_keywords=[str(k.id) for k in matched_keywords],
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
                return recipients

            parsed = [addr for _, addr in getaddresses([recipient_str]) if addr]
            if parsed:
                recipients.extend(parsed)
            else:
                for addr in recipient_str.split(";"):
                    addr = addr.strip()
                    if addr:
                        name, email = parseaddr(addr)
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

        for stakeholder in stakeholders:
            # Match by email
            if stakeholder.email and stakeholder.email.lower() in [
                e.lower() for e in all_emails if e
            ]:
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
        matched = []

        search_text = "{subject} {body_text}".lower()

        for keyword in keywords:
            # Build search terms (keyword + variations)
            search_terms = [keyword.keyword_name.lower()]

            if keyword.variations:
                variations = [v.strip().lower() for v in keyword.variations.split(",")]
                search_terms.extend(variations)

            # Check if any term matches
            for term in search_terms:
                if keyword.is_regex:
                    # Use regex matching
                    try:
                        if re.search(term, search_text, re.IGNORECASE):
                            matched.append(keyword)
                            break
                    except (re.error, TypeError):
                        continue
                else:
                    # Simple substring matching
                    if term in search_text:
                        matched.append(keyword)
                        break

        return list(set(matched))  # Remove duplicates

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
    ) -> list[dict[str, Any]]:
        """Build email threads using Message-ID and In-Reply-To headers"""

        # Get all emails for the case or project
        query = self.db.query(EmailMessage)
        if is_project:
            emails = query.filter_by(project_id=entity_id).all()
        else:
            emails = query.filter_by(case_id=entity_id).all()
        # region agent log H6 threading start
        agent_log(
            "H6",
            "Loaded emails for threading",
            {
                "entity_id": entity_id,
                "is_project": is_project,
                "num_emails": len(emails),
            },
        )
        # endregion agent log H6 threading start
        # Build message_id to email map
        message_id_map: dict[str, EmailMessage] = {}
        for email in emails:
            try:
                message_identifier = email.message_id
                if message_identifier:
                    message_id_map[message_identifier] = email
            except (AttributeError, TypeError):
                continue

        # Build threads
        threads = {}

        for email in emails:
            # Find root of thread
            root_id = self._find_thread_root(email, message_id_map)

            if root_id not in threads:
                threads[root_id] = []

            threads[root_id].append(email)

        # Sort emails within each thread by date
        for thread_emails in threads.values():
            thread_emails.sort(key=lambda e: e.date_sent or datetime.min)
        # region agent log H6 threading complete
        agent_log(
            "H6",
            "Email threads built",
            {
                "entity_id": entity_id,
                "num_threads": len(threads),
                "total_emails": sum(len(t) for t in threads.values()),
            },
        )
        # endregion agent log H6 threading complete
        logger.info(f"Built {len(threads)} email threads from {len(emails)} emails")

        return [{"root_id": k, "emails": v} for k, v in threads.items()]

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
    s3_bucket: str,
    s3_key: str,
    case_id: str = None,
    project_id: str = None,
) -> dict[str, Any]:
    """
    Sync Celery task wrapper for forensic PST processing
    Uses sync call for worker compatibility
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
        processor = ForensicPSTProcessor(db)
        # Update PST record with case/project if provided
        pst_file = db.query(PSTFile).filter_by(id=pst_file_id).first()
        if not pst_file:
            raise ValueError(f"PST file {pst_file_id} not found")
        if case_id:
            pst_file.case_id = uuid.UUID(case_id)
        if project_id:
            pst_file.project_id = uuid.UUID(project_id)
        db.commit()
        result = processor.process_pst_file(pst_file_id, s3_bucket, s3_key)  # Sync call
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
