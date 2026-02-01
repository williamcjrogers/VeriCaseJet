"""
Background tasks for VeriCase Analysis
Handles long-running operations like semantic indexing, OCR, etc.
"""

import logging
import sys
from typing import Any
from celery import Celery
from kombu import Queue
from .config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "vericase-docs", broker=settings.REDIS_URL, backend=settings.REDIS_URL
)


def _running_under_celery_cli() -> bool:
    argv = " ".join(sys.argv).lower()
    return "celery" in argv and any(
        cmd in argv for cmd in (" worker", " beat", " flower")
    )


# Optional OpenTelemetry tracing (disabled by default)
if _running_under_celery_cli():
    try:
        from .tracing import (
            setup_tracing,
            instrument_celery,
            instrument_requests,
            instrument_sqlalchemy,
        )

        if setup_tracing("vericase-worker"):
            instrument_celery()
            instrument_requests()
            from .db import engine

            instrument_sqlalchemy(engine)
    except Exception:
        pass

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    result_expires=86400,  # Auto-expire job results after 24 hours
    # Declare queues so workers started without `-Q` will consume both.
    task_default_queue=settings.CELERY_QUEUE,
    task_create_missing_queues=True,
    task_queues=(
        Queue(settings.CELERY_QUEUE),
        Queue(settings.CELERY_PST_QUEUE),
    ),
)


def cascade_spam_to_evidence(db, entity_id: str, entity_type: str) -> dict[str, int]:
    """
    Bulk cascade spam classification from emails to their evidence items.

    When an email is marked as spam/hidden, its attachments (evidence items)
    should also be hidden. When an email is restored, its evidence should be restored.

    Args:
        db: Database session
        entity_id: Project or case UUID
        entity_type: "project" or "case"

    Returns:
        Dict with 'updated' (hidden) and 'restored' counts
    """
    from sqlalchemy import text
    import uuid

    stats = {"updated": 0, "restored": 0}

    try:
        entity_uuid = uuid.UUID(entity_id)

        # Determine the filter column
        if entity_type == "project":
            filter_clause = "ei.project_id = :entity_id"
        else:
            filter_clause = "ei.case_id = :entity_id"

        # 1. Mark evidence as hidden where parent email is hidden
        # Only update if not already marked with same spam info
        update_hidden_sql = text(
            f"""
            UPDATE evidence_items ei
            SET meta = jsonb_set(
                COALESCE(meta, '{{}}'),
                '{{spam}}',
                jsonb_build_object(
                    'is_hidden', true,
                    'inherited_from_email', em.id::text,
                    'score', (em.meta->'spam'->>'score')::int,
                    'category', em.meta->'spam'->>'category'
                )
            )
            FROM email_messages em
            WHERE ei.source_email_id = em.id
              AND em.meta->'spam'->>'is_hidden' = 'true'
              AND {filter_clause}
              AND (
                  ei.meta IS NULL 
                  OR ei.meta->'spam'->>'is_hidden' IS NULL 
                  OR ei.meta->'spam'->>'is_hidden' != 'true'
              )
        """
        )

        result = db.execute(update_hidden_sql, {"entity_id": entity_uuid})
        stats["updated"] = result.rowcount

        # 2. Restore evidence where parent email is no longer hidden
        # Only restore if it was inherited (not manually hidden)
        restore_sql = text(
            f"""
            UPDATE evidence_items ei
            SET meta = meta - 'spam'
            FROM email_messages em
            WHERE ei.source_email_id = em.id
              AND {filter_clause}
              AND ei.meta->'spam'->>'inherited_from_email' IS NOT NULL
              AND (
                  em.meta->'spam'->>'is_hidden' IS NULL 
                  OR em.meta->'spam'->>'is_hidden' = 'false'
              )
              AND ei.meta->'spam'->>'is_hidden' = 'true'
        """
        )

        result = db.execute(restore_sql, {"entity_id": entity_uuid})
        stats["restored"] = result.rowcount

        db.commit()

    except Exception as e:
        logger.warning(f"Evidence cascade failed: {e}")
        db.rollback()

    return stats


def _index_emails_semantic(
    task_self,
    entity_type: str,
    entity_id: str,
    batch_size: int = 50,
) -> dict[str, Any]:
    """
    Shared implementation for semantic indexing of emails.

    Indexes all visible emails for a given project or case into OpenSearch
    using the SemanticIngestionService.

    Args:
        task_self: The bound Celery task instance (for progress updates).
        entity_type: Either "project" or "case".
        entity_id: UUID string of the project or case.
        batch_size: Number of emails to process per batch.

    Returns:
        Dict with indexing statistics.
    """
    from .db import SessionLocal
    from .models import EmailMessage
    from .visibility import build_email_visibility_filter
    from sqlalchemy import func
    import uuid

    logger.info(f"Starting semantic indexing for {entity_type} {entity_id}")

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

        visibility_filter = build_email_visibility_filter(EmailMessage)

        # Build the entity filter based on type
        if entity_type == "project":
            entity_filter = EmailMessage.project_id == uuid.UUID(entity_id)
        else:
            entity_filter = EmailMessage.case_id == uuid.UUID(entity_id)

        # Get total count
        total_count = (
            db.query(func.count(EmailMessage.id))
            .filter(entity_filter)
            .filter(visibility_filter)
            .scalar()
        ) or 0

        stats["total_emails"] = total_count
        logger.info(f"Found {total_count} emails to index")

        # Process in batches
        offset = 0
        while offset < total_count:
            emails = (
                db.query(EmailMessage)
                .filter(entity_filter)
                .filter(visibility_filter)
                .order_by(EmailMessage.created_at)
                .offset(offset)
                .limit(batch_size)
                .all()
            )

            if not emails:
                break

            for email in emails:
                try:
                    if (email.subject or "").startswith("IPM."):
                        stats["skipped"] += 1
                        continue

                    # Index this email
                    body_text = email.body_text_clean or email.body_text or ""

                    # Extract attachment info for multi-vector indexing
                    attachment_names: list[str] = []
                    attachment_types: list[str] = []
                    if hasattr(email, "attachments") and email.attachments:
                        for att in email.attachments:
                            if hasattr(att, "filename") and att.filename:
                                attachment_names.append(att.filename)
                                # Extract file extension
                                if "." in att.filename:
                                    ext = att.filename.rsplit(".", 1)[-1].lower()
                                    attachment_types.append(ext)

                    semantic_service.process_email(
                        email_id=str(email.id),
                        subject=email.subject or "",
                        body_text=body_text,
                        sender=email.sender_email or "",
                        recipients=email.recipients_to or [],
                        case_id=str(email.case_id) if email.case_id else None,
                        project_id=str(email.project_id) if email.project_id else None,
                        sent_date=(
                            email.sent_date if hasattr(email, "sent_date") else None
                        ),
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
            task_self.update_state(
                state="PROGRESS",
                meta={
                    "current": offset,
                    "total": total_count,
                    "percent": progress,
                    "indexed": stats["indexed"],
                },
            )

        logger.info(
            f"Semantic indexing complete for {entity_type} {entity_id}: "
            f"{stats['indexed']} indexed, {stats['errors']} errors"
        )

        return {
            "status": "completed",
            "stats": stats,
        }

    except Exception as e:
        logger.exception(f"Semantic indexing failed for {entity_type} {entity_id}: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "stats": stats,
        }
    finally:
        db.close()


@celery_app.task(bind=True, name="index_project_emails_semantic")
def index_project_emails_semantic(
    self, project_id: str, batch_size: int = 50
) -> dict[str, Any]:
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
    return _index_emails_semantic(self, "project", project_id, batch_size)


@celery_app.task(bind=True, name="index_case_emails_semantic")
def index_case_emails_semantic(
    self, case_id: str, batch_size: int = 50
) -> dict[str, Any]:
    """
    Background task to semantically index all emails in a case.

    Args:
        case_id: UUID of the case
        batch_size: Number of emails to process per batch

    Returns:
        Dict with indexing statistics
    """
    return _index_emails_semantic(self, "case", case_id, batch_size)


@celery_app.task(bind=True, name="apply_spam_filter_batch")
def apply_spam_filter_batch(
    self,
    project_id: str | None = None,
    case_id: str | None = None,
    batch_size: int = 100,
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
    from .spam_filter import extract_other_project, get_spam_classifier
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
            db.query(func.count(EmailMessage.id)).filter(base_filter).scalar()
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
                    body_text = (
                        email.body_text_clean
                        or email.body_text
                        or email.body_preview
                        or ""
                    )
                    result = classifier.classify(
                        subject=email.subject,
                        sender=email.sender_email,
                        body=body_text,
                    )

                    # Update meta JSON with spam info
                    meta = email.meta or {}

                    # Preserve any user override so restored emails stay visible
                    existing_spam = meta.get("spam")
                    user_override: str | None = None
                    if isinstance(existing_spam, dict):
                        user_override = existing_spam.get("user_override")

                    existing_status = meta.get("status")
                    existing_applied_status: str | None = None
                    existing_status_set_by: str | None = None
                    if isinstance(existing_spam, dict):
                        existing_applied_status = existing_spam.get("applied_status")
                        existing_status_set_by = existing_spam.get("status_set_by")

                    computed_is_hidden = bool(result["is_hidden"])
                    if user_override == "visible":
                        computed_is_hidden = False
                    elif user_override == "hidden":
                        computed_is_hidden = True

                    result_category = result.get("category")
                    derived_status: str | None = None
                    if computed_is_hidden:
                        derived_status = (
                            "other_project"
                            if result_category == "other_projects"
                            else "spam"
                        )

                    spam_payload: dict[str, Any] = {
                        "is_spam": bool(result["is_spam"]),
                        "score": int(result["score"]),
                        "category": result_category,
                        "is_hidden": computed_is_hidden,
                    }
                    if user_override:
                        spam_payload["user_override"] = user_override

                    # Align the correspondence UI visibility convention.
                    # Only set/clear meta['status'] when we know it's ours to manage.
                    if computed_is_hidden and derived_status:
                        should_apply_status = (
                            existing_status is None
                            or existing_status == "active"
                            or existing_status_set_by
                            in {"spam_filter_batch", "spam_filter_ingest"}
                        )
                        if should_apply_status:
                            meta["status"] = derived_status
                            spam_payload["status_set_by"] = "spam_filter_batch"
                            spam_payload["applied_status"] = derived_status
                    else:
                        # If the email was previously hidden by this batch task, restore it.
                        if (
                            existing_status_set_by
                            in {"spam_filter_batch", "spam_filter_ingest"}
                            and existing_applied_status
                            and existing_status == existing_applied_status
                        ):
                            meta.pop("status", None)

                    # Canonical nested spam structure (used by evidence cascading)
                    meta["spam"] = spam_payload

                    # Backward-compatible top-level flags (used by multiple subsystems)
                    meta["is_spam"] = spam_payload["is_spam"]
                    meta["spam_score"] = spam_payload["score"]
                    meta["is_hidden"] = spam_payload["is_hidden"]
                    meta["excluded"] = spam_payload["is_hidden"]

                    category = spam_payload.get("category")
                    meta["spam_reasons"] = [category] if category else []

                    # Populate other_project name for downstream filtering and UI grouping
                    if category == "other_projects":
                        detected_project = extract_other_project(email.subject or "")
                        if detected_project:
                            meta["other_project"] = detected_project
                        else:
                            meta.setdefault("other_project", None)
                    email.meta = meta

                    stats["processed"] += 1

                    if result["is_spam"]:
                        stats["spam_detected"] += 1
                        category = result["category"] or "unknown"
                        stats["by_category"][category] = (
                            stats["by_category"].get(category, 0) + 1
                        )

                        if computed_is_hidden:
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
                state="PROGRESS",
                meta={
                    "current": offset,
                    "total": total_count,
                    "percent": progress,
                    "spam_detected": stats["spam_detected"],
                    "hidden": stats["hidden"],
                },
            )

        logger.info(
            f"Spam filter complete for {entity_type} {entity_id}: "
            f"{stats['spam_detected']} spam detected, {stats['hidden']} hidden"
        )

        # Cascade spam classification to evidence items
        evidence_cascade_stats = cascade_spam_to_evidence(db, entity_id, entity_type)
        stats["evidence_cascaded"] = evidence_cascade_stats.get("updated", 0)
        stats["evidence_restored"] = evidence_cascade_stats.get("restored", 0)

        logger.info(
            f"Evidence cascade complete: {stats['evidence_cascaded']} hidden, "
            f"{stats['evidence_restored']} restored"
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


@celery_app.task(bind=True, name="apply_email_dedupe_batch")
def apply_email_dedupe_batch(
    self,
    project_id: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Background task to deduplicate emails for a project or case."""

    from .db import SessionLocal
    from .email_dedupe import dedupe_emails

    entity_type = "project" if project_id else "case"
    entity_id = project_id or case_id

    if not entity_id:
        return {"status": "failed", "error": "Must provide project_id or case_id"}

    logger.info("Starting email dedupe for %s %s", entity_type, entity_id)

    db = SessionLocal()
    try:
        stats = dedupe_emails(
            db,
            case_id=case_id,
            project_id=project_id,
            run_id="dedupe_batch",
        )
        result = {
            "emails_total": stats.emails_total,
            "duplicates_found": stats.duplicates_found,
            "groups_matched": stats.groups_matched,
            "decisions_recorded": stats.decisions_recorded,
        }
        logger.info(
            "Email dedupe complete for %s %s: %s duplicates",
            entity_type,
            entity_id,
            result["duplicates_found"],
        )
        return {"status": "completed", "stats": result}
    except Exception as e:
        logger.exception("Email dedupe failed for %s %s: %s", entity_type, entity_id, e)
        db.rollback()
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="link_emails_to_programme_activities")
def link_emails_to_programme_activities_task(
    self,
    project_id: str | None = None,
    case_id: str | None = None,
    overwrite_existing: bool = False,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Background task to link emails to programme activities.

    For each email, uses EmailMessage.date_sent to pick the active activity in a
    baseline (as-planned) programme and a current (as-built/current) programme.

    Persists:
    - EmailMessage.as_planned_activity
    - EmailMessage.as_planned_finish_date
    - EmailMessage.as_built_activity
    - EmailMessage.as_built_finish_date
    - EmailMessage.delay_days (built - planned)

    Notes:
    - When project-level programmes are not present, the task attempts to infer a
      single case_id from the project's emails and link using case-level programmes.
    """

    from .db import SessionLocal
    from .programme_linking import link_emails_to_programme_activities

    entity_type = "project" if project_id else "case"
    entity_id = project_id or case_id

    if not entity_id:
        return {"status": "failed", "error": "Must provide project_id or case_id"}

    logger.info(
        "Starting programme-linking for %s %s (overwrite_existing=%s)",
        entity_type,
        entity_id,
        overwrite_existing,
    )

    db = SessionLocal()
    try:

        def _progress(done: int, total: int) -> None:
            if total <= 0:
                percent = 100
            else:
                percent = int((done / total) * 100)
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": done,
                    "total": total,
                    "percent": percent,
                },
            )

        stats = link_emails_to_programme_activities(
            db=db,
            project_id=project_id,
            case_id=case_id,
            overwrite_existing=overwrite_existing,
            batch_size=batch_size,
            progress_cb=_progress,
        )

        logger.info(
            "Programme-linking complete for %s %s: %s updated, %s processed",
            entity_type,
            entity_id,
            stats.get("updated"),
            stats.get("processed"),
        )
        return stats

    except Exception as e:
        logger.exception(
            "Programme-linking failed for %s %s: %s", entity_type, entity_id, e
        )
        db.rollback()
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, name="apply_contract_intelligence_batch")
def apply_contract_intelligence_batch(
    self,
    project_id: str | None = None,
    case_id: str | None = None,
    batch_size: int = 100,
) -> dict[str, Any]:
    """
    Background task to apply contract intelligence to emails.

    Analyzes emails for contract clauses, risks, and entitlements.

    Args:
        project_id: UUID of the project (optional)
        case_id: UUID of the case (optional)
        batch_size: Number of emails to process per batch

    Returns:
        Dict with analysis statistics
    """
    from .db import SessionLocal
    from .models import EmailMessage, Case
    from .contract_intelligence.models import ProjectContract
    from .contract_intelligence.auto_tagger import auto_tagger
    from sqlalchemy import func
    import uuid

    entity_type = "project" if project_id else "case"
    entity_id = project_id or case_id

    if not entity_id:
        return {"status": "failed", "error": "Must provide project_id or case_id"}

    logger.info(
        f"Starting contract intelligence analysis for {entity_type} {entity_id}"
    )

    db = SessionLocal()
    stats = {
        "total_emails": 0,
        "processed": 0,
        "risks_identified": 0,
        "entitlements_identified": 0,
        "errors": 0,
    }

    try:
        project_contract = None

        # Build query based on entity type
        if project_id:
            base_filter = EmailMessage.project_id == uuid.UUID(project_id)
            # Find active contract for this project
            project_contract = (
                db.query(ProjectContract)
                .filter(
                    ProjectContract.project_id == uuid.UUID(project_id),
                    ProjectContract.is_active == True,
                )
                .first()
            )
        else:
            base_filter = EmailMessage.case_id == uuid.UUID(case_id)
            # Find project from case to get contract
            case = db.query(Case).get(uuid.UUID(case_id))
            if case and case.project_id:
                project_contract = (
                    db.query(ProjectContract)
                    .filter(
                        ProjectContract.project_id == case.project_id,
                        ProjectContract.is_active == True,
                    )
                    .first()
                )

        if not project_contract:
            logger.warning(f"No active contract found for {entity_type} {entity_id}")
            return {"status": "skipped", "reason": "No active contract found"}

        # Get total count
        total_count = (
            db.query(func.count(EmailMessage.id)).filter(base_filter).scalar()
        ) or 0

        stats["total_emails"] = total_count
        logger.info(f"Found {total_count} emails to analyze for contract intelligence")

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
                    analysis = auto_tagger.analyze_correspondence(
                        db, email, project_contract
                    )
                    if analysis:
                        stats["processed"] += 1
                        if analysis.risk_score and analysis.risk_score > 0:
                            stats["risks_identified"] += 1
                        if (
                            analysis.entitlement_score
                            and analysis.entitlement_score > 0
                        ):
                            stats["entitlements_identified"] += 1

                except Exception as e:
                    logger.warning(f"Failed to analyze email {email.id}: {e}")
                    stats["errors"] += 1

            offset += batch_size

            # Update task progress
            progress = int((offset / total_count) * 100)
            self.update_state(
                state="PROGRESS",
                meta={
                    "current": offset,
                    "total": total_count,
                    "percent": progress,
                    "risks": stats["risks_identified"],
                },
            )

        logger.info(f"Contract intelligence analysis complete: {stats}")
        return {"status": "completed", "stats": stats}

    except Exception as e:
        logger.exception(f"Contract intelligence analysis failed: {e}")
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()
