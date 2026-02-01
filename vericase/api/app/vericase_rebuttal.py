"""
VeriCase Rebuttal - Flagship Multi-Agent Opposing Document Rebuttal Platform
=============================================================================
Comprehensive multi-agent orchestrated system for analysing opposing party
documents and producing forensic, point-by-point rebuttals backed by evidence.

Architecture (mirrors VeriCase Analysis):
- DocumentAnalyzerAgent: Forensic parsing of opposing documents
- StakeholderDetectorAgent: Auto-identifies who the document is from
- EvidenceHunterAgent: Cross-references ALL case evidence per assertion
- RebuttalStrategistAgent: Categorises and prioritises rebuttal points
- RebuttalWriterAgent: Generates comprehensive rebuttal with citations
- RebuttalValidatorAgent: Quality assurance and hallucination detection
- RebuttalOrchestrator: Master controller managing the full pipeline
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, NotRequired, TypedDict, cast
from enum import Enum
from dataclasses import dataclass

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    BackgroundTasks,
    File,
    Form,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, not_, func

try:  # Optional Redis
    from redis import Redis  # type: ignore
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore

from .models import (
    User,
    EmailMessage,
    Project,
    Case,
    EvidenceItem,
    ChronologyItem,
    Stakeholder,
    WorkspaceAbout,
    WorkspacePurpose,
    ContentiousMatter,
    HeadOfClaim,
    ItemClaimLink,
    EvidenceCorrespondenceLink,
    Programme,
)
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

# Import shared evidence context builder and SearcherAgent from VeriCase Analysis
from .vericase_analysis import (
    build_evidence_context,
    EvidenceContext,
    EvidenceCitation,
    SearcherAgent,
)

# AWS services for Comprehend entity extraction and Bedrock reranking
try:
    from .aws_services import get_aws_services
except ImportError:
    get_aws_services = None  # type: ignore[assignment,misc]

# Forensic integrity for DEP URI citations
try:
    from .forensic_integrity import make_dep_uri, compute_span_hash
except ImportError:
    make_dep_uri = None  # type: ignore[assignment,misc]
    compute_span_hash = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# VeriCase Rebuttal API
router = APIRouter(prefix="/api/vericase-rebuttal", tags=["vericase-rebuttal"])


# =============================================================================
# Data Models
# =============================================================================


class RebuttalStatus(str, Enum):
    """Status of a VeriCase rebuttal session."""

    PENDING = "pending"
    UPLOADING = "uploading"
    PARSING_DOCUMENT = "parsing_document"
    DETECTING_STAKEHOLDERS = "detecting_stakeholders"
    EXTRACTING_ASSERTIONS = "extracting_assertions"
    AWAITING_APPROVAL = "awaiting_approval"
    HUNTING_EVIDENCE = "hunting_evidence"
    STRATEGIZING = "strategizing"
    DRAFTING_REBUTTAL = "drafting_rebuttal"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OpposingDocumentType(str, Enum):
    """Type of opposing party document."""

    CLAIM = "claim"
    DEFENCE = "defence"
    EXPERT_REPORT = "expert_report"
    WITNESS_STATEMENT = "witness_statement"
    LETTER = "letter"
    SUBMISSION = "submission"
    OTHER = "other"


class RebuttalTone(str, Enum):
    """Tone/style for the generated rebuttal."""

    FORMAL = "formal"
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"


class OpposingAssertion(BaseModel):
    """A single assertion extracted from the opposing document."""

    id: str
    assertion_text: str
    assertion_type: str = "factual_claim"  # factual_claim, legal_argument, opinion, date_reference, amount_reference, causation_claim
    section: str | None = None  # Where in the document this appears
    page_reference: str | None = None
    parties_mentioned: list[str] = Field(default_factory=list)
    dates_mentioned: list[str] = Field(default_factory=list)
    amounts_mentioned: list[str] = Field(default_factory=list)
    priority: str = "medium"  # high, medium, low
    include_in_rebuttal: bool = True  # User can exclude during approval

    # Populated by strategist
    rebuttal_category: str | None = None  # factual_error, misrepresentation, omission, unsupported, partial_truth, valid_point
    rebuttal_strength: str | None = None  # strong, moderate, weak, no_rebuttal

    # Populated by evidence hunter
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    contradicting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    contextual_evidence: list[dict[str, Any]] = Field(default_factory=list)


class RebuttalPlan(BaseModel):
    """The structured rebuttal strategy."""

    document_summary: str = ""
    document_type: str = ""
    detected_stakeholder: dict[str, Any] | None = None
    stakeholder_confidence: float = 0.0
    assertions: list[OpposingAssertion] = Field(default_factory=list)
    assertion_count: int = 0
    key_themes: list[str] = Field(default_factory=list)
    rebuttal_strategy: str = ""  # Overall approach description
    prioritized_points: list[str] = Field(default_factory=list)  # Assertion IDs in priority order
    evidence_gaps: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RebuttalSession(BaseModel):
    """Complete rebuttal session state."""

    id: str
    user_id: str
    project_id: str | None = None
    case_id: str | None = None
    status: RebuttalStatus = RebuttalStatus.PENDING

    # Document
    document_filename: str | None = None
    document_s3_key: str | None = None
    document_text: str | None = None
    document_type: OpposingDocumentType | None = None
    document_size_bytes: int = 0

    # User-provided context
    document_from: str | None = None  # Who it's from (user-overridable)
    focus_areas: str | None = None
    rebuttal_tone: RebuttalTone = RebuttalTone.FORMAL

    # Plan (populated after parsing + stakeholder detection + assertion extraction)
    plan: RebuttalPlan | None = None

    # Evidence hunting results per assertion
    assertion_evidence: dict[str, dict[str, Any]] = Field(default_factory=dict)
    assertions_hunted: int = 0
    total_assertions: int = 0

    # Final outputs
    final_rebuttal: str | None = None
    executive_summary: str | None = None
    key_contradictions: list[str] = Field(default_factory=list)
    point_by_point: list[dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    # Validation
    validation_result: dict[str, Any] = Field(default_factory=dict)
    validation_passed: bool = True

    # Evidence tracking
    evidence_used: list[dict[str, Any]] = Field(default_factory=list)
    cited_evidence: list[EvidenceCitation] = Field(default_factory=list)
    next_citation_number: int = 1

    # Metadata
    total_assertions_analyzed: int = 0
    total_sources_searched: int = 0
    processing_time_seconds: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None
    models_used: dict[str, str] = Field(default_factory=dict)

    # Current processing step (for frontend progress)
    processing_step: str = ""  # "parsing_document" | "detecting_stakeholder" | "extracting_assertions" | etc.


# =============================================================================
# Session Store (Redis + in-memory, mirrors VeriCase Analysis)
# =============================================================================

_rebuttal_sessions: dict[str, RebuttalSession] = {}


def _get_redis() -> Redis | None:
    try:
        if settings.REDIS_URL and Redis:
            return Redis.from_url(settings.REDIS_URL)  # type: ignore[call-arg]
    except Exception as e:  # pragma: no cover
        logger.warning(f"Redis unavailable for VeriCase Rebuttal sessions: {e}")
    return None


def save_session(session: RebuttalSession) -> None:
    """Persist session to in-memory store and Redis (if available)."""
    _rebuttal_sessions[session.id] = session
    try:
        redis_client = _get_redis()
        if redis_client:
            redis_client.set(
                f"vericase:rebuttal:{session.id}", session.model_dump_json()
            )
    except Exception as e:  # pragma: no cover
        logger.warning(f"Failed to persist rebuttal session to Redis: {e}")


def load_session(session_id: str) -> RebuttalSession | None:
    """Load session from in-memory store or Redis."""
    cached = _rebuttal_sessions.get(session_id)
    redis_session: RebuttalSession | None = None

    try:
        redis_client = _get_redis()
        if redis_client:
            data = redis_client.get(f"vericase:rebuttal:{session_id}")
            if data:
                redis_session = RebuttalSession.model_validate_json(data)
    except Exception as e:  # pragma: no cover
        logger.warning(f"Failed to load rebuttal session from Redis: {e}")

    if redis_session:
        if not cached or redis_session.updated_at >= cached.updated_at:
            _rebuttal_sessions[session_id] = redis_session
            return redis_session

    if cached:
        return cached

    return None


# =============================================================================
# Request/Response Models
# =============================================================================


class StartRebuttalResponse(BaseModel):
    session_id: str
    status: str
    message: str


class ApprovePlanRequest(BaseModel):
    session_id: str
    approved: bool
    modifications: str | None = None
    excluded_assertion_ids: list[str] = Field(default_factory=list)
    stakeholder_override: str | None = None  # Override detected stakeholder name


class RebuttalStatusResponse(BaseModel):
    """Status response for a VeriCase rebuttal session."""

    session_id: str
    status: str
    document_filename: str | None = None
    document_type: str | None = None
    plan: RebuttalPlan | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    final_rebuttal: str | None = None
    executive_summary: str | None = None
    key_contradictions: list[str] = Field(default_factory=list)
    processing_time_seconds: float = 0
    report_available: bool = False
    error_message: str | None = None
    models_used: list[str] = Field(default_factory=list)
    processing_step: str = ""


class RebuttalReportResponse(BaseModel):
    """Full rebuttal report response."""

    session_id: str
    case_id: str | None = None
    project_id: str | None = None
    document_filename: str | None = None
    document_type: str | None = None
    detected_stakeholder: dict[str, Any] | None = None
    executive_summary: str | None = None
    final_rebuttal: str | None = None
    key_contradictions: list[str] = Field(default_factory=list)
    point_by_point: list[dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    evidence_used: list[dict[str, Any]] = Field(default_factory=list)
    cited_evidence: list[EvidenceCitation] = Field(default_factory=list)
    validation_score: float = 0.0
    validation_passed: bool = True
    models_used: list[str] = Field(default_factory=list)
    total_duration_seconds: float = 0


# =============================================================================
# AI Agent Base Class (local copy with TOOL_NAME = "vericase_rebuttal")
# =============================================================================


class BaseAgent:
    """
    Base class for all rebuttal agents.
    Supports 6 providers: OpenAI, Anthropic, Gemini, Bedrock, xAI, Perplexity.
    """

    TOOL_NAME = "vericase_rebuttal"

    def __init__(self, db: Session, agent_name: str | None = None):
        self.db = db
        self.agent_name = agent_name

        # Load tool configuration
        self.tool_config = get_tool_config(self.TOOL_NAME, db)
        self.fallback_chain = get_tool_fallback_chain(self.TOOL_NAME, db)

        # Load agent-specific config if applicable
        if agent_name:
            self.agent_config = get_tool_agent_config(
                self.TOOL_NAME, agent_name, db
            )
        else:
            self.agent_config = {}

        # API keys for all providers
        self.openai_key = get_ai_api_key("openai", db)
        self.anthropic_key = get_ai_api_key("anthropic", db)
        self.gemini_key = get_ai_api_key("gemini", db)

        # Bedrock uses IAM credentials
        self.bedrock_enabled = is_bedrock_enabled(db) and bedrock_available()
        self.bedrock_region = get_bedrock_region(db)
        self._bedrock_provider: BedrockProvider | None = None

        # Model selections
        self.openai_model = (
            self.agent_config.get("model")
            if self.agent_config.get("provider") == "openai"
            else get_ai_model("openai", db)
        )
        self.anthropic_model = (
            self.agent_config.get("model")
            if self.agent_config.get("provider") == "anthropic"
            else get_ai_model("anthropic", db)
        )
        self.gemini_model = (
            self.agent_config.get("model")
            if self.agent_config.get("provider") == "gemini"
            else get_ai_model("gemini", db)
        )
        self.bedrock_model = (
            self.agent_config.get("model")
            if self.agent_config.get("provider") == "bedrock"
            else get_ai_model("bedrock", db)
        )

        # Tool-specific settings
        self.max_tokens = self.tool_config.get("max_tokens", 8000)
        self.temperature = self.tool_config.get("temperature", 0.2)
        self.max_duration = self.tool_config.get("max_duration_seconds", 900)

    @property
    def bedrock_provider(self) -> BedrockProvider | None:
        if self._bedrock_provider is None and self.bedrock_enabled:
            try:
                self._bedrock_provider = BedrockProvider(
                    region=self.bedrock_region
                )
            except Exception as e:
                logger.warning(f"Failed to initialize Bedrock provider: {e}")
        return self._bedrock_provider

    async def _call_llm(
        self, prompt: str, system_prompt: str = "", use_powerful: bool = False
    ) -> str:
        """Call the appropriate LLM - Bedrock first for cost optimization."""
        errors: list[str] = []

        if self.bedrock_enabled:
            try:
                return await self._call_bedrock(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Bedrock call failed, trying fallback: {e}")
                errors.append(f"Bedrock: {e}")

        if use_powerful and self.anthropic_key:
            try:
                return await self._call_anthropic(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Anthropic (powerful) call failed: {e}")
                errors.append(f"Anthropic: {e}")

        if self.openai_key:
            try:
                return await self._call_openai(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"OpenAI call failed: {e}")
                errors.append(f"OpenAI: {e}")

        if self.gemini_key:
            try:
                return await self._call_gemini(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Gemini call failed: {e}")
                errors.append(f"Gemini: {e}")

        if self.anthropic_key and "Anthropic" not in str(errors):
            try:
                return await self._call_anthropic(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Anthropic (fallback) call failed: {e}")
                errors.append(f"Anthropic: {e}")

        if errors:
            error_summary = "; ".join(errors)
            raise HTTPException(500, f"All AI providers failed: {error_summary}")

        raise HTTPException(
            500,
            "No AI providers configured. Please add API keys in Admin Settings.",
        )

    async def _call_openai(self, prompt: str, system_prompt: str = "") -> str:
        return await complete_chat(
            provider="openai",
            model_id=self.openai_model,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.openai_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_anthropic(self, prompt: str, system_prompt: str = "") -> str:
        return await complete_chat(
            provider="anthropic",
            model_id=self.anthropic_model,
            prompt=prompt,
            system_prompt=(
                system_prompt
                if system_prompt
                else "You are an expert legal and construction dispute analyst."
            ),
            api_key=self.anthropic_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_gemini(self, prompt: str, system_prompt: str = "") -> str:
        return await complete_chat(
            provider="gemini",
            model_id=self.gemini_model,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.gemini_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_bedrock(self, prompt: str, system_prompt: str = "") -> str:
        if not self.bedrock_provider:
            raise RuntimeError("Bedrock provider not available")
        return await complete_chat(
            provider="bedrock",
            model_id=self.bedrock_model,
            prompt=prompt,
            system_prompt=system_prompt,
            bedrock_provider=self.bedrock_provider,
            bedrock_region=self.bedrock_region,
            max_tokens=4000,
            temperature=0.3,
        )


# =============================================================================
# Agent 1: Document Analyzer
# =============================================================================


class DocumentAnalyzerAgent(BaseAgent):
    """
    Forensically parses and analyses an opposing party document.
    Extracts every assertion, claim, date, amount, and party mentioned.
    """

    SYSTEM_PROMPT = """You are an expert forensic legal document analyst specialising in construction disputes.
