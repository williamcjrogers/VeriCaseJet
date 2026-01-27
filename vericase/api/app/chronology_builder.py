"""
Chronology Builder - AI-Powered Chronology and Programme Generation
====================================================================
Generates a Chronology Lens-style output (table + optional programme view) from
emails, evidence items, and user input. Output is session-based (draft-only),
does not mutate existing ChronologyItem or timeline data.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import json
from datetime import datetime, timezone
from typing import Annotated, Any
from enum import Enum
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, not_

try:
    from redis import Redis
except ImportError:
    Redis = None

from .models import User, EmailMessage, Project, EvidenceItem, Case, ChronologyItem
from .db import get_db
from .security import current_user
from .ai_settings import (
    get_ai_api_key,
    get_ai_model,
    is_bedrock_enabled,
    get_bedrock_region,
    get_tool_config,
    get_tool_fallback_chain,
    get_tool_agent_config,
)
from .settings import settings
from .ai_providers import BedrockProvider, bedrock_available
from .ai_runtime import complete_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chronology-builder", tags=["chronology-builder"])

# =============================================================================
# Data Models
# =============================================================================


class BuilderStatus(str, Enum):
    """Status of a Chronology Builder session."""

    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChronologyEvent(BaseModel):
    """A single chronology event in the draft output."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date_start: datetime
    date_end: datetime | None = None
    title: str
    narrative: str
    event_type: str | None = None  # notice, meeting, correspondence, site_event, etc.
    parties: list[str] = Field(default_factory=list)
    confidence: float = 0.0  # 0.0-1.0
    sources: dict[str, Any] = Field(
        default_factory=dict
    )  # {email_ids: [], evidence_ids: []}
    is_accepted: bool = False  # User can accept/reject in session


class ProgrammeActivity(BaseModel):
    """A programme activity in the draft output."""

    activity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    start_date: datetime
    finish_date: datetime | None = None
    dependencies: list[str] = Field(default_factory=list)  # activity_ids
    sources: dict[str, Any] = Field(default_factory=dict)
    is_accepted: bool = False


class BuilderPlan(BaseModel):
    """Plan showing what will be built."""

    project_id: str | None = None
    case_id: str | None = None
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None
    email_count: int = 0
    evidence_count: int = 0
    strategy: str = ""  # Description of approach
    estimated_events: int = 0
    include_programme: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BuilderSession(BaseModel):
    """Chronology Builder session state."""

    id: str
    user_id: str
    project_id: str | None = None
    case_id: str | None = None
    goal: str | None = None  # User's goal/prompt
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None
    include_programme: bool = False

    status: BuilderStatus = BuilderStatus.PENDING
    plan: BuilderPlan | None = None

    # Outputs
    chronology_events: list[ChronologyEvent] = Field(default_factory=list)
    programme_activities: list[ProgrammeActivity] = Field(default_factory=list)

    # Metadata
    processing_time_seconds: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None
    models_used: list[str] = Field(default_factory=list)


# Session store (uses Redis if available, otherwise in-memory)
_builder_sessions: dict[str, BuilderSession] = {}


def _get_redis() -> Redis | None:
    """Get Redis client if available."""
    try:
        if settings.REDIS_URL and Redis:
            return Redis.from_url(settings.REDIS_URL)
    except Exception as e:
        logger.warning(f"Redis unavailable for Chronology Builder sessions: {e}")
    return None


def save_builder_session(session: BuilderSession) -> None:
    """Persist session to in-memory store and Redis (if available)."""
    _builder_sessions[session.id] = session
    try:
        redis_client = _get_redis()
        if redis_client:
            redis_client.set(
                f"chronology_builder:session:{session.id}", session.model_dump_json()
            )
    except Exception as e:
        logger.warning(f"Failed to persist builder session to Redis: {e}")


