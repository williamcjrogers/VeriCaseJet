"""
Chronology Lense - Forensic, session-based chronology builder.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .ai_runtime import complete_chat
from .ai_settings import get_tool_config, get_tool_fallback_chain, get_tool_provider_model
from .db import SessionLocal, get_db
from .models import (
    Case,
    ChronologyItem,
    DelayEvent,
    EmailMessage,
    EvidenceItem,
    Programme,
    Project,
    User,
)
from .security import current_user
from .settings import settings
from .trace_context import get_trace_context
from .visibility import build_email_visibility_filter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chronology-lense", tags=["chronology-lense"])

try:
    from redis import Redis
except ImportError:
    Redis = None


# =============================================================================
# Models
# =============================================================================


class LenseStatus(str, Enum):
    AWAITING_INPUT = "awaiting_input"
    AWAITING_APPROVAL = "awaiting_approval"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"


class LenseStage(str, Enum):
    RETRIEVING = "retrieving"
    SCORING = "scoring"
    SYNTHESIZING = "synthesizing"
    VALIDATING = "validating"
    IDLE = "idle"


class DetailLevel(str, Enum):
    SUMMARY = "summary"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"


class ScopeMode(str, Enum):
    LIFECYCLE = "lifecycle"
    DATE_RANGE = "date_range"


class LenseQuestion(BaseModel):
    id: str
    prompt: str
    required: bool = True


class LenseCitation(BaseModel):
    source_type: str
    source_id: str
    excerpt: str
    confidence: float = 0.0


class LenseEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_date: datetime
    title: str
    description: str | None = None
    event_type: str | None = None
    parties_involved: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    citations: list[LenseCitation] = Field(default_factory=list)
    milestone_band: str | None = None
    confidence: float = 0.0


class LenseSession(BaseModel):
    id: str
    user_id: str
    project_id: str | None = None
    case_id: str | None = None
    topic: str | None = None
    keywords: list[str] = Field(default_factory=list)
    detail_level: DetailLevel = DetailLevel.STANDARD
    scope: ScopeMode = ScopeMode.LIFECYCLE
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None
    hard_evidence_only: bool = False
    questions: list[LenseQuestion] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    status: LenseStatus = LenseStatus.AWAITING_INPUT
    stage: LenseStage = LenseStage.IDLE
    events: list[LenseEvent] = Field(default_factory=list)
    retrieval_stats: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
    model_used: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None


# =============================================================================
# Session Store
# =============================================================================


_sessions: dict[str, LenseSession] = {}

def _get_redis() -> Redis | None:
    try:
        if settings.REDIS_URL and Redis:
            return Redis.from_url(settings.REDIS_URL)
    except Exception as exc:
        logger.warning("Redis unavailable for Chronology Lense sessions: %s", exc)
    return None


def save_session(session: LenseSession) -> None:
    session.updated_at = datetime.now(timezone.utc)
    _sessions[session.id] = session
    try:
        redis_client = _get_redis()
        if redis_client:
            redis_client.set(
                f"chronology_lense:session:{session.id}",
                session.model_dump_json(),
            )
    except Exception as exc:
        logger.warning("Failed to persist Lense session to Redis: %s", exc)


def load_session(session_id: str) -> LenseSession | None:
    cached = _sessions.get(session_id)
    redis_session: LenseSession | None = None
    try:
        redis_client = _get_redis()
        if redis_client:
            data = redis_client.get(f"chronology_lense:session:{session_id}")
            if data:
                redis_session = LenseSession.model_validate_json(data)
    except Exception as exc:
        logger.warning("Failed to load Lense session from Redis: %s", exc)

    if redis_session:
        if not cached or redis_session.updated_at >= cached.updated_at:
            _sessions[session_id] = redis_session
            return redis_session

    return cached


# =============================================================================
# Requests/Responses
# =============================================================================


class StartLenseRequest(BaseModel):
    project_id: str | None = None
    case_id: str | None = None
    topic: str
    keywords: list[str] = Field(default_factory=list)
    detail_level: DetailLevel = DetailLevel.STANDARD
    scope: ScopeMode = ScopeMode.LIFECYCLE
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None
    hard_evidence_only: bool = False


class StartLenseResponse(BaseModel):
    session_id: str
    status: LenseStatus
    stage: LenseStage
    questions: list[LenseQuestion]
    message: str


class RespondLenseRequest(BaseModel):
    session_id: str
    answers: dict[str, str] = Field(default_factory=dict)


class RespondLenseResponse(BaseModel):
    session_id: str
    status: LenseStatus
    stage: LenseStage
    questions: list[LenseQuestion]
    ready_for_approval: bool


class StatusLenseResponse(BaseModel):
    session_id: str
    status: LenseStatus
    stage: LenseStage
    ready_for_approval: bool
    retrieval_stats: dict[str, Any] | None = None
    error_message: str | None = None


class ApproveLenseRequest(BaseModel):
    session_id: str


class PublishLenseRequest(BaseModel):
    session_id: str
    only_milestones: bool = False


class PublishLenseResponse(BaseModel):
    published_count: int


class ResultsLenseResponse(BaseModel):
    session_id: str
    status: LenseStatus
    events: list[LenseEvent]
    retrieval_stats: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None


# =============================================================================
# Helpers
# =============================================================================


@dataclass
class EvidenceRef:
    ref_id: str
    source_type: str
    source_id: str
    excerpt: str
    score: float
    date: datetime | None = None
    title: str = ""


def _clip(text: str | None, limit: int = 300) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _keyword_tokens(topic: str | None, keywords: list[str], answers: dict[str, str]) -> list[str]:
    tokens: list[str] = []
    if topic:
        tokens.extend(re.split(r"[,;/\s]+", topic))
    tokens.extend(keywords or [])
    for answer in answers.values():
        tokens.extend(re.split(r"[,;/\s]+", answer))
    return [t.strip().lower() for t in tokens if t and t.strip()]


def _matches_keywords(text: str, tokens: list[str]) -> bool:
    if not tokens:
        return True
    lower = text.lower()
    return any(token in lower for token in tokens)


def _contains_date(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b", text)
    )


def score_evidence_item(item: Any) -> float:
    score = 0.0
    if getattr(item, "document_date", None):
        score += 0.3
    conf = getattr(item, "document_date_confidence", None)
    if conf is not None:
        score += min(max(conf, 0), 100) / 100 * 0.2
    if _contains_date(getattr(item, "extracted_text", "") or ""):
        score += 0.1
    if getattr(item, "evidence_type", None) or getattr(item, "document_category", None):
        score += 0.1
    if getattr(item, "source_email_id", None):
        score += 0.1
    return min(score, 1.0)


def score_email(email: Any) -> float:
    score = 0.0
    if getattr(email, "date_sent", None):
        score += 0.35
    if getattr(email, "has_attachments", False):
        score += 0.2
    if _contains_date(getattr(email, "subject", "") or ""):
        score += 0.1
    if getattr(email, "is_critical_path", False):
        score += 0.1
    return min(score, 1.0)


def score_delay(delay: Any) -> float:
    score = 0.2
    if getattr(delay, "actual_finish", None) or getattr(delay, "planned_finish", None):
        score += 0.2
    if getattr(delay, "delay_days", None):
        score += 0.2
    if getattr(delay, "delay_cause", None):
        score += 0.1
    return min(score, 1.0)


def score_programme(activity: dict[str, Any]) -> float:
    score = 0.2
    if activity.get("is_milestone"):
        score += 0.2
    if activity.get("start_date"):
        score += 0.2
    if activity.get("finish_date"):
        score += 0.1
    return min(score, 1.0)


def score_chronology_item(item: Any) -> float:
    score = 0.2
    if getattr(item, "event_date", None):
        score += 0.2
    if getattr(item, "evidence_ids", None):
        score += 0.2
    return min(score, 1.0)


def classify_milestone_band(score: float) -> str:
    if score >= 0.75:
        return "MilestoneHard"
    if score >= 0.55:
        return "SupportedStrong"
    return "SupportedWeak"


def compute_event_score(
    citations: list[LenseCitation], source_scores: dict[str, float]
) -> float:
    if not citations:
        return 0.0
    scores = []
    types = set()
    for citation in citations:
        key = f"{citation.source_type}:{citation.source_id}"
        if key in source_scores:
            scores.append(source_scores[key])
            types.add(citation.source_type)
    if not scores:
        return 0.0
    base = sum(scores) / len(scores)
    if len(types) >= 2:
        base += 0.1
    return min(base, 1.0)


def _extract_json_block(text: str) -> str:
    if "```json" in text:
        return text.split("```json")[1].split("```")[0].strip()
    if "```" in text:
        return text.split("```")[1].split("```")[0].strip()
    return text.strip()


async def _call_llm_with_fallback(
    prompt: str,
    system_prompt: str,
    db: Session,
    tool_name: str,
    trace_info: dict[str, Any],
) -> tuple[str, str]:
    config = get_tool_config(tool_name, db)
    provider, model = get_tool_provider_model(tool_name, db)
    fallback_chain = get_tool_fallback_chain(tool_name, db) or []
    chain = [(provider, model)] + [x for x in fallback_chain if x != (provider, model)]
    errors: list[str] = []
    for provider_name, model_id in chain:
        try:
            response = await complete_chat(
                provider=provider_name,
                model_id=model_id,
                prompt=prompt,
                system_prompt=system_prompt,
                db=db,
                max_tokens=config.get("max_tokens", 6000),
                temperature=config.get("temperature", 0.2),
                function_name="chronology_lense",
                task_type="chronology_lense",
                chain_id=trace_info.get("chain_id"),
                run_id=trace_info.get("run_id"),
            )
            return response, f"{provider_name}:{model_id}"
        except Exception as exc:
            errors.append(f"{provider_name}:{model_id} -> {exc}")
            continue
    raise HTTPException(500, f"Chronology Lense AI failed: {'; '.join(errors)}")


def _build_questions() -> list[LenseQuestion]:
    return [
        LenseQuestion(
            id="parties",
            prompt="Which parties or organisations should be emphasised?",
        ),
        LenseQuestion(
            id="evidence",
            prompt="Any evidence types to prioritise (emails, documents, programme, delays, existing chronology)?",
        ),
        LenseQuestion(
            id="timeframe",
            prompt="What timeframe or milestones matter most?",
        ),
        LenseQuestion(
            id="constraints",
            prompt="Any constraints, exclusions, or focus areas?",
        ),
    ]


def _get_trace_ids(request: Request) -> dict[str, Any]:
    trace = get_trace_context()
    return {
        "chain_id": request.headers.get("X-Chain-ID") or trace.chain_id,
        "run_id": request.headers.get("X-Run-ID") or trace.run_id,
    }


# =============================================================================
# Retrieval
# =============================================================================


async def _fetch_emails(
    user_id: str,
    project_id: str | None,
    case_id: str | None,
    date_start: datetime | None,
    date_end: datetime | None,
    tokens: list[str],
) -> list[EmailMessage]:
    def run() -> list[EmailMessage]:
        db = SessionLocal()
        try:
            query = db.query(EmailMessage).filter(
                build_email_visibility_filter(EmailMessage)
            )
            if project_id:
                query = query.filter(EmailMessage.project_id == project_id)
            elif case_id:
                query = query.filter(EmailMessage.case_id == case_id)
            if date_start:
                query = query.filter(EmailMessage.date_sent >= date_start)
            if date_end:
                query = query.filter(EmailMessage.date_sent <= date_end)
            query = query.filter(EmailMessage.date_sent.isnot(None))
            emails = query.order_by(EmailMessage.date_sent.desc()).limit(500).all()
            if tokens:
                filtered = []
                for email in emails:
                    blob = " ".join(
                        [
                            email.subject or "",
                            email.body_preview or "",
                            email.body_text or "",
                        ]
                    )
                    if _matches_keywords(blob, tokens):
                        filtered.append(email)
                return filtered
            return emails
        finally:
            db.close()

    return await asyncio.to_thread(run)


async def _fetch_evidence(
    project_id: str | None,
    case_id: str | None,
    date_start: datetime | None,
    date_end: datetime | None,
    tokens: list[str],
) -> list[EvidenceItem]:
    def run() -> list[EvidenceItem]:
        db = SessionLocal()
        try:
            query = db.query(EvidenceItem).filter(
                or_(
                    EvidenceItem.meta.is_(None),
                    EvidenceItem.meta.op("->>")("spam").is_(None),
                    EvidenceItem.meta.op("->")("spam").op("->>")("is_hidden")
                    != "true",
                )
            )
            if project_id:
                query = query.filter(EvidenceItem.project_id == project_id)
            if case_id:
                query = query.filter(EvidenceItem.case_id == case_id)
            if date_start:
                query = query.filter(
                    or_(
                        EvidenceItem.document_date >= date_start,
                        and_(
                            EvidenceItem.document_date.is_(None),
                            EvidenceItem.created_at >= date_start,
                        ),
                    )
                )
            if date_end:
                query = query.filter(
                    or_(
                        EvidenceItem.document_date <= date_end,
                        and_(
                            EvidenceItem.document_date.is_(None),
                            EvidenceItem.created_at <= date_end,
                        ),
                    )
                )
            items = query.order_by(EvidenceItem.created_at.desc()).limit(300).all()
            if tokens:
                filtered = []
                for item in items:
                    blob = " ".join(
                        [
                            item.title or "",
                            item.filename or "",
                            item.description or "",
                            item.extracted_text or "",
                        ]
                    )
                    if _matches_keywords(blob, tokens):
                        filtered.append(item)
                return filtered
            return items
        finally:
            db.close()

    return await asyncio.to_thread(run)


async def _fetch_delays(case_id: str | None) -> list[DelayEvent]:
    def run() -> list[DelayEvent]:
        db = SessionLocal()
        try:
            query = db.query(DelayEvent)
            if case_id:
                query = query.filter(DelayEvent.case_id == case_id)
            return query.order_by(DelayEvent.created_at.desc()).limit(200).all()
        finally:
            db.close()

    return await asyncio.to_thread(run)


async def _fetch_programmes(case_id: str | None, project_id: str | None) -> list[Programme]:
    def run() -> list[Programme]:
        db = SessionLocal()
        try:
            query = db.query(Programme)
            if case_id:
                query = query.filter(Programme.case_id == case_id)
            if project_id:
                query = query.filter(Programme.project_id == project_id)
            return query.order_by(Programme.created_at.desc()).limit(50).all()
        finally:
            db.close()

    return await asyncio.to_thread(run)


async def _fetch_chronology_items(
    case_id: str | None,
    project_id: str | None,
    date_start: datetime | None,
    date_end: datetime | None,
) -> list[ChronologyItem]:
    def run() -> list[ChronologyItem]:
        db = SessionLocal()
        try:
            query = db.query(ChronologyItem)
            if case_id:
                query = query.filter(ChronologyItem.case_id == case_id)
            if project_id:
                query = query.filter(ChronologyItem.project_id == project_id)
            if date_start:
                query = query.filter(ChronologyItem.event_date >= date_start)
            if date_end:
                query = query.filter(ChronologyItem.event_date <= date_end)
            return query.order_by(ChronologyItem.event_date.desc()).limit(200).all()
        finally:
            db.close()

    return await asyncio.to_thread(run)


def _build_evidence_refs(
    emails: list[EmailMessage],
    evidence_items: list[EvidenceItem],
    delays: list[DelayEvent],
    programmes: list[Programme],
    chronology_items: list[ChronologyItem],
) -> tuple[list[str], dict[str, EvidenceRef], dict[str, float]]:
    lines: list[str] = []
    ref_map: dict[str, EvidenceRef] = {}
    score_map: dict[str, float] = {}

    def register(ref: EvidenceRef) -> None:
        ref_map[ref.ref_id] = ref
        score_map[f"{ref.source_type}:{ref.source_id}"] = ref.score

    email_refs: list[tuple[str, EmailMessage]] = []
    for email in emails[:200]:
        email_refs.append((f"EMAIL-{len(email_refs) + 1}", email))

    for ref_id, email in email_refs:
        date_str = email.date_sent.strftime("%Y-%m-%d %H:%M") if email.date_sent else "Unknown"
        content = _clip(email.body_text or email.body_preview or "", 800)
        lines.append(
            "\n".join(
                [
                    f"[{ref_id}]",
                    f"Date: {date_str}",
                    f"From: {email.sender_name or email.sender_email or 'Unknown'}",
                    f"To: {', '.join(email.recipients_to or [])}",
                    f"Subject: {email.subject or 'No subject'}",
                    f"Content: {content}",
                    "---",
                ]
            )
        )
        register(
            EvidenceRef(
                ref_id=ref_id,
                source_type="email",
                source_id=str(email.id),
                excerpt=_clip(content or email.subject or ""),
                score=score_email(email),
                date=email.date_sent,
                title=email.subject or "Email",
            )
        )

    evidence_refs: list[tuple[str, EvidenceItem]] = []
    for item in evidence_items[:150]:
        evidence_refs.append((f"EVIDENCE-{len(evidence_refs) + 1}", item))

    for ref_id, item in evidence_refs:
        date_str = (
            item.document_date.strftime("%Y-%m-%d") if item.document_date else None
        ) or (
            item.created_at.strftime("%Y-%m-%d") if item.created_at else "Unknown"
        )
        content = _clip(item.extracted_text or item.description or "", 900)
        lines.append(
            "\n".join(
                [
                    f"[{ref_id}]",
                    f"Date: {date_str}",
                    f"Filename: {item.filename or 'Unknown'}",
                    f"Type: {item.evidence_type or 'Unknown'}",
                    f"Content: {content}",
                    "---",
                ]
            )
        )
        register(
            EvidenceRef(
                ref_id=ref_id,
                source_type="evidence",
                source_id=str(item.id),
                excerpt=_clip(content or item.title or item.filename or ""),
                score=score_evidence_item(item),
                date=item.document_date or item.created_at,
                title=item.title or item.filename or "Evidence",
            )
        )

    delay_refs: list[tuple[str, DelayEvent]] = []
    for delay in delays[:100]:
        delay_refs.append((f"DELAY-{len(delay_refs) + 1}", delay))

    for ref_id, delay in delay_refs:
        date_str = (
            delay.actual_finish or delay.planned_finish or delay.actual_start or delay.planned_start
        )
        date_value = date_str.strftime("%Y-%m-%d") if date_str else "Unknown"
        desc = _clip(delay.description or "", 600)
        lines.append(
            "\n".join(
                [
                    f"[{ref_id}]",
                    f"Date: {date_value}",
                    f"Activity: {delay.activity_name or 'Delay Event'}",
                    f"Delay Days: {delay.delay_days or 0}",
                    f"Description: {desc}",
                    "---",
                ]
            )
        )
        register(
            EvidenceRef(
                ref_id=ref_id,
                source_type="delay",
                source_id=str(delay.id),
                excerpt=_clip(desc or delay.activity_name or ""),
                score=score_delay(delay),
                date=date_str,
                title=delay.activity_name or "Delay",
            )
        )

    programme_refs: list[tuple[str, dict[str, Any]]] = []
    for programme in programmes:
        for activity in (programme.activities or []):
            if not isinstance(activity, dict):
                continue
            programme_refs.append(
                (f"PROG-{len(programme_refs) + 1}", activity)
            )
            if len(programme_refs) >= 120:
                break

    for ref_id, activity in programme_refs:
        name = activity.get("name", "Programme Activity")
        start = activity.get("start_date") or "Unknown"
        finish = activity.get("finish_date") or "Unknown"
        lines.append(
            "\n".join(
                [
                    f"[{ref_id}]",
                    f"Start: {start}",
                    f"Finish: {finish}",
                    f"Activity: {name}",
                    f"Milestone: {'Yes' if activity.get('is_milestone') else 'No'}",
                    "---",
                ]
            )
        )
        register(
            EvidenceRef(
                ref_id=ref_id,
                source_type="programme",
                source_id=str(activity.get("id", ref_id)),
                excerpt=_clip(name),
                score=score_programme(activity),
                title=name,
            )
        )

    chrono_refs: list[tuple[str, ChronologyItem]] = []
    for item in chronology_items[:120]:
        chrono_refs.append((f"CHRONO-{len(chrono_refs) + 1}", item))

    for ref_id, item in chrono_refs:
        date_value = item.event_date.strftime("%Y-%m-%d") if item.event_date else "Unknown"
        desc = _clip(item.description or "", 600)
        lines.append(
            "\n".join(
                [
                    f"[{ref_id}]",
                    f"Date: {date_value}",
                    f"Title: {item.title or 'Chronology Item'}",
                    f"Description: {desc}",
                    "---",
                ]
            )
        )
        register(
            EvidenceRef(
                ref_id=ref_id,
                source_type="chronology",
                source_id=str(item.id),
                excerpt=_clip(desc or item.title or ""),
                score=score_chronology_item(item),
                date=item.event_date,
                title=item.title or "Chronology Item",
            )
        )

    return lines, ref_map, score_map


def _fallback_events(ref_map: dict[str, EvidenceRef]) -> list[LenseEvent]:
    events: list[LenseEvent] = []
    refs = sorted(ref_map.values(), key=lambda r: r.date or datetime.min)
    for ref in refs[:50]:
        if not ref.date:
            continue
        citation = LenseCitation(
            source_type=ref.source_type,
            source_id=ref.source_id,
            excerpt=ref.excerpt,
            confidence=ref.score,
        )
        events.append(
            LenseEvent(
                event_date=ref.date,
                title=ref.title or "Evidence Event",
                description=ref.excerpt,
                event_type="chronology",
                citations=[citation],
                evidence_ids=[ref.source_id],
            )
        )
    return events


def _parse_events_from_llm(
    response_text: str,
    ref_map: dict[str, EvidenceRef],
) -> list[LenseEvent]:
    payload = _extract_json_block(response_text)
    data = json.loads(payload)
    raw_events = data.get("events") or data.get("chronology_events") or []
    events: list[LenseEvent] = []

    for raw in raw_events:
        date_str = raw.get("event_date") or raw.get("date_start")
        if not date_str:
            continue
        try:
            event_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            continue

        citations: list[LenseCitation] = []
        evidence_ids: list[str] = []
        for cite in raw.get("citations", []):
            ref_id = cite.get("source_ref") or cite.get("ref") or cite.get("id")
            if ref_id and ref_id in ref_map:
                ref = ref_map[ref_id]
                citations.append(
                    LenseCitation(
                        source_type=ref.source_type,
                        source_id=ref.source_id,
                        excerpt=ref.excerpt,
                        confidence=ref.score,
                    )
                )
                evidence_ids.append(ref.source_id)

        if not citations:
            continue

        events.append(
            LenseEvent(
                event_date=event_date,
                title=raw.get("title") or "Untitled Event",
                description=raw.get("description") or raw.get("narrative"),
                event_type=raw.get("event_type") or "chronology",
                parties_involved=raw.get("parties_involved")
                or raw.get("parties")
                or [],
                citations=citations,
                evidence_ids=evidence_ids,
            )
        )
    return events


async def _build_events_from_evidence(
    db: Session,
    session: LenseSession,
    ref_lines: list[str],
    ref_map: dict[str, EvidenceRef],
    trace_info: dict[str, Any],
) -> tuple[list[LenseEvent], str]:
    detail_hint = {
        DetailLevel.SUMMARY: "Keep the chronology concise, 10-20 key events.",
        DetailLevel.STANDARD: "Provide a balanced chronology, 20-35 events.",
        DetailLevel.COMPREHENSIVE: "Provide a comprehensive chronology, up to 60 events.",
    }
    system_prompt = (
        "You are a forensic construction disputes expert. "
        "Build a chronology with citations to source references."
    )
    prompt = f"""