Your role is to meticulously parse opposing party documents and extract every assertion, claim, and factual statement.

When analysing a document:
1. Identify EVERY distinct assertion, claim, or factual statement made
2. Classify each assertion by type (factual_claim, legal_argument, opinion, date_reference, amount_reference, causation_claim)
3. Extract parties, dates, and amounts mentioned in each assertion
4. Identify which section/paragraph each assertion comes from
5. Assess the priority/importance of each assertion (high, medium, low)
6. Be exhaustive - miss nothing that could be relevant to a rebuttal

You must be thorough and forensic in your analysis. Every claim that could be challenged must be identified."""

    async def analyze_document(
        self,
        document_text: str,
        document_type: str | None = None,
        focus_areas: str | None = None,
    ) -> tuple[str, list[OpposingAssertion]]:
        """
        Parse opposing document and extract all assertions.

        Pipeline:
        1. AWS Comprehend entity extraction (people, orgs, dates, amounts, sentiment)
        2. LLM analysis with Comprehend enrichment for precise assertion extraction

        Returns:
            tuple of (document_summary, list of OpposingAssertion)
        """
        doc_type_str = f"\nDocument Type: {document_type}" if document_type else ""
        focus_str = f"\nAreas to focus on: {focus_areas}" if focus_areas else ""

        # ------------------------------------------------------------------
        # Stage 1: AWS Comprehend entity enrichment (Upgrade 2)
        # ------------------------------------------------------------------
        comprehend_context = ""
        try:
            if get_aws_services is not None:
                aws = get_aws_services()
                # Comprehend has a 5KB limit per call
                analysis = await aws.analyze_document_entities(document_text[:5000])
                if analysis:
                    entities = analysis.get("entities", [])
                    key_phrases = analysis.get("key_phrases", [])
                    sentiment = analysis.get("sentiment", {})

                    entity_lines: list[str] = []
                    for ent in entities[:30]:
                        ent_type = ent.get("Type", "UNKNOWN")
                        ent_text = ent.get("Text", "")
                        ent_score = ent.get("Score", 0)
                        if ent_score > 0.7:
                            entity_lines.append(f"  {ent_type}: {ent_text} ({ent_score:.0%})")

                    phrase_lines = [
                        f"  {p.get('Text', '')}" for p in key_phrases[:15]
                        if p.get("Score", 0) > 0.7
                    ]

                    sentiment_label = sentiment.get("Sentiment", "UNKNOWN")
                    sentiment_scores = sentiment.get("SentimentScore", {})

                    comprehend_parts = ["[DOCUMENT INTELLIGENCE - AWS Comprehend NER]"]
                    if entity_lines:
                        comprehend_parts.append("Detected Entities:")
                        comprehend_parts.extend(entity_lines)
                    if phrase_lines:
                        comprehend_parts.append("Key Phrases:")
                        comprehend_parts.extend(phrase_lines)
                    comprehend_parts.append(
                        f"Sentiment: {sentiment_label} "
                        f"(Positive: {sentiment_scores.get('Positive', 0):.0%}, "
                        f"Negative: {sentiment_scores.get('Negative', 0):.0%})"
                    )
                    comprehend_context = "\n".join(comprehend_parts)
                    logger.info(
                        f"Comprehend extracted {len(entities)} entities, "
                        f"{len(key_phrases)} phrases, sentiment: {sentiment_label}"
                    )
        except Exception as e:
            logger.warning(f"AWS Comprehend enrichment failed (proceeding with LLM-only): {e}")

        comprehend_section = f"\n\n{comprehend_context}" if comprehend_context else ""

        # Truncate very large documents but keep as much as possible
        max_doc_chars = 80000
        truncated = document_text[:max_doc_chars]
        truncation_note = (
            f"\n\n[Document truncated at {max_doc_chars} characters. Original length: {len(document_text)} characters.]"
            if len(document_text) > max_doc_chars
            else ""
        )

        prompt = f"""Analyse the following opposing party document and extract every distinct assertion, claim, and factual statement.
{doc_type_str}{focus_str}{comprehend_section}

DOCUMENT:
{truncated}{truncation_note}

Provide your analysis as JSON with this exact structure:
{{
    "document_summary": "A concise 2-3 sentence summary of the document's main arguments and purpose",
    "assertions": [
        {{
            "id": "a1",
            "assertion_text": "The exact or closely paraphrased assertion from the document",
            "assertion_type": "factual_claim|legal_argument|opinion|date_reference|amount_reference|causation_claim",
            "section": "The section or paragraph where this appears (e.g. 'Paragraph 12', 'Section 3.2')",
            "page_reference": "Page number if identifiable",
            "parties_mentioned": ["Party A", "Party B"],
            "dates_mentioned": ["2024-01-15", "March 2024"],
            "amounts_mentioned": ["$500,000", "120 days"],
            "priority": "high|medium|low"
        }}
    ]
}}

Be exhaustive. Extract ALL assertions - typically 10-40 for a substantial document. Priority should reflect:
- high: Key claims central to the opposing argument that MUST be rebutted
- medium: Supporting claims that strengthen the opposing case
- low: Minor points, context, or undisputed facts"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT, use_powerful=True)

        # Parse JSON response
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())
            summary = data.get("document_summary", "")

            assertions = []
            for a in data.get("assertions", []):
                assertions.append(
                    OpposingAssertion(
                        id=a.get("id", f"a{len(assertions) + 1}"),
                        assertion_text=a.get("assertion_text", ""),
                        assertion_type=a.get("assertion_type", "factual_claim"),
                        section=a.get("section"),
                        page_reference=a.get("page_reference"),
                        parties_mentioned=a.get("parties_mentioned", []),
                        dates_mentioned=a.get("dates_mentioned", []),
                        amounts_mentioned=a.get("amounts_mentioned", []),
                        priority=a.get("priority", "medium"),
                    )
                )

            return summary, assertions

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse document analysis response: {e}")
            # Fallback: create a single assertion from the summary
            return (
                "Document analysis parsing failed - manual review recommended",
                [
                    OpposingAssertion(
                        id="a1",
                        assertion_text="Full document requires manual review - automated parsing encountered an error",
                        assertion_type="factual_claim",
                        priority="high",
                    )
                ],
            )


# =============================================================================
# Agent 2: Stakeholder Detector
# =============================================================================


class StakeholderDetectorAgent(BaseAgent):
    """
    Auto-identifies who the opposing document is from by matching against
    known stakeholders in the case/project. Uses the same 3-tier matching
    logic as pst_processor.py: exact email -> domain -> name -> text.
    """

    SYSTEM_PROMPT = """You are an expert at identifying parties and stakeholders in legal documents.
Your role is to extract the name and organisation of the party who authored or is represented by a document."""

    async def detect_stakeholder(
        self,
        document_text: str,
        case_id: str | None,
        project_id: str | None,
    ) -> dict[str, Any]:
        """
        Detect who the opposing document is from.

        Returns:
            dict with: stakeholder_id, name, role, organisation, email, confidence
        """
        # Step 1: Get known stakeholders from DB
        stakeholders = self._get_stakeholders(case_id, project_id)

        if not stakeholders:
            # No stakeholders in DB - use LLM to extract author info
            return await self._detect_via_llm(document_text)

        # Step 2: Try matching document content against known stakeholders
        doc_lower = document_text[:20000].lower()  # Search first 20K chars
        best_match: dict[str, Any] | None = None
        best_confidence = 0.0

        for sh in stakeholders:
            confidence = 0.0

            # Tier 1: Exact name match (highest confidence)
            if sh.name and sh.name.lower() in doc_lower:
                confidence = max(confidence, 0.85)

            # Tier 2: Organisation match
            if sh.organization and sh.organization.lower() in doc_lower:
                confidence = max(confidence, 0.80)

            # Tier 3: Email match
            if sh.email and sh.email.lower() in doc_lower:
                confidence = max(confidence, 0.90)

            # Tier 4: Domain match
            if sh.email_domain and sh.email_domain.lower() in doc_lower:
                confidence = max(confidence, 0.70)

            if confidence > best_confidence:
                best_confidence = confidence
                best_match = {
                    "stakeholder_id": str(sh.id),
                    "name": sh.name,
                    "role": sh.role,
                    "organisation": sh.organization,
                    "email": sh.email,
                    "confidence": confidence,
                }

        # Step 3: If no strong DB match, supplement with LLM detection
        if best_confidence < 0.6:
            llm_result = await self._detect_via_llm(document_text)
            # Try to match LLM-extracted name against stakeholders
            llm_name = (llm_result.get("name") or "").lower()
            llm_org = (llm_result.get("organisation") or "").lower()
            for sh in stakeholders:
                if sh.name and llm_name and sh.name.lower() in llm_name:
                    return {
                        "stakeholder_id": str(sh.id),
                        "name": sh.name,
                        "role": sh.role,
                        "organisation": sh.organization or llm_result.get("organisation"),
                        "email": sh.email,
                        "confidence": 0.75,
                    }
                if sh.organization and llm_org and sh.organization.lower() in llm_org:
                    return {
                        "stakeholder_id": str(sh.id),
                        "name": sh.name,
                        "role": sh.role,
                        "organisation": sh.organization,
                        "email": sh.email,
                        "confidence": 0.70,
                    }

            # No match found - return LLM result
            return llm_result

        return best_match or {"name": "Unknown", "confidence": 0.0}

    def _get_stakeholders(
        self, case_id: str | None, project_id: str | None
    ) -> list[Stakeholder]:
        """Get stakeholders from the database for this case/project."""
        try:
            query = self.db.query(Stakeholder)
            filters = []
            if case_id:
                filters.append(Stakeholder.case_id == case_id)
            if project_id:
                filters.append(Stakeholder.project_id == project_id)
            if filters:
                query = query.filter(or_(*filters))
            return query.all()
        except Exception as e:
            logger.warning(f"Failed to query stakeholders: {e}")
            return []

    async def _detect_via_llm(self, document_text: str) -> dict[str, Any]:
        """Use LLM to extract the authoring party from the document."""
        prompt = f"""Identify who authored or is represented by this document. Extract their name, role, and organisation.

DOCUMENT (first 5000 characters):
{document_text[:5000]}

Output as JSON:
{{
    "name": "The person or party name",
    "role": "Their role (e.g., Claimant, Defendant, Expert Witness, Solicitor)",
    "organisation": "Their organisation/firm if mentioned",
    "confidence": 0.0-1.0
}}"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            result = json.loads(json_str.strip())
            result.setdefault("confidence", 0.5)
            return result
        except (json.JSONDecodeError, KeyError):
            return {"name": "Unknown", "confidence": 0.0}


# =============================================================================
# Agent 3: Evidence Hunter
# =============================================================================


class EvidenceHunterAgent(BaseAgent):
    """
    Intelligent evidence hunter using 4-vector semantic search, cross-encoder
    reranking, MMR diversity, claims cross-referencing, chronology queries,
    programme data, and Bedrock Cohere Rerank.

    For each assertion, searches for contradicting, supporting, and contextual
    evidence across emails, documents, chronology items, claims, and schedules.
    """

    SYSTEM_PROMPT = """You are an expert legal evidence researcher specialising in construction disputes.