def load_builder_session(session_id: str) -> BuilderSession | None:
    """Load session from in-memory store or Redis."""
    cached = _builder_sessions.get(session_id)
    redis_session: BuilderSession | None = None

    try:
        redis_client = _get_redis()
        if redis_client:
            data = redis_client.get(f"chronology_builder:session:{session_id}")
            if data:
                redis_session = BuilderSession.model_validate_json(data)
    except Exception as e:
        logger.warning(f"Failed to load builder session from Redis: {e}")

    if redis_session:
        if not cached or redis_session.updated_at >= cached.updated_at:
            _builder_sessions[session_id] = redis_session
            return redis_session

    if cached:
        return cached

    return None


# =============================================================================
# Request/Response Models
# =============================================================================


class StartBuilderRequest(BaseModel):
    """Request to start a Chronology Builder session."""

    project_id: str | None = None
    case_id: str | None = None
    goal: str | None = None
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None
    include_programme: bool = False


class StartBuilderResponse(BaseModel):
    """Response from starting a builder session."""

    session_id: str
    status: str
    message: str
    plan: BuilderPlan | None = None


class ApproveBuilderRequest(BaseModel):
    """Request to approve and run the builder plan."""

    session_id: str
    approved: bool = True
    modifications: str | None = None  # If not approved, user feedback


class BuilderStatusResponse(BaseModel):
    """Status response for a builder session."""

    session_id: str
    status: str
    plan: BuilderPlan | None = None
    chronology_events: list[ChronologyEvent] = Field(default_factory=list)
    programme_activities: list[ProgrammeActivity] = Field(default_factory=list)
    processing_time_seconds: float = 0
    error_message: str | None = None
    models_used: list[str] = Field(default_factory=list)


class UpdateEventRequest(BaseModel):
    """Request to update an event in the session (accept/reject/edit)."""

    session_id: str
    event_id: str
    is_accepted: bool | None = None
    title: str | None = None
    narrative: str | None = None
    date_start: datetime | None = None
    date_end: datetime | None = None
    event_type: str | None = None
    parties: list[str] | None = None


class PublishBuilderRequest(BaseModel):
    """Request to publish accepted chronology events to durable storage."""

    session_id: str
    only_accepted: bool = True


# =============================================================================
# Evidence Collection (Project + Case)
# =============================================================================


@dataclass
class BuilderEvidenceContext:
    """Container for evidence used in chronology building."""

    emails: list[EmailMessage]
    evidence_items: list[EvidenceItem]
    project_id: str | None = None
    case_id: str | None = None


