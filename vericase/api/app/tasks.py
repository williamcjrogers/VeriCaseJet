"""
Background tasks for VeriCase Analysis
Handles long-running operations like semantic indexing, OCR, etc.
"""

import logging
from typing import Any
from celery import Celery
from .config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "vericase-docs", broker=settings.REDIS_URL, backend=settings.REDIS_URL
)

# Configure Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
)


@celery_app.task(bind=True, name="index_project_emails_semantic")
def index_project_emails_semantic(self, project_id: str, batch_size: int = 50) -> dict[str, Any]:
    """
    Background task to semantically index all emails in a project.

    This runs after PST processing completes to enable advanced search
    without slowing down the initial import.

    Args:
        project_id: UUID of the project
        batch_size: Number of emails to process per batch

    Returns:
        Dict with indexing statistics
    """
    from .db import SessionLocal
    from .models import EmailMessage
    from sqlalchemy import func
    import uuid

    logger.info(f"Starting semantic indexing for project {project_id}")

    db = SessionLocal()
    stats = {
        "total_emails": 0,
        "indexed": 0,
        "skipped": 0,
        "errors": 0,
    }

    try:
        # Initialize semantic service
        try:
            from .semantic_engine import SemanticIngestionService
            from .opensearch_client import get_opensearch_client

            opensearch_client = get_opensearch_client()
            if not opensearch_client:
                logger.warning("OpenSearch not available, skipping semantic indexing")
                return {"status": "skipped", "reason": "OpenSearch not configured"}

            semantic_service = SemanticIngestionService(opensearch_client)
        except ImportError:
            logger.warning("Semantic service not available, skipping indexing")
            return {"status": "skipped", "reason": "Semantic service not installed"}

        # Get total count
        total_count = (
            db.query(func.count(EmailMessage.id))
            .filter(EmailMessage.project_id == uuid.UUID(project_id))
            .scalar()
        ) or 0

        stats["total_emails"] = total_count
        logger.info(f"Found {total_count} emails to index")

        # Process in batches
        offset = 0
        while offset < total_count:
            emails = (
                db.query(EmailMessage)
                .filter(EmailMessage.project_id == uuid.UUID(project_id))
                .order_by(EmailMessage.created_at)
                .offset(offset)
                .limit(batch_size)
                .all()
            )

            if not emails:
                break

            for email in emails:
                try:
                    # Index this email
                    body_text = email.body_text_clean or email.body_text or ""

                    # Extract attachment info for multi-vector indexing
                    attachment_names: list[str] = []
                    attachment_types: list[str] = []
                    if hasattr(email, 'attachments') and email.attachments:
                        for att in email.attachments:
                            if hasattr(att, 'filename') and att.filename:
                                attachment_names.append(att.filename)
                                # Extract file extension
                                if '.' in att.filename:
                                    ext = att.filename.rsplit('.', 1)[-1].lower()
                                    attachment_types.append(ext)

                    semantic_service.process_email(
                        email_id=str(email.id),
                        subject=email.subject or "",
                        body_text=body_text,
                        sender=email.sender_email or "",
                        recipients=email.recipients_to or [],
                        case_id=str(email.case_id) if email.case_id else None,
                        project_id=str(email.project_id) if email.project_id else None,
                        sent_date=email.sent_date if hasattr(email, 'sent_date') else None,
                        attachment_names=attachment_names,
                        attachment_types=attachment_types,
                    )

                    stats["indexed"] += 1

                except Exception as e:
                    logger.warning(f"Failed to index email {email.id}: {e}")
                    stats["errors"] += 1

            offset += batch_size

            # Update task progress
            progress = int((offset / total_count) * 100)
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': offset,
                    'total': total_count,
                    'percent': progress,
                    'indexed': stats["indexed"],
                }
            )

        logger.info(
            f"Semantic indexing complete for project {project_id}: "
            f"{stats['indexed']} indexed, {stats['errors']} errors"
        )

        return {
            "status": "completed",
            "stats": stats,
        }

    except Exception as e:
        logger.exception(f"Semantic indexing failed for project {project_id}: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "stats": stats,
        }
    finally:
        db.close()


