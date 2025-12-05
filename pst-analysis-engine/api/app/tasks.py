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

                    semantic_service.process_email(
                        email_id=str(email.id),
                        subject=email.subject or "",
                        body_text=body_text,
                        sender=email.sender_email or "",
                        recipients=email.recipients_to or [],
                        case_id=str(email.case_id) if email.case_id else None,
                        project_id=str(email.project_id) if email.project_id else None,
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

                    semantic_service.process_email(
                        email_id=str(email.id),
                        subject=email.subject or "",
                        body_text=body_text,
                        sender=email.sender_email or "",
                        recipients=email.recipients_to or [],
                        case_id=str(email.case_id) if email.case_id else None,
                        project_id=str(email.project_id) if email.project_id else None,
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