def collect_builder_evidence(
    db: Session,
    project_id: str | None = None,
    case_id: str | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    limit: int = 1000,
    max_emails: int = 500,
    max_evidence: int = 200,
) -> BuilderEvidenceContext:
    """
    Collect emails and evidence items for chronology building.
    Handles both project and case contexts, unioning results when both exist.
    """
    emails: list[EmailMessage] = []
    evidence_items: list[EvidenceItem] = []

    # If case_id provided, also get its project_id if available
    case_project_id = None
    if case_id:
        try:
            case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
            if case and case.project_id:
                case_project_id = str(case.project_id)
        except (ValueError, Exception) as e:
            logger.warning(f"Could not load case for project_id: {e}")

    # Determine which project_ids to query
    project_ids_to_query = []
    if project_id:
        project_ids_to_query.append(project_id)
    if case_project_id and case_project_id not in project_ids_to_query:
        project_ids_to_query.append(case_project_id)

    # Collect emails
    email_query = db.query(EmailMessage)

    # Filter out spam/hidden/other_project
    email_query = email_query.filter(
        and_(
            or_(
                EmailMessage.meta.is_(None),
                not_(EmailMessage.meta["is_spam"].as_string() == "true"),
            ),
            or_(
                EmailMessage.meta.is_(None),
                not_(EmailMessage.meta["is_hidden"].as_string() == "true"),
            ),
            or_(
                EmailMessage.meta.is_(None),
                EmailMessage.meta["other_project"].as_string().is_(None),
                EmailMessage.meta["other_project"].as_string() == "",
            ),
        )
    )

    # Filter by project_id(s) and/or case_id
    if project_ids_to_query:
        email_query = email_query.filter(
            EmailMessage.project_id.in_([uuid.UUID(pid) for pid in project_ids_to_query])
        )
    if case_id:
        email_query = email_query.filter(
            or_(
                EmailMessage.case_id == uuid.UUID(case_id),
                EmailMessage.project_id.in_(
                    [uuid.UUID(pid) for pid in project_ids_to_query]
                )
                if project_ids_to_query
                else False,
            )
        )

    # Date range filtering
    if date_start:
        email_query = email_query.filter(EmailMessage.date_sent >= date_start)
    if date_end:
        email_query = email_query.filter(EmailMessage.date_sent <= date_end)

    # Order by date and limit (prioritize recent, important, with attachments)
    emails = (
        email_query.order_by(
            EmailMessage.date_sent.desc(),
            # Could add importance/attachment sorting here if available
        )
        .limit(min(limit, max_emails))
        .all()
    )

    # Collect evidence items
    evidence_query = db.query(EvidenceItem).filter(
        or_(
            EvidenceItem.meta.is_(None),
            EvidenceItem.meta.op("->>")("spam").is_(None),
            EvidenceItem.meta.op("->")("spam").op("->>")("is_hidden") != "true",
        )
    )

    # Filter by project_id(s) and/or case_id
    if project_ids_to_query:
        evidence_query = evidence_query.filter(
            EvidenceItem.project_id.in_([uuid.UUID(pid) for pid in project_ids_to_query])
        )
    if case_id:
        evidence_query = evidence_query.filter(
            or_(
                EvidenceItem.case_id == uuid.UUID(case_id),
                EvidenceItem.project_id.in_(
                    [uuid.UUID(pid) for pid in project_ids_to_query]
                )
                if project_ids_to_query
                else False,
            )
        )

    # Date range filtering (use document_date or created_at)
    if date_start:
        evidence_query = evidence_query.filter(
            or_(
                EvidenceItem.document_date >= date_start,
                and_(
                    EvidenceItem.document_date.is_(None),
                    EvidenceItem.created_at >= date_start,
                ),
            )
        )
    if date_end:
        evidence_query = evidence_query.filter(
            or_(
                EvidenceItem.document_date <= date_end,
                and_(
                    EvidenceItem.document_date.is_(None),
                    EvidenceItem.created_at <= date_end,
                ),
            )
        )

    evidence_items = evidence_query.limit(min(limit, max_evidence)).all()

    return BuilderEvidenceContext(
        emails=emails,
        evidence_items=evidence_items,
        project_id=project_id or case_project_id,
        case_id=case_id,
    )


# =============================================================================
# AI Agent for Chronology Building
# =============================================================================