@celery_app.task(bind=True, name="index_case_emails_semantic")
def index_case_emails_semantic(self, case_id: str, batch_size: int = 50) -> dict[str, Any]:
    """
    Background task to semantically index all emails in a case.

    Args:
        case_id: UUID of the case
        batch_size: Number of emails to process per batch

    Returns:
        Dict with indexing statistics
    """
    from .db import SessionLocal
    from .models import EmailMessage
    from sqlalchemy import func
    import uuid

    logger.info(f"Starting semantic indexing for case {case_id}")

    db = SessionLocal()
    stats = {
        "total_emails": 0,
        "indexed": 0,
        "skipped": 0,
        "errors": 0,
    }

    try:
        # Initialize semantic service
        try:
            from .semantic_engine import SemanticIngestionService
            from .opensearch_client import get_opensearch_client

            opensearch_client = get_opensearch_client()
            if not opensearch_client:
                logger.warning("OpenSearch not available, skipping semantic indexing")
                return {"status": "skipped", "reason": "OpenSearch not configured"}

            semantic_service = SemanticIngestionService(opensearch_client)
        except ImportError:
            logger.warning("Semantic service not available, skipping indexing")
            return {"status": "skipped", "reason": "Semantic service not installed"}

        # Get total count
        total_count = (
            db.query(func.count(EmailMessage.id))
            .filter(EmailMessage.case_id == uuid.UUID(case_id))
            .scalar()
        ) or 0

        stats["total_emails"] = total_count
        logger.info(f"Found {total_count} emails to index")

        # Process in batches
        offset = 0
        while offset < total_count:
            emails = (
                db.query(EmailMessage)
                .filter(EmailMessage.case_id == uuid.UUID(case_id))
                .order_by(EmailMessage.created_at)
                .offset(offset)
                .limit(batch_size)
                .all()
            )

            if not emails:
                break

            for email in emails:
                try:
                    # Index this email
                    body_text = email.body_text_clean or email.body_text or ""

                    # Extract attachment info for multi-vector indexing
                    attachment_names: list[str] = []
                    attachment_types: list[str] = []
                    if hasattr(email, 'attachments') and email.attachments:
                        for att in email.attachments:
                            if hasattr(att, 'filename') and att.filename:
                                attachment_names.append(att.filename)
                                # Extract file extension
                                if '.' in att.filename:
                                    ext = att.filename.rsplit('.', 1)[-1].lower()
                                    attachment_types.append(ext)

                    semantic_service.process_email(
                        email_id=str(email.id),
                        subject=email.subject or "",
                        body_text=body_text,
                        sender=email.sender_email or "",
                        recipients=email.recipients_to or [],
                        case_id=str(email.case_id) if email.case_id else None,
                        project_id=str(email.project_id) if email.project_id else None,
                        sent_date=email.sent_date if hasattr(email, 'sent_date') else None,
                        attachment_names=attachment_names,
                        attachment_types=attachment_types,
                    )

                    stats["indexed"] += 1

                except Exception as e:
                    logger.warning(f"Failed to index email {email.id}: {e}")
                    stats["errors"] += 1

            offset += batch_size

            # Update task progress
            progress = int((offset / total_count) * 100)
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': offset,
                    'total': total_count,
                    'percent': progress,
                    'indexed': stats["indexed"],
                }
            )

        logger.info(
            f"Semantic indexing complete for case {case_id}: "
            f"{stats['indexed']} indexed, {stats['errors']} errors"
        )

        return {
            "status": "completed",
            "stats": stats,
        }

    except Exception as e:
        logger.exception(f"Semantic indexing failed for case {case_id}: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "stats": stats,
        }
    finally:
        db.close()


@celery_app.task(bind=True, name="apply_spam_filter_batch")
def apply_spam_filter_batch(
    self, project_id: str | None = None, case_id: str | None = None, batch_size: int = 100
) -> dict[str, Any]:
    """
    Background task to apply spam filter to all emails in a project or case.

    Classifies emails and stores results in the `meta` JSON column.
    Runs after PST processing completes or can be triggered manually.

    Args:
        project_id: UUID of the project (optional)
        case_id: UUID of the case (optional)
        batch_size: Number of emails to process per batch

    Returns:
        Dict with filtering statistics
    """
    from .db import SessionLocal
    from .models import EmailMessage
    from .spam_filter import get_spam_classifier
    from sqlalchemy import func
    import uuid

    entity_type = "project" if project_id else "case"
    entity_id = project_id or case_id

    if not entity_id:
        return {"status": "failed", "error": "Must provide project_id or case_id"}

    logger.info(f"Starting spam filter for {entity_type} {entity_id}")

    db = SessionLocal()
    classifier = get_spam_classifier()

    stats = {
        "total_emails": 0,
        "processed": 0,
        "spam_detected": 0,
        "hidden": 0,
        "errors": 0,
        "by_category": {},
    }

    try:
        # Build query based on entity type
        if project_id:
            base_filter = EmailMessage.project_id == uuid.UUID(project_id)
        else:
            base_filter = EmailMessage.case_id == uuid.UUID(case_id)

        # Get total count
        total_count = (
            db.query(func.count(EmailMessage.id))
            .filter(base_filter)
            .scalar()
        ) or 0

        stats["total_emails"] = total_count
        logger.info(f"Found {total_count} emails to classify")

        # Process in batches
        offset = 0
        while offset < total_count:
            emails = (
                db.query(EmailMessage)
                .filter(base_filter)
                .order_by(EmailMessage.id)
                .offset(offset)
                .limit(batch_size)
                .all()
            )

            if not emails:
                break

            for email in emails:
                try:
                    # Classify this email
                    result = classifier.classify(
                        subject=email.subject,
                        sender=email.sender_email,
                        body=email.body_text,
                    )

                    # Update meta JSON with spam info
                    meta = email.meta or {}
                    meta["spam"] = {
                        "is_spam": result["is_spam"],
                        "score": result["score"],
                        "category": result["category"],
                        "is_hidden": result["is_hidden"],
                    }
                    email.meta = meta

                    stats["processed"] += 1

                    if result["is_spam"]:
                        stats["spam_detected"] += 1
                        category = result["category"] or "unknown"
                        stats["by_category"][category] = (
                            stats["by_category"].get(category, 0) + 1
                        )

                        if result["is_hidden"]:
                            stats["hidden"] += 1

                except Exception as e:
                    logger.warning(f"Failed to classify email {email.id}: {e}")
                    stats["errors"] += 1

            # Commit batch
            db.commit()

            offset += batch_size

            # Update task progress
            progress = int((offset / total_count) * 100)
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': offset,
                    'total': total_count,
                    'percent': progress,
                    'spam_detected': stats["spam_detected"],
                    'hidden': stats["hidden"],
                }
            )

        logger.info(
            f"Spam filter complete for {entity_type} {entity_id}: "
            f"{stats['spam_detected']} spam detected, {stats['hidden']} hidden"
        )

        return {
            "status": "completed",
            "stats": stats,
        }

    except Exception as e:
        logger.exception(f"Spam filter failed for {entity_type} {entity_id}: {e}")
        db.rollback()
        return {
            "status": "failed",
            "error": str(e),
            "stats": stats,
        }
    finally:
        db.close()
