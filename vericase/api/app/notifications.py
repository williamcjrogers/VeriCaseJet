"""
Notification system for collaboration features.

Handles:
- @mention notifications via email
- Comment reply notifications
- Activity notifications
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from .email_service import email_service, FRONTEND_URL
from .models import User, HeadOfClaim, ItemComment

logger = logging.getLogger(__name__)


def parse_mentions(content: str) -> List[str]:
    """
    Extract @mentions from comment content.
    Supports formats: @username, @email@domain.com, @"Full Name"
    Returns list of identifiers (usernames or emails).
    """
    mentions = []

    # Pattern for @email format
    email_pattern = r"@([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
    email_matches = re.findall(email_pattern, content)
    mentions.extend(email_matches)

    # Pattern for @"Full Name" format
    quoted_pattern = r'@"([^"]+)"'
    quoted_matches = re.findall(quoted_pattern, content)
    mentions.extend(quoted_matches)

    # Pattern for @username (alphanumeric, no spaces)
    # Exclude emails already captured
    simple_pattern = r"@([a-zA-Z][a-zA-Z0-9_]{2,})"
    simple_matches = re.findall(simple_pattern, content)
    for match in simple_matches:
        if "@" not in match and match not in mentions:
            mentions.append(match)

    return list(set(mentions))  # Remove duplicates


def resolve_mentioned_users(db: Session, mentions: List[str]) -> List[User]:
    """
    Resolve mention identifiers to User objects.
    Looks up by email or display_name.
    """
    if not mentions:
        return []

    users = []
    for identifier in mentions:
        # Try email first
        user = db.query(User).filter(User.email == identifier.lower()).first()
        if user:
            users.append(user)
            continue

        # Try display_name
        user = db.query(User).filter(User.display_name == identifier).first()
        if user:
            users.append(user)

    return users


def send_mention_notification(
    db: Session,
    mentioned_user: User,
    author: User,
    comment: ItemComment,
    claim: Optional[HeadOfClaim] = None,
) -> bool:
    """
    Send email notification to a mentioned user.
    Returns True if notification was sent successfully.
    """
    if not mentioned_user.email:
        logger.warning(
            f"Cannot send mention notification - user {mentioned_user.id} has no email"
        )
        return False

    # Build context
    claim_name = claim.name if claim else "a discussion"
    claim_ref = claim.reference_number if claim else None
    author_name = author.display_name or author.email

    # Build link to the discussion
    claim_id = str(claim.id) if claim else ""
    discussion_link = f"{FRONTEND_URL}/ui/contentious-matters.html?claim={claim_id}"

    # Truncate comment preview
    comment_preview = comment.content[:200]
    if len(comment.content) > 200:
        comment_preview += "..."

    # Send email
    subject = f"[VeriCase] {author_name} mentioned you in {claim_name}"
    if claim_ref:
        subject = f"[VeriCase] {author_name} mentioned you in {claim_ref}"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #1a2b3c 0%, #2d4a5e 100%);
                        color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">You were mentioned</h2>
            </div>

            <div style="background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef; border-top: none;">
                <p>Hi {mentioned_user.display_name or mentioned_user.email.split('@')[0]},</p>

                <p><strong>{author_name}</strong> mentioned you in a comment on
                   <strong>{claim_name}</strong>{f' ({claim_ref})' if claim_ref else ''}:</p>

                <div style="background: white; border-left: 4px solid #667eea; padding: 15px;
                            margin: 20px 0; border-radius: 0 4px 4px 0;">
                    <p style="margin: 0; color: #333; font-style: italic;">
                        "{comment_preview}"
                    </p>
                </div>

                <p style="margin: 30px 0;">
                    <a href="{discussion_link}"
                       style="background: #667eea; color: white; padding: 12px 30px;
                              text-decoration: none; border-radius: 5px; display: inline-block;">
                        View Discussion
                    </a>
                </p>
            </div>

            <div style="background: #f1f3f4; padding: 15px; border-radius: 0 0 8px 8px;
                        border: 1px solid #e9ecef; border-top: none;">
                <p style="margin: 0; color: #666; font-size: 12px;">
                    This notification was sent because you were @mentioned.
                    You can manage notification preferences in your account settings.
                </p>
            </div>
        </body>
    </html>
    """

    text_content = f"""
You were mentioned in VeriCase

Hi {mentioned_user.display_name or mentioned_user.email.split('@')[0]},

{author_name} mentioned you in a comment on {claim_name}{f' ({claim_ref})' if claim_ref else ''}:

"{comment_preview}"

View the discussion: {discussion_link}

---
This notification was sent because you were @mentioned.
"""

    try:
        email_service._send_email(
            mentioned_user.email,
            subject,
            html_content,
            text_content,
        )
        logger.info(f"Mention notification sent to {mentioned_user.email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send mention notification: {e}")
        return False