You are provided with RANKED evidence items that have been retrieved via semantic search and relevance scoring.
Your role is to classify each evidence item as:
1. CONTRADICTING - evidence that disproves, weakens, or challenges the opposing assertion
2. SUPPORTING - evidence that corroborates the opposing assertion (we need to know their strongest points)
3. CONTEXTUAL - evidence that provides important timeline, background, or related facts

Be thorough and precise. Every piece of relevant evidence matters for building a strong rebuttal.
Evidence items marked [HUMAN-VERIFIED] have been pre-classified by case analysts and should be given high weight."""

    def __init__(self, db: Session, agent_key: str = "evidence_hunter"):
        super().__init__(db, agent_key)
        self.searcher = SearcherAgent(db)

    async def hunt_evidence_for_assertions(
        self,
        assertions: list[OpposingAssertion],
        evidence_context: EvidenceContext,
        session: RebuttalSession,
    ) -> dict[str, dict[str, Any]]:
        """
        Search for evidence relevant to each assertion using intelligent retrieval.

        Pipeline per assertion:
        1. SearcherAgent: 4-vector semantic search → cross-encoder → MMR
        2. Claims cross-reference: pre-tagged evidence from ItemClaimLink
        3. Chronology query: direct timeline matching
        4. Correspondence query: party-filtered email search
        5. Programme data: schedule context for delay-related assertions
        6. Bedrock Cohere Rerank: cloud-level relevance scoring
        7. LLM classification: categorise results as contradicting/supporting/contextual
        """
        results: dict[str, dict[str, Any]] = {}
        active_assertions = [a for a in assertions if a.include_in_rebuttal]
        case_id = session.case_id
        project_id = session.project_id

        # Process in batches of 3 for parallel efficiency
        batch_size = 3
        for i in range(0, len(active_assertions), batch_size):
            batch = active_assertions[i : i + batch_size]
            batch_tasks = [
                self._hunt_single_assertion(
                    a, evidence_context, case_id, project_id
                )
                for a in batch
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for assertion, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.warning(
                        f"Evidence hunting failed for assertion {assertion.id}: {result}"
                    )
                    results[assertion.id] = {
                        "contradicting": [],
                        "supporting": [],
                        "contextual": [],
                        "error": str(result),
                    }
                else:
                    results[assertion.id] = result

                # Update progress
                session.assertions_hunted = len(results)
                session.updated_at = datetime.now(timezone.utc)
                save_session(session)

        return results

    async def _hunt_single_assertion(
        self,
        assertion: OpposingAssertion,
        evidence_context: EvidenceContext,
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Full intelligence pipeline for a single assertion.

        Uses SearcherAgent's proven 3-stage retrieval, enriched with claims,
        chronology, correspondence, and programme data.
        """

        # Build a focused search query from the assertion
        search_query = self._build_search_query(assertion)

        # ------------------------------------------------------------------
        # Stage 1: SearcherAgent - 4-vector semantic search + cross-encoder + MMR
        # ------------------------------------------------------------------
        semantic_results: list[dict[str, Any]] = []
        try:
            semantic_results = await self.searcher.search_and_retrieve(
                query=search_query,
                evidence_items=evidence_context.items,
                top_k=20,
                apply_diversity=True,
                case_id=case_id,
                project_id=project_id,
                use_multi_vector=True,
            )
            logger.info(
                f"SearcherAgent retrieved {len(semantic_results)} results for assertion {assertion.id}"
            )
        except Exception as e:
            logger.warning(f"SearcherAgent failed for assertion {assertion.id}: {e}")

        # ------------------------------------------------------------------
        # Stage 2: Claims cross-reference - pre-tagged evidence from ItemClaimLink
        # ------------------------------------------------------------------
        claims_evidence = self._query_claims_evidence(assertion, case_id, project_id)

        # ------------------------------------------------------------------
        # Stage 3: Chronology query - direct timeline matching
        # ------------------------------------------------------------------
        chronology_items = self._query_chronology(assertion, case_id, project_id)

        # ------------------------------------------------------------------
        # Stage 4: Correspondence query - party-filtered email search
        # ------------------------------------------------------------------
        correspondence_items = self._query_related_emails(assertion, case_id, project_id)

        # ------------------------------------------------------------------
        # Stage 5: Programme data - schedule context for delay assertions
        # ------------------------------------------------------------------
        programme_context = self._query_programme_context(assertion, case_id, project_id)

        # ------------------------------------------------------------------
        # Stage 6: Bedrock Cohere Rerank (cloud-level relevance scoring)
        # ------------------------------------------------------------------
        all_candidates = self._merge_evidence_sources(
            semantic_results, claims_evidence, chronology_items, correspondence_items
        )
        reranked = await self._cloud_rerank(assertion, all_candidates)

        # ------------------------------------------------------------------
        # Stage 7: LLM classification
        # ------------------------------------------------------------------
        search_context = self._format_ranked_evidence(reranked, programme_context)

        # If no evidence found at all, fall back to plaintext dump
        if not search_context.strip():
            search_context = self._build_search_context_fallback(evidence_context)

        return await self._classify_evidence(assertion, search_context)

    def _build_search_query(self, assertion: OpposingAssertion) -> str:
        """Build a focused search query from assertion metadata."""
        parts = [assertion.assertion_text[:300]]
        if assertion.parties_mentioned:
            parts.append(f"parties: {', '.join(assertion.parties_mentioned[:5])}")
        if assertion.dates_mentioned:
            parts.append(f"dates: {', '.join(assertion.dates_mentioned[:5])}")
        if assertion.amounts_mentioned:
            parts.append(f"amounts: {', '.join(assertion.amounts_mentioned[:3])}")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # Claims cross-reference (Upgrade 3)
    # ------------------------------------------------------------------

    def _query_claims_evidence(
        self,
        assertion: OpposingAssertion,
        case_id: str | None,
        project_id: str | None,
    ) -> list[dict[str, Any]]:
        """Query ItemClaimLink for pre-tagged evidence relevant to this assertion."""
        results: list[dict[str, Any]] = []
        try:
            # Find claims/matters for this case/project
            claim_query = self.db.query(HeadOfClaim)
            filters: list[Any] = []
            if case_id:
                filters.append(HeadOfClaim.case_id == case_id)
            if project_id:
                filters.append(HeadOfClaim.project_id == project_id)
            if not filters:
                return []
            claims = claim_query.filter(or_(*filters)).all()
            if not claims:
                return []

            # Get all item links for these claims
            claim_ids = [c.id for c in claims]
            links = (
                self.db.query(ItemClaimLink)
                .filter(
                    ItemClaimLink.head_of_claim_id.in_(claim_ids),
                    ItemClaimLink.status == "active",
                )
                .all()
            )

            assertion_lower = assertion.assertion_text.lower()
            for link in links:
                # Check relevance: claim name/description overlaps with assertion
                claim = next((c for c in claims if c.id == link.head_of_claim_id), None)
                if not claim:
                    continue

                claim_text = f"{claim.name or ''} {claim.description or ''}".lower()
                # Quick keyword overlap check
                assertion_words = set(assertion_lower.split())
                claim_words = set(claim_text.split())
                overlap = assertion_words & claim_words - {
                    "the", "a", "an", "is", "was", "are", "were", "in", "on", "at",
                    "to", "for", "of", "and", "or", "that", "this", "it", "by", "with",
                }
                if len(overlap) < 2:
                    continue

                # Map ItemClaimLink.link_type to our categories
                link_type = str(getattr(link, "link_type", "neutral")).lower()
                category = {
                    "supporting": "supporting",
                    "contradicting": "contradicting",
                    "neutral": "contextual",
                    "key": "contradicting",  # key evidence is most useful for rebuttal
                }.get(link_type, "contextual")

                results.append({
                    "id": str(link.item_id),
                    "type": link.item_type.upper() if link.item_type else "EVIDENCE",
                    "content": f"[HUMAN-VERIFIED {link_type.upper()}] Linked to claim: {claim.name}. "
                               f"Notes: {(getattr(link, 'notes', '') or '')[:200]}",
                    "title": claim.name or "Linked claim evidence",
                    "relevance_score": (getattr(link, "relevance_score", 50) or 50) / 100.0,
                    "source": "claims_module",
                    "pre_classified": category,
                    "claim_name": claim.name,
                    "claim_type": claim.claim_type,
                })

            logger.info(f"Claims cross-ref found {len(results)} pre-tagged items for assertion {assertion.id}")
        except Exception as e:
            logger.warning(f"Claims cross-reference failed: {e}")
        return results

    # ------------------------------------------------------------------
    # Chronology query (Upgrade 4)
    # ------------------------------------------------------------------

    def _query_chronology(
        self,
        assertion: OpposingAssertion,
        case_id: str | None,
        project_id: str | None,
    ) -> list[dict[str, Any]]:
        """Query ChronologyItem table filtered by assertion dates."""
        results: list[dict[str, Any]] = []
        if not assertion.dates_mentioned:
            return []

        try:
            parsed_dates: list[datetime] = []
            for date_str in assertion.dates_mentioned[:5]:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%B %Y", "%d %B %Y", "%Y"):
                    try:
                        parsed_dates.append(datetime.strptime(date_str.strip(), fmt))
                        break
                    except ValueError:
                        continue

            if not parsed_dates:
                return []

            query = self.db.query(ChronologyItem)
            filters: list[Any] = []
            if case_id:
                filters.append(ChronologyItem.case_id == case_id)
            if project_id:
                filters.append(ChronologyItem.project_id == project_id)
            if not filters:
                return []
            query = query.filter(or_(*filters))

            # Search within ±30 days of any mentioned date
            date_filters = []
            for d in parsed_dates:
                date_filters.append(
                    and_(
                        ChronologyItem.event_date >= d - timedelta(days=30),
                        ChronologyItem.event_date <= d + timedelta(days=30),
                    )
                )
            if date_filters:
                query = query.filter(or_(*date_filters))

            items = query.limit(20).all()

            for item in items:
                results.append({
                    "id": str(item.id),
                    "type": "CHRONOLOGY",
                    "content": f"[{getattr(item, 'event_date', '')}] "
                               f"{getattr(item, 'title', '') or getattr(item, 'description', '')}"[:600],
                    "title": getattr(item, "title", None) or getattr(item, "description", "Chronology event")[:100],
                    "date": str(getattr(item, "event_date", "")),
                    "source": "chronology",
                })

            logger.info(f"Chronology query found {len(results)} items for assertion {assertion.id}")
        except Exception as e:
            logger.warning(f"Chronology query failed: {e}")
        return results

    # ------------------------------------------------------------------
    # Correspondence query (Upgrade 4)
    # ------------------------------------------------------------------

    def _query_related_emails(
        self,
        assertion: OpposingAssertion,
        case_id: str | None,
        project_id: str | None,
    ) -> list[dict[str, Any]]:
        """Query emails involving parties mentioned in the assertion."""
        results: list[dict[str, Any]] = []
        if not assertion.parties_mentioned:
            return []

        try:
            query = self.db.query(EmailMessage)
            scope_filters: list[Any] = []
            if case_id:
                scope_filters.append(EmailMessage.case_id == case_id)
            if project_id:
                scope_filters.append(EmailMessage.project_id == project_id)
            if not scope_filters:
                return []
            query = query.filter(or_(*scope_filters))

            # Filter by parties in sender or recipients
            party_filters = []
            for party in assertion.parties_mentioned[:5]:
                party_lower = party.lower().strip()
                if not party_lower:
                    continue
                party_filters.append(func.lower(EmailMessage.sender).contains(party_lower))
                party_filters.append(func.lower(EmailMessage.recipients).contains(party_lower))

            if party_filters:
                query = query.filter(or_(*party_filters))

            emails = query.order_by(EmailMessage.date.desc()).limit(15).all()

            for email in emails:
                subject = getattr(email, "subject", "") or ""
                body = getattr(email, "body_text_clean", None) or getattr(email, "body_text", "") or ""
                results.append({
                    "id": str(email.id),
                    "type": "EMAIL",
                    "content": f"Subject: {subject}\nFrom: {getattr(email, 'sender', '')}\n"
                               f"Date: {getattr(email, 'date', '')}\n{body[:400]}",
                    "title": subject or "Email",
                    "sender": getattr(email, "sender", ""),
                    "date": str(getattr(email, "date", "")),
                    "source": "correspondence",
                })

            # Also pull evidence items linked to these emails via EvidenceCorrespondenceLink
            if emails:
                email_ids = [e.id for e in emails[:10]]
                links = (
                    self.db.query(EvidenceCorrespondenceLink)
                    .filter(EvidenceCorrespondenceLink.email_message_id.in_(email_ids))
                    .limit(20)
                    .all()
                )
                for link in links:
                    evidence_id = getattr(link, "evidence_item_id", None)
                    if evidence_id:
                        results.append({
                            "id": str(evidence_id),
                            "type": "LINKED_EVIDENCE",
                            "content": f"Evidence linked to email (confidence: {getattr(link, 'link_confidence', '?')}%)",
                            "title": f"Evidence linked via correspondence",
                            "source": "correspondence_link",
                            "link_confidence": getattr(link, "link_confidence", 0),
                        })

            logger.info(f"Correspondence query found {len(results)} items for assertion {assertion.id}")
        except Exception as e:
            logger.warning(f"Correspondence query failed: {e}")
        return results

    # ------------------------------------------------------------------
    # Programme/schedule data (Upgrade 6)
    # ------------------------------------------------------------------

    def _query_programme_context(
        self,
        assertion: OpposingAssertion,
        case_id: str | None,
        project_id: str | None,
    ) -> str:
        """Query Programme table for schedule data relevant to delay assertions."""
        # Only for delay-related assertions
        delay_keywords = {"delay", "extension", "critical path", "programme", "schedule",
                          "eot", "liquidated damages", "time at large", "float", "concurrent"}
        text_lower = assertion.assertion_text.lower()
        is_delay = (
            assertion.assertion_type == "causation_claim"
            or any(kw in text_lower for kw in delay_keywords)
        )
        if not is_delay:
            return ""

        try:
            query = self.db.query(Programme)
            filters: list[Any] = []
            if case_id:
                filters.append(Programme.case_id == case_id)
            if project_id:
                filters.append(Programme.project_id == project_id)
            if not filters:
                return ""
            programmes = query.filter(or_(*filters)).limit(3).all()
            if not programmes:
                return ""

            parts = ["[PROGRAMME/SCHEDULE DATA]"]
            for prog in programmes:
                parts.append(
                    f"Programme: {prog.programme_name} ({getattr(prog, 'programme_type', 'unknown')})"
                )
                start = getattr(prog, "project_start", None)
                finish = getattr(prog, "project_finish", None)
                if start:
                    parts.append(f"  Project Start: {start}")
                if finish:
                    parts.append(f"  Project Finish: {finish}")

                critical_path = getattr(prog, "critical_path", None)
                if critical_path and isinstance(critical_path, list):
                    parts.append(f"  Critical Path Activities: {', '.join(str(a) for a in critical_path[:10])}")

                milestones = getattr(prog, "milestones", None)
                if milestones and isinstance(milestones, list):
                    for ms in milestones[:5]:
                        if isinstance(ms, dict):
                            parts.append(
                                f"  Milestone: {ms.get('name', '?')} - "
                                f"Planned: {ms.get('planned_date', '?')}, "
                                f"Actual: {ms.get('actual_date', 'N/A')}"
                            )

                activities = getattr(prog, "activities", None)
                if activities and isinstance(activities, list):
                    parts.append(f"  Total Activities: {len(activities)}")
                    # Show first few relevant activities
                    for act in activities[:8]:
                        if isinstance(act, dict):
                            parts.append(
                                f"  Activity: {act.get('name', '?')} | "
                                f"Start: {act.get('start', '?')} | "
                                f"Finish: {act.get('finish', '?')} | "
                                f"Duration: {act.get('duration', '?')}"
                            )

            # Also check evidence items with delay data
            ev_query = self.db.query(EvidenceItem).filter(
                EvidenceItem.delay_days.isnot(None)
            )
            scope_filters: list[Any] = []
            if case_id:
                scope_filters.append(EvidenceItem.case_id == case_id)
            if project_id:
                scope_filters.append(EvidenceItem.project_id == project_id)
            if scope_filters:
                ev_query = ev_query.filter(or_(*scope_filters))
            delay_items = ev_query.limit(10).all()

            if delay_items:
                parts.append("\n[EVIDENCE WITH DELAY DATA]")
                for item in delay_items:
                    parts.append(
                        f"  {getattr(item, 'name', 'Evidence')} | "
                        f"Planned: {getattr(item, 'as_planned_date', '?')} | "
                        f"Actual: {getattr(item, 'as_built_date', '?')} | "
                        f"Delay: {item.delay_days} days | "
                        f"Critical Path: {getattr(item, 'is_critical_path', False)}"
                    )

            result = "\n".join(parts)
            if len(result) > 100:
                logger.info(f"Programme context built for delay assertion {assertion.id}")
            return result

        except Exception as e:
            logger.warning(f"Programme query failed: {e}")
            return ""

    # ------------------------------------------------------------------
    # Merge and rerank (Upgrades 1 + 7)
    # ------------------------------------------------------------------

    def _merge_evidence_sources(
        self,
        semantic: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        chronology: list[dict[str, Any]],
        correspondence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge evidence from all sources, deduplicating by ID."""
        seen_ids: set[str] = set()
        merged: list[dict[str, Any]] = []

        # Semantic results first (already ranked by SearcherAgent)
        for item in semantic:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                item["source"] = item.get("source", "semantic_search")
                merged.append(item)

        # Claims evidence (human-verified, high value)
        for item in claims:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                merged.append(item)
            elif item_id in seen_ids:
                # Enrich existing item with claims metadata
                for m in merged:
                    if str(m.get("id", "")) == item_id:
                        m["pre_classified"] = item.get("pre_classified")
                        m["claim_name"] = item.get("claim_name")
                        m["source"] = "semantic_search+claims"
                        break

        # Chronology items
        for item in chronology:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                merged.append(item)

        # Correspondence items
        for item in correspondence:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                merged.append(item)

        return merged

    async def _cloud_rerank(
        self,
        assertion: OpposingAssertion,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply Bedrock Cohere Rerank for cloud-level relevance scoring."""
        if not candidates or len(candidates) <= 15:
            return candidates

        try:
            if get_aws_services is None:
                return candidates[:30]

            aws = get_aws_services()
            texts = [
                str(c.get("content", c.get("text", c.get("title", ""))))[:2000]
                for c in candidates[:50]
            ]
            query = assertion.assertion_text[:500]

            reranked = await aws.rerank_texts(query=query, texts=texts, top_n=25)
            if reranked:
                # Map reranked indices back to candidates
                result: list[dict[str, Any]] = []
                for item in reranked:
                    idx = item.get("index", 0)
                    if 0 <= idx < len(candidates):
                        candidate = dict(candidates[idx])
                        candidate["cloud_rerank_score"] = item.get("relevance_score", 0)
                        result.append(candidate)
                logger.info(f"Bedrock Rerank scored {len(result)} items for assertion {assertion.id}")
                return result
        except Exception as e:
            logger.warning(f"Bedrock Rerank failed (using SearcherAgent results): {e}")

        return candidates[:30]

    # ------------------------------------------------------------------
    # Format and classify (LLM stage)
    # ------------------------------------------------------------------

    def _format_ranked_evidence(
        self,
        ranked_items: list[dict[str, Any]],
        programme_context: str = "",
    ) -> str:
        """Format ranked evidence for LLM classification prompt."""
        parts: list[str] = []
        for i, item in enumerate(ranked_items[:30], 1):
            item_id = item.get("id", "unknown")
            item_type = str(item.get("type", "EVIDENCE")).upper()
            title = item.get("title") or item.get("subject") or item.get("name") or ""
            sender = item.get("sender", "")
            date = item.get("date", "")
            content = str(item.get("content", item.get("text", "")))[:600]
            source = item.get("source", "")
            score = item.get("relevance_score", item.get("cloud_rerank_score", ""))

            # Highlight human-verified evidence
            verified_tag = ""
            pre_classified = item.get("pre_classified")
            if pre_classified:
                verified_tag = f" [HUMAN-VERIFIED: {pre_classified.upper()}]"

            line = f"[{i}] {item_type} | ID: {item_id}{verified_tag}"
            if title:
                line += f" | {title}"
            if sender:
                line += f" | From: {sender}"
            if date:
                line += f" | Date: {date}"
            if score:
                line += f" | Relevance: {float(score) if isinstance(score, (int, float)) else score:.2f}"
            if source:
                line += f" | Source: {source}"
            if content:
                line += f"\n  {content}"
            parts.append(line)

        result = "\n\n".join(parts)

        # Append programme context for delay assertions
        if programme_context:
            result += f"\n\n{programme_context}"

        return result[:40000]  # Cap at 40K chars (more generous with ranked results)

    async def _classify_evidence(
        self,
        assertion: OpposingAssertion,
        search_context: str,
    ) -> dict[str, Any]:
        """Use LLM to classify ranked evidence as contradicting/supporting/contextual."""
        prompt = f"""Analyse the following opposing assertion and classify the RANKED evidence items provided.

OPPOSING ASSERTION:
"{assertion.assertion_text}"

Assertion Type: {assertion.assertion_type}
Parties Mentioned: {', '.join(assertion.parties_mentioned) if assertion.parties_mentioned else 'None specified'}
Dates Mentioned: {', '.join(assertion.dates_mentioned) if assertion.dates_mentioned else 'None specified'}
Amounts Mentioned: {', '.join(assertion.amounts_mentioned) if assertion.amounts_mentioned else 'None specified'}

RANKED EVIDENCE (ordered by relevance):
{search_context}

Classify each relevant evidence item into one of three categories:
1. CONTRADICTING - evidence that disproves, weakens, or challenges the claim
2. SUPPORTING - evidence that corroborates it (we need to know their strongest points)
3. CONTEXTUAL - evidence providing important background or timeline context

Items marked [HUMAN-VERIFIED] have been pre-classified by case analysts — respect their classification unless you have strong reason to override.

Output as JSON:
{{
    "contradicting": [
        {{
            "evidence_id": "ID of the evidence item",
            "evidence_type": "email|document|chronology|claim",
            "title": "Title or subject",
            "excerpt": "The specific relevant excerpt or quote (max 200 chars)",
            "relevance": "Why this contradicts the assertion",
            "strength": "strong|moderate|weak"
        }}
    ],
    "supporting": [
        {{
            "evidence_id": "ID",
            "evidence_type": "type",
            "title": "Title",
            "excerpt": "Relevant excerpt",
            "relevance": "Why this supports the assertion"
        }}
    ],
    "contextual": [
        {{
            "evidence_id": "ID",
            "evidence_type": "type",
            "title": "Title",
            "excerpt": "Relevant excerpt",
            "relevance": "Why this provides important context"
        }}
    ]
}}

Be precise with evidence IDs. Only include genuinely relevant evidence."""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            return cast(dict[str, Any], json.loads(json_str.strip()))

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse evidence classification response: {e}")
            return {"contradicting": [], "supporting": [], "contextual": []}

    def _build_search_context_fallback(self, evidence_context: EvidenceContext) -> str:
        """Fallback: build plaintext evidence context when SearcherAgent is unavailable."""
        parts: list[str] = []
        for item in evidence_context.items[:200]:
            item_id = item.get("id", "unknown")
            item_type = str(item.get("type", "EVIDENCE")).upper()
            title = item.get("title") or item.get("subject") or item.get("name") or ""
            sender = item.get("sender", "")
            date = item.get("date", "")
            content = str(item.get("content", item.get("text", "")))[:300]

            line = f"[{item_id}] {item_type}"
            if title:
                line += f" | {title}"
            if sender:
                line += f" | From: {sender}"
            if date:
                line += f" | Date: {date}"
            if content:
                line += f"\n  {content}"
            parts.append(line)

        return "\n\n".join(parts)[:30000]


# =============================================================================
# Agent 4: Rebuttal Strategist
# =============================================================================


class RebuttalStrategistAgent(BaseAgent):
    """
    Analyses the evidence hunting results and creates a rebuttal strategy.
    Categorises assertions, prioritises rebuttal points, identifies evidence gaps.
    """

    SYSTEM_PROMPT = """You are an expert legal strategist specialising in construction dispute rebuttals.
Your role is to analyse opposing assertions and available evidence to create an optimal rebuttal strategy.

When strategising:
1. Categorise each assertion: factual_error, misrepresentation, omission, unsupported, partial_truth, valid_point
2. Assess rebuttal strength: strong (clear contradicting evidence), moderate (some evidence), weak (limited evidence), no_rebuttal (assertion appears correct)
3. Prioritise points: lead with the strongest contradictions
4. Identify evidence gaps where more investigation is needed
5. Consider the overall narrative and how points connect"""

    async def strategize(
        self,
        assertions: list[OpposingAssertion],
        evidence_results: dict[str, dict[str, Any]],
        rebuttal_tone: RebuttalTone = RebuttalTone.FORMAL,
    ) -> tuple[list[OpposingAssertion], str, list[str], list[str]]:
        """
        Create rebuttal strategy.

        Returns:
            tuple of (updated_assertions, strategy_text, prioritized_ids, evidence_gaps)
        """
        # Build assertion + evidence summary with richer detail for the strategist
        assertion_summary = []
        for a in assertions:
            if not a.include_in_rebuttal:
                continue
            ev = evidence_results.get(a.id, {})
            contras = ev.get("contradicting", [])
            supports = ev.get("supporting", [])
            contexts = ev.get("contextual", [])

            lines = [
                f"[{a.id}] {a.assertion_type} (Priority: {a.priority})",
                f"  Assertion: {a.assertion_text[:300]}",
                f"  Evidence: {len(contras)} contradicting, {len(supports)} supporting, {len(contexts)} contextual",
            ]

            # Show top contradicting evidence excerpts for strategy decisions
            for c in contras[:3]:
                strength = c.get("strength", "")
                excerpt = c.get("excerpt", "")[:200]
                source = c.get("source", "")
                verified = " [HUMAN-VERIFIED]" if source == "claims_module" else ""
                lines.append(f"  ↳ Contra{verified}: {excerpt} (strength: {strength})")

            # Show top supporting evidence for awareness
            for s in supports[:2]:
                excerpt = s.get("excerpt", "")[:150]
                lines.append(f"  ↳ Support: {excerpt}")

            assertion_summary.append("\n".join(lines))

        prompt = f"""Analyse the following opposing assertions and their evidence to create a rebuttal strategy.

REBUTTAL TONE: {rebuttal_tone.value}

ASSERTIONS AND EVIDENCE:
{chr(10).join(assertion_summary)}

For each assertion, determine:
1. rebuttal_category: factual_error, misrepresentation, omission, unsupported, partial_truth, or valid_point
2. rebuttal_strength: strong, moderate, weak, or no_rebuttal

Then create an overall strategy.

Output as JSON:
{{
    "assertion_categories": {{
        "assertion_id": {{
            "rebuttal_category": "category",
            "rebuttal_strength": "strength",
            "reasoning": "Brief explanation"
        }}
    }},
    "strategy": "A 2-3 paragraph description of the overall rebuttal approach and narrative",
    "prioritized_order": ["a3", "a1", "a7"],
    "evidence_gaps": ["Description of areas where more evidence would strengthen the rebuttal"],
    "key_themes": ["theme1", "theme2"]
}}

Prioritised order should lead with the STRONGEST contradictions (most impactful points first).
Evidence gaps should identify specific areas where the rebuttal would benefit from additional evidence."""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT, use_powerful=True)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())

            # Update assertions with categories and strengths
            categories = data.get("assertion_categories", {})
            for a in assertions:
                if a.id in categories:
                    cat = categories[a.id]
                    a.rebuttal_category = cat.get("rebuttal_category", "unsupported")
                    a.rebuttal_strength = cat.get("rebuttal_strength", "moderate")

            strategy = data.get("strategy", "")
            prioritized = data.get("prioritized_order", [a.id for a in assertions])
            gaps = data.get("evidence_gaps", [])

            return assertions, strategy, prioritized, gaps

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse strategy response: {e}")
            # Fallback: simple priority ordering
            prioritized = [a.id for a in sorted(assertions, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.priority, 1))]
            return assertions, "Strategy generation encountered an error. Points ordered by original priority.", prioritized, []


