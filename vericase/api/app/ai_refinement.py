"""
VeriCase AI Refinement Engine
=============================
Intelligent evidence refinement using AI to:
- Cross-reference against configured project details
- Identify other projects, codes, and references
- Detect spam, newsletters, and irrelevant content
- Ask progressive questions to filter data

This is a multi-stage, conversational refinement process that
learns from each answer to ask increasingly targeted questions.
"""

import asyncio
import logging
import uuid
import json
import re
from datetime import datetime, timezone
from typing import Any, Annotated, cast
from collections import defaultdict
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import get_db
from .security import current_user
from .models import (
    EmailMessage,
    Project,
    Stakeholder,
    Keyword,
    User,
    RefinementSessionDB,
)
from .ai_settings import get_ai_api_key, get_ai_model, is_bedrock_enabled, get_bedrock_region
from .ai_providers import BedrockProvider, bedrock_available

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-refinement", tags=["ai-refinement"])

# =============================================================================
# Constants and Configuration
# =============================================================================

# Spam/Newsletter detection patterns - CONSERVATIVE to avoid false positives
# Only flag clear marketing/bulk mail, NOT normal business correspondence
SPAM_INDICATORS = {
    # HIGH CONFIDENCE - Clear marketing/newsletter indicators only (+3 points each)
    "high_confidence_words": [
        "unsubscribe from this",
        "click here to unsubscribe",
        "view in browser",
        "view this email in your browser",
        "email preferences",
        "manage your subscription",
        "% off",
        "discount code",
        "limited time offer",
    ],
    # MEDIUM CONFIDENCE - Likely bulk mail but review suggested (+1 point each)
    # NOTE: Removed "out of office", "automatic reply", "survey", "feedback"
    # as these are NORMAL business emails, not spam
    "medium_confidence_words": [
        "weekly digest",
        "daily digest",
        "monthly newsletter",
    ],
    # Marketing/automation domains - only clear bulk mail services (+3 points)
    "spam_domains": [
        "sendgrid.net",
        "constantcontact.com",
        "mailchimp.com",
        "hubspot.com",
        "marketo.com",
        "pardot.com",
        "mailgun.org",
        "eventbrite.com",
        "surveymonkey.com",
    ],
    # Social notification patterns - only clear automated notifications (+3 points)
    "automated_subjects": [
        "person is noticing",
        "person noticed",
        "people viewed your profile",
        "your weekly linkedin",
    ],
}

# Construction project patterns - including UK project naming conventions
PROJECT_CODE_PATTERNS = [
    r"\b([A-Z]{2,5}[-/]\d{2,6})\b",  # WGL-001, PRJ/12345
    r"\b(\d{4,6}[-/][A-Z]{2,4})\b",  # 12345-WGL
    r"\bProject\s+([A-Z0-9]{3,10})\b",  # Project ABC123
    r"\bRef[:\s]+([A-Z0-9-]{4,15})\b",  # Ref: ABC-123-DEF
    r"\bJob\s+(?:No\.?|Number)?[:\s]*([A-Z0-9-]{3,12})\b",  # Job No: 12345
    r"\bContract\s+(?:No\.?)?[:\s]*([A-Z0-9-/]{3,15})\b",  # Contract No: ABC/123
    r"\bSite[:\s]+([A-Za-z0-9\s-]{3,30})\b",  # Site: Main Street
]

# UK Construction Project Names - common patterns for residential/commercial developments
UK_PROJECT_NAME_PATTERNS = [
    # Street/Road names with suffix
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Road|Street|Lane|Avenue|Way|Place|Drive|Close|Court|Gardens|Crescent|Square|Gate|Row|Walk|Terrace|Mews|Yard|Wharf|Estate))\b",
    # Named developments ending in Works, House, Tower, Plaza, etc.
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Works|House|Tower|Plaza|Centre|Center|Park|Gardens|Estate|Quarter|Village|Regeneration|Development|Scheme|Phase))\b",
    # Abbreviations like BFR, LSA (3+ capital letters)
    r"\b([A-Z]{3,5})\b(?=\s+(?:project|scheme|site|development)|\s*[-–]\s*)",
]

# Known UK construction project names - EMPTY to avoid false positives
# The system will detect other projects dynamically using patterns and AI
# rather than hardcoding project names which causes false matches
KNOWN_UK_PROJECT_NAMES: list[str] = []

# Known project codes - EMPTY to avoid false positives
# Hardcoded codes cause false matches. The system detects project codes
# dynamically using patterns and cross-references with the actual project config.
KNOWN_PROJECT_CODES: dict[str, str] = {}

# Project stakeholders - EMPTY to avoid false positives
# Hardcoded stakeholder names cause false "other project" detections.
# Use the project configuration (Stakeholders table) to identify relevant parties.
PROJECT_STAKEHOLDERS: dict[str, list[str]] = {}


# =============================================================================
# Data Models
# =============================================================================


class RefinementStage(str, Enum):
    """Stages of the refinement process"""

    INITIAL_ANALYSIS = "initial_analysis"
    PROJECT_CROSS_REF = "project_cross_reference"
    SPAM_DETECTION = "spam_detection"
    PEOPLE_VALIDATION = "people_validation"
    TOPIC_FILTERING = "topic_filtering"
    DOMAIN_QUESTIONS = "domain_questions"
    FINAL_REVIEW = "final_review"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DetectedItem(BaseModel):
    """A detected item that needs user decision"""

    id: str
    item_type: str  # project, spam, person, domain, topic
    name: str
    description: str
    sample_emails: list[dict[str, Any]] = Field(default_factory=list)
    email_count: int
    confidence: ConfidenceLevel
    ai_reasoning: str
    recommended_action: str  # exclude, include, review
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefinementQuestion(BaseModel):
    """A question for the user to answer"""

    id: str
    question_text: str
    question_type: str  # yes_no, multiple_choice, multi_select, text_input
    context: str  # Why we're asking
    options: list[dict[str, Any]] = Field(default_factory=list)
    detected_items: list[DetectedItem] = Field(default_factory=list)
    priority: int = 1  # 1 = highest
    stage: RefinementStage


class RefinementAnswer(BaseModel):
    """User's answer to a question"""

    question_id: str
    answer_value: object = None  # depends on question_type
    selected_items: list[str] = Field(
        default_factory=list
    )  # IDs of items to exclude/include
    notes: str | None = None


class RefinementSession(BaseModel):
    """Complete refinement session state"""

    id: str
    project_id: str
    user_id: str
    status: str = "active"  # active, completed, cancelled
    current_stage: RefinementStage = RefinementStage.INITIAL_ANALYSIS
    questions_asked: list[RefinementQuestion] = Field(default_factory=list)
    answers_received: list[RefinementAnswer] = Field(default_factory=list)
    analysis_results: dict[str, Any] = Field(default_factory=dict)
    exclusion_rules: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisRequest(BaseModel):
    """Request to start AI analysis"""

    project_id: str
    include_spam_detection: bool = True
    include_project_detection: bool = True
    max_emails_to_analyze: int = 50000  # Increased from 2000 to handle large datasets