def send_reply_notification(
    db: Session,
    original_author: User,
    replier: User,
    original_comment: ItemComment,
    reply_comment: ItemComment,
    claim: Optional[HeadOfClaim] = None,
) -> bool:
    """
    Send email notification when someone replies to a user's comment.
    """
    # Don't notify if replying to own comment
    if original_author.id == replier.id:
        return False

    if not original_author.email:
        return False

    claim_name = claim.name if claim else "a discussion"
    replier_name = replier.display_name or replier.email
    claim_id = str(claim.id) if claim else ""
    discussion_link = f"{FRONTEND_URL}/ui/contentious-matters.html?claim={claim_id}"

    # Truncate previews
    original_preview = original_comment.content[:100]
    if len(original_comment.content) > 100:
        original_preview += "..."

    reply_preview = reply_comment.content[:200]
    if len(reply_comment.content) > 200:
        reply_preview += "..."

    subject = f"[VeriCase] {replier_name} replied to your comment"

    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #1a2b3c 0%, #2d4a5e 100%);
                        color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">New reply to your comment</h2>
            </div>

            <div style="background: #f8f9fa; padding: 20px; border: 1px solid #e9ecef; border-top: none;">
                <p>Hi {original_author.display_name or original_author.email.split('@')[0]},</p>

                <p><strong>{replier_name}</strong> replied to your comment on
                   <strong>{claim_name}</strong>:</p>

                <div style="background: #e9ecef; padding: 10px 15px; margin: 15px 0;
                            border-radius: 4px; font-size: 13px; color: #666;">
                    <strong>Your comment:</strong> "{original_preview}"
                </div>

                <div style="background: white; border-left: 4px solid #38a169; padding: 15px;
                            margin: 15px 0; border-radius: 0 4px 4px 0;">
                    <p style="margin: 0; color: #333;">
                        <strong>{replier_name}:</strong> "{reply_preview}"
                    </p>
                </div>

                <p style="margin: 30px 0;">
                    <a href="{discussion_link}"
                       style="background: #667eea; color: white; padding: 12px 30px;
                              text-decoration: none; border-radius: 5px; display: inline-block;">
                        View Thread
                    </a>
                </p>
            </div>

            <div style="background: #f1f3f4; padding: 15px; border-radius: 0 0 8px 8px;
                        border: 1px solid #e9ecef; border-top: none;">
                <p style="margin: 0; color: #666; font-size: 12px;">
                    You received this because someone replied to your comment.
                </p>
            </div>
        </body>
    </html>
    """

    text_content = f"""
New reply to your comment

Hi {original_author.display_name or original_author.email.split('@')[0]},

{replier_name} replied to your comment on {claim_name}:

Your comment: "{original_preview}"

{replier_name}'s reply: "{reply_preview}"

View the thread: {discussion_link}

---
You received this because someone replied to your comment.
"""

    try:
        email_service._send_email(
            original_author.email,
            subject,
            html_content,
            text_content,
        )
        logger.info(f"Reply notification sent to {original_author.email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send reply notification: {e}")
        return False


def process_comment_notifications(
    db: Session,
    comment: ItemComment,
    author: User,
    claim: Optional[HeadOfClaim] = None,
) -> dict:
    """
    Process all notifications for a new comment:
    1. Parse @mentions and send notifications
    2. Send reply notification if this is a reply

    Returns summary of notifications sent.
    """
    result = {
        "mentions_found": [],
        "mentions_notified": [],
        "reply_notified": False,
    }

    # Process @mentions
    mentions = parse_mentions(comment.content)
    result["mentions_found"] = mentions

    if mentions:
        mentioned_users = resolve_mentioned_users(db, mentions)
        for user in mentioned_users:
            # Don't notify the author about their own mention
            if user.id != author.id:
                success = send_mention_notification(db, user, author, comment, claim)
                if success:
                    result["mentions_notified"].append(user.email)

    # Process reply notification
    if comment.parent_comment_id:
        parent = (
            db.query(ItemComment)
            .filter(ItemComment.id == comment.parent_comment_id)
            .first()
        )
        if parent and parent.created_by:
            original_author = (
                db.query(User).filter(User.id == parent.created_by).first()
            )
            if original_author:
                success = send_reply_notification(
                    db, original_author, author, parent, comment, claim
                )
                result["reply_notified"] = success

    return result