# =============================================================================
# Agent 5: Rebuttal Writer
# =============================================================================


class RebuttalWriterAgent(BaseAgent):
    """
    Generates the comprehensive point-by-point rebuttal document with
    numbered evidence citations. Mirrors the SynthesizerAgent from
    VeriCase Analysis but specialised for rebuttal format.
    """

    SYSTEM_PROMPT = """You are an expert legal writer specialising in construction dispute rebuttals.
Your role is to write forensic, compelling, point-by-point rebuttals backed by evidence citations.

When writing rebuttals:
1. Address each opposing assertion directly and specifically
2. Lead with the strongest contradictions
3. Cite evidence using superscript numbers (e.g., "The contractor's own records show otherwise\u00b9")
4. Be precise, factual, and professional
5. Acknowledge valid points where appropriate (shows credibility)
6. Highlight omissions and misrepresentations clearly
7. Build a coherent narrative across all points"""

    async def write_rebuttal(
        self,
        plan: RebuttalPlan,
        evidence_results: dict[str, dict[str, Any]],
        evidence_context: EvidenceContext,
        rebuttal_tone: RebuttalTone = RebuttalTone.FORMAL,
        case_id: str | None = None,
    ) -> tuple[str, str, list[str], list[dict[str, Any]], list[str], list[dict[str, Any]], list[EvidenceCitation]]:
        """
        Generate the comprehensive rebuttal.

        Returns:
            tuple of (rebuttal_text, executive_summary, key_contradictions,
                      point_by_point, evidence_gaps, evidence_used, cited_evidence)
        """
        # Build the assertion + evidence details for the prompt
        assertion_details = self._build_assertion_details(plan, evidence_results)

        # Get evidence items for citation building
        evidence_items = evidence_context.items

        tone_instructions = {
            RebuttalTone.FORMAL: "Write in a measured, professional tone suitable for formal legal proceedings. Be authoritative but restrained.",
            RebuttalTone.AGGRESSIVE: "Write in a direct, assertive tone that forcefully challenges every weak point. Be bold and uncompromising while remaining professional.",
            RebuttalTone.BALANCED: "Write in a balanced, fair tone that acknowledges valid points while firmly challenging errors. Be persuasive through reasonableness.",
        }

        prompt = f"""Write a comprehensive point-by-point rebuttal of the following opposing document.

DOCUMENT SUMMARY: {plan.document_summary}
DOCUMENT TYPE: {plan.document_type}
OPPOSING PARTY: {plan.detected_stakeholder.get('name', 'Unknown') if plan.detected_stakeholder else 'Unknown'}
REBUTTAL STRATEGY: {plan.rebuttal_strategy}

TONE: {tone_instructions.get(rebuttal_tone, tone_instructions[RebuttalTone.FORMAL])}

ASSERTIONS TO REBUT (in priority order):
{assertion_details}

Write the rebuttal as a professional document with these sections:

1. EXECUTIVE SUMMARY (2-3 paragraphs summarising the key issues with the opposing document)

2. KEY CONTRADICTIONS (bullet points of the 3-5 strongest points against the opposing document)

3. DETAILED POINT-BY-POINT REBUTTAL
For each assertion, use this format:
### [Assertion Category]: [Brief description]
**Opposing claim (Section X):** "[Quote from opposing document]"
**Response:** [Your rebuttal with evidence citations using superscript numbers like \u00b9 \u00b2 \u00b3]
**Strength:** [Strong/Moderate/Weak]

4. EVIDENCE GAPS (areas where additional evidence would strengthen the rebuttal)

5. RECOMMENDATIONS (next steps and suggested actions)

Use numbered superscript citations (\u00b9, \u00b2, \u00b3, etc.) throughout the text to reference evidence.
At the end, include an EVIDENCE APPENDIX listing each citation number and its source.

Output the complete rebuttal document in markdown format."""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT, use_powerful=True)

        # Parse the rebuttal into sections
        rebuttal_text = response
        executive_summary = self._extract_section(response, "EXECUTIVE SUMMARY")
        key_contradictions = self._extract_bullet_points(
            self._extract_section(response, "KEY CONTRADICTIONS")
        )
        evidence_gaps = self._extract_bullet_points(
            self._extract_section(response, "EVIDENCE GAPS")
        )
        recommendations_text = self._extract_bullet_points(
            self._extract_section(response, "RECOMMENDATIONS")
        )

        # Build point-by-point from the assertions
        point_by_point = self._build_point_by_point(plan, evidence_results)

        # Build evidence used and citation registry (with DEP URI forensic citations)
        evidence_used = self._collect_evidence_used(evidence_results, evidence_items)
        cited_evidence = self._build_citation_registry(evidence_used, evidence_items, case_id)

        return (
            rebuttal_text,
            executive_summary,
            key_contradictions,
            point_by_point,
            evidence_gaps,
            evidence_used,
            cited_evidence,
        )

    def _build_assertion_details(
        self,
        plan: RebuttalPlan,
        evidence_results: dict[str, dict[str, Any]],
    ) -> str:
        """
        Build detailed assertion + evidence text for the writer prompt.

        Provides full evidence excerpts (800 chars), relevance scores, source types,
        and human-verified flags for maximum context.
        """
        parts = []
        order = plan.prioritized_points or [a.id for a in plan.assertions]

        # Build lookup
        assertion_map = {a.id: a for a in plan.assertions}

        for aid in order:
            a = assertion_map.get(aid)
            if not a or not a.include_in_rebuttal:
                continue

            ev = evidence_results.get(aid, {})

            section = f"[{a.id}] {a.assertion_type.upper()} | Priority: {a.priority} | Category: {a.rebuttal_category or 'unclassified'} | Strength: {a.rebuttal_strength or 'unknown'}"
            section += f"\nAssertion: \"{a.assertion_text}\""
            if a.section:
                section += f"\nSource section: {a.section}"
            if a.dates_mentioned:
                section += f"\nDates: {', '.join(a.dates_mentioned[:5])}"
            if a.parties_mentioned:
                section += f"\nParties: {', '.join(a.parties_mentioned[:5])}"

            # Contradicting evidence (full excerpts for writing)
            contras = ev.get("contradicting", [])
            if contras:
                section += f"\nContradicting evidence ({len(contras)} items):"
                for c in contras[:7]:
                    eid = c.get('evidence_id', '?')
                    etype = c.get('evidence_type', '')
                    title = c.get('title', '')
                    excerpt = c.get('excerpt', '')[:800]  # Full excerpts for writer
                    relevance = c.get('relevance', '')
                    strength = c.get('strength', '')
                    verified = " [HUMAN-VERIFIED]" if c.get('source') == 'claims_module' else ""
                    section += f"\n  [{eid}] {etype}{verified} | {title}"
                    if strength:
                        section += f" | Strength: {strength}"
                    if relevance:
                        section += f"\n    Relevance: {relevance}"
                    if excerpt:
                        section += f"\n    Content: {excerpt}"

            # Supporting evidence (for awareness)
            supports = ev.get("supporting", [])
            if supports:
                section += f"\nSupporting evidence ({len(supports)} items - opponent's strength):"
                for s in supports[:4]:
                    eid = s.get('evidence_id', '?')
                    title = s.get('title', '')
                    excerpt = s.get('excerpt', '')[:400]
                    relevance = s.get('relevance', '')
                    section += f"\n  [{eid}] {title}"
                    if relevance:
                        section += f"\n    Relevance: {relevance}"
                    if excerpt:
                        section += f"\n    Content: {excerpt}"

            # Contextual evidence
            contexts = ev.get("contextual", [])
            if contexts:
                section += f"\nContextual evidence ({len(contexts)} items):"
                for c in contexts[:4]:
                    eid = c.get('evidence_id', '?')
                    title = c.get('title', '')
                    excerpt = c.get('excerpt', '')[:400]
                    section += f"\n  [{eid}] {title}"
                    if excerpt:
                        section += f"\n    Content: {excerpt}"

            parts.append(section)

        return "\n\n---\n\n".join(parts)

    def _extract_section(self, text: str, section_name: str) -> str:
        """Extract content of a named section from markdown text."""
        patterns = [
            rf"#+\s*{re.escape(section_name)}\s*\n(.*?)(?=\n#+\s|\Z)",
            rf"\*\*{re.escape(section_name)}\*\*\s*\n(.*?)(?=\n\*\*|\n#+\s|\Z)",
            rf"{re.escape(section_name)}\s*\n[-=]+\s*\n(.*?)(?=\n[A-Z]{{2,}}|\n#+\s|\Z)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_bullet_points(self, text: str) -> list[str]:
        """Extract bullet points from a section."""
        points = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
                # Remove leading bullet/number
                cleaned = re.sub(r"^[\-\*\d]+[\.\)]\s*", "", line).strip()
                if cleaned:
                    points.append(cleaned)
        return points

    def _build_point_by_point(
        self,
        plan: RebuttalPlan,
        evidence_results: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build structured point-by-point data for the frontend."""
        points = []
        order = plan.prioritized_points or [a.id for a in plan.assertions]
        assertion_map = {a.id: a for a in plan.assertions}

        for aid in order:
            a = assertion_map.get(aid)
            if not a or not a.include_in_rebuttal:
                continue

            ev = evidence_results.get(aid, {})
            points.append({
                "assertion_id": a.id,
                "assertion_text": a.assertion_text,
                "assertion_type": a.assertion_type,
                "section": a.section,
                "page_reference": a.page_reference,
                "priority": a.priority,
                "rebuttal_category": a.rebuttal_category,
                "rebuttal_strength": a.rebuttal_strength,
                "contradicting_evidence_count": len(ev.get("contradicting", [])),
                "supporting_evidence_count": len(ev.get("supporting", [])),
                "contextual_evidence_count": len(ev.get("contextual", [])),
                "contradicting_evidence": ev.get("contradicting", [])[:5],
                "supporting_evidence": ev.get("supporting", [])[:3],
            })

        return points

    def _collect_evidence_used(
        self,
        evidence_results: dict[str, dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect all unique evidence items referenced across all assertions."""
        evidence_map: dict[str, dict[str, Any]] = {}

        for assertion_id, ev in evidence_results.items():
            for category in ("contradicting", "supporting", "contextual"):
                for item in ev.get(category, []):
                    eid = item.get("evidence_id")
                    if eid and eid not in evidence_map:
                        evidence_map[eid] = {
                            "id": eid,
                            "type": item.get("evidence_type", "evidence"),
                            "title": item.get("title", "Unknown"),
                            "excerpt": item.get("excerpt", ""),
                            "relevance": item.get("relevance", ""),
                            "date": item.get("date"),
                            "category": category,
                        }

        # Enrich with evidence_items metadata if available
        if evidence_items:
            items_by_id = {}
            for ei in evidence_items:
                eid = ei.get("id") or ei.get("evidence_id")
                if eid:
                    items_by_id[str(eid)] = ei

            for eid, ev_data in evidence_map.items():
                if eid in items_by_id:
                    ei = items_by_id[eid]
                    ev_data["title"] = ev_data["title"] or ei.get("title") or ei.get("subject") or ei.get("name", "Unknown")
                    ev_data["date"] = ev_data["date"] or ei.get("date") or ei.get("created_at")
                    ev_data["filename"] = ei.get("filename")

        return list(evidence_map.values())

    def _build_citation_registry(
        self,
        evidence_used: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
        case_id: str | None = None,
    ) -> list[EvidenceCitation]:
        """
        Build numbered citation registry for the evidence appendix.
        Includes DEP URI forensic citations when source text is available.
        """
        citations: list[EvidenceCitation] = []

        # Build lookup for evidence content (for DEP URI span computation)
        items_by_id: dict[str, dict[str, Any]] = {}
        if evidence_items:
            for ei in evidence_items:
                eid = str(ei.get("id") or ei.get("evidence_id") or "")
                if eid:
                    items_by_id[eid] = ei

        for i, ev in enumerate(evidence_used, 1):
            eid = ev.get("id", "")
            excerpt = ev.get("excerpt", "")[:500]
            ev_type = ev.get("type", "document")

            # Compute DEP URI if forensic_integrity is available and we have source text
            dep_uri = None
            if make_dep_uri and compute_span_hash and case_id and excerpt and eid:
                try:
                    source_item = items_by_id.get(eid, {})
                    source_text = str(
                        source_item.get("content", source_item.get("text", ""))
                    )
                    if source_text and excerpt in source_text:
                        start = source_text.index(excerpt)
                        end = start + len(excerpt)
                        span_hash = compute_span_hash(source_text, start, end)
                        source_type = (
                            "email_message" if ev_type.lower() in ("email", "correspondence")
                            else "evidence_item"
                        )
                        dep_uri = make_dep_uri(
                            case_id=case_id,
                            source_type=source_type,
                            source_id=eid,
                            start=start,
                            end=end,
                            span_hash=span_hash,
                        )
                except Exception as e:
                    logger.debug(f"DEP URI computation failed for {eid}: {e}")

            # Store DEP URI on the evidence dict for API access
            if dep_uri:
                ev["dep_uri"] = dep_uri

            citations.append(
                EvidenceCitation(
                    citation_number=i,
                    evidence_id=eid,
                    evidence_type=ev_type,
                    title=ev.get("title", "Unknown"),
                    date=ev.get("date"),
                    excerpt=excerpt,
                    relevance=ev.get("relevance"),
                    page_reference=dep_uri,  # Store DEP URI in page_reference for forensic access
                )
            )

        return citations


# =============================================================================
# Agent 6: Rebuttal Validator
# =============================================================================


class RebuttalValidatorAgent(BaseAgent):
    """
    Validates the rebuttal for accuracy, coherence, completeness,
    and persuasiveness. Detects hallucinations and unsupported claims.
    """

    SYSTEM_PROMPT = """You are an expert quality assurance analyst for legal rebuttal documents.
Your role is to rigorously validate rebuttals for accuracy, logical consistency, and persuasiveness.

When validating:
1. Verify every factual claim in the rebuttal has supporting evidence
2. Check that citations accurately represent the source material
3. Identify logical inconsistencies or contradictions
4. Flag potential hallucinations or unsupported claims
5. Assess persuasiveness - would this rebuttal be effective?
6. Check completeness - are all key opposing assertions addressed?

Be thorough and skeptical. Quality matters more than being polite about issues."""

    async def validate_rebuttal(
        self,
        rebuttal_text: str,
        plan: RebuttalPlan,
        evidence_results: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Validate the rebuttal for quality.

        Returns:
            Validation result with scores, issues, and recommendations.
        """
        # Build summary of what should be in the rebuttal
        assertions_summary = "\n".join(
            f"- [{a.id}] {a.assertion_text[:150]}... (Category: {a.rebuttal_category}, Strength: {a.rebuttal_strength})"
            for a in plan.assertions
            if a.include_in_rebuttal
        )

        prompt = f"""Validate the following rebuttal document for quality and accuracy.

OPPOSING DOCUMENT SUMMARY: {plan.document_summary}

ASSERTIONS THAT SHOULD BE ADDRESSED:
{assertions_summary}

REBUTTAL DOCUMENT TO VALIDATE:
{rebuttal_text[:15000]}

Perform a thorough validation and output as JSON:
{{
    "overall_score": 0.0-1.0,
    "citation_accuracy": {{
        "score": 0.0-1.0,
        "verified_claims": 0,
        "unverified_claims": 0,
        "issues": ["list of citation issues"]
    }},
    "logical_coherence": {{
        "score": 0.0-1.0,
        "issues": ["list of logical inconsistencies"]
    }},
    "completeness": {{
        "score": 0.0-1.0,
        "addressed_assertions": 0,
        "missed_assertions": ["IDs of assertions not addressed"],
        "issues": []
    }},
    "persuasiveness": {{
        "score": 0.0-1.0,
        "strengths": ["what makes the rebuttal compelling"],
        "weaknesses": ["areas that could be stronger"]
    }},
    "factual_accuracy": {{
        "score": 0.0-1.0,
        "potential_hallucinations": ["claims that may be fabricated"],
        "verified_facts": ["key facts that are well-supported"]
    }},
    "recommendations": ["specific improvements"],
    "validation_passed": true/false,
    "confidence": "high|medium|low"
}}"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT, use_powerful=True)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            return cast(dict[str, Any], json.loads(json_str.strip()))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse validation response: {e}")
            return {
                "overall_score": 0.5,
                "validation_passed": True,
                "confidence": "low",
                "recommendations": [
                    "Validation parsing failed - manual review recommended"
                ],
                "raw_response": response[:1000],
            }


# =============================================================================
# Master Orchestrator
# =============================================================================


class RebuttalOrchestrator:
    """
    Master orchestrator for the VeriCase Rebuttal pipeline.

    Workflow:
    1. Build workspace context (case background, purpose, key facts)
    2. Parse and analyse the opposing document (with Comprehend enrichment)
    3. Detect stakeholder (who it's from)
    4. Extract all assertions
    5. Wait for user approval (HITL)
    6. Hunt evidence for each assertion (SearcherAgent + claims + chronology + programme)
    7. Strategise rebuttal approach
    8. Write comprehensive rebuttal
    9. Validate quality
    """

    def __init__(self, db: Session, session: RebuttalSession):
        self.db = db
        self.session = session
        self.workspace_context = ""  # Built at start of each phase

        self.document_analyzer = DocumentAnalyzerAgent(db, "document_analyzer")
        self.stakeholder_detector = StakeholderDetectorAgent(db, "stakeholder_detector")
        self.evidence_hunter = EvidenceHunterAgent(db, "evidence_hunter")
        self.strategist = RebuttalStrategistAgent(db, "strategist")
        self.writer = RebuttalWriterAgent(db, "writer")
        self.validator = RebuttalValidatorAgent(db, "validator")

    def _build_workspace_context(self) -> str:
        """
        Build workspace context from WorkspaceAbout and WorkspacePurpose.
        Injected into all agent system prompts for case-aware reasoning.
        """
        parts: list[str] = []

        # Resolve workspace from project or case
        workspace_uuid = None
        try:
            if self.session.project_id:
                proj = (
                    self.db.query(Project)
                    .filter(Project.id == uuid.UUID(self.session.project_id))
                    .first()
                )
                if proj:
                    workspace_uuid = getattr(proj, "workspace_id", None)
            elif self.session.case_id:
                cs = (
                    self.db.query(Case)
                    .filter(Case.id == uuid.UUID(self.session.case_id))
                    .first()
                )
                if cs:
                    workspace_uuid = getattr(cs, "workspace_id", None)
        except Exception:
            workspace_uuid = None

        if not workspace_uuid:
            return ""

        try:
            about = (
                self.db.query(WorkspaceAbout)
                .filter(WorkspaceAbout.workspace_id == workspace_uuid)
                .first()
            )
            if about:
                notes = (getattr(about, "user_notes", None) or "").strip()[:2000]
                summary = (getattr(about, "summary_md", None) or "").strip()[:2500]
                if notes or summary:
                    parts.append("[CASE CONTEXT]")
                    if notes:
                        parts.append(f"User Notes: {notes}")
                    if summary:
                        parts.append(f"Case Summary: {summary}")

            purpose = (
                self.db.query(WorkspacePurpose)
                .filter(WorkspacePurpose.workspace_id == workspace_uuid)
                .first()
            )
            if purpose:
                goal = (getattr(purpose, "purpose_text", None) or "").strip()[:2000]
                purpose_summary = (getattr(purpose, "summary_md", None) or "").strip()[:2500]
                if goal or purpose_summary:
                    if not parts:
                        parts.append("[CASE CONTEXT]")
                    if goal:
                        parts.append(f"Case Purpose: {goal}")
                    if purpose_summary:
                        parts.append(f"Purpose Summary: {purpose_summary}")
        except Exception as e:
            logger.warning(f"Failed to build workspace context: {e}")

        context = "\n".join(parts)
        if context:
            logger.info(f"Workspace context built ({len(context)} chars)")
        return context

    def _inject_workspace_context(self) -> None:
        """Inject workspace context into all agent system prompts."""
        if not self.workspace_context:
            return

        context_block = f"\n\n{self.workspace_context}\n\nUse this context to ground your analysis in the specifics of this case."

        for agent in (
            self.document_analyzer,
            self.stakeholder_detector,
            self.evidence_hunter,
            self.strategist,
            self.writer,
            self.validator,
        ):
            if hasattr(agent, "SYSTEM_PROMPT"):
                # Append workspace context to the agent's system prompt
                original = agent.SYSTEM_PROMPT
                agent.SYSTEM_PROMPT = original + context_block

    async def run_parsing_phase(self) -> None:
        """
        Phase 1: Parse document, detect stakeholder, extract assertions.
        Results in AWAITING_APPROVAL status.
        """
        if not self.session.document_text:
            raise ValueError("No document text available for parsing")

        # Step 0: Build workspace context and inject into all agents
        self.workspace_context = self._build_workspace_context()
        self._inject_workspace_context()

        # Step 1: Parse document and extract assertions
        self.session.status = RebuttalStatus.PARSING_DOCUMENT
        self.session.processing_step = "parsing_document"
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        summary, assertions = await self.document_analyzer.analyze_document(
            self.session.document_text,
            self.session.document_type.value if self.session.document_type else None,
            self.session.focus_areas,
        )

        # Step 2: Detect stakeholder
        self.session.status = RebuttalStatus.DETECTING_STAKEHOLDERS
        self.session.processing_step = "detecting_stakeholder"
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        stakeholder = await self.stakeholder_detector.detect_stakeholder(
            self.session.document_text,
            self.session.case_id,
            self.session.project_id,
        )

        # If user provided a name, use it with high confidence
        if self.session.document_from:
            stakeholder["name"] = self.session.document_from
            stakeholder["confidence"] = max(stakeholder.get("confidence", 0), 0.95)

        # Step 3: Build plan
        self.session.status = RebuttalStatus.EXTRACTING_ASSERTIONS
        self.session.processing_step = "extracting_assertions"
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        plan = RebuttalPlan(
            document_summary=summary,
            document_type=self.session.document_type.value if self.session.document_type else "other",
            detected_stakeholder=stakeholder,
            stakeholder_confidence=stakeholder.get("confidence", 0.0),
            assertions=assertions,
            assertion_count=len(assertions),
        )

        self.session.plan = plan
        self.session.total_assertions = len(assertions)
        self.session.status = RebuttalStatus.AWAITING_APPROVAL
        self.session.processing_step = ""
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

    async def run_rebuttal_phase(self, evidence_context: EvidenceContext) -> None:
        """
        Phase 2: Hunt evidence, strategise, write rebuttal, validate.
        Called after user approves the plan.
        """
        if not self.session.plan:
            raise ValueError("No plan available for rebuttal phase")

        # Re-inject workspace context (orchestrator may be fresh for phase 2)
        if not self.workspace_context:
            self.workspace_context = self._build_workspace_context()
            self._inject_workspace_context()

        plan = self.session.plan

        # Step 1: Hunt evidence for each assertion
        self.session.status = RebuttalStatus.HUNTING_EVIDENCE
        self.session.processing_step = "hunting_evidence"
        self.session.assertions_hunted = 0
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        evidence_results = await self.evidence_hunter.hunt_evidence_for_assertions(
            plan.assertions,
            evidence_context,
            self.session,
        )
        self.session.assertion_evidence = evidence_results

        # Populate evidence on assertions for downstream agents
        for a in plan.assertions:
            ev = evidence_results.get(a.id, {})
            a.contradicting_evidence = ev.get("contradicting", [])
            a.supporting_evidence = ev.get("supporting", [])
            a.contextual_evidence = ev.get("contextual", [])

        # Step 2: Strategise
        self.session.status = RebuttalStatus.STRATEGIZING
        self.session.processing_step = "strategizing"
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        updated_assertions, strategy, prioritized, gaps = await self.strategist.strategize(
            plan.assertions, evidence_results, self.session.rebuttal_tone
        )

        plan.assertions = updated_assertions
        plan.rebuttal_strategy = strategy
        plan.prioritized_points = prioritized
        plan.evidence_gaps = gaps

        # Step 3: Write the rebuttal
        self.session.status = RebuttalStatus.DRAFTING_REBUTTAL
        self.session.processing_step = "drafting_rebuttal"
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        (
            rebuttal_text,
            executive_summary,
            key_contradictions,
            point_by_point,
            evidence_gaps_writer,
            evidence_used,
            cited_evidence,
        ) = await self.writer.write_rebuttal(
            plan, evidence_results, evidence_context, self.session.rebuttal_tone,
            case_id=self.session.case_id,
        )

        self.session.final_rebuttal = rebuttal_text
        self.session.executive_summary = executive_summary
        self.session.key_contradictions = key_contradictions
        self.session.point_by_point = point_by_point
        self.session.evidence_gaps = list(set(gaps + evidence_gaps_writer))
        self.session.evidence_used = evidence_used
        self.session.cited_evidence = cited_evidence
        self.session.next_citation_number = len(cited_evidence) + 1

        # Step 4: Validate
        self.session.status = RebuttalStatus.VALIDATING
        self.session.processing_step = "validating"
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        validation_result = await self.validator.validate_rebuttal(
            rebuttal_text, plan, evidence_results
        )

        self.session.validation_result = validation_result
        self.session.validation_passed = validation_result.get("validation_passed", True)
        self.session.total_assertions_analyzed = len(
            [a for a in plan.assertions if a.include_in_rebuttal]
        )
        self.session.total_sources_searched = len(evidence_used)


# =============================================================================
# Document Text Extraction Helper
# =============================================================================


async def extract_document_text(
    file_content: bytes, filename: str
) -> str:
    """
    Extract text from an uploaded document.
    Uses the evidence module's text extraction pipeline.
    """
    from .evidence.text_extract import extract_text_from_bytes

    text = extract_text_from_bytes(file_content, filename=filename)

    if not text or len(text.strip()) < 50:
        # Try Tika as fallback for PDFs and other binary formats
        try:
            from .evidence.text_extract import tika_url_candidates
            import httpx

            tika_urls = tika_url_candidates(None)
            for tika_url in tika_urls:
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.put(
                            f"{tika_url}/tika",
                            content=file_content,
                            headers={"Accept": "text/plain"},
                        )
                        if resp.status_code == 200 and len(resp.text.strip()) > 50:
                            return resp.text
                except Exception:
                    continue
        except ImportError:
            pass

    return text or ""


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/start", response_model=StartRebuttalResponse)
async def start_vericase_rebuttal(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
    case_id: str | None = Form(None),
    document_type: str | None = Form(None),
    document_from: str | None = Form(None),
    focus_areas: str | None = Form(None),
    rebuttal_tone: str | None = Form(None),
):
    """
    Start a new VeriCase Rebuttal session.

    Accepts a file upload (PDF, DOCX, TXT) along with metadata.
    Extracts text, analyses the document, and returns a session ID.
    """
    # Validate file type
    if not file.filename:
        raise HTTPException(400, "No file provided")

    allowed_extensions = {".pdf", ".docx", ".doc", ".txt", ".rtf", ".md"}
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed_extensions:
        raise HTTPException(
            400,
            f"Unsupported file type: {ext}. Allowed: {', '.join(allowed_extensions)}",
        )

    # Read file content
    file_content = await file.read()
    if not file_content:
        raise HTTPException(400, "Empty file")

    session_id = str(uuid.uuid4())

    # Parse enum values
    doc_type = None
    if document_type:
        try:
            doc_type = OpposingDocumentType(document_type)
        except ValueError:
            doc_type = OpposingDocumentType.OTHER

    tone = RebuttalTone.FORMAL
    if rebuttal_tone:
        try:
            tone = RebuttalTone(rebuttal_tone)
        except ValueError:
            tone = RebuttalTone.FORMAL

    session = RebuttalSession(
        id=session_id,
        user_id=str(user.id),
        project_id=project_id,
        case_id=case_id,
        document_filename=file.filename,
        document_type=doc_type,
        document_from=document_from,
        focus_areas=focus_areas,
        rebuttal_tone=tone,
        document_size_bytes=len(file_content),
        status=RebuttalStatus.PENDING,
    )

    save_session(session)

    # Upload to S3 and extract text
    user_id = str(user.id)
    filename = file.filename

    def sync_run_parsing():
        import asyncio
        from .db import SessionLocal

        async def run_parsing():
            task_db = None
            try:
                # Step 1: Upload to S3
                session.status = RebuttalStatus.UPLOADING
                session.processing_step = "uploading"
                session.updated_at = datetime.now(timezone.utc)
                save_session(session)

                s3_key = f"evidence/rebuttal/{session_id}/{filename}"
                try:
                    from .storage import put_object

                    put_object(s3_key, file_content)
                    session.document_s3_key = s3_key
                except Exception as e:
                    logger.warning(f"S3 upload failed (non-critical): {e}")

                # Step 2: Extract text
                session.status = RebuttalStatus.PARSING_DOCUMENT
                session.processing_step = "extracting_text"
                session.updated_at = datetime.now(timezone.utc)
                save_session(session)

                document_text = await extract_document_text(file_content, filename)
                if not document_text or len(document_text.strip()) < 20:
                    raise ValueError(
                        f"Could not extract meaningful text from '{filename}'. "
                        "The file may be empty, corrupted, or in an unsupported format."
                    )

                session.document_text = document_text
                session.updated_at = datetime.now(timezone.utc)
                save_session(session)

                # Step 3: Run parsing phase (document analysis + stakeholder detection + assertion extraction)
                task_db = SessionLocal()
                orchestrator = RebuttalOrchestrator(task_db, session)
                await orchestrator.run_parsing_phase()

            except Exception as e:
                logger.exception(f"Parsing failed for rebuttal session {session.id}: {e}")
                session.status = RebuttalStatus.FAILED
                session.error_message = str(e)
            finally:
                if task_db is not None:
                    task_db.close()
                save_session(session)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_parsing())
        except Exception as e:
            logger.exception(
                f"Background parsing task crashed for session {session.id}: {e}"
            )
            session.status = RebuttalStatus.FAILED
            session.error_message = f"Background task error: {e}"
            save_session(session)
        finally:
            loop.close()

    background_tasks.add_task(sync_run_parsing)

    return StartRebuttalResponse(
        session_id=session_id,
        status="pending",
        message="VeriCase Rebuttal started. Poll /status for updates.",
    )


@router.get("/status/{session_id}", response_model=RebuttalStatusResponse)
async def get_rebuttal_status(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """Get the current status of a VeriCase Rebuttal session."""
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Rebuttal session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized to view this session")

    # Build progress info
    total_assertions = session.total_assertions
    assertions_hunted = session.assertions_hunted

    progress = {
        "total_assertions": total_assertions,
        "assertions_hunted": assertions_hunted,
        "current_phase": session.status.value,
        "document_filename": session.document_filename,
    }

    return RebuttalStatusResponse(
        session_id=session_id,
        status=session.status.value,
        document_filename=session.document_filename,
        document_type=session.document_type.value if session.document_type else None,
        plan=session.plan,
        progress=progress,
        final_rebuttal=session.final_rebuttal,
        executive_summary=session.executive_summary,
        key_contradictions=session.key_contradictions,
        processing_time_seconds=session.processing_time_seconds,
        report_available=session.final_rebuttal is not None,
        error_message=session.error_message,
        models_used=list(session.models_used.values()),
        processing_step=session.processing_step,
    )


@router.post("/approve-plan")
async def approve_rebuttal_plan(
    request: ApprovePlanRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Approve or modify the rebuttal plan (Human-in-the-Loop).

    If approved, the evidence hunting and rebuttal generation begins.
    User can exclude specific assertions and override stakeholder detection.
    """
    session = load_session(request.session_id)
    if not session:
        raise HTTPException(404, "Rebuttal session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Normalize status if plan exists but status hasn't caught up
    if session.plan and session.status in {
        RebuttalStatus.PENDING,
        RebuttalStatus.PARSING_DOCUMENT,
        RebuttalStatus.DETECTING_STAKEHOLDERS,
        RebuttalStatus.EXTRACTING_ASSERTIONS,
    }:
        session.status = RebuttalStatus.AWAITING_APPROVAL
        save_session(session)

    if session.status != RebuttalStatus.AWAITING_APPROVAL:
        raise HTTPException(
            400, f"Session not awaiting approval. Status: {session.status}"
        )

    if not request.approved:
        # User wants modifications - re-run parsing with feedback
        if request.modifications and session.document_text:
            session.focus_areas = (
                f"{session.focus_areas or ''}\n\nUser feedback: {request.modifications}"
            ).strip()

        session.status = RebuttalStatus.PENDING
        save_session(session)

        user_id = str(user.id)

        def sync_regenerate():
            import asyncio
            from .db import SessionLocal

            async def regenerate():
                task_db = SessionLocal()
                try:
                    orchestrator = RebuttalOrchestrator(task_db, session)
                    await orchestrator.run_parsing_phase()
                except Exception as e:
                    logger.exception(f"Plan regeneration failed: {e}")
                    session.status = RebuttalStatus.FAILED
                    session.error_message = str(e)
                finally:
                    task_db.close()
                    save_session(session)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(regenerate())
            finally:
                loop.close()

        background_tasks.add_task(sync_regenerate)
        return {
            "status": "regenerating",
            "message": "Plan is being regenerated with your feedback",
        }

    # Apply user modifications before approving
    if session.plan:
        # Exclude assertions the user doesn't want
        if request.excluded_assertion_ids:
            for a in session.plan.assertions:
                if a.id in request.excluded_assertion_ids:
                    a.include_in_rebuttal = False

        # Override stakeholder if user provided one
        if request.stakeholder_override and session.plan.detected_stakeholder:
            session.plan.detected_stakeholder["name"] = request.stakeholder_override
            session.plan.detected_stakeholder["confidence"] = 1.0

    # Approved - start rebuttal pipeline
    start_time = datetime.now(timezone.utc)
    session.status = RebuttalStatus.HUNTING_EVIDENCE
    session.updated_at = datetime.now(timezone.utc)
    save_session(session)

    user_id = str(user.id)
    project_id = session.project_id
    case_id = session.case_id

    def sync_run_rebuttal():
        import asyncio
        from .db import SessionLocal

        async def run_rebuttal():
            task_db = SessionLocal()
            try:
                evidence_context = await build_evidence_context(
                    task_db, user_id, project_id, case_id
                )

                orchestrator = RebuttalOrchestrator(task_db, session)
                await orchestrator.run_rebuttal_phase(evidence_context)

                session.processing_time_seconds = (
                    datetime.now(timezone.utc) - start_time
                ).total_seconds()
                session.status = RebuttalStatus.COMPLETED
                session.completed_at = datetime.now(timezone.utc)

            except Exception as e:
                logger.exception(f"Rebuttal generation failed: {e}")
                session.status = RebuttalStatus.FAILED
                session.error_message = str(e)
            finally:
                task_db.close()
                save_session(session)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_rebuttal())
        except Exception as e:
            logger.exception(
                f"Background rebuttal task crashed for session {session.id}: {e}"
            )
            session.status = RebuttalStatus.FAILED
            session.error_message = f"Background task error: {e}"
            save_session(session)
        finally:
            loop.close()

    background_tasks.add_task(sync_run_rebuttal)

    return {"status": "approved", "message": "Rebuttal generation started"}


@router.get("/report/{session_id}", response_model=RebuttalReportResponse)
async def get_rebuttal_report(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
):
    """Get the full VeriCase Rebuttal report."""
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Rebuttal session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    if session.status != RebuttalStatus.COMPLETED:
        raise HTTPException(
            400, f"Rebuttal not complete. Status: {session.status.value}"
        )

    return RebuttalReportResponse(
        session_id=session_id,
        case_id=session.case_id,
        project_id=session.project_id,
        document_filename=session.document_filename,
        document_type=session.document_type.value if session.document_type else None,
        detected_stakeholder=session.plan.detected_stakeholder if session.plan else None,
        executive_summary=session.executive_summary,
        final_rebuttal=session.final_rebuttal,
        key_contradictions=session.key_contradictions,
        point_by_point=session.point_by_point,
        evidence_gaps=session.evidence_gaps,
        recommendations=session.recommendations,
        evidence_used=session.evidence_used,
        cited_evidence=session.cited_evidence,
        validation_score=session.validation_result.get("overall_score", 0.0),
        validation_passed=session.validation_passed,
        models_used=list(session.models_used.values()),
        total_duration_seconds=session.processing_time_seconds,
    )


@router.get("/{session_id}/evidence/{citation_number}")
async def get_evidence_item(
    session_id: str,
    citation_number: int,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    download: bool = False,
):
    """
    Get a specific evidence item by its citation number.

    Returns preview metadata or a download URL for the evidence.
    """
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Rebuttal session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Find the citation
    citation = next(
        (c for c in session.cited_evidence if c.citation_number == citation_number),
        None,
    )
    if not citation:
        raise HTTPException(404, f"Citation {citation_number} not found")

    response_data: dict[str, Any] = {
        "citation_number": citation.citation_number,
        "evidence_id": citation.evidence_id,
        "evidence_type": citation.evidence_type,
        "title": citation.title,
        "date": citation.date,
        "excerpt": citation.excerpt,
    }

    # Include DEP URI forensic citation if available
    if citation.page_reference and citation.page_reference.startswith("dep://"):
        response_data["dep_uri"] = citation.page_reference

    if download and citation.evidence_id:
        # Try to find downloadable content
        try:
            evidence_item = (
                db.query(EvidenceItem)
                .filter(EvidenceItem.id == citation.evidence_id)
                .first()
            )
            if evidence_item and evidence_item.s3_key:
                from .storage import presign_get

                url = presign_get(evidence_item.s3_key, expires=3600)
                response_data["download_url"] = url
                response_data["filename"] = evidence_item.filename
        except Exception as e:
            logger.warning(f"Could not generate download URL: {e}")

        # Try email attachment
        if "download_url" not in response_data:
            try:
                from .models import EmailAttachment

                attachment = (
                    db.query(EmailAttachment)
                    .filter(EmailAttachment.id == citation.evidence_id)
                    .first()
                )
                if attachment and attachment.s3_key:
                    from .storage import presign_get

                    url = presign_get(attachment.s3_key, expires=3600)
                    response_data["download_url"] = url
                    response_data["filename"] = attachment.filename
            except Exception as e:
                logger.warning(f"Could not find attachment: {e}")

    return response_data


@router.get("/{session_id}/evidence-bundle")
async def download_evidence_bundle(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get a manifest of all cited evidence with download URLs.

    Returns a list of all evidence items cited in the rebuttal with
    pre-signed URLs for downloading. Client can create a ZIP bundle.
    """
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Rebuttal session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    if not session.cited_evidence:
        return {
            "session_id": session_id,
            "document_filename": session.document_filename,
            "evidence_count": 0,
            "items": [],
            "message": "No evidence was cited in this rebuttal",
        }

    items = []
    for citation in session.cited_evidence:
        item_data: dict[str, Any] = {
            "citation_number": citation.citation_number,
            "evidence_id": citation.evidence_id,
            "evidence_type": citation.evidence_type,
            "title": citation.title,
            "date": citation.date,
            "download_url": None,
            "filename": None,
            "can_download": False,
        }

        if citation.evidence_id:
            # Try evidence item
            try:
                evidence_item = (
                    db.query(EvidenceItem)
                    .filter(EvidenceItem.id == citation.evidence_id)
                    .first()
                )
                if evidence_item and evidence_item.s3_key:
                    from .storage import presign_get

                    item_data["download_url"] = presign_get(
                        evidence_item.s3_key, expires=3600
                    )
                    item_data["filename"] = evidence_item.filename
                    item_data["can_download"] = True
            except Exception as e:
                logger.warning(
                    f"Could not generate URL for {citation.evidence_id}: {e}"
                )

            # Try email attachment if evidence item not found
            if not item_data["can_download"]:
                try:
                    from .models import EmailAttachment

                    attachment = (
                        db.query(EmailAttachment)
                        .filter(EmailAttachment.id == citation.evidence_id)
                        .first()
                    )
                    if attachment and attachment.s3_key:
                        from .storage import presign_get

                        item_data["download_url"] = presign_get(
                            attachment.s3_key, expires=3600
                        )
                        item_data["filename"] = attachment.filename
                        item_data["can_download"] = True
                except Exception as e:
                    logger.warning(f"Could not find attachment: {e}")

        items.append(item_data)

    return {
        "session_id": session_id,
        "document_filename": session.document_filename,
        "evidence_count": len(items),
        "downloadable_count": sum(1 for i in items if i["can_download"]),
        "items": items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.delete("/{session_id}")
async def cancel_rebuttal(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """Cancel a VeriCase Rebuttal session."""
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Rebuttal session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    session.status = RebuttalStatus.CANCELLED
    save_session(session)

    return {"status": "cancelled", "message": "VeriCase Rebuttal session cancelled"}


@router.get("/sessions")
async def list_rebuttal_sessions(
    user: Annotated[User, Depends(current_user)], limit: int = 20
):
    """List user's VeriCase Rebuttal sessions."""
    user_sessions = [
        {
            "id": s.id,
            "document_filename": s.document_filename,
            "document_type": s.document_type.value if s.document_type else None,
            "status": s.status.value,
            "created_at": s.created_at.isoformat(),
            "has_report": s.final_rebuttal is not None,
            "detected_stakeholder": (
                s.plan.detected_stakeholder.get("name")
                if s.plan and s.plan.detected_stakeholder
                else None
            ),
        }
        for s in (
            list(_rebuttal_sessions.values())
            + [
                load_session(
                    key.decode().split(":")[-1]
                    if isinstance(key, (bytes, bytearray))
                    else str(key).split(":")[-1]
                )
                for key in (
                    _get_redis().scan_iter("vericase:rebuttal:*")
                    if _get_redis()
                    else []
                )
            ]
        )
        if s and s.user_id == str(user.id)
    ]

    # Sort by created_at descending
    user_sessions.sort(key=lambda x: x["created_at"], reverse=True)

    return {"sessions": user_sessions[:limit]}
