"""
Backfill Semantic Index
=======================
Run this script to process all existing emails through the semantic engine.
This generates embeddings and indexes them to OpenSearch for fast k-NN retrieval.

Usage:
    python -m app.backfill_semantic

Or from API:
    POST /api/admin/backfill-semantic
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import EmailMessage
from .semantic_engine import SemanticIngestionService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def backfill_emails(
    db: Session,
    batch_size: int = 100,
    project_id: str | None = None,
    case_id: str | None = None,
) -> dict:
    """
    Process all existing emails through the semantic engine.

    Args:
        db: Database session
        batch_size: Number of emails to process before refreshing index
        project_id: Optional - only process emails from this project
        case_id: Optional - only process emails from this case

    Returns:
        Statistics dict with processed count, errors, etc.
    """
    stats = {
        "total": 0,
        "processed": 0,
        "skipped": 0,
        "errors": 0,
        "error_messages": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }

    # Initialize semantic service
    try:
        semantic_service = SemanticIngestionService()
        if not semantic_service.ensure_ready():
            logger.error(
                "Failed to initialize semantic service - OpenSearch may be down"
            )
            stats["error_messages"].append("OpenSearch connection failed")
            return stats
        logger.info("Semantic service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize semantic service: {e}")
        stats["error_messages"].append(str(e))
        return stats

    # Build query
    query = db.query(EmailMessage)
    if project_id:
        query = query.filter(EmailMessage.project_id == project_id)
    if case_id:
        query = query.filter(EmailMessage.case_id == case_id)

    # Get total count
    stats["total"] = query.count()
    logger.info(f"Found {stats['total']} emails to process")

    if stats["total"] == 0:
        logger.info("No emails to process")
        stats["completed_at"] = datetime.now(timezone.utc).isoformat()
        return stats

    # Process in batches
    offset = 0
    while offset < stats["total"]:
        batch = query.order_by(EmailMessage.id).offset(offset).limit(batch_size).all()

        if not batch:
            break

        for email in batch:
            try:
                # Skip if no body text
                body_text = (
                    email.body_text_clean or email.body_text or email.body_preview
                )
                if not body_text or not body_text.strip():
                    stats["skipped"] += 1
                    continue

                # Get recipients as list
                recipients = []
                if email.recipients_to:
                    if isinstance(email.recipients_to, list):
                        recipients = email.recipients_to
                    elif isinstance(email.recipients_to, str):
                        recipients = [r.strip() for r in email.recipients_to.split(",")]

                # Process through semantic engine
                chunks_indexed = semantic_service.process_email(
                    email_id=str(email.id),
                    subject=email.subject,
                    body_text=body_text,
                    sender=email.sender_email or email.sender_name,
                    recipients=recipients[:5],  # Limit recipients
                    case_id=str(email.case_id) if email.case_id else None,
                    project_id=str(email.project_id) if email.project_id else None,
                )

                if chunks_indexed > 0:
                    stats["processed"] += 1
                else:
                    stats["skipped"] += 1

            except Exception as e:
                stats["errors"] += 1
                if len(stats["error_messages"]) < 10:  # Limit error messages
                    stats["error_messages"].append(f"Email {email.id}: {str(e)[:100]}")
                logger.warning(f"Error processing email {email.id}: {e}")

        # Refresh index after each batch
        try:
            semantic_service.refresh()
        except Exception as e:
            logger.warning(f"Index refresh failed: {e}")

        offset += batch_size
        progress = min(100, (offset / stats["total"]) * 100)
        logger.info(
            f"Progress: {offset}/{stats['total']} ({progress:.1f}%) - Processed: {stats['processed']}, Errors: {stats['errors']}"
        )

    stats["completed_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"Backfill complete: {stats}")

    return stats


def main():
    """CLI entry point"""
    logger.info("Starting semantic backfill...")

    db = SessionLocal()
    try:
        stats = backfill_emails(db)

        print("\n" + "=" * 50)
        print("SEMANTIC BACKFILL COMPLETE")
        print("=" * 50)
        print(f"Total emails:     {stats['total']}")
        print(f"Processed:        {stats['processed']}")
        print(f"Skipped (empty):  {stats['skipped']}")
        print(f"Errors:           {stats['errors']}")
        print(f"Started:          {stats['started_at']}")
        print(f"Completed:        {stats['completed_at']}")

        if stats["error_messages"]:
            print("\nErrors:")
            for msg in stats["error_messages"][:10]:
                print(f"  - {msg}")

        print("=" * 50)

    finally:
        db.close()


if __name__ == "__main__":
    main()
