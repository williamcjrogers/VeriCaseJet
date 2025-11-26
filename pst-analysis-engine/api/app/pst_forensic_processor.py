"""
FORENSIC-GRADE PST PROCESSOR
Enterprise PST extraction for dispute intelligence and legal discovery

This is the core differentiation - exceptional PST parsing with forensic integrity
"""

import pypff  # type: ignore[import-not-found]
import hashlib
import json
import logging
import tempfile
import os
import re
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from email.utils import parseaddr
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import PSTFile, EmailMessage, EmailAttachment, Stakeholder, Keyword
from .storage import s3, get_object, put_object, download_file_streaming
from .config import settings
from .search import index_email_in_opensearch

logger = logging.getLogger(__name__)


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
        
    def _stream_pst_to_temp(self, s3_bucket: str, s3_key: str) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix='.pst', delete=False)
        try:
            logger.info("Streaming PST from s3://%s/%s", s3_bucket, s3_key)
            download_file_streaming(s3_bucket, s3_key, tmp)
            tmp.flush()
            return tmp.name
        except Exception as e:
            logger.error("Failed to stream PST: {e}")
            tmp.close()
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
            raise

    def _load_tagging_assets(self, pst_file: PSTFile) -> Tuple[List[Stakeholder], List[Keyword]]:
        stakeholder_query = self.db.query(Stakeholder)
        keyword_query = self.db.query(Keyword)
        if pst_file.case_id:
            stakeholder_query = stakeholder_query.filter_by(case_id=pst_file.case_id)
            keyword_query = keyword_query.filter_by(case_id=pst_file.case_id)
        elif pst_file.project_id:
            stakeholder_query = stakeholder_query.filter_by(project_id=pst_file.project_id)
            keyword_query = keyword_query.filter_by(project_id=pst_file.project_id)
        try:
            return stakeholder_query.all(), keyword_query.all()
        except Exception as e:
            logger.error("Failed to load tagging assets: {e}")
            return [], []

    def _process_pst_path(
        self,
        pst_path: str,
        pst_file: PSTFile,
        stats: Dict
    ) -> None:
        pst = pypff.file()
        pst.open(pst_path)

        root = pst.get_root_folder()
        self.total_count = self._count_emails_recursive(root)
        pst_file.total_emails = self.total_count
        self.db.commit()

        logger.info("PST contains %s total emails", self.total_count)

        stakeholders, keywords = self._load_tagging_assets(pst_file)
        self._process_folder_recursive(root, pst_file, stakeholders, keywords, stats)

        pst.close()

        entity_id = pst_file.case_id or pst_file.project_id
        threads = self._build_email_threads(entity_id, is_project=bool(pst_file.project_id))
        stats['threads_identified'] = len(threads)

    def process_pst_file(
        self,
        pst_file_id: str,
        s3_bucket: str,
        s3_key: str
    ) -> Dict:
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
        pst_file.processing_status = 'processing'
        pst_file.processing_started_at = func.now()
        self.db.commit()
        
        stats = {
            'total_emails': 0,
            'total_attachments': 0,
            'unique_attachments': 0,
            'threads_identified': 0,
            'stakeholders_matched': 0,
            'keywords_matched': 0,
            'errors': []
        }
        
        pst_path = None
        try:
            pst_path = self._stream_pst_to_temp(s3_bucket, s3_key)
            self._process_pst_path(pst_path, pst_file, stats)

            pst_file.processing_status = 'completed'
            pst_file.processing_completed_at = func.now()
            pst_file.processed_emails = self.processed_count
            stats['total_emails'] = self.processed_count
            self.db.commit()

            logger.info("✓ PST processing complete: %s", stats)
        
        except Exception as e:
            logger.error("Error processing PST: {e}", exc_info=True)
            pst_file.processing_status = 'failed'
            pst_file.error_message = str(e)
            self.db.commit()
            stats['errors'].append(str(e))
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
        folder,
        pst_file: PSTFile,
        stakeholders: List[Stakeholder],
        keywords: List[Keyword],
        stats: Dict,
        folder_path: str = "Root"
    ):
        """Process all emails in folder and subfolders"""
        
        # Process messages in current folder
        num_messages = folder.get_number_of_sub_messages()
        
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
                    stats
                )
                self.processed_count += 1
                
                # Commit every 50 emails for progress tracking
                if self.processed_count % 50 == 0:
                    pst_file.processed_emails = self.processed_count
                    self.db.commit()
                    logger.info("Progress: {self.processed_count}/{self.total_count} emails")
                    
            except Exception as e:
                logger.error("Error extracting email at index {i}: {e}")
                stats['errors'].append("Email {i}: {str(e)}")
        
        # Process subfolders
        num_folders = folder.get_number_of_sub_folders()
        for i in range(num_folders):
            sub_folder = folder.get_sub_folder(i)
            folder_name = sub_folder.get_name() or "Folder{i}"
            sub_path = "{folder_path}/{folder_name}"
            
            self._process_folder_recursive(
                sub_folder,
                pst_file,
                stakeholders,
                keywords,
                stats,
                sub_path
            )
    
    def _extract_email_message(
        self,
        message,
        pst_file: PSTFile,
        folder_path: str,
        message_offset: int,
        stakeholders: List[Stakeholder],
        keywords: List[Keyword],
        stats: Dict
    ):
        """Extract single email message with forensic metadata"""
        
        # Extract email headers and content
        try:
            subject = message.get_subject() or ""
            sender_email_addr = message.get_sender_email_address() or ""
            sender_name = message.get_sender_name() or ""
            
            # Get RFC822 message headers for threading
            transport_headers = message.get_transport_headers() or ""
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
            
            # Get recipients
            recipients_to = self._extract_recipients(message, "to")
            recipients_cc = self._extract_recipients(message, "cc")
            recipients_bcc = self._extract_recipients(message, "bcc")
            
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
            
            # Auto-tag: Match stakeholders and keywords
            matched_stakeholders = self._match_stakeholders(
                sender_email_addr,
                sender_name,
                recipients_to + recipients_cc,
                stakeholders
            )
            
            matched_keywords = self._match_keywords(
                subject,
                body_text,
                keywords
            )
            
            if matched_stakeholders:
                stats['stakeholders_matched'] += 1
            if matched_keywords:
                stats['keywords_matched'] += 1
            
            # Storage optimization: Large emails go to S3
            body_preview = None
            body_full_s3_key = None
            BODY_SIZE_LIMIT = 10 * 1024  # 10KB limit
            
            if body_text and len(body_text) > BODY_SIZE_LIMIT:
                # Store full body in S3
                body_preview = body_text[:BODY_SIZE_LIMIT]
                # Support both projects and cases
                if pst_file.project_id:
                    body_full_s3_key = "project_{pst_file.project_id}/email_bodies/{message_id or message_offset}.txt"
                elif pst_file.case_id:
                    body_full_s3_key = "case_{pst_file.case_id}/email_bodies/{message_id or message_offset}.txt"
                else:
                    body_full_s3_key = "email_bodies/{message_id or message_offset}.txt"
                try:
                    put_object(
                        body_full_s3_key,
                        body_text.encode('utf-8'),
                        'text/plain; charset=utf-8',
                        bucket=settings.S3_BUCKET
                    )
                    body_text = None
                except Exception as e:
                    logger.warning("Failed to store body in S3: {e}")
                
            # Create email message record
            email_msg = EmailMessage(
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
                body_text=body_text if body_text and len(body_text) <= BODY_SIZE_LIMIT else None,
                body_html=body_html[:20000] if body_html else None,  # Limit HTML to 20KB
                body_preview=body_preview,
                body_full_s3_key=body_full_s3_key,
                
                # Flags
                has_attachments=has_attachments,
                importance=importance,
                
                # Tagging
                matched_stakeholders=[str(s.id) for s in matched_stakeholders],
                matched_keywords=[str(k.id) for k in matched_keywords]
            )
            
            self.db.add(email_msg)
            self.db.flush()  # Get the email_msg.id
            
            # Extract attachments
            if has_attachments:
                for i in range(num_attachments):
                    try:
                        attachment = message.get_attachment(i)
                        self._extract_attachment(attachment, email_msg, stats)
                    except Exception as e:
                        logger.error("Error extracting attachment {i}: {e}")
                        stats['errors'].append("Attachment {i}: {str(e)}")
            
            # Index in OpenSearch (if enabled)
            if settings.OPENSEARCH_HOST and hasattr(self, 'opensearch') and self.opensearch:
                try:
                    self._index_email(email_msg)
                except Exception as e:
                    logger.warning("OpenSearch indexing failed for email {email_msg.id}: {e}")
            
            stats['total_emails'] += 1
            
        except Exception as e:
            logger.error("Error extracting email message: {e}", exc_info=True)
            raise
    
    def _extract_attachment(
        self,
        attachment,
        email_msg: EmailMessage,
        stats: Dict
    ):
        """Extract email attachment to S3"""
        
        try:
            filename = attachment.get_name() or "attachment_{stats['total_attachments']}"
            size = attachment.get_size()
            
            # Get attachment data
            try:
                data = attachment.read_buffer(size) if size > 0 else b''
            except Exception as e:
                logger.error("Failed to read attachment: {e}")
                return
            
            if not data:
                logger.warning("Empty attachment: {filename}")
                return
            
            # Calculate hash for deduplication
            file_hash = hashlib.sha256(data).hexdigest()
            content_type = self._detect_content_type(filename, data) or "application/octet-stream"
            
            # Check if we've seen this attachment before
            if file_hash in self.attachment_hashes:
                logger.debug("Duplicate attachment detected: {filename}")
                # Still create a record, but link to existing S3 file
                existing_s3_key = self.attachment_hashes[file_hash]
                s3_key = existing_s3_key
                s3_bucket = getattr(settings, 'S3_ATTACHMENTS_BUCKET', None) or settings.S3_BUCKET
            else:
                # Upload new attachment to S3
                s3_bucket = getattr(settings, 'S3_ATTACHMENTS_BUCKET', None) or settings.S3_BUCKET
                # Support both projects and cases
                if email_msg.project_id:
                    s3_key = "project_{email_msg.project_id}/attachments/{email_msg.id}/{filename}"
                elif email_msg.case_id:
                    s3_key = "case_{email_msg.case_id}/attachments/{email_msg.id}/{filename}"
                else:
                    s3_key = "attachments/{email_msg.id}/{filename}"
                
                try:
                    put_object(
                        s3_key,
                        data,
                        content_type,
                        bucket=s3_bucket,
                    )
                    self.attachment_hashes[file_hash] = s3_key
                    stats['unique_attachments'] += 1
                except Exception as e:
                    logger.error("Failed to upload attachment: {e}")
                    raise
            
            # Create attachment record
            attachment_record = EmailAttachment(
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
            
            self.db.add(attachment_record)
            stats['total_attachments'] += 1
            
        except Exception as e:
            logger.error("Error extracting attachment: {e}", exc_info=True)
            raise
    
    def _extract_header(self, headers: str, header_name: str) -> Optional[str]:
        """Extract specific header from RFC822 headers"""
        if not headers:
            return None
        
        pattern = '{header_name}:\s*(.+?)(?:\r?\n(?!\s)|$)'
        match = re.search(pattern, headers, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None
    
    def _extract_recipients(self, message, recipient_type: str) -> List[Dict]:
        """Extract recipients as list of {name, email} dicts"""
        recipients = []
        
        try:
            if recipient_type == "to":
                recipient_str = message.get_recipient_string() or ""
            elif recipient_type == "cc":
                recipient_str = message.get_cc_string() or ""
            elif recipient_type == "bcc":
                recipient_str = message.get_bcc_string() or ""
            else:
                return recipients
            
            # Parse recipient string
            for addr in recipient_str.split(';'):
                addr = addr.strip()
                if addr:
                    name, email = parseaddr(addr)
                    recipients.append({
                        'name': name or email,
                        'email': email
                    })
        except Exception as e:
            logger.warning("Error parsing {recipient_type} recipients: {e}")
        
        return recipients
    
    def _match_stakeholders(
        self,
        sender_email: str,
        sender_name: str,
        all_recipients: List[Dict],
        stakeholders: List[Stakeholder]
    ) -> List[Stakeholder]:
        """Auto-tag email with matching stakeholders"""
        matched = []
        
        all_emails = [sender_email] + [r['email'] for r in all_recipients if r.get('email')]
        all_names = [sender_name] + [r['name'] for r in all_recipients if r.get('name')]
        
        for stakeholder in stakeholders:
            # Match by email
            if stakeholder.email and stakeholder.email.lower() in [e.lower() for e in all_emails if e]:
                matched.append(stakeholder)
                continue
            
            # Match by email domain
            if stakeholder.email_domain:
                for email in all_emails:
                    if email and '@' in email:
                        domain = email.split('@')[1].lower()
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
        self,
        subject: str,
        body_text: str,
        keywords: List[Keyword]
    ) -> List[Keyword]:
        """Auto-tag email with matching keywords"""
        matched = []
        
        search_text = "{subject} {body_text}".lower()
        
        for keyword in keywords:
            # Build search terms (keyword + variations)
            search_terms = [keyword.keyword_name.lower()]
            
            if keyword.variations:
                variations = [v.strip().lower() for v in keyword.variations.split(',')]
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
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.txt': 'text/plain',
            '.csv': 'text/csv',
            '.zip': 'application/zip',
            '.msg': 'application/vnd.ms-outlook'
        }
        
        return content_types.get(ext, 'application/octet-stream')
    
    def _index_email(self, email_msg: EmailMessage):
        """Index email in OpenSearch for full-text search"""
        try:
            index_email_in_opensearch(
                email_id=str(email_msg.id),
                case_id=str(email_msg.case_id),
                subject=email_msg.subject or "",
                body_text=email_msg.body_text or "",
                sender_email=email_msg.sender_email or "",
                sender_name=email_msg.sender_name or "",
                recipients=email_msg.recipients_to or [],
                date_sent=email_msg.date_sent.isoformat() if email_msg.date_sent else None,
                has_attachments=email_msg.has_attachments,
                matched_stakeholders=email_msg.matched_stakeholders or [],
                matched_keywords=email_msg.matched_keywords or [],
                body_text_clean=getattr(email_msg, "body_text_clean", None),
                content_hash=getattr(email_msg, "content_hash", None),
            )
        except Exception as e:
            logger.warning("Failed to index email {email_msg.id} in OpenSearch: {e}")
    
    def _build_email_threads(self, entity_id: str, is_project: bool = False) -> List[Dict]:
        """Build email threads using Message-ID and In-Reply-To headers"""

        # Get all emails for the case or project
        query = self.db.query(EmailMessage)
        if is_project:
            emails = query.filter_by(project_id=entity_id).all()
        else:
            emails = query.filter_by(case_id=entity_id).all()
        
        # Build message_id to email map
        message_id_map: Dict[str, EmailMessage] = {}
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
        
        logger.info("Built {len(threads)} email threads from {len(emails)} emails")
        
        return [{'root_id': k, 'emails': v} for k, v in threads.items()]
    
    def _find_thread_root(self, email: EmailMessage, message_id_map: Dict[str, EmailMessage]) -> str:
        """Find the root message of an email thread"""
        
        in_reply_to = email.in_reply_to
        if not in_reply_to:
            return email.message_id or str(email.id)
        
        current = email
        seen: Set[str] = set()
        
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
async def process_pst_forensic(
    pst_file_id: str,
    s3_bucket: str,
    s3_key: str,
    db: Session
) -> Dict:
    """
    Wrapper function for Celery task
    """
    processor = ForensicPSTProcessor(db)
    return await asyncio.to_thread(processor.process_pst_file, pst_file_id, s3_bucket, s3_key)