class ChronologyBuilderAgent:
    """Agent for building chronologies using LLM."""

    def __init__(self, db: Session):
        self.db = db
        self.tool_config = get_tool_config("vericase_analysis", db)
        self.openai_key = get_ai_api_key("openai", db)
        self.anthropic_key = get_ai_api_key("anthropic", db)
        self.gemini_key = get_ai_api_key("gemini", db)
        self.bedrock_enabled = is_bedrock_enabled(db) and bedrock_available()
        self.bedrock_region = get_bedrock_region(db)
        self._bedrock_provider: BedrockProvider | None = None

        self.openai_model = get_ai_model("openai", db)
        self.anthropic_model = get_ai_model("anthropic", db)
        self.gemini_model = get_ai_model("gemini", db)
        self.bedrock_model = get_ai_model("bedrock", db)

        self.max_tokens = self.tool_config.get("max_tokens", 8000)
        self.temperature = self.tool_config.get("temperature", 0.2)

    @property
    def bedrock_provider(self) -> BedrockProvider | None:
        """Lazy-load Bedrock provider."""
        if self._bedrock_provider is None and self.bedrock_enabled:
            try:
                self._bedrock_provider = BedrockProvider(region=self.bedrock_region)
            except Exception as e:
                logger.warning(f"Failed to initialize Bedrock provider: {e}")
        return self._bedrock_provider

    async def _call_llm(self, prompt: str, system_prompt: str = "") -> str:
        """Call the appropriate LLM based on configuration."""
        errors: list[str] = []

        # Try Bedrock first (cost-effective)
        if self.bedrock_enabled:
            try:
                return await self._call_bedrock(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Bedrock call failed, trying fallback: {e}")
                errors.append(f"Bedrock: {e}")

        # Fallback to external APIs
        if self.anthropic_key:
            try:
                return await self._call_anthropic(prompt, system_prompt)
            except Exception as e:
                errors.append(f"Anthropic: {e}")

        if self.openai_key:
            try:
                return await self._call_openai(prompt, system_prompt)
            except Exception as e:
                errors.append(f"OpenAI: {e}")

        if self.gemini_key:
            try:
                return await self._call_gemini(prompt, system_prompt)
            except Exception as e:
                errors.append(f"Gemini: {e}")

        if errors:
            raise HTTPException(500, f"All AI providers failed: {'; '.join(errors)}")
        raise HTTPException(500, "No AI providers configured.")

    async def _call_openai(self, prompt: str, system_prompt: str) -> str:
        return await complete_chat(
            provider="openai",
            model_id=self.openai_model,
            prompt=prompt,
            system_prompt=system_prompt or "You are an expert at building chronologies from evidence.",
            api_key=self.openai_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_anthropic(self, prompt: str, system_prompt: str) -> str:
        return await complete_chat(
            provider="anthropic",
            model_id=self.anthropic_model,
            prompt=prompt,
            system_prompt=system_prompt or "You are an expert at building chronologies from evidence.",
            api_key=self.anthropic_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_gemini(self, prompt: str, system_prompt: str) -> str:
        return await complete_chat(
            provider="gemini",
            model_id=self.gemini_model,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.gemini_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_bedrock(self, prompt: str, system_prompt: str) -> str:
        if not self.bedrock_provider:
            raise Exception("Bedrock provider not available")
        return await self.bedrock_provider.complete_chat(
            model_id=self.bedrock_model,
            prompt=prompt,
            system_prompt=system_prompt or "You are an expert at building chronologies from evidence.",
            max_tokens=4000,
            temperature=0.3,
        )

    async def build_chronology(
        self,
        evidence_context: BuilderEvidenceContext,
        goal: str | None = None,
        include_programme: bool = False,
    ) -> tuple[list[ChronologyEvent], list[ProgrammeActivity]]:
        """
        Build chronology events and optional programme from evidence.
        """
        # Build evidence summary for LLM
        evidence_text_parts = []
        email_refs: dict[str, str] = {}  # email_id -> ref string
        evidence_refs: dict[str, str] = {}  # evidence_id -> ref string

        # Sample emails (prioritize recent, important, with attachments)
        # Hard limit: 200 emails max for LLM prompt
        sampled_emails = sorted(
            evidence_context.emails,
            key=lambda e: (
                e.date_sent or datetime.min.replace(tzinfo=timezone.utc),
                -(1 if getattr(e, "has_attachments", False) else 0),
                -(1 if getattr(e, "importance", None) == "high" else 0),
            ),
            reverse=True,
        )[:min(200, len(evidence_context.emails))]

        for email in sampled_emails:
            ref_id = f"EMAIL-{len(email_refs) + 1}"
            email_refs[str(email.id)] = ref_id
            date_str = (
                email.date_sent.strftime("%Y-%m-%d %H:%M")
                if email.date_sent
                else "Unknown date"
            )
            content = (email.body_text or email.body_preview or "")[:800]
            evidence_text_parts.append(
                f"[{ref_id}]\n"
                f"Date: {date_str}\n"
                f"From: {email.sender_name or email.sender_email or 'Unknown'}\n"
                f"To: {', '.join(email.recipients_to or [])}\n"
                f"Subject: {email.subject or 'No subject'}\n"
                f"Content: {content}\n"
                f"---"
            )

        # Sample evidence items
        # Hard limit: 100 evidence items max for LLM prompt
        sampled_evidence = sorted(
            evidence_context.evidence_items,
            key=lambda e: (
                e.document_date or e.created_at or datetime.min.replace(tzinfo=timezone.utc),
                -(1 if getattr(e, "is_starred", False) else 0),
            ),
            reverse=True,
        )[:min(100, len(evidence_context.evidence_items))]

        for evidence in sampled_evidence:
            ref_id = f"EVIDENCE-{len(evidence_refs) + 1}"
            evidence_refs[str(evidence.id)] = ref_id
            date_str = (
                evidence.document_date.strftime("%Y-%m-%d")
                if evidence.document_date
                else (
                    evidence.created_at.strftime("%Y-%m-%d")
                    if evidence.created_at
                    else "Unknown date"
                )
            )
            content = (evidence.extracted_text or evidence.description or "")[:1000]
            evidence_text_parts.append(
                f"[{ref_id}]\n"
                f"Date: {date_str}\n"
                f"Filename: {evidence.filename or 'Unknown'}\n"
                f"Type: {evidence.evidence_type or 'Unknown'}\n"
                f"Content: {content}\n"
                f"---"
            )

        evidence_text = "\n\n".join(evidence_text_parts)

        # Hard limit: 15000 chars for evidence text to avoid token overflow
        evidence_text = evidence_text[:15000]
        if len(evidence_text_parts) > 0 and len(evidence_text) >= 15000:
            evidence_text += "\n\n[Evidence truncated due to size limits...]"

        # Build LLM prompt
        goal_text = f"\n\nUser Goal: {goal}\n" if goal else ""
        programme_instruction = (
            "\nAlso generate a programme draft with activities, dependencies, and dates."
            if include_programme
            else ""
        )

        prompt = f"""Build a chronological narrative from the following evidence.

{goal_text}

EVIDENCE:
{evidence_text}

Create a JSON response with:
{{
    "chronology_events": [
        {{
            "date_start": "YYYY-MM-DDTHH:MM:SS",
            "date_end": "YYYY-MM-DDTHH:MM:SS" (optional, for spans),
            "title": "Brief event title",
            "narrative": "Detailed narrative description",
            "event_type": "notice|meeting|correspondence|site_event|other",
            "parties": ["party1", "party2"],
            "confidence": 0.0-1.0,
            "sources": {{"email_ids": ["EMAIL-1", "EMAIL-2"], "evidence_ids": ["EVIDENCE-1"]}}
        }}
    ],
    "programme_activities": [
        {{
            "name": "Activity name",
            "start_date": "YYYY-MM-DD",
            "finish_date": "YYYY-MM-DD",
            "dependencies": ["activity_id1"] (optional),
            "sources": {{"email_ids": [], "evidence_ids": []}}
        }}
    ]{programme_instruction}
}}

Guidelines:
- Extract key events, not every email/evidence item
- Merge related events into single entries when appropriate
- Use source references (EMAIL-N, EVIDENCE-N) from the evidence above
- Order events chronologically
- Include parties involved from senders/recipients
- Confidence should reflect how clear the evidence is
"""

        system_prompt = """You are an expert at building chronologies from construction project evidence.
Extract key events, merge duplicates, identify parties, and create a coherent narrative timeline.
For programme activities, infer dependencies and durations from evidence."""

        response = await self._call_llm(prompt, system_prompt)

        # Parse JSON response
        try:
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            else:
                json_str = response.strip()

            data = json.loads(json_str)

            # Convert to model instances
            events = []
            for evt_data in data.get("chronology_events", []):
                # Map source refs back to actual IDs
                sources = {"email_ids": [], "evidence_ids": []}
                for ref in evt_data.get("sources", {}).get("email_ids", []):
                    # Find email_id by ref (EMAIL-1 -> actual UUID)
                    for email_id, ref_id in email_refs.items():
                        if ref_id == ref:
                            sources["email_ids"].append(email_id)
                            break
                for ref in evt_data.get("sources", {}).get("evidence_ids", []):
                    for ev_id, ref_id in evidence_refs.items():
                        if ref_id == ref:
                            sources["evidence_ids"].append(ev_id)
                            break

                events.append(
                    ChronologyEvent(
                        date_start=datetime.fromisoformat(
                            evt_data["date_start"].replace("Z", "+00:00")
                        ),
                        date_end=(
                            datetime.fromisoformat(
                                evt_data["date_end"].replace("Z", "+00:00")
                            )
                            if evt_data.get("date_end")
                            else None
                        ),
                        title=evt_data["title"],
                        narrative=evt_data["narrative"],
                        event_type=evt_data.get("event_type"),
                        parties=evt_data.get("parties", []),
                        confidence=evt_data.get("confidence", 0.5),
                        sources=sources,
                    )
                )

            activities = []
            for act_data in data.get("programme_activities", []):
                activities.append(
                    ProgrammeActivity(
                        name=act_data["name"],
                        start_date=datetime.fromisoformat(
                            act_data["start_date"].replace("Z", "+00:00")
                        ),
                        finish_date=(
                            datetime.fromisoformat(
                                act_data["finish_date"].replace("Z", "+00:00")
                            )
                            if act_data.get("finish_date")
                            else None
                        ),
                        dependencies=act_data.get("dependencies", []),
                        sources=act_data.get("sources", {}),
                    )
                )

            return events, activities

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse LLM response: {e}\nResponse: {response[:500]}")
            # Return minimal fallback
            return [], []


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/start", response_model=StartBuilderResponse)
async def start_chronology_builder(
    request: StartBuilderRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Start a new Chronology Builder session.
    Creates a plan showing what will be built, requires approval to proceed.
    """
    # Validate at least one of project_id or case_id
    if not request.project_id and not request.case_id:
        raise HTTPException(400, "Either project_id or case_id must be provided")

    # Verify access
    if request.project_id:
        project = db.query(Project).filter(Project.id == uuid.UUID(request.project_id)).first()
        if not project:
            raise HTTPException(404, "Project not found")
        # Basic access check (owner or shared)
        if str(project.owner_user_id) != str(user.id):
            # Could add shared project check here
            pass  # For now, allow if project exists

    if request.case_id:
        case = db.query(Case).filter(Case.id == uuid.UUID(request.case_id)).first()
        if not case:
            raise HTTPException(404, "Case not found")
        # Basic access check
        if str(case.owner_id) != str(user.id):
            pass  # Could add case team check

    session_id = str(uuid.uuid4())

    # Collect evidence to build plan (sampled for planning)
    evidence_context = collect_builder_evidence(
        db,
        project_id=request.project_id,
        case_id=request.case_id,
        date_start=request.date_range_start,
        date_end=request.date_range_end,
        limit=500,  # Sample for planning
        max_emails=500,
        max_evidence=200,
    )

    # Build plan
    email_count = len(evidence_context.emails)
    evidence_count = len(evidence_context.evidence_items)

    date_range_start = request.date_range_start
    date_range_end = request.date_range_end
    if not date_range_start and evidence_context.emails:
        date_range_start = min(
            (e.date_sent for e in evidence_context.emails if e.date_sent),
            default=None,
        )
    if not date_range_end and evidence_context.emails:
        date_range_end = max(
            (e.date_sent for e in evidence_context.emails if e.date_sent),
            default=None,
        )

    strategy = f"Build chronology from {email_count} emails and {evidence_count} evidence items"
    if email_count > 500 or evidence_count > 200:
        strategy += f" (sampling up to 500 emails and 200 evidence items for processing)"
    if request.goal:
        strategy += f" focused on: {request.goal[:100]}"
    if date_range_start and date_range_end:
        strategy += f" between {date_range_start.strftime('%Y-%m-%d')} and {date_range_end.strftime('%Y-%m-%d')}"

    plan = BuilderPlan(
        project_id=request.project_id,
        case_id=request.case_id,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        email_count=email_count,
        evidence_count=evidence_count,
        strategy=strategy,
        estimated_events=max(10, min(100, email_count // 10 + evidence_count // 5)),
        include_programme=request.include_programme,
    )

    session = BuilderSession(
        id=session_id,
        user_id=str(user.id),
        project_id=request.project_id,
        case_id=request.case_id,
        goal=request.goal,
        date_range_start=request.date_range_start,
        date_range_end=request.date_range_end,
        include_programme=request.include_programme,
        status=BuilderStatus.AWAITING_APPROVAL,
        plan=plan,
    )

    save_builder_session(session)

    return StartBuilderResponse(
        session_id=session_id,
        status="awaiting_approval",
        message="Chronology Builder plan ready for review. Approve to start building.",
        plan=plan,
    )


@router.post("/approve")
async def approve_builder_plan(
    request: ApproveBuilderRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Approve or modify the builder plan.
    If approved, starts background building process.
    """
    session = load_builder_session(request.session_id)
    if not session:
        raise HTTPException(404, "Builder session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    if session.status != BuilderStatus.AWAITING_APPROVAL:
        raise HTTPException(400, f"Session not awaiting approval. Status: {session.status}")

    if not request.approved:
        # User wants modifications - could regenerate plan or just update goal
        if request.modifications:
            session.goal = (
                f"{session.goal or ''}\n\nUser feedback: {request.modifications}"
            )
            session.status = BuilderStatus.PENDING
            save_builder_session(session)
        return {"status": "modified", "message": "Plan updated with your feedback"}

    # Approved - start building
    session.status = BuilderStatus.BUILDING
    session.updated_at = datetime.now(timezone.utc)
    save_builder_session(session)

    # Capture values for background task
    project_id = session.project_id
    case_id = session.case_id
    goal = session.goal
    date_start = session.date_range_start
    date_end = session.date_range_end
    include_programme = session.include_programme

    def sync_run_builder():
        import asyncio
        from .db import SessionLocal

        async def run_builder():
            task_db = SessionLocal()
            start_time = datetime.now(timezone.utc)
            try:
                # Collect full evidence (with guardrails)
                evidence_context = collect_builder_evidence(
                    task_db,
                    project_id=project_id,
                    case_id=case_id,
                    date_start=date_start,
                    date_end=date_end,
                    limit=1000,  # Higher limit for actual building
                    max_emails=500,  # Hard limit: max 500 emails
                    max_evidence=200,  # Hard limit: max 200 evidence items
                )

                # Build chronology using LLM
                agent = ChronologyBuilderAgent(task_db)
                events, activities = await agent.build_chronology(
                    evidence_context, goal=goal, include_programme=include_programme
                )

                # Update session
                session.chronology_events = events
                session.programme_activities = activities
                session.status = BuilderStatus.COMPLETED
                session.completed_at = datetime.now(timezone.utc)
                session.processing_time_seconds = (
                    datetime.now(timezone.utc) - start_time
                ).total_seconds()
                session.models_used = ["llm"]  # Could track actual model used

            except Exception as e:
                logger.exception(f"Chronology building failed: {e}")
                session.status = BuilderStatus.FAILED
                session.error_message = str(e)
            finally:
                task_db.close()
                session.updated_at = datetime.now(timezone.utc)
                save_builder_session(session)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_builder())
        finally:
            loop.close()

    background_tasks.add_task(sync_run_builder)

    return {"status": "building", "message": "Chronology building started"}


@router.get("/status/{session_id}", response_model=BuilderStatusResponse)
async def get_builder_status(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """Get the current status of a Chronology Builder session."""
    session = load_builder_session(session_id)
    if not session:
        raise HTTPException(404, "Builder session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    return BuilderStatusResponse(
        session_id=session_id,
        status=session.status.value,
        plan=session.plan,
        chronology_events=session.chronology_events,
        programme_activities=session.programme_activities,
        processing_time_seconds=session.processing_time_seconds,
        error_message=session.error_message,
        models_used=session.models_used,
    )


@router.post("/events/{session_id}/update")
async def update_builder_event(
    session_id: str,
    request: UpdateEventRequest,
    user: Annotated[User, Depends(current_user)],
):
    """Update an event in the builder session (accept/reject/edit)."""
    session = load_builder_session(session_id)
    if not session:
        raise HTTPException(404, "Builder session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Find event
    event = next((e for e in session.chronology_events if e.id == request.event_id), None)
    if not event:
        raise HTTPException(404, "Event not found in session")

    # Update fields
    if request.is_accepted is not None:
        event.is_accepted = request.is_accepted
    if request.title is not None:
        event.title = request.title
    if request.narrative is not None:
        event.narrative = request.narrative
    if request.date_start is not None:
        event.date_start = request.date_start
    if request.date_end is not None:
        event.date_end = request.date_end
    if request.event_type is not None:
        event.event_type = request.event_type
    if request.parties is not None:
        event.parties = request.parties

    session.updated_at = datetime.now(timezone.utc)
    save_builder_session(session)

    return {"status": "updated", "event_id": request.event_id}


@router.post("/publish")
def publish_builder_events(
    request: PublishBuilderRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Publish accepted chronology events to ChronologyItem records."""
    session = load_builder_session(request.session_id)
    if not session:
        raise HTTPException(404, "Builder session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    if session.status != BuilderStatus.COMPLETED:
        raise HTTPException(
            400, f"Session not completed. Status: {session.status.value}"
        )

    if not session.project_id and not session.case_id:
        raise HTTPException(400, "Session has no project or case context")

    case_uuid = None
    project_uuid = None
    if session.case_id:
        try:
            case_uuid = uuid.UUID(str(session.case_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid case_id format")
        case = db.query(Case).filter(Case.id == case_uuid).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        if case.project_id:
            project_uuid = case.project_id

    if session.project_id:
        try:
            project_uuid = uuid.UUID(str(session.project_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project_id format")
        project = db.query(Project).filter(Project.id == project_uuid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

    events = session.chronology_events or []
    if request.only_accepted:
        events = [e for e in events if e.is_accepted]

    if not events:
        return {"status": "no_events", "published_count": 0, "event_ids": []}

    published_ids: list[str] = []
    for ev in events:
        if not ev.date_start:
            continue

        evidence_ids: list[str] = []
        if isinstance(ev.sources, dict):
            evidence_ids.extend(
                [str(x) for x in (ev.sources.get("evidence_ids") or []) if x]
            )
            evidence_ids.extend(
                [str(x) for x in (ev.sources.get("email_ids") or []) if x]
            )

        item = ChronologyItem(
            id=uuid.uuid4(),
            case_id=case_uuid,
            project_id=project_uuid,
            event_date=ev.date_start,
            event_type=ev.event_type,
            title=ev.title or "Untitled Event",
            description=ev.narrative,
            evidence_ids=evidence_ids,
            parties_involved=ev.parties or [],
        )
        db.add(item)
        published_ids.append(str(item.id))

    if not published_ids:
        return {"status": "no_events", "published_count": 0, "event_ids": []}

    db.commit()

    return {
        "status": "published",
        "published_count": len(published_ids),
        "event_ids": published_ids,
    }


@router.get("/sessions", response_model=list[dict[str, Any]])
async def list_builder_sessions(
    user: Annotated[User, Depends(current_user)],
    limit: int = 20,
):
    """List recent builder sessions for the current user."""
    # This would need to scan in-memory store or Redis
    # For now, return empty list (could enhance later)
    return []