Topic: {session.topic or "General chronology"}
Keywords: {", ".join(session.keywords) or "None"}
Detail level: {session.detail_level}
Scope: {session.scope}
Date range: {session.date_range_start or "All"} to {session.date_range_end or "All"}
Additional context: {json.dumps(session.answers or {}, ensure_ascii=False)}

EVIDENCE REFERENCES:
{chr(10).join(ref_lines)}

Return JSON only with this shape:
{{
  "events": [
    {{
      "event_date": "YYYY-MM-DDTHH:MM:SS",
      "title": "Event title",
      "description": "Narrative summary grounded in evidence",
      "event_type": "notice|meeting|correspondence|site_event|chronology",
      "parties_involved": ["party1", "party2"],
      "citations": [
        {{ "source_ref": "EMAIL-1" }},
        {{ "source_ref": "EVIDENCE-3" }}
      ]
    }}
  ]
}}

Rules:
- Every event must include at least one citation reference from the evidence list above.
- Do not invent facts or citations.
- Favor contemporaneous evidence (emails, documents) over summaries.
- {detail_hint[session.detail_level]}
"""
    response_text, model_used = await _call_llm_with_fallback(
        prompt=prompt.strip(),
        system_prompt=system_prompt,
        db=db,
        tool_name="chronology_lense",
        trace_info=trace_info,
    )
    try:
        events = _parse_events_from_llm(response_text, ref_map)
        if not events:
            return _fallback_events(ref_map), model_used
        return events, model_used
    except Exception:
        return _fallback_events(ref_map), model_used


def _validate_and_score_events(
    events: list[LenseEvent],
    source_scores: dict[str, float],
    hard_only: bool,
) -> list[LenseEvent]:
    validated: list[LenseEvent] = []
    for event in events:
        if not event.citations:
            continue
        score = compute_event_score(event.citations, source_scores)
        event.confidence = score
        event.milestone_band = classify_milestone_band(score)
        event.evidence_ids = [c.source_id for c in event.citations]
        if hard_only and event.milestone_band != "MilestoneHard":
            continue
        validated.append(event)
    return validated


async def _build_session(session_id: str, user_id: str) -> None:
    session = load_session(session_id)
    if not session:
        return

    session.status = LenseStatus.BUILDING
    session.stage = LenseStage.RETRIEVING
    save_session(session)

    tokens = _keyword_tokens(session.topic, session.keywords, session.answers)
    date_start = session.date_range_start if session.scope == ScopeMode.DATE_RANGE else None
    date_end = session.date_range_end if session.scope == ScopeMode.DATE_RANGE else None

    try:
        emails, evidence_items, delays, programmes, chronology_items = await asyncio.gather(
            _fetch_emails(user_id, session.project_id, session.case_id, date_start, date_end, tokens),
            _fetch_evidence(session.project_id, session.case_id, date_start, date_end, tokens),
            _fetch_delays(session.case_id),
            _fetch_programmes(session.case_id, session.project_id),
            _fetch_chronology_items(session.case_id, session.project_id, date_start, date_end),
        )

        session.retrieval_stats = {
            "emails": len(emails),
            "evidence_items": len(evidence_items),
            "delays": len(delays),
            "programmes": len(programmes),
            "chronology_items": len(chronology_items),
        }
        save_session(session)

        session.stage = LenseStage.SCORING
        save_session(session)

        ref_lines, ref_map, score_map = _build_evidence_refs(
            emails, evidence_items, delays, programmes, chronology_items
        )

        session.stage = LenseStage.SYNTHESIZING
        save_session(session)

        trace = get_trace_context()
        trace_info = {"chain_id": trace.chain_id, "run_id": trace.run_id}

        db = SessionLocal()
        try:
            start_time = time.time()
            events, model_used = await _build_events_from_evidence(
                db, session, ref_lines, ref_map, trace_info
            )
            session.model_used = model_used
            existing_audit = session.audit or {}
            session.audit = {
                **existing_audit,
                "inputs": {
                    "topic": session.topic,
                    "keywords": session.keywords,
                    "detail_level": session.detail_level,
                    "scope": session.scope,
                    "date_range_start": session.date_range_start,
                    "date_range_end": session.date_range_end,
                    "hard_evidence_only": session.hard_evidence_only,
                    "answers": session.answers,
                },
                "retrieval_stats": session.retrieval_stats,
                "model_used": model_used,
                "duration_seconds": round(time.time() - start_time, 2),
            }
        finally:
            db.close()

        session.stage = LenseStage.VALIDATING
        save_session(session)

        session.events = _validate_and_score_events(
            events, score_map, session.hard_evidence_only
        )
        session.status = LenseStatus.COMPLETED
        session.stage = LenseStage.IDLE
        session.completed_at = datetime.now(timezone.utc)
        save_session(session)

    except Exception as exc:
        logger.exception("Chronology Lense build failed: %s", exc)
        session.status = LenseStatus.FAILED
        session.error_message = str(exc)
        session.stage = LenseStage.IDLE
        save_session(session)


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/start", response_model=StartLenseResponse)
async def start_lense(
    request: StartLenseRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    http_request: Request,
):
    if not request.project_id and not request.case_id:
        raise HTTPException(400, "Either project_id or case_id must be provided")

    if request.project_id:
        try:
            project_uuid = uuid.UUID(request.project_id)
        except ValueError:
            raise HTTPException(400, "Invalid project ID format")
        project = db.query(Project).filter(Project.id == project_uuid).first()
        if not project:
            raise HTTPException(404, "Project not found")
    if request.case_id:
        try:
            case_uuid = uuid.UUID(request.case_id)
        except ValueError:
            raise HTTPException(400, "Invalid case ID format")
        case = db.query(Case).filter(Case.id == case_uuid).first()
        if not case:
            raise HTTPException(404, "Case not found")

    session_id = str(uuid.uuid4())
    questions = _build_questions()
    trace_ids = _get_trace_ids(http_request)

    session = LenseSession(
        id=session_id,
        user_id=str(user.id),
        project_id=request.project_id,
        case_id=request.case_id,
        topic=request.topic,
        keywords=request.keywords,
        detail_level=request.detail_level,
        scope=request.scope,
        date_range_start=request.date_range_start,
        date_range_end=request.date_range_end,
        hard_evidence_only=request.hard_evidence_only,
        questions=questions,
        status=LenseStatus.AWAITING_INPUT,
        stage=LenseStage.IDLE,
        audit={"trace_ids": trace_ids},
    )
    save_session(session)

    return StartLenseResponse(
        session_id=session_id,
        status=session.status,
        stage=session.stage,
        questions=questions,
        message="Chronology Lense session started. Please answer the guided questions.",
    )


@router.post("/respond", response_model=RespondLenseResponse)
async def respond_lense(
    request: RespondLenseRequest,
    user: Annotated[User, Depends(current_user)],
):
    session = load_session(request.session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    session.answers.update(request.answers or {})
    ready = all(session.answers.get(q.id) for q in session.questions if q.required)
    if ready:
        session.status = LenseStatus.AWAITING_APPROVAL
    save_session(session)

    return RespondLenseResponse(
        session_id=session.id,
        status=session.status,
        stage=session.stage,
        questions=session.questions,
        ready_for_approval=ready,
    )


@router.get("/status/{session_id}", response_model=StatusLenseResponse)
async def get_lense_status(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    ready = session.status == LenseStatus.AWAITING_APPROVAL
    return StatusLenseResponse(
        session_id=session.id,
        status=session.status,
        stage=session.stage,
        ready_for_approval=ready,
        retrieval_stats=session.retrieval_stats or None,
        error_message=session.error_message,
    )


@router.post("/approve")
async def approve_lense(
    request: ApproveLenseRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
):
    session = load_session(request.session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    session.status = LenseStatus.BUILDING
    session.stage = LenseStage.RETRIEVING
    save_session(session)

    def run_build() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_build_session(session.id, session.user_id))
        finally:
            loop.close()

    background_tasks.add_task(run_build)
    return {"status": "building", "session_id": session.id}


@router.get("/results/{session_id}", response_model=ResultsLenseResponse)
async def get_lense_results(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    if session.status != LenseStatus.COMPLETED:
        raise HTTPException(409, "Results not ready")

    return ResultsLenseResponse(
        session_id=session.id,
        status=session.status,
        events=session.events,
        retrieval_stats=session.retrieval_stats or None,
        audit=session.audit or None,
    )


@router.post("/publish", response_model=PublishLenseResponse)
async def publish_lense(
    request: PublishLenseRequest,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    session = load_session(request.session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    if session.status != LenseStatus.COMPLETED:
        raise HTTPException(409, "Chronology not ready for publish")

    published = 0
    for event in session.events:
        if request.only_milestones and event.milestone_band != "MilestoneHard":
            continue
        item = ChronologyItem(
            id=uuid.uuid4(),
            case_id=uuid.UUID(session.case_id) if session.case_id else None,
            project_id=uuid.UUID(session.project_id) if session.project_id else None,
            event_date=event.event_date,
            event_type=event.event_type,
            title=event.title,
            description=event.description,
            evidence_ids=event.evidence_ids,
            parties_involved=event.parties_involved,
        )
        db.add(item)
        published += 1

    db.commit()
    return PublishLenseResponse(published_count=published)
