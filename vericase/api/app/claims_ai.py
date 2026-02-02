"""
Claims Module - AI Collaboration, Reactions, Pinning, Read/Unread, Notification Preferences

Endpoints for AI-powered claim analysis (summarize, suggest evidence, draft reply,
auto-tag), comment reactions, comment pinning, read/unread status tracking,
and user notification preferences.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .db import get_db
from .security import current_user
from .models import (
    User,
    HeadOfClaim,
    ItemClaimLink,
    ItemComment,
    EvidenceItem,
    CommentReaction,
    CommentReadStatus,
    UserNotificationPreferences,
)
from .ai_runtime import complete_chat
from .ai_settings import get_ai_api_key
from .deep_research import start_research, StartResearchRequest
from .claims_schemas import (
    AISummarizeRequest,
    AISuggestEvidenceRequest,
    AIDraftReplyRequest,
    AIResponse,
    ReactionRequest,
    NotificationPreferencesUpdate,
    NotificationPreferencesResponse,
    ALLOWED_EMOJIS,
    _parse_uuid,
    _log_claim_activity,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims-ai"])


# ---------------------------------------------------------------------------
# AI Collaboration Endpoints
# ---------------------------------------------------------------------------


@router.post("/heads-of-claim/{claim_id}/research")
async def start_claim_research(
    claim_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Initialize a Deep Research session for this claim.
    Automatically gathers context from claim details and linked evidence.
    """
    claim_uuid = _parse_uuid(claim_id, "claim_id")
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()

    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Gather context
    topic = f"Investigate claim: {claim.name}"
    if claim.description:
        topic += f"\n\nClaim Description:\n{claim.description}"

    # Get linked items for context (reserved for future use)
    _links = (  # noqa: F841
        db.query(ItemClaimLink)
        .filter(
            ItemClaimLink.head_of_claim_id == claim_uuid,
            ItemClaimLink.status == "active",
        )
        .all()
    )

    focus_areas = []
    if claim.claim_type:
        focus_areas.append(f"Claim Type: {claim.claim_type}")
    if claim.supporting_contract_clause:
        focus_areas.append(f"Contract Clause: {claim.supporting_contract_clause}")

    # Create research request
    request = StartResearchRequest(
        topic=topic,
        project_id=str(claim.project_id) if claim.project_id else None,
        case_id=str(claim.case_id) if claim.case_id else None,
        focus_areas=focus_areas,
    )

    # Call deep research module
    return await start_research(
        request=request, background_tasks=background_tasks, user=user, db=db
    )


