"""
Claims Module - Shared Schemas, Constants, and Helpers

Pydantic models, type aliases, constants, and utility functions
shared across all claims sub-modules.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .security import current_user
from .models import User, CollaborationActivity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared type aliases
# ---------------------------------------------------------------------------

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_LANES = {"core", "counsel", "expert"}
ALLOWED_EMOJIS = ["\U0001f44d", "\U0001f44e", "\u2764\ufe0f", "\U0001f389", "\U0001f914", "\U0001f440"]

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _parse_uuid(value: Optional[str], field: str) -> Optional[uuid.UUID]:
    """Safely parse UUID strings and surface a 400 instead of 500 on bad input."""
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(value)
    except Exception:
        raise HTTPException(400, f"Invalid {field} format. Expected UUID.")


def _log_claim_activity(
    db: Session,
    action: str,
    claim_id: Optional[uuid.UUID] = None,
    user_id: uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    """Log an activity entry for a head of claim."""
    if claim_id is None:
        logger.warning("Skipping activity log due to missing claim_id")
        return

    activity = CollaborationActivity(
        action=action,
        resource_type="claim",
        resource_id=claim_id,
        user_id=user_id,
        details=details or {},
    )
    db.add(activity)


def _normalize_lane(lane: Optional[str], default_core: bool = True) -> Optional[str]:
    if lane is None or not str(lane).strip():
        return "core" if default_core else None
    normalized = str(lane).strip().lower()
    if normalized not in ALLOWED_LANES:
        allowed = ", ".join(sorted(ALLOWED_LANES))
        raise HTTPException(400, f"Invalid lane. Allowed: {allowed}")
    return normalized


# ---------------------------------------------------------------------------
# Pydantic Models - Contentious Matters
# ---------------------------------------------------------------------------


class ContentiousMatterCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    case_id: Optional[str] = None
    status: str = "active"
    priority: str = "normal"
    estimated_value: Optional[int] = None  # In cents/pence
    currency: str = "GBP"
    date_identified: Optional[datetime] = None


class ContentiousMatterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    estimated_value: Optional[int] = None
    currency: Optional[str] = None
    date_identified: Optional[datetime] = None
    resolution_date: Optional[datetime] = None


class ContentiousMatterResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    project_id: Optional[str]
    case_id: Optional[str]
    status: str
    priority: str
    estimated_value: Optional[int]
    currency: str
    date_identified: Optional[datetime]
    resolution_date: Optional[datetime]
    created_at: Optional[datetime]
    created_by: Optional[str]
    item_count: int = 0
    claim_count: int = 0


# ---------------------------------------------------------------------------
# Pydantic Models - Heads of Claim
# ---------------------------------------------------------------------------


class HeadOfClaimCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    case_id: Optional[str] = None
    contentious_matter_id: Optional[str] = None
    reference_number: Optional[str] = None
    claim_type: Optional[str] = None
    claimed_amount: Optional[int] = None  # In cents/pence
    currency: str = "GBP"
    status: str = "draft"
    submission_date: Optional[datetime] = None
    response_due_date: Optional[datetime] = None
    supporting_contract_clause: Optional[str] = None


class HeadOfClaimUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    contentious_matter_id: Optional[str] = None
    reference_number: Optional[str] = None
    claim_type: Optional[str] = None
    claimed_amount: Optional[int] = None
    awarded_amount: Optional[int] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    submission_date: Optional[datetime] = None
    response_due_date: Optional[datetime] = None
    determination_date: Optional[datetime] = None
    supporting_contract_clause: Optional[str] = None


class HeadOfClaimResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    project_id: Optional[str]
    case_id: Optional[str]
    contentious_matter_id: Optional[str]
    contentious_matter_name: Optional[str] = None
    reference_number: Optional[str]
    claim_type: Optional[str]
    claimed_amount: Optional[int]
    awarded_amount: Optional[int]
    currency: str
    status: str
    submission_date: Optional[datetime]
    response_due_date: Optional[datetime]
    determination_date: Optional[datetime]
    supporting_contract_clause: Optional[str]
    created_at: Optional[datetime]
    created_by: Optional[str]
    item_count: int = 0


# ---------------------------------------------------------------------------
# Pydantic Models - Item Links
# ---------------------------------------------------------------------------


class ItemLinkCreate(BaseModel):
    item_type: str  # 'correspondence' or 'evidence'
    item_id: str
    contentious_matter_id: Optional[str] = None
    head_of_claim_id: Optional[str] = None
    link_type: str = "supporting"  # supporting, contradicting, neutral, key
    relevance_score: Optional[int] = None
    notes: Optional[str] = None


class ItemLinkUpdate(BaseModel):
    link_type: Optional[str] = None
    relevance_score: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class ItemLinkResponse(BaseModel):
    id: str
    item_type: str
    item_id: str
    item_title: Optional[str] = None
    item_date: Optional[datetime] = None
    contentious_matter_id: Optional[str]
    contentious_matter_name: Optional[str] = None
    head_of_claim_id: Optional[str]
    head_of_claim_name: Optional[str] = None
    link_type: str
    relevance_score: Optional[int]
    notes: Optional[str]
    status: str
    created_at: Optional[datetime]
    created_by: Optional[str]
    comment_count: int = 0


# ---------------------------------------------------------------------------
# Pydantic Models - Comments
# ---------------------------------------------------------------------------


class CommentCreate(BaseModel):
    content: str
    item_claim_link_id: Optional[str] = None
    item_type: Optional[str] = None
    item_id: Optional[str] = None
    parent_comment_id: Optional[str] = None
    lane: Optional[str] = None


class CommentUpdate(BaseModel):
    content: str


class CommentResponse(BaseModel):
    id: str
    content: str
    item_claim_link_id: Optional[str]
    item_type: Optional[str]
    item_id: Optional[str]
    parent_comment_id: Optional[str]
    lane: str
    is_edited: bool
    edited_at: Optional[datetime]
    is_pinned: bool = False
    pinned_at: Optional[datetime] = None
    created_at: Optional[datetime]
    created_by: Optional[str]
    created_by_name: Optional[str] = None
    replies: List["CommentResponse"] = []


# ---------------------------------------------------------------------------
# Pydantic Models - Team Members
# ---------------------------------------------------------------------------


class TeamMemberResponse(BaseModel):
    id: str
    email: str
    display_name: Optional[str]


# ---------------------------------------------------------------------------
# Pydantic Models - AI Collaboration
# ---------------------------------------------------------------------------


class AISummarizeRequest(BaseModel):
    max_length: Optional[int] = 500


class AISuggestEvidenceRequest(BaseModel):
    context: Optional[str] = None


class AIDraftReplyRequest(BaseModel):
    context: Optional[str] = None
    tone: str = "professional"  # professional, formal, casual


class AIAutoTagRequest(BaseModel):
    content: str


class AIResponse(BaseModel):
    result: str
    tokens_used: Optional[int] = None
    model_used: Optional[str] = None


# ---------------------------------------------------------------------------
# Pydantic Models - Reactions
# ---------------------------------------------------------------------------


class ReactionRequest(BaseModel):
    emoji: str


class ReactionResponse(BaseModel):
    emoji: str
    count: int
    users: List[str]  # User emails/names who reacted
    user_reacted: bool  # Whether current user has this reaction


# ---------------------------------------------------------------------------
# Pydantic Models - Notification Preferences
# ---------------------------------------------------------------------------


class NotificationPreferencesUpdate(BaseModel):
    email_mentions: Optional[bool] = None
    email_replies: Optional[bool] = None
    email_claim_updates: Optional[bool] = None
    email_daily_digest: Optional[bool] = None


class NotificationPreferencesResponse(BaseModel):
    email_mentions: bool
    email_replies: bool
    email_claim_updates: bool
    email_daily_digest: bool