class AnalysisResponse(BaseModel):
    """Response from AI analysis"""

    session_id: str
    status: str
    message: str
    next_questions: list[RefinementQuestion] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


# In-memory cache for active sessions (backed by database for persistence)
_refinement_sessions: dict[str, RefinementSession] = {}


def _save_session_to_db(session: RefinementSession, db: Session) -> None:
    """Save a refinement session to the database for persistence."""
    db_session = db.query(RefinementSessionDB).filter_by(id=session.id).first()

    if db_session:
        # Update existing
        db_session.status = session.status
        db_session.current_stage = session.current_stage.value
        db_session.questions_asked = [q.model_dump() for q in session.questions_asked]
        db_session.answers_received = [a.model_dump() for a in session.answers_received]
        db_session.analysis_results = session.analysis_results
        db_session.exclusion_rules = session.exclusion_rules
    else:
        # Create new
        db_session = RefinementSessionDB(
            id=session.id,
            project_id=session.project_id,
            user_id=session.user_id,
            status=session.status,
            current_stage=session.current_stage.value,
            questions_asked=[q.model_dump() for q in session.questions_asked],
            answers_received=[a.model_dump() for a in session.answers_received],
            analysis_results=session.analysis_results,
            exclusion_rules=session.exclusion_rules,
        )
        db.add(db_session)

    db.commit()


def _load_session_from_db(session_id: str, db: Session) -> RefinementSession | None:
    """Load a refinement session from the database."""
    db_session = db.query(RefinementSessionDB).filter_by(id=session_id).first()

    if not db_session:
        return None

    # Parse questions and answers from JSON with proper typing - use cast() for SQLAlchemy JSON fields
    raw_questions = cast(list[dict[str, object]], db_session.questions_asked or [])
    questions_list: list[RefinementQuestion] = [
        RefinementQuestion.model_validate(q_data) for q_data in raw_questions
    ]

    raw_answers = cast(list[dict[str, object]], db_session.answers_received or [])
    answers_list: list[RefinementAnswer] = [
        RefinementAnswer.model_validate(a_data) for a_data in raw_answers
    ]

    # Convert back to Pydantic model
    session = RefinementSession(
        id=db_session.id,
        project_id=db_session.project_id,
        user_id=db_session.user_id,
        status=db_session.status,
        current_stage=RefinementStage(db_session.current_stage),
        questions_asked=questions_list,
        answers_received=answers_list,
        analysis_results=db_session.analysis_results or {},
        exclusion_rules=db_session.exclusion_rules or {},
    )

    # Cache it
    _refinement_sessions[session_id] = session

    return session


def _get_session(session_id: str, db: Session) -> RefinementSession | None:
    """Get a session from cache or database."""
    # Check cache first
    if session_id in _refinement_sessions:
        return _refinement_sessions[session_id]

    # Try to load from database
    return _load_session_from_db(session_id, db)


# =============================================================================
# AI Engine Class
# =============================================================================