@router.post("/heads-of-claim/{claim_id}/ai/summarize")
async def ai_summarize_discussion(
    claim_id: str,
    request: AISummarizeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-powered summary of claim discussion threads"""

    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get all comments on this claim
    comments = (
        db.query(ItemComment)
        .filter(
            ItemComment.item_type == "claim",
            ItemComment.item_id == claim_uuid,
        )
        .order_by(ItemComment.created_at.desc())
        .all()
    )

    if not comments:
        return AIResponse(
            result="No discussion to summarize yet.",
            tokens_used=0,
            model_used=None,
        )

    # Build discussion text
    discussion_parts = []
    for comment in comments:
        creator = db.query(User).filter(User.id == comment.created_by).first()
        creator_name = creator.display_name or creator.email if creator else "Unknown"
        discussion_parts.append(f"[{creator_name}]: {comment.content}")

    discussion_text = "\n".join(discussion_parts)

    system_prompt = """You are an assistant summarizing legal claim discussions.
Provide a concise summary highlighting:
1. Key discussion points
2. Any decisions or agreements reached
3. Outstanding questions or action items
Keep the summary professional and factual."""

    prompt = f"""Summarize this discussion about claim "{claim.name}" (Reference: {claim.reference_number or "N/A"}):

{discussion_text}

Provide a summary in no more than {request.max_length} words."""

    try:
        # Try to get an API key and make the call
        api_key = get_ai_api_key("openai", db) or get_ai_api_key("anthropic", db)
        if not api_key:
            raise HTTPException(503, "No AI provider configured")

        provider = "openai" if get_ai_api_key("openai", db) else "anthropic"
        model = "gpt-5-mini" if provider == "openai" else "claude-4.5-haiku"

        result = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=prompt,
            system_prompt=system_prompt,
            db=db,
            max_tokens=1000,
            temperature=0.3,
        )

        return AIResponse(
            result=result,
            model_used=f"{provider}/{model}",
        )
    except Exception as e:
        logger.error(f"AI summarize failed: {e}")
        raise HTTPException(503, f"AI service unavailable: {str(e)}")


@router.post("/heads-of-claim/{claim_id}/ai/suggest-evidence")
async def ai_suggest_evidence(
    claim_id: str,
    request: AISuggestEvidenceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-powered evidence suggestions based on claim discussion"""

    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get recent comments for context
    comments = (
        db.query(ItemComment)
        .filter(
            ItemComment.item_type == "claim",
            ItemComment.item_id == claim_uuid,
        )
        .order_by(ItemComment.created_at.desc())
        .limit(10)
        .all()
    )

    comment_text = "\n".join([c.content for c in comments]) if comments else ""

    # Get already linked evidence
    linked = (
        db.query(ItemClaimLink)
        .filter(
            ItemClaimLink.head_of_claim_id == claim_uuid,
            ItemClaimLink.status == "active",
        )
        .all()
    )
    linked_ids = {str(link.item_id) for link in linked}

    # Get available evidence not yet linked
    available_evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.project_id == claim.project_id)
        .limit(50)
        .all()
    )

    evidence_list = []
    for ev in available_evidence:
        if str(ev.id) not in linked_ids:
            evidence_list.append(
                f"- {ev.title or ev.filename} (Type: {ev.document_type or 'Unknown'})"
            )

    if not evidence_list:
        return AIResponse(
            result="No additional evidence available to suggest.",
            model_used=None,
        )

    system_prompt = """You are a legal research assistant helping identify relevant evidence for claims.
Based on the claim details and discussion, suggest which evidence items would be most relevant to link."""

    prompt = f"""Claim: {claim.name}
Type: {claim.claim_type or "General"}
Description: {claim.description or "N/A"}
Contract Clause: {claim.supporting_contract_clause or "N/A"}

Recent Discussion:
{comment_text or "No discussion yet"}

Additional Context: {request.context or "None provided"}

Available Evidence (not yet linked):
{chr(10).join(evidence_list[:20])}

Suggest which evidence items should be linked to this claim and why. Format as a numbered list."""

    try:
        api_key = get_ai_api_key("openai", db) or get_ai_api_key("anthropic", db)
        if not api_key:
            raise HTTPException(503, "No AI provider configured")

        provider = "openai" if get_ai_api_key("openai", db) else "anthropic"
        model = "gpt-5-mini" if provider == "openai" else "claude-4.5-haiku"

        result = await complete_chat(
            provider=provider,
            model_id=model,
            prompt=prompt,
            system_prompt=system_prompt,
            db=db,
            max_tokens=1000,
            temperature=0.3,
        )

        return AIResponse(
            result=result,
            model_used=f"{provider}/{model}",
        )
    except Exception as e:
        logger.error(f"AI suggest evidence failed: {e}")
        raise HTTPException(503, f"AI service unavailable: {str(e)}")


