"""
Hybrid Spam Filter - FAST classification with optional AI fallback.

This module provides blazing-fast email spam classification by:
1. Using the regex-based SpamClassifier FIRST (microseconds per email)
2. Only calling AI for genuinely uncertain cases (optional, configurable)

Performance improvement: ~1000x faster than pure AI filtering.
- Regex: ~0.001s per email
- AI API: ~1-2s per email

For 26,000 emails:
- Pure AI: ~7-14 hours
- Hybrid: ~30 seconds for regex + minimal AI calls
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .spam_filter import SpamResult, get_spam_classifier

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Configuration
AI_FALLBACK_ENABLED = False  # Set to True to enable AI for uncertain cases
AI_THRESHOLD_SCORE = 40  # Only use AI for scores between 20-60 (uncertain)


def classify_email_fast(
    subject: str,
    sender: str,
    body_preview: str,
    db: "Session | None" = None,
) -> SpamResult:
    """
    FAST spam classification using regex patterns.

    This is the primary classifier for PST processing.
    Uses pre-compiled regex patterns for instant classification.

    Args:
        subject: Email subject line
        sender: Sender email address
        body_preview: Body text (currently not used by regex classifier)
        db: Database session (only needed if AI fallback enabled)

    Returns:
        SpamResult with classification details
    """
    classifier = get_spam_classifier()
    result = classifier.classify(subject=subject, sender=sender, body=body_preview)

    # Add fields expected by the AI version
    enriched_result: SpamResult = {
        "is_spam": result["is_spam"],
        "score": result["score"],
        "category": result["category"],
        "is_hidden": result["is_hidden"],
        "explanation": f"Regex classification: {result['category'] or 'clean'}",
        "extracted_entity": None,
    }

    # Extract other_project entity if category matches
    if result["category"] == "other_projects":
        from .spam_filter import extract_other_project

        enriched_result["extracted_entity"] = extract_other_project(subject)

    # Optional AI fallback for uncertain scores (disabled by default for speed)
    if AI_FALLBACK_ENABLED and db is not None:
        score = result["score"]
        # Only call AI for uncertain cases (score between 20-60)
        if 20 <= score <= 60:
            try:
                from .ai_spam_filter import classify_email_ai_sync

                ai_result = classify_email_ai_sync(subject, sender, body_preview, db)
                # Blend the results - AI takes precedence for uncertain cases
                enriched_result = ai_result
                enriched_result["explanation"] = f"AI verified (was score {score})"
            except Exception as e:
                logger.debug(f"AI fallback failed, using regex result: {e}")

    return enriched_result


def classify_email_batch_fast(
    emails: list[dict[str, str | None]],
    db: "Session | None" = None,
) -> list[SpamResult]:
    """
    Batch classify emails using fast regex patterns.

    Args:
        emails: List of dicts with 'subject', 'sender', 'body' keys
        db: Database session (optional, for AI fallback)

    Returns:
        List of SpamResult for each email
    """
    return [
        classify_email_fast(
            subject=e.get("subject") or "",
            sender=e.get("sender") or "",
            body_preview=e.get("body") or "",
            db=db,
        )
        for e in emails
    ]


# Provide the same interface as ai_spam_filter for drop-in replacement
classify_email_ai_sync = classify_email_fast