class AIRefinementEngine:
    """
    AI-powered refinement engine that analyzes emails and generates
    intelligent questions for the user.
    """

    def __init__(self, db: Session, project: Project):
        self.db = db
        self.project = project
        self.openai_key = get_ai_api_key("openai", db)
        self.anthropic_key = get_ai_api_key("anthropic", db)
        self.gemini_key = get_ai_api_key("gemini", db)

        # Bedrock uses IAM credentials, not API keys
        self.bedrock_enabled = is_bedrock_enabled(db) and bedrock_available()
        self.bedrock_region = get_bedrock_region(db)
        self._bedrock_provider: BedrockProvider | None = None

        self.openai_model = get_ai_model("openai", db)
        self.anthropic_model = get_ai_model("anthropic", db)
        self.gemini_model = get_ai_model("gemini", db)
        self.bedrock_model = get_ai_model("bedrock", db)

        # Build project context from configuration
        self.project_context = self._build_project_context()

    @property
    def bedrock_provider(self) -> BedrockProvider | None:
        """Lazy-load Bedrock provider"""
        if self._bedrock_provider is None and self.bedrock_enabled:
            try:
                self._bedrock_provider = BedrockProvider(region=self.bedrock_region)
            except Exception as e:
                logger.warning(f"Failed to initialize Bedrock provider: {e}")
        return self._bedrock_provider

    def _build_project_context(
        self,
    ) -> dict[str, str | list[str] | list[dict[str, str]] | None]:
        """Build comprehensive project context from configuration"""
        context: dict[str, str | list[str] | list[dict[str, str]] | None] = {
            "project_name": self.project.project_name,
            "project_code": self.project.project_code,
            "aliases": list[str](),
            "site_address": None,
            "include_domains": list[str](),
            "exclude_people": list[str](),
            "project_terms": list[str](),
            "exclude_keywords": list[str](),
            "stakeholders": list[dict[str, str]](),
            "keywords": list[dict[str, str]](),
        }

        # Parse project fields
        if self.project.project_aliases:
            context["aliases"] = [
                a.strip() for a in self.project.project_aliases.split(",") if a.strip()
            ]

        if self.project.site_address:
            context["site_address"] = self.project.site_address

        if self.project.include_domains:
            context["include_domains"] = [
                d.strip() for d in self.project.include_domains.split(",") if d.strip()
            ]

        if self.project.exclude_people:
            context["exclude_people"] = [
                p.strip() for p in self.project.exclude_people.split(",") if p.strip()
            ]

        if self.project.project_terms:
            context["project_terms"] = [
                t.strip() for t in self.project.project_terms.split(",") if t.strip()
            ]

        if self.project.exclude_keywords:
            context["exclude_keywords"] = [
                k.strip() for k in self.project.exclude_keywords.split(",") if k.strip()
            ]

        # Get configured stakeholders
        stakeholders = (
            self.db.query(Stakeholder)
            .filter(Stakeholder.project_id == str(self.project.id))
            .all()
        )
        stakeholder_list: list[dict[str, str]] = []
        for s in stakeholders:
            stakeholder_list.append(
                {
                    "name": s.name or "",
                    "role": s.role or "",
                    "email": s.email or "",
                    "organization": s.organization or "",
                }
            )
        context["stakeholders"] = stakeholder_list

        # Get configured keywords
        keywords = (
            self.db.query(Keyword)
            .filter(Keyword.project_id == str(self.project.id))
            .all()
        )
        keyword_list: list[dict[str, str]] = []
        for k in keywords:
            keyword_list.append(
                {"keyword": k.keyword_name or "", "variations": k.variations or ""}
            )
        context["keywords"] = keyword_list

        return context

    async def _call_llm(self, prompt: str, system_prompt: str = "") -> str:
        """Call the best available LLM (4 providers) - Bedrock first for cost optimization"""
        # Try Bedrock FIRST - uses AWS billing, more cost effective
        if self.bedrock_enabled:
            try:
                return await self._call_bedrock(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Bedrock call failed, trying fallback: {e}")

        # Fallback to external APIs
        if self.anthropic_key:
            return await self._call_anthropic(prompt, system_prompt)

        if self.openai_key:
            return await self._call_openai(prompt, system_prompt)

        if self.gemini_key:
            return await self._call_gemini(prompt, system_prompt)

        raise HTTPException(
            500, "No AI providers configured. Please add API keys in Admin Settings."
        )

    async def _call_openai(self, prompt: str, system_prompt: str = "") -> str:
        from .ai_runtime import complete_chat

        model_id = self.openai_model
        return await complete_chat(
            provider="openai",
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.openai_key,
            max_tokens=4000,
            temperature=0.2,
        )

    async def _call_anthropic(self, prompt: str, system_prompt: str = "") -> str:
        from .ai_runtime import complete_chat

        model_id = self.anthropic_model
        return await complete_chat(
            provider="anthropic",
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt
            or "You are an expert legal analyst specializing in construction disputes and e-discovery.",
            api_key=self.anthropic_key,
            max_tokens=4000,
            temperature=0.2,
        )

    async def _call_gemini(self, prompt: str, system_prompt: str = "") -> str:
        from .ai_runtime import complete_chat

        model_id = self.gemini_model
        return await complete_chat(
            provider="gemini",
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.gemini_key,
            max_tokens=4000,
            temperature=0.2,
        )

    async def _call_bedrock(self, prompt: str, system_prompt: str = "") -> str:
        from .ai_runtime import complete_chat

        if not self.bedrock_provider:
            raise RuntimeError("Bedrock provider not available")

        model_id = self.bedrock_model
        return await complete_chat(
            provider="bedrock",
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            bedrock_provider=self.bedrock_provider,
            bedrock_region=self.bedrock_region,
            max_tokens=4000,
            temperature=0.2,
        )

    async def analyze_for_other_projects(
        self, emails: list[EmailMessage]
    ) -> list[DetectedItem]:
        """
        Use AI to intelligently detect references to other projects
        that don't match the configured project.
        """
        # Extract potential project references using patterns
        project_refs: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "samples": [], "sources": set()}
        )

        # Build list of known project identifiers to ignore
        known_identifiers: set[str] = {
            self.project.project_name.lower(),
            self.project.project_code.lower(),
        }
        aliases_raw = self.project_context.get("aliases") or []
        for alias in aliases_raw:
            if isinstance(alias, str):
                known_identifiers.add(alias.lower())

        # Extract references from emails
        for email in emails:
            text = f"{email.subject or ''} {email.body_text or ''}"

            # Standard project code patterns
            for pattern in PROJECT_CODE_PATTERNS:
                pattern_matches: list[str] = re.findall(pattern, text, re.IGNORECASE)
                for match_str in pattern_matches:
                    ref = match_str.strip()
                    if len(ref) >= 3 and ref.lower() not in known_identifiers:
                        ref_data = project_refs[ref]
                        current_count: int = int(ref_data.get("count") or 0)
                        ref_data["count"] = current_count + 1
                        samples_list: list[dict[str, Any]] = (
                            ref_data.get("samples") or []
                        )
                        ref_data["samples"] = samples_list
                        if len(samples_list) < 3:
                            samples_list.append(
                                {
                                    "subject": email.subject,
                                    "date": (
                                        email.date_sent.isoformat()
                                        if email.date_sent
                                        else None
                                    ),
                                    "sender": email.sender_email,
                                }
                            )

            # UK construction project name patterns
            for pattern in UK_PROJECT_NAME_PATTERNS:
                uk_pattern_matches: list[str] = re.findall(pattern, text)
                for uk_match_str in uk_pattern_matches:
                    ref = uk_match_str.strip()
                    # Filter out common false positives
                    if (
                        len(ref) >= 5
                        and ref.lower() not in known_identifiers
                        and ref.lower()
                        not in {"the road", "main street", "high street", "the works"}
                    ):
                        ref_data2 = project_refs[ref]
                        current_count2: int = int(ref_data2.get("count") or 0)
                        ref_data2["count"] = current_count2 + 1
                        samples_list2: list[dict[str, Any]] = (
                            ref_data2.get("samples") or []
                        )
                        ref_data2["samples"] = samples_list2
                        if len(samples_list2) < 3:
                            samples_list2.append(
                                {
                                    "subject": email.subject,
                                    "date": (
                                        email.date_sent.isoformat()
                                        if email.date_sent
                                        else None
                                    ),
                                    "sender": email.sender_email,
                                }
                            )

            # Check for known UK project names
            text_lower = text.lower()
            for known_name in KNOWN_UK_PROJECT_NAMES:
                if (
                    known_name.lower() in text_lower
                    and known_name.lower() not in known_identifiers
                ):
                    ref_data3 = project_refs[known_name]
                    current_count3: int = int(ref_data3.get("count") or 0)
                    ref_data3["count"] = current_count3 + 1
                    samples_list3: list[dict[str, Any]] = ref_data3.get("samples") or []
                    ref_data3["samples"] = samples_list3
                    if len(samples_list3) < 3:
                        samples_list3.append(
                            {
                                "subject": email.subject,
                                "date": (
                                    email.date_sent.isoformat()
                                    if email.date_sent
                                    else None
                                ),
                                "sender": email.sender_email,
                            }
                        )

            # Check for known project codes (e.g., "1328", "8001")
            for code, proj_name in KNOWN_PROJECT_CODES.items():
                if code in text and proj_name.lower() not in known_identifiers:
                    ref_data4 = project_refs[proj_name]
                    current_count4: int = int(ref_data4.get("count") or 0)
                    ref_data4["count"] = current_count4 + 1
                    ref_data4["detected_code"] = code
                    samples_list4: list[dict[str, Any]] = ref_data4.get("samples") or []
                    ref_data4["samples"] = samples_list4
                    if len(samples_list4) < 3:
                        samples_list4.append(
                            {
                                "subject": email.subject,
                                "date": (
                                    email.date_sent.isoformat()
                                    if email.date_sent
                                    else None
                                ),
                                "sender": email.sender_email,
                                "matched_code": code,
                            }
                        )

            # Check for project stakeholder keywords
            for proj_name, stakeholders in PROJECT_STAKEHOLDERS.items():
                if proj_name.lower() in known_identifiers:
                    continue
                for stakeholder in stakeholders:
                    if stakeholder.lower() in text_lower:
                        ref_data5 = project_refs[proj_name]
                        current_count5: int = int(ref_data5.get("count") or 0)
                        ref_data5["count"] = current_count5 + 1
                        matched_stakeholders: list[str] = (
                            ref_data5.get("matched_stakeholders") or []
                        )
                        ref_data5["matched_stakeholders"] = matched_stakeholders
                        if stakeholder not in matched_stakeholders:
                            matched_stakeholders.append(stakeholder)
                        samples_list5: list[dict[str, Any]] = (
                            ref_data5.get("samples") or []
                        )
                        ref_data5["samples"] = samples_list5
                        if len(samples_list5) < 3:
                            samples_list5.append(
                                {
                                    "subject": email.subject,
                                    "date": (
                                        email.date_sent.isoformat()
                                        if email.date_sent
                                        else None
                                    ),
                                    "sender": email.sender_email,
                                    "matched_stakeholder": stakeholder,
                                }
                            )
                        break  # Only count once per email per project

        # Filter to significant references
        significant_refs = {
            ref: data for ref, data in project_refs.items() if data["count"] >= 3
        }

        if not significant_refs:
            return []

        # Use AI to analyze these references
        refs_summary = json.dumps(
            {
                ref: {"count": data["count"], "samples": data["samples"][:2]}
                for ref, data in list(significant_refs.items())[:20]
            },
            indent=2,
        )

        system_prompt = """You are an expert at analyzing construction project correspondence.
Your task is to identify references to OTHER projects that are NOT the main project being analyzed.

You must distinguish between:
- References to OTHER separate projects (should be flagged for exclusion)
- Sub-projects or phases of the MAIN project (should NOT be flagged)
- Generic reference codes that aren't projects (invoice numbers, PO numbers, etc.)"""

        prompt = f"""Analyze these potential project references found in emails.

MAIN PROJECT CONTEXT:
- Project Name: {self.project.project_name}
- Project Code: {self.project.project_code}
- Aliases: {', '.join(str(a) for a in (self.project_context.get('aliases') or [])) or 'None'}
- Site Address: {self.project_context.get('site_address') or 'Not specified'}
- Key Terms: {', '.join(str(t) for t in (self.project_context.get('project_terms') or [])) or 'None'}

DETECTED REFERENCES:
{refs_summary}

For each reference, determine:
1. Is this a DIFFERENT project (not a sub-project or phase of {self.project.project_name})?
2. How confident are you? (high/medium/low)
3. Why do you think this?
4. What action do you recommend?

Output JSON array:
[
  {{
    "reference": "the code or name",
    "is_other_project": true/false,
    "confidence": "high/medium/low",
    "reasoning": "explanation",
    "recommended_action": "exclude" or "keep" or "review"
  }}
]

Only include references that appear to be OTHER projects (is_other_project: true).
"""

        response = await self._call_llm(prompt, system_prompt)

        # Parse AI response
        detected_items: list[DetectedItem] = []
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            ai_results_raw: object = json.loads(json_str.strip())
            ai_results: list[dict[str, object]] = []
            if isinstance(ai_results_raw, list):
                raw_list = cast(list[object], ai_results_raw)
                for raw_item in raw_list:
                    if isinstance(raw_item, dict):
                        ai_results.append(cast(dict[str, object], raw_item))

            for result in ai_results:
                if result.get("is_other_project"):
                    ref_name: str = str(result.get("reference") or "")
                    ref_data_result = significant_refs.get(
                        ref_name, {"count": 0, "samples": []}
                    )
                    ref_count_obj: object = ref_data_result.get("count")
                    ref_count: int = (
                        int(ref_count_obj)
                        if isinstance(ref_count_obj, (int, float))
                        else 0
                    )
                    ref_samples_obj: object = ref_data_result.get("samples")
                    ref_samples: list[dict[str, Any]] = (
                        cast(list[dict[str, Any]], ref_samples_obj)
                        if isinstance(ref_samples_obj, list)
                        else []
                    )

                    confidence_val: str = str(result.get("confidence") or "medium")
                    reasoning_val: str = str(result.get("reasoning") or "")
                    action_val: str = str(result.get("recommended_action") or "review")

                    # Convert any sets to lists for JSON serialization
                    serializable_ref_data: dict[str, Any] = {}
                    ref_data_items: list[tuple[str, object]] = list(
                        ref_data_result.items()
                    )
                    for k, v in ref_data_items:
                        if isinstance(v, set):
                            serializable_ref_data[k] = list(cast(set[object], v))
                        else:
                            serializable_ref_data[k] = v

                    detected_items.append(
                        DetectedItem(
                            id=f"proj_{uuid.uuid4().hex[:8]}",
                            item_type="other_project",
                            name=ref_name,
                            description=f"Project reference '{ref_name}' found {ref_count} times",
                            sample_emails=ref_samples,
                            email_count=ref_count,
                            confidence=ConfidenceLevel(confidence_val),
                            ai_reasoning=reasoning_val,
                            recommended_action=action_val,
                            metadata={"pattern_matches": serializable_ref_data},
                        )
                    )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse AI response for project detection: {e}")

        return detected_items

    async def analyze_for_duplicates(
        self, emails: list[EmailMessage]
    ) -> list[DetectedItem]:
        """
        Detect duplicate emails based on subject, body content, and timestamps.
        Groups duplicates and identifies which to keep.
        """
        import hashlib

        # Build content signatures for each email
        email_signatures: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for email in emails:
            # Create content signature from subject + body
            content = f"{(email.subject or '').strip().lower()}"
            body_text = (email.body_text or "").strip()
            if body_text:
                # Normalize body - remove whitespace variations
                normalized_body = " ".join(body_text.split()[:100])  # First 100 words
                content += f":{normalized_body}"

            # Create hash signature
            signature = hashlib.md5(content.encode()).hexdigest()[:16]

            email_signatures[signature].append(
                {
                    "id": str(email.id),
                    "subject": email.subject,
                    "sender": email.sender_email,
                    "date": email.date_sent,
                    "date_str": (
                        email.date_sent.isoformat() if email.date_sent else None
                    ),
                }
            )

        # Find duplicates (more than 1 email with same signature)
        detected_items: list[DetectedItem] = []

        for signature, email_list in email_signatures.items():
            if len(email_list) >= 2:
                # Sort by date to find the original
                sorted_emails = sorted(
                    email_list, key=lambda x: x["date"] or datetime.min
                )

                original = sorted_emails[0]
                duplicates = sorted_emails[1:]

                # Calculate timespan
                original_date: datetime | None = original.get("date")
                last_date: datetime | None = sorted_emails[-1].get("date")
                timespan: int = 0
                if original_date and last_date:
                    timespan = (last_date - original_date).days

                detected_items.append(
                    DetectedItem(
                        id=f"dup_{signature}",
                        item_type="duplicate_email",
                        name=original["subject"] or "No Subject",
                        description=f"Found {len(duplicates)} duplicate(s) of email from {original['sender']}",
                        sample_emails=[
                            {
                                "subject": e["subject"],
                                "sender": e["sender"],
                                "date": e["date_str"],
                            }
                            for e in sorted_emails[:4]
                        ],
                        email_count=len(email_list),
                        confidence=(
                            ConfidenceLevel.HIGH
                            if len(email_list) >= 3
                            else ConfidenceLevel.MEDIUM
                        ),
                        ai_reasoning=f"Identical content found {len(email_list)} times. Original from {original['date_str']}. Span: {timespan} days.",
                        recommended_action="remove_duplicates",
                        metadata={
                            "signature": signature,
                            "original_id": original["id"],
                            "duplicate_ids": [e["id"] for e in duplicates],
                            "all_ids": [e["id"] for e in email_list],
                            "timespan_days": timespan,
                        },
                    )
                )

        # Sort by count descending
        detected_items.sort(key=lambda x: x.email_count, reverse=True)
        return detected_items[:30]  # Top 30 duplicate groups

    async def analyze_for_spam(self, emails: list[EmailMessage]) -> list[DetectedItem]:
        """
        Detect spam, newsletters, automated messages, and irrelevant content.
        """
        spam_candidates: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "samples": [],
                "reasons": set(),
                "domain": None,
                "sender": None,
            }
        )

        for email in emails:
            spam_score = 0
            reasons: set[str] = set()

            subject_lower = (email.subject or "").lower()
            body_lower = (email.body_text or "").lower()
            sender_email_addr = (email.sender_email or "").lower()
            sender_domain = (
                sender_email_addr.split("@")[-1] if "@" in sender_email_addr else ""
            )

            # Check HIGH CONFIDENCE spam indicators (+3 points each)
            for word in SPAM_INDICATORS["high_confidence_words"]:
                if word in body_lower or word in subject_lower:
                    spam_score += 3
                    reasons.add(f"Contains '{word}'")

            # Check MEDIUM CONFIDENCE indicators (+1 point each)
            for word in SPAM_INDICATORS["medium_confidence_words"]:
                if word in body_lower or word in subject_lower:
                    spam_score += 1
                    reasons.add(f"Contains '{word}' (review suggested)")

            # Check spam domains (+3 points)
            for domain in SPAM_INDICATORS["spam_domains"]:
                if domain in sender_domain or domain in sender_email_addr:
                    spam_score += 3
                    reasons.add(f"From marketing/social domain: {domain}")

            # Check automated subjects (+3 points)
            for pattern in SPAM_INDICATORS["automated_subjects"]:
                if pattern in subject_lower:
                    spam_score += 3
                    reasons.add(f"Automated notification: '{pattern}'")

            # Check for HTML-heavy content with minimal text (typical of newsletters)
            if email.body_html and len(email.body_html) > 5000:
                body_text_len = len(email.body_text or "")
                if body_text_len < 500:
                    spam_score += 1
                    reasons.add("HTML-heavy with minimal text content")

            # Group by sender domain for bulk detection (threshold: 3 = high confidence hit)
            if spam_score >= 3:
                key = sender_domain or sender_email_addr
                candidate = spam_candidates[key]
                cand_count_obj: object = candidate.get("count")
                cand_count: int = (
                    int(cand_count_obj)
                    if isinstance(cand_count_obj, (int, float))
                    else 0
                )
                candidate["count"] = cand_count + 1
                cand_reasons_obj: object = candidate.get("reasons")
                existing_reasons: set[str] = (
                    cand_reasons_obj if isinstance(cand_reasons_obj, set) else set()
                )
                existing_reasons.update(reasons)
                candidate["reasons"] = existing_reasons
                candidate["domain"] = sender_domain
                candidate["sender"] = email.sender_name or sender_email_addr
                cand_samples_obj: object = candidate.get("samples")
                spam_samples: list[dict[str, Any]] = (
                    cast(list[dict[str, Any]], cand_samples_obj)
                    if isinstance(cand_samples_obj, list)
                    else []
                )
                candidate["samples"] = spam_samples
                if len(spam_samples) < 3:
                    spam_samples.append(
                        {
                            "subject": email.subject,
                            "date": (
                                email.date_sent.isoformat() if email.date_sent else None
                            ),
                            "sender": sender_email_addr,
                        }
                    )

        # Convert to detected items
        spam_detected_items: list[DetectedItem] = []

        def get_spam_count(item: tuple[str, dict[str, Any]]) -> int:
            count_obj: object = item[1].get("count")
            return int(count_obj) if isinstance(count_obj, (int, float)) else 0

        sorted_spam = sorted(spam_candidates.items(), key=get_spam_count, reverse=True)
        for key, data in sorted_spam:
            data_count_obj: object = data.get("count")
            data_count: int = (
                int(data_count_obj) if isinstance(data_count_obj, (int, float)) else 0
            )
            if data_count >= 2:  # At least 2 emails to consider bulk
                confidence = (
                    ConfidenceLevel.HIGH if data_count >= 5 else ConfidenceLevel.MEDIUM
                )
                data_reasons_obj: object = data.get("reasons")
                data_reasons: set[str] = (
                    data_reasons_obj if isinstance(data_reasons_obj, set) else set()
                )
                data_samples_obj: object = data.get("samples")
                data_samples: list[dict[str, Any]] = (
                    cast(list[dict[str, Any]], data_samples_obj)
                    if isinstance(data_samples_obj, list)
                    else []
                )
                data_domain_obj: object = data.get("domain")
                data_domain: str | None = (
                    data_domain_obj if isinstance(data_domain_obj, str) else None
                )
                data_sender_obj: object = data.get("sender")
                data_sender: str | None = (
                    data_sender_obj if isinstance(data_sender_obj, str) else None
                )

                spam_detected_items.append(
                    DetectedItem(
                        id=f"spam_{uuid.uuid4().hex[:8]}",
                        item_type="spam_newsletter",
                        name=data_sender or key,
                        description=f"Potential spam/newsletter from {key} ({data_count} emails)",
                        sample_emails=data_samples,
                        email_count=data_count,
                        confidence=confidence,
                        ai_reasoning=f"Detected indicators: {', '.join(list(data_reasons)[:3])}",
                        recommended_action="exclude" if data_count >= 5 else "review",
                        metadata={"domain": data_domain, "reasons": list(data_reasons)},
                    )
                )

        return spam_detected_items[:20]  # Top 20 spam candidates

    async def analyze_domains_and_people(
        self, emails: list[EmailMessage]
    ) -> tuple[list[DetectedItem], list[DetectedItem]]:
        """
        Analyze email domains and people, cross-referencing with project config.
        """
        domain_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "people": set(), "first_seen": None, "last_seen": None}
        )

        include_domains_raw = self.project_context.get("include_domains") or []
        known_domains: set[str] = set()
        for d in include_domains_raw:
            if isinstance(d, str):
                known_domains.add(d.lower())

        exclude_people_raw = self.project_context.get("exclude_people") or []
        excluded_people: set[str] = set()
        for p in exclude_people_raw:
            if isinstance(p, str):
                excluded_people.add(p.lower())

        stakeholders_raw = self.project_context.get("stakeholders") or []
        known_stakeholder_emails: set[str] = set()
        for s in stakeholders_raw:
            if isinstance(s, dict):
                s_email = s.get("email")
                if isinstance(s_email, str) and s_email:
                    known_stakeholder_emails.add(s_email.lower())

        for email in emails:
            email_sender = (email.sender_email or "").lower()
            if "@" not in email_sender:
                continue

            domain = email_sender.split("@")[-1]
            sender_name = email.sender_name or email_sender.split("@")[0]

            dom_stat = domain_stats[domain]
            dom_count_obj: object = dom_stat.get("count")
            dom_count: int = (
                int(dom_count_obj) if isinstance(dom_count_obj, (int, float)) else 0
            )
            dom_stat["count"] = dom_count + 1
            dom_people_obj: object = dom_stat.get("people")
            people_set: set[str] = (
                dom_people_obj if isinstance(dom_people_obj, set) else set()
            )
            people_set.add(sender_name)
            dom_stat["people"] = people_set

            if email.date_sent:
                first_seen = dom_stat.get("first_seen")
                last_seen = dom_stat.get("last_seen")
                if not first_seen or email.date_sent < first_seen:
                    dom_stat["first_seen"] = email.date_sent
                if not last_seen or email.date_sent > last_seen:
                    dom_stat["last_seen"] = email.date_sent

        # Identify unknown domains (not in project config)
        unknown_domains: list[DetectedItem] = []

        def get_dom_count(item: tuple[str, dict[str, Any]]) -> int:
            c: object = item[1].get("count")
            return int(c) if isinstance(c, (int, float)) else 0

        sorted_domains = sorted(domain_stats.items(), key=get_dom_count, reverse=True)
        for domain, stats in sorted_domains:
            stats_count_obj: object = stats.get("count")
            stats_count: int = (
                int(stats_count_obj) if isinstance(stats_count_obj, (int, float)) else 0
            )
            if domain not in known_domains and stats_count >= 3:
                # Check if any stakeholders are from this domain
                is_stakeholder_domain = False
                for s in stakeholders_raw:
                    if isinstance(s, dict):
                        s_email_check = s.get("email")
                        if (
                            isinstance(s_email_check, str)
                            and domain in s_email_check.lower()
                        ):
                            is_stakeholder_domain = True
                            break

                if not is_stakeholder_domain:
                    stats_people_raw = stats.get("people")
                    stats_people: set[str] = (
                        stats_people_raw if isinstance(stats_people_raw, set) else set()
                    )
                    stats_first_raw = stats.get("first_seen")
                    stats_first: datetime | None = (
                        stats_first_raw
                        if isinstance(stats_first_raw, datetime)
                        else None
                    )
                    stats_last_raw = stats.get("last_seen")
                    stats_last: datetime | None = (
                        stats_last_raw if isinstance(stats_last_raw, datetime) else None
                    )
                    unknown_domains.append(
                        DetectedItem(
                            id=f"domain_{uuid.uuid4().hex[:8]}",
                            item_type="unknown_domain",
                            name=domain,
                            description=f"Unknown domain with {stats_count} emails from {len(stats_people)} people",
                            sample_emails=[],
                            email_count=stats_count,
                            confidence=ConfidenceLevel.MEDIUM,
                            ai_reasoning=f"Domain not in project configuration. People: {', '.join(list(stats_people)[:5])}",
                            recommended_action="review",
                            metadata={
                                "people": list(stats_people),
                                "first_seen": (
                                    stats_first.isoformat() if stats_first else None
                                ),
                                "last_seen": (
                                    stats_last.isoformat() if stats_last else None
                                ),
                            },
                        )
                    )

        # Identify high-volume senders not in stakeholders
        people_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "domain": None, "name": None}
        )

        for email in emails:
            email_sender_addr = (email.sender_email or "").lower()
            if email_sender_addr and email_sender_addr not in known_stakeholder_emails:
                pstat = people_stats[email_sender_addr]
                pstat_count_obj: object = pstat.get("count")
                pstat_count_val: int = (
                    int(pstat_count_obj)
                    if isinstance(pstat_count_obj, (int, float))
                    else 0
                )
                pstat["count"] = pstat_count_val + 1
                pstat["name"] = email.sender_name
                if "@" in email_sender_addr:
                    pstat["domain"] = email_sender_addr.split("@")[-1]

        unknown_people: list[DetectedItem] = []

        def get_people_count(item: tuple[str, dict[str, Any]]) -> int:
            c: object = item[1].get("count")
            return int(c) if isinstance(c, (int, float)) else 0

        sorted_people = sorted(
            people_stats.items(), key=get_people_count, reverse=True
        )[:30]
        for email_addr, stats in sorted_people:
            pstat_count_obj2: object = stats.get("count")
            pstat_count: int = (
                int(pstat_count_obj2)
                if isinstance(pstat_count_obj2, (int, float))
                else 0
            )
            if pstat_count >= 5:
                # Check if this person should be excluded
                pstat_name: str = str(stats.get("name") or "")
                is_excluded = False
                for excl in excluded_people:
                    if excl in email_addr or excl in pstat_name.lower():
                        is_excluded = True
                        break

                unknown_people.append(
                    DetectedItem(
                        id=f"person_{uuid.uuid4().hex[:8]}",
                        item_type="unknown_person",
                        name=pstat_name or email_addr,
                        description=f"Sender with {pstat_count} emails, not in stakeholder list",
                        sample_emails=[],
                        email_count=pstat_count,
                        confidence=ConfidenceLevel.MEDIUM,
                        ai_reasoning=f"Email: {email_addr}, Domain: {stats.get('domain')}",
                        recommended_action="exclude" if is_excluded else "review",
                        metadata={
                            "email": email_addr,
                            "domain": stats.get("domain"),
                            "pre_excluded": is_excluded,
                        },
                    )
                )

        return unknown_domains[:15], unknown_people[:20]

    async def generate_intelligent_questions(
        self,
        session: RefinementSession,
        detected_projects: list[DetectedItem],
        detected_spam: list[DetectedItem],
        detected_domains: list[DetectedItem],
        detected_people: list[DetectedItem],
        detected_duplicates: list[DetectedItem],
        total_emails: int,
    ) -> list[RefinementQuestion]:
        """
        Generate intelligent questions in a LOGICAL order:
        1. Date range - scope the analysis period
        2. Relevant parties - identify who matters (skip if project config exists)
        3. Other projects - filter out unrelated project emails
        4. Spam/newsletters - remove marketing content
        5. Duplicates - clean up duplicated emails
        """
        questions: list[RefinementQuestion] = []

        # Check if project already has stakeholder configuration
        has_stakeholder_config = bool(self.project_context.get("stakeholders"))

        # STEP 1: Date range - Define the analysis scope first
        questions.append(
            RefinementQuestion(
                id=f"q_{uuid.uuid4().hex[:8]}",
                question_text="What date range should I focus on for this analysis?",
                question_type="date_range",
                context=f"You have {total_emails} emails. Narrowing the date range can help focus on the relevant period.",
                options=[
                    {"value": "all", "label": "Analyze all dates"},
                    {"value": "custom", "label": "Set custom date range"},
                    {"value": "last_year", "label": "Last 12 months only"},
                    {"value": "last_2_years", "label": "Last 2 years"},
                ],
                detected_items=[],
                priority=1,
                stage=RefinementStage.INITIAL_ANALYSIS,
            )
        )

        # STEP 2: Identify relevant parties (skip redundant questions if config exists)
        if not has_stakeholder_config:
            # Ask about high-volume senders to understand who the key parties are
            high_volume_unknown = [p for p in detected_people if p.email_count >= 10]
            if high_volume_unknown:
                questions.append(
                    RefinementQuestion(
                        id=f"q_{uuid.uuid4().hex[:8]}",
                        question_text=f"These {len(high_volume_unknown)} people sent many emails. Who are the key parties?",
                        question_type="categorize",
                        context="Identifying key parties helps understand the correspondence. Categorize by role.",
                        options=[
                            {"value": "client", "label": "Client/Employer"},
                            {"value": "contractor", "label": "Main Contractor"},
                            {"value": "subcontractor", "label": "Subcontractor"},
                            {"value": "consultant", "label": "Consultant/Professional"},
                            {"value": "exclude", "label": "Not relevant - exclude"},
                            {"value": "keep", "label": "Keep but don't categorize"},
                        ],
                        detected_items=high_volume_unknown,
                        priority=2,
                        stage=RefinementStage.PEOPLE_VALIDATION,
                    )
                )

            # Ask about unknown domains
            if detected_domains:
                questions.append(
                    RefinementQuestion(
                        id=f"q_{uuid.uuid4().hex[:8]}",
                        question_text=f"I found emails from {len(detected_domains)} domains not in your config. Which are relevant?",
                        question_type="multi_select",
                        context="Select the domains that should be INCLUDED in your analysis.",
                        options=[
                            {"value": "include_selected", "label": "Include only selected domains"},
                            {"value": "include_all", "label": "Include all domains shown"},
                            {"value": "review_later", "label": "Skip for now"},
                        ],
                        detected_items=detected_domains,
                        priority=2,
                        stage=RefinementStage.DOMAIN_QUESTIONS,
                    )
                )

        # STEP 3: Filter out other projects
        if detected_projects:
            questions.append(
                RefinementQuestion(
                    id=f"q_{uuid.uuid4().hex[:8]}",
                    question_text=f"I found references to {len(detected_projects)} other projects. Exclude emails about these?",
                    question_type="multi_select",
                    context=f"Your project is '{self.project.project_name}'. These appear to be different projects.",
                    options=[
                        {"value": "exclude_all", "label": "Exclude all other project emails"},
                        {"value": "select_individual", "label": "Let me select which to exclude"},
                        {"value": "keep_all", "label": "Keep all (might be related)"},
                    ],
                    detected_items=detected_projects,
                    priority=3,
                    stage=RefinementStage.PROJECT_CROSS_REF,
                )
            )

        # STEP 4: Remove spam/newsletters
        if detected_spam:
            total_spam_count = sum(item.email_count for item in detected_spam)
            questions.append(
                RefinementQuestion(
                    id=f"q_{uuid.uuid4().hex[:8]}",
                    question_text=f"I identified {total_spam_count} likely spam/newsletter emails. Remove these?",
                    question_type="multi_select",
                    context="These contain marketing language, unsubscribe links, or come from bulk mail services.",
                    options=[
                        {"value": "exclude_all", "label": f"Remove all {total_spam_count} spam emails"},
                        {"value": "select_individual", "label": "Let me review each source"},
                        {"value": "keep_all", "label": "Keep all"},
                    ],
                    detected_items=detected_spam,
                    priority=4,
                    stage=RefinementStage.SPAM_DETECTION,
                )
            )

        # STEP 5: Remove duplicates
        if detected_duplicates:
            total_dup_count = sum(item.email_count - 1 for item in detected_duplicates)
            questions.append(
                RefinementQuestion(
                    id=f"q_{uuid.uuid4().hex[:8]}",
                    question_text=f"I found {total_dup_count} duplicate emails. Remove these?",
                    question_type="multi_select",
                    context="Duplicate emails have identical content. Removing keeps one copy of each.",
                    options=[
                        {"value": "remove_all", "label": f"Remove all {total_dup_count} duplicates (keep originals)"},
                        {"value": "select_individual", "label": "Let me review the duplicate groups"},
                        {"value": "keep_all", "label": "Keep all including duplicates"},
                    ],
                    detected_items=detected_duplicates,
                    priority=5,
                    stage=RefinementStage.FINAL_REVIEW,
                )
            )

        return questions


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/analyze", response_model=AnalysisResponse)
async def start_ai_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Start AI-powered analysis of project emails.
    Returns a session ID and first set of questions.
    """
    # Verify project
    project = db.query(Project).filter_by(id=request.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    # Create session
    session_id = str(uuid.uuid4())
    session = RefinementSession(
        id=session_id,
        project_id=request.project_id,
        user_id=str(user.id),
        status="analyzing",
    )
    _refinement_sessions[session_id] = session

    # Get emails for analysis
    emails = (
        db.query(EmailMessage)
        .filter(EmailMessage.project_id == request.project_id)
        .order_by(EmailMessage.date_sent.desc())
        .limit(request.max_emails_to_analyze)
        .all()
    )

    if not emails:
        raise HTTPException(400, "No emails found in project")

    # Run AI analysis
    engine = AIRefinementEngine(db, project)

    try:
        # Run analysis tasks
        detected_projects = []
        detected_spam = []
        detected_domains = []
        detected_people = []

        if request.include_project_detection:
            detected_projects = await engine.analyze_for_other_projects(emails)

        if request.include_spam_detection:
            detected_spam = await engine.analyze_for_spam(emails)

        detected_domains, detected_people = await engine.analyze_domains_and_people(
            emails
        )

        # Detect duplicate emails
        detected_duplicates = await engine.analyze_for_duplicates(emails)

        # Generate questions
        questions = await engine.generate_intelligent_questions(
            session,
            detected_projects,
            detected_spam,
            detected_domains,
            detected_people,
            detected_duplicates,
            len(emails),
        )

        # Update session
        session.analysis_results = {
            "total_emails": len(emails),
            "detected_projects": [p.model_dump() for p in detected_projects],
            "detected_spam": [s.model_dump() for s in detected_spam],
            "detected_domains": [d.model_dump() for d in detected_domains],
            "detected_people": [p.model_dump() for p in detected_people],
            "detected_duplicates": [d.model_dump() for d in detected_duplicates],
        }
        session.questions_asked = questions
        session.status = "awaiting_answers"
        session.current_stage = (
            RefinementStage.PROJECT_CROSS_REF
            if detected_projects
            else RefinementStage.SPAM_DETECTION
        )

        # Save session to database for persistence
        _save_session_to_db(session, db)

        return AnalysisResponse(
            session_id=session_id,
            status="ready",
            message=f"Analysis complete. Analyzed {len(emails)} emails and generated {len(questions)} questions.",
            next_questions=questions,
            summary={
                "total_emails": len(emails),
                "duplicates_found": len(detected_duplicates),
                "other_projects_found": len(detected_projects),
                "spam_sources_found": len(detected_spam),
                "unknown_domains": len(detected_domains),
                "unknown_people": len(detected_people),
            },
        )

    except Exception as e:
        logger.exception(f"AI analysis failed: {e}")
        session.status = "failed"
        raise HTTPException(500, f"Analysis failed: {str(e)}")


@router.post("/answer")
async def submit_answer(
    answer: RefinementAnswer,
    session_id: Annotated[str, Query(description="Session ID")],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Submit an answer to a refinement question.
    Returns the next question or final summary.
    """
    session = _get_session(session_id, db)
    if not session:
        raise HTTPException(404, "Session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Record answer
    session.answers_received.append(answer)
    session.updated_at = datetime.now(timezone.utc)

    # Process answer and build exclusion rules
    question = next(
        (q for q in session.questions_asked if q.id == answer.question_id), None
    )
    raw_answer: object = answer.answer_value
    answer_val = str(raw_answer) if raw_answer is not None else ""

    if question:
        # Handle deduplication answers
        if (
            question.stage == RefinementStage.INITIAL_ANALYSIS
            and "duplicate" in question.question_text.lower()
        ):
            if answer_val == "remove_all":
                # Collect all duplicate IDs (not originals)
                duplicate_ids: list[str] = []
                for item in question.detected_items:
                    dup_ids_raw: object = item.metadata.get("duplicate_ids", [])
                    if isinstance(dup_ids_raw, list):
                        dup_list = cast(list[object], dup_ids_raw)
                        duplicate_ids.extend([str(d_item) for d_item in dup_list])
                session.exclusion_rules["remove_duplicate_ids"] = duplicate_ids
            elif answer_val == "select_individual":
                session.exclusion_rules["remove_duplicate_ids"] = answer.selected_items

        elif question.stage == RefinementStage.PROJECT_CROSS_REF:
            if answer_val == "exclude_all":
                session.exclusion_rules["exclude_project_refs"] = [
                    item.name for item in question.detected_items
                ]
            elif answer_val == "select_individual":
                # Map selected IDs back to project names
                selected_names = [
                    item.name
                    for item in question.detected_items
                    if item.id in answer.selected_items
                ]
                session.exclusion_rules["exclude_project_refs"] = selected_names

        elif question.stage == RefinementStage.SPAM_DETECTION:
            if answer_val == "exclude_all":
                session.exclusion_rules["exclude_spam_domains"] = [
                    item.metadata.get("domain")
                    for item in question.detected_items
                    if item.metadata.get("domain")
                ]
            elif answer_val == "select_individual":
                # Map selected IDs back to domains
                selected_domains = [
                    item.metadata.get("domain")
                    for item in question.detected_items
                    if item.id in answer.selected_items and item.metadata.get("domain")
                ]
                session.exclusion_rules["exclude_spam_domains"] = selected_domains

    # Find next unanswered question
    answered_ids = {a.question_id for a in session.answers_received}
    remaining = [q for q in session.questions_asked if q.id not in answered_ids]

    # Save session to database
    _save_session_to_db(session, db)

    if remaining:
        return {
            "status": "more_questions",
            "next_question": remaining[0],
            "questions_remaining": len(remaining),
            "progress": len(session.answers_received) / len(session.questions_asked),
        }
    else:
        session.status = "ready_to_apply"
        _save_session_to_db(session, db)
        return {
            "status": "complete",
            "message": "All questions answered. Ready to apply refinement.",
            "exclusion_rules": session.exclusion_rules,
            "summary": session.analysis_results,
        }


@router.post("/{session_id}/apply")
async def apply_refinement(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Apply the refinement rules to exclude emails.
    """
    session = _get_session(session_id, db)
    if not session:
        raise HTTPException(404, "Session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Get project
    project = db.query(Project).filter_by(id=session.project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    # Apply exclusion rules
    excluded_count = 0
    duplicate_removed_count = 0
    rules = session.exclusion_rules

    emails = (
        db.query(EmailMessage)
        .filter(EmailMessage.project_id == session.project_id)
        .all()
    )

    # Build sets for faster lookup with proper typing
    exclude_project_refs: list[str] = []
    exclude_spam_domains: list[str] = []
    exclude_people: list[str] = []
    remove_duplicate_ids: set[str] = set()

    raw_project_refs: object = rules.get("exclude_project_refs")
    if isinstance(raw_project_refs, list):
        refs_list = cast(list[object], raw_project_refs)
        exclude_project_refs = [str(r_item) for r_item in refs_list]

    raw_spam_domains: object = rules.get("exclude_spam_domains")
    if isinstance(raw_spam_domains, list):
        domains_list = cast(list[object], raw_spam_domains)
        exclude_spam_domains = [str(d_item) for d_item in domains_list]

    raw_exclude_people: object = rules.get("exclude_people")
    if isinstance(raw_exclude_people, list):
        people_list = cast(list[object], raw_exclude_people)
        exclude_people = [str(p_item) for p_item in people_list]

    raw_duplicate_ids: object = rules.get("remove_duplicate_ids")
    if isinstance(raw_duplicate_ids, list):
        dup_list = cast(list[object], raw_duplicate_ids)
        remove_duplicate_ids = {str(dup_item) for dup_item in dup_list}

    for email in emails:
        should_exclude = False
        exclude_reason: str | None = None
        email_id_str = str(email.id)

        # Check if email is a duplicate to remove
        if email_id_str in remove_duplicate_ids:
            should_exclude = True
            exclude_reason = "duplicate"
            duplicate_removed_count += 1

        # Check project references
        if not should_exclude and exclude_project_refs:
            text = f"{email.subject or ''} {email.body_text or ''}".lower()
            for ref in exclude_project_refs:
                if ref.lower() in text:
                    should_exclude = True
                    exclude_reason = f"other_project:{ref}"
                    break

        # Check spam domains
        if not should_exclude and exclude_spam_domains:
            sender_domain = (email.sender_email or "").split("@")[-1].lower()
            if sender_domain in [d.lower() for d in exclude_spam_domains]:
                should_exclude = True
                exclude_reason = f"spam:{sender_domain}"

        # Check excluded people
        if not should_exclude and exclude_people:
            sender = (email.sender_email or "").lower()
            if sender in [p.lower() for p in exclude_people]:
                should_exclude = True
                exclude_reason = f"excluded_person:{sender}"

        if should_exclude:
            meta = dict(email.meta) if email.meta else {}
            meta["ai_excluded"] = True
            meta["ai_exclude_reason"] = exclude_reason
            meta["ai_exclude_session"] = session_id
            email.meta = meta
            excluded_count += 1

    # Save refinement to project
    project_meta = dict(project.meta) if project.meta else {}
    project_meta["ai_refinement"] = {
        "session_id": session_id,
        "rules": rules,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "excluded_count": excluded_count,
    }
    project.meta = project_meta

    db.commit()

    session.status = "applied"
    _save_session_to_db(session, db)

    return {
        "success": True,
        "session_id": session_id,
        "excluded_count": excluded_count,
        "total_emails": len(emails),
        "remaining_emails": len(emails) - excluded_count,
    }


@router.get("/session/{session_id}")
async def get_session_status(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get the current status of a refinement session"""
    session = _get_session(session_id, db)
    if not session:
        raise HTTPException(404, "Session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    return {
        "session_id": session.id,
        "status": session.status,
        "current_stage": session.current_stage.value,
        "questions_total": len(session.questions_asked),
        "questions_answered": len(session.answers_received),
        "analysis_summary": session.analysis_results.get("summary", {}),
        "exclusion_rules": session.exclusion_rules,
    }


@router.delete("/session/{session_id}")
async def cancel_session(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Cancel a refinement session"""
    session = _get_session(session_id, db)
    if not session:
        raise HTTPException(404, "Session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    session.status = "cancelled"
    _save_session_to_db(session, db)

    # Remove from cache
    if session_id in _refinement_sessions:
        del _refinement_sessions[session_id]

    return {"success": True, "message": "Session cancelled"}