@router.post("/heads-of-claim/{claim_id}/ai/draft-reply")
async def ai_draft_reply(
    claim_id: str,
    request: AIDraftReplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-assisted reply drafting for claim discussions"""

    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Get recent comments
    comments = (
        db.query(ItemComment)
        .filter(
            ItemComment.item_type == "claim",
            ItemComment.item_id == claim_uuid,
        )
        .order_by(ItemComment.created_at.desc())
        .limit(5)
        .all()
    )

    recent_discussion = []
    for comment in reversed(comments):
        creator = db.query(User).filter(User.id == comment.created_by).first()
        creator_name = creator.display_name or creator.email if creator else "Unknown"
        recent_discussion.append(f"[{creator_name}]: {comment.content}")

    tone_guidance = {
        "professional": "Use a professional, clear tone suitable for business communication.",
        "formal": "Use formal language appropriate for legal/official correspondence.",
        "casual": "Use a friendly but professional tone.",
    }

    system_prompt = f"""You are an assistant helping draft replies in claim discussions.
{tone_guidance.get(request.tone, tone_guidance["professional"])}
Draft a thoughtful response that addresses the discussion points."""

    prompt = f"""Claim: {claim.name}
Type: {claim.claim_type or "General"}

Recent Discussion:
{chr(10).join(recent_discussion) or "No prior discussion"}

Context for reply: {request.context or "General response needed"}

Draft a reply for the current user to post. Keep it concise but comprehensive."""

    try:
        result = await complete_chat(
            provider="gemini",
            model_id="gemini-2.0-flash",
            prompt=prompt,
            system_prompt=system_prompt,
            db=db,
            max_tokens=500,
        )

        return AIResponse(
            result=result,
            model_used="gemini/gemini-2.0-flash",
        )
    except Exception as e:
        logger.error(f"AI draft reply failed: {e}")
        raise HTTPException(503, f"AI service unavailable: {str(e)}")


@router.post("/comments/{comment_id}/ai/auto-tag")
async def ai_auto_tag_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI-powered auto-tagging of comments - extracts dates, amounts, clauses, entities"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    if comment_uuid is None:
        return {"status": "error", "message": "Invalid comment ID"}

    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()

    if not comment:
        raise HTTPException(404, "Comment not found")

    content = comment.content
    tags = []

    # Extract dates (various formats)
    date_patterns = [
        r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b",
    ]
    for pattern in date_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            tags.append({"type": "date", "value": match})

    # Extract monetary amounts
    amount_patterns = [
        r"\xa3[\d,]+(?:\.\d{2})?(?:\s*[kmb])?",
        r"\$[\d,]+(?:\.\d{2})?(?:\s*[kmb])?",
        r"\u20ac[\d,]+(?:\.\d{2})?(?:\s*[kmb])?",
        r"\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:GBP|USD|EUR)\b",
    ]
    for pattern in amount_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            tags.append({"type": "amount", "value": match})

    # Extract clause references
    clause_patterns = [
        r"\b[Cc]lause\s+\d+(?:\.\d+)*\b",
        r"\b[Ss]ection\s+\d+(?:\.\d+)*\b",
        r"\xa7\s*\d+(?:\.\d+)*",
        r"\bArticle\s+\d+\b",
    ]
    for pattern in clause_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            tags.append({"type": "clause", "value": match})

    # Extract document references
    doc_patterns = [
        r"\b(?:DRG|DWG|VI|SI|RFI|CO|PCO)[-\s]?\d+\b",
        r"\b[A-Z]{2,4}-\d{3,6}\b",
    ]
    for pattern in doc_patterns:
        matches = re.findall(pattern, content)
        for match in matches:
            tags.append({"type": "reference", "value": match})

    # Remove duplicates
    seen = set()
    unique_tags = []
    for tag in tags:
        key = (tag["type"], tag["value"])
        if key not in seen:
            seen.add(key)
            unique_tags.append(tag)

    return {
        "comment_id": comment_id,
        "tags": unique_tags,
        "tag_count": len(unique_tags),
    }


# ---------------------------------------------------------------------------
# Comment Reactions Endpoints
# ---------------------------------------------------------------------------


@router.post("/comments/{comment_id}/reactions")
async def add_reaction(
    comment_id: str,
    request: ReactionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Add a reaction to a comment"""
    if request.emoji not in ALLOWED_EMOJIS:
        raise HTTPException(400, f"Invalid emoji. Allowed: {', '.join(ALLOWED_EMOJIS)}")

    comment_uuid = _parse_uuid(comment_id, "comment_id")

    if comment_uuid is None:
        raise HTTPException(404, "Comment not found")

    # Verify comment exists
    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()
    if not comment:
        raise HTTPException(404, "Comment not found")

    # Check if user already has this reaction
    existing = (
        db.query(CommentReaction)
        .filter(
            CommentReaction.comment_id == comment_uuid,
            CommentReaction.user_id == user.id,
            CommentReaction.emoji == request.emoji,
        )
        .first()
    )

    if existing:
        # Remove existing reaction (toggle off)
        db.delete(existing)
        db.commit()
        action = "removed"
    else:
        # Add new reaction
        reaction = CommentReaction(
            comment_id=comment_uuid,
            user_id=user.id,
            emoji=request.emoji,
        )
        db.add(reaction)
        db.commit()
        action = "added"

    # Get updated reaction counts
    reaction_groups = (
        db.query(CommentReaction.emoji, func.count(CommentReaction.id))
        .filter(CommentReaction.comment_id == comment_uuid)
        .group_by(CommentReaction.emoji)
        .all()
    )

    reactions = []
    for group in reaction_groups:
        reactions.append(
            {
                "emoji": group[0],
                "count": group[1],
                "users": [
                    user.display_name or user.email
                    for user in (db.query(User).filter(User.id == group.user_id).all())
                ],
                "user_reacted": any(
                    r.emoji == request.emoji and r.user_id == user.id
                    for r in comment.reactions
                ),
            }
        )

    return {
        "status": action,
        "emoji": request.emoji,
        "reactions": reactions,
    }


@router.delete("/comments/{comment_id}/reactions/{emoji}")
async def remove_reaction(
    comment_id: str,
    emoji: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Remove a reaction from a comment"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    reaction = (
        db.query(CommentReaction)
        .filter(
            CommentReaction.comment_id == comment_uuid,
            CommentReaction.user_id == user.id,
            CommentReaction.emoji == emoji,
        )
        .first()
    )

    if not reaction:
        raise HTTPException(404, "Reaction not found")

    db.delete(reaction)
    db.commit()

    reaction_groups = (
        db.query(CommentReaction.emoji, func.count(CommentReaction.id))
        .filter(CommentReaction.comment_id == comment_uuid)
        .group_by(CommentReaction.emoji)
        .all()
    )

    # Check if current user still has a reaction on this comment
    user_reactions = (
        db.query(CommentReaction.emoji)
        .filter(
            CommentReaction.comment_id == comment_uuid,
            CommentReaction.user_id == user.id,
        )
        .all()
    )
    user_emojis = {r[0] for r in user_reactions}

    reactions = []
    for group in reaction_groups:
        reactions.append(
            {
                "emoji": group[0],
                "count": group[1],
                "users": [],
                "user_reacted": group[0] in user_emojis,
            }
        )

    return {
        "status": "removed",
        "emoji": emoji,
        "reactions": reactions,
    }


@router.get("/comments/{comment_id}/reactions")
async def get_reactions(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get all reactions for a comment"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    reactions = (
        db.query(CommentReaction)
        .filter(
            CommentReaction.comment_id == comment_uuid,
        )
        .all()
    )

    return {"comment_id": comment_id, "reactions": reactions}


# ---------------------------------------------------------------------------
# Comment Pinning Endpoints
# ---------------------------------------------------------------------------


@router.post("/comments/{comment_id}/pin")
async def pin_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Pin a comment to the top of the thread"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()
    if not comment:
        raise HTTPException(404, "Comment not found")

    # Only allow pinning on claim-level comments (not evidence)
    if comment.item_type != "claim":
        raise HTTPException(400, "Only claim discussion comments can be pinned")

    # Toggle pin status
    if comment.is_pinned:
        comment.is_pinned = False
        comment.pinned_at = None
        comment.pinned_by = None
        action = "unpinned"
    else:
        comment.is_pinned = True
        comment.pinned_at = datetime.utcnow()
        comment.pinned_by = user.id

        # Log activity
        if comment.item_id:
            _log_claim_activity(
                db,
                action="comment.pinned",
                claim_id=comment.item_id,
                user_id=user.id,
                details={"comment_id": str(comment.id)},
            )
        action = "pinned"

    db.commit()

    return {
        "comment_id": comment_id,
        "is_pinned": comment.is_pinned,
        "status": action,
    }


@router.delete("/comments/{comment_id}/pin")
async def unpin_comment(
    comment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Unpin a comment"""
    comment_uuid = _parse_uuid(comment_id, "comment_id")

    comment = db.query(ItemComment).filter(ItemComment.id == comment_uuid).first()
    if not comment:
        raise HTTPException(404, "Comment not found")

    if not comment.is_pinned:
        raise HTTPException(400, "Comment is not pinned")

    comment.is_pinned = False
    comment.pinned_at = None
    comment.pinned_by = None

    db.commit()

    return {"comment_id": comment_id, "is_pinned": False, "status": "unpinned"}


# ---------------------------------------------------------------------------
# Read/Unread Status Endpoints
# ---------------------------------------------------------------------------


@router.post("/heads-of-claim/{claim_id}/mark-read")
async def mark_claim_read(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Mark all comments on a claim as read for the current user"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Verify claim exists
    claim = db.query(HeadOfClaim).filter(HeadOfClaim.id == claim_uuid).first()
    if not claim:
        raise HTTPException(404, "Head of claim not found")

    # Upsert read status
    read_status = (
        db.query(CommentReadStatus)
        .filter(
            CommentReadStatus.user_id == user.id,
            CommentReadStatus.claim_id == claim_uuid,
        )
        .first()
    )

    if read_status:
        read_status.last_read_at = datetime.utcnow()
    else:
        read_status = CommentReadStatus(
            user_id=user.id,
            claim_id=claim_uuid,
            last_read_at=datetime.utcnow(),
        )
        db.add(read_status)

    db.commit()

    return {
        "claim_id": claim_id,
        "last_read_at": read_status.last_read_at.isoformat(),
        "status": "marked_read",
    }


@router.get("/heads-of-claim/{claim_id}/unread-count")
async def get_unread_count(
    claim_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get count of unread comments for a claim"""
    claim_uuid = _parse_uuid(claim_id, "claim_id")

    # Get user's last read timestamp
    read_status = (
        db.query(CommentReadStatus)
        .filter(
            CommentReadStatus.user_id == user.id,
            CommentReadStatus.claim_id == claim_uuid,
        )
        .first()
    )

    last_read = read_status.last_read_at if read_status else None

    # Count comments after last_read
    query = db.query(func.count(ItemComment.id)).filter(
        ItemComment.item_type == "claim",
        ItemComment.item_id == claim_uuid,
    )

    if last_read:
        query = query.filter(ItemComment.created_at > last_read)

    unread_count = query.scalar() or 0

    return {
        "claim_id": claim_id,
        "unread_count": unread_count,
        "last_read_at": last_read.isoformat() if last_read else None,
    }


# ---------------------------------------------------------------------------
# User Notification Preferences Endpoints
# ---------------------------------------------------------------------------


@router.get("/notification-preferences")
async def get_notification_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Get current user's notification preferences"""
    prefs = (
        db.query(UserNotificationPreferences)
        .filter(UserNotificationPreferences.user_id == user.id)
        .first()
    )

    if not prefs:
        # Return defaults if no preferences set
        return NotificationPreferencesResponse(
            email_mentions=True,
            email_replies=True,
            email_claim_updates=True,
            email_daily_digest=False,
        )

    return NotificationPreferencesResponse(
        email_mentions=prefs.email_mentions,
        email_replies=prefs.email_replies,
        email_claim_updates=prefs.email_claim_updates,
        email_daily_digest=prefs.email_daily_digest,
    )


@router.put("/notification-preferences")
async def update_notification_preferences(
    request: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Update current user's notification preferences"""
    prefs = (
        db.query(UserNotificationPreferences)
        .filter(UserNotificationPreferences.user_id == user.id)
        .first()
    )

    if not prefs:
        prefs = UserNotificationPreferences(user_id=user.id)
        db.add(prefs)

    # Update only provided fields
    if request.email_mentions is not None:
        prefs.email_mentions = request.email_mentions
    if request.email_replies is not None:
        prefs.email_replies = request.email_replies
    if request.email_claim_updates is not None:
        prefs.email_claim_updates = request.email_claim_updates
    if request.email_daily_digest is not None:
        prefs.email_daily_digest = request.email_daily_digest

    db.commit()
    db.refresh(prefs)

    return NotificationPreferencesResponse(
        email_mentions=prefs.email_mentions,
        email_replies=prefs.email_replies,
        email_claim_updates=prefs.email_claim_updates,
        email_daily_digest=prefs.email_daily_digest,
    )