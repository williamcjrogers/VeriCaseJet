"""
VeriCase Analysis - Flagship Multi-Agent Legal Research Platform
=================================================================
Comprehensive multi-agent orchestrated system for legal evidence analysis.
Originally developed as "Deep Research Agent", now the flagship VeriCase feature.

Architecture (based on Egnyte Deep Research patterns):
- Master Agent: Orchestrates the entire research workflow
- Planner Agent: Creates DAG-based research strategy
- Searcher Agent: k-NN + cross-encoder + MMR for intelligent retrieval
- Researcher Agents: Parallel investigation workers
- Synthesizer Agent: Thematic analysis and report generation
- Validator Agent: Quality assurance and hallucination detection

Multi-Vector Semantic Processing:
- content_vec: Semantic meaning of text content
- participant_vec: Who's involved (sender, recipients, mentioned people)
- temporal_vec: When things happened (cyclical month + linear year encoding)
- attachment_vec: What's attached (file types, document categories)

Reference: https://www.egnyte.com/blog/post/inside-the-architecture-of-a-deep-research-agent
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import json
import re
from datetime import datetime, timezone
from typing import Annotated, Any, NotRequired, TypedDict, cast
from enum import Enum
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, not_

try:  # Optional Redis
    from redis import Redis  # type: ignore
except ImportError:  # pragma: no cover - runtime fallback if redis-py not installed
    Redis = None  # type: ignore

from .models import (
    User,
    EmailMessage,
    Project,
    Case,
    EvidenceItem,
    ChronologyItem,
    WorkspaceAbout,
    WorkspacePurpose,
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

# Deliberative planning imports (Phase 2 upgrade)
try:
    from .deliberative_planner import (
        DeliberativePlanner,
        DeliberationEvent,
        estimate_deliberation_time,
    )
    DELIBERATIVE_PLANNER_AVAILABLE = True
except ImportError:
    DELIBERATIVE_PLANNER_AVAILABLE = False
    DeliberativePlanner = None  # type: ignore
    DeliberationEvent = None  # type: ignore

logger = logging.getLogger(__name__)

# Flagship VeriCase Analysis API
router = APIRouter(prefix="/api/vericase-analysis", tags=["vericase-analysis"])

# =============================================================================
# Data Models
# =============================================================================


class AnalysisStatus(str, Enum):
    """Status of a VeriCase analysis session."""

    PENDING = "pending"
    PLANNING = "planning"
    DELIBERATING = "deliberating"  # New: Multi-phase deliberative planning
    AWAITING_APPROVAL = "awaiting_approval"
    RESEARCHING = "researching"
    RUNNING_TIMELINE = "running_timeline"
    RUNNING_DELAY = "running_delay"
    SYNTHESIZING = "synthesizing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisScope(str, Enum):
    """Scope of analysis to perform."""

    FULL = "full"  # All analyses (timeline, delay, research)
    TIMELINE_ONLY = "timeline_only"
    DELAY_ONLY = "delay_only"
    RESEARCH_ONLY = "research_only"
    QUICK = "quick"  # Basic analysis only


class EvidenceCitation(BaseModel):
    """
    A numbered citation linking a statement to its source evidence.
    
    Citations appear as superscript numbers in the report text (e.g., "The delay occurred¹")
    and are listed in the Evidence Appendix with full source details.
    """

    citation_number: int  # The superscript number shown in the report
    evidence_id: str  # ID of the evidence item (attachment_id or document_id)
    evidence_type: str = "document"  # document, email, attachment, image
    title: str  # Document subject/title for display
    date: str | None = None  # Date of the evidence if available
    excerpt: str  # The specific quoted text supporting the statement
    page_reference: str | None = None  # Page/section reference if applicable
    relevance: str | None = None  # Why this evidence is relevant
    download_url: str | None = None  # Pre-signed URL for download (populated on request)
    preview_url: str | None = None  # URL to preview in UI


class ResearchQuestion(BaseModel):
    """A single research question in the DAG"""

    id: str
    question: str
    rationale: str
    dependencies: list[str] = Field(
        default_factory=list
    )  # IDs of questions that must complete first
    status: str = "pending"
    findings: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None


class ResearchPlan(BaseModel):
    """The DAG-structured research plan"""

    topic: str
    problem_statement: str
    key_angles: list[str]
    questions: list[ResearchQuestion]
    estimated_time_minutes: int = 5
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Deliberative planning metadata (populated when using DeliberativePlanner)
    deliberation_metadata: dict[str, Any] | None = None
    deliberation_summary: str | None = None


class AnalysisSession(BaseModel):
    """Complete VeriCase analysis session state"""

    id: str
    user_id: str
    project_id: str | None = None
    case_id: str | None = None
    topic: str
    scope: AnalysisScope = AnalysisScope.FULL
    status: AnalysisStatus = AnalysisStatus.PENDING

    # Planning
    plan: ResearchPlan | None = None
    focus_areas: list[str] = Field(default_factory=list)

    # Research results
    question_analyses: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Timeline & Delay results (for FULL scope)
    timeline_result: dict[str, Any] = Field(default_factory=dict)
    delay_result: dict[str, Any] = Field(default_factory=dict)

    # Final outputs
    final_report: str | None = None
    executive_summary: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    key_themes: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    # Validation
    validation_result: dict[str, Any] = Field(default_factory=dict)
    validation_passed: bool = True

    # Evidence tracking - records which evidence/attachments were used in analysis
    evidence_used: list[dict[str, Any]] = Field(default_factory=list)

    # Citation tracking - numbered evidence citations for the report appendix
    # Each citation maps a superscript number to a specific evidence item
    cited_evidence: list[EvidenceCitation] = Field(default_factory=list)
    next_citation_number: int = 1  # Counter for generating sequential citation numbers

    # Metadata
    total_sources_analyzed: int = 0
    processing_time_seconds: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None

    # Model tracking for transparency
    models_used: dict[str, str] = Field(default_factory=dict)

    # Deliberative planning options
    use_deliberative_planning: bool = True  # Default: use the new thorough planning
    deliberation_events: list[dict[str, Any]] = Field(default_factory=list)

    # Planning progress (visible to frontend during PLANNING status)
    planning_step: str = ""  # "gathering_evidence" | "configuring_agents" | "formulating_strategy"


# Session store (uses Redis if available, otherwise in-memory)
_analysis_sessions: dict[str, AnalysisSession] = {}


def _get_redis() -> Redis | None:
    try:
        if settings.REDIS_URL and Redis:
            return Redis.from_url(settings.REDIS_URL)  # type: ignore[call-arg]
    except Exception as e:  # pragma: no cover - best-effort cache
        logger.warning(f"Redis unavailable for VeriCase sessions: {e}")
    return None


def save_session(session: AnalysisSession) -> None:
    """Persist session to in-memory store and Redis (if available)."""
    _analysis_sessions[session.id] = session
    try:
        redis_client = _get_redis()
        if redis_client:
            redis_client.set(
                f"vericase:session:{session.id}", session.model_dump_json()
            )
    except Exception as e:  # pragma: no cover - non-critical
        logger.warning(f"Failed to persist session to Redis: {e}")


def load_session(session_id: str) -> AnalysisSession | None:
    """Load session from in-memory store or Redis."""
    cached = _analysis_sessions.get(session_id)
    redis_session: AnalysisSession | None = None

    try:
        redis_client = _get_redis()
        if redis_client:
            data = redis_client.get(f"vericase:session:{session_id}")
            if data:
                redis_session = AnalysisSession.model_validate_json(data)
    except Exception as e:  # pragma: no cover - non-critical
        logger.warning(f"Failed to load session from Redis: {e}")

    if redis_session:
        if not cached or redis_session.updated_at >= cached.updated_at:
            _analysis_sessions[session_id] = redis_session
            return redis_session

    if cached:
        return cached

    return None


# =============================================================================
# Request/Response Models
# =============================================================================


class PlanQuestionPayload(TypedDict):
    id: str
    question: str
    rationale: str
    dependencies: NotRequired[list[str]]


class PlanPayload(TypedDict):
    problem_statement: str
    key_angles: list[str]
    questions: list[PlanQuestionPayload]
    estimated_time_minutes: NotRequired[int]


class StartAnalysisRequest(BaseModel):
    """Request to start a VeriCase analysis session."""

    topic: str = Field(..., description="The research topic or question")
    project_id: str | None = None
    case_id: str | None = None
    scope: AnalysisScope = AnalysisScope.FULL
    focus_areas: list[str] = Field(
        default_factory=list, description="Optional focus areas to prioritize"
    )
    include_timeline: bool = True
    include_delay: bool = True
    use_deliberative_planning: bool = Field(
        default=True,
        description=(
            "Use multi-phase deliberative planning (5-25 min) instead of quick planning (~5 sec). "
            "Deliberative mode provides visible chain-of-thought reasoning, comprehensive entity "
            "extraction via AWS Comprehend, and multi-angle legal analysis."
        ),
    )


class StartAnalysisResponse(BaseModel):
    session_id: str
    status: str
    message: str


class ApprovePlanRequest(BaseModel):
    session_id: str
    approved: bool
    modifications: str | None = None  # User feedback for plan modification


class AnalysisStatusResponse(BaseModel):
    """Status response for a VeriCase analysis."""

    session_id: str
    status: str
    scope: str = "full"
    plan: ResearchPlan | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    timeline_status: str = "pending"
    delay_status: str = "pending"
    research_status: str = "pending"
    final_report: str | None = None
    executive_summary: str | None = None
    key_themes: list[str] = Field(default_factory=list)
    processing_time_seconds: float = 0
    report_available: bool = False
    error_message: str | None = None
    models_used: list[str] = Field(default_factory=list)

    # Deliberative planning events for chain-of-thought UI
    deliberation_events: list[dict[str, Any]] = Field(default_factory=list)

    # Planning sub-step for progress visibility
    planning_step: str = ""


class AnalysisReportResponse(BaseModel):
    """Full analysis report response."""

    session_id: str
    case_id: str | None = None
    project_id: str | None = None
    topic: str
    executive_summary: str | None = None
    final_report: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    key_themes: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    timeline_summary: dict[str, Any] = Field(default_factory=dict)
    delay_summary: dict[str, Any] = Field(default_factory=dict)
    research_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_used: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Evidence and attachments referenced in the analysis",
    )

    # Evidence Appendix - numbered citations for footnotes
    cited_evidence: list[EvidenceCitation] = Field(
        default_factory=list,
        description=(
            "Numbered citations linking report statements to source evidence. "
            "Each citation has a superscript number that appears in the report text."
        ),
    )

    validation_score: float = 0.0
    validation_passed: bool = True
    models_used: list[str] = Field(default_factory=list)
    total_duration_seconds: float = 0


# =============================================================================
# Evidence Context
# =============================================================================


@dataclass
class EvidenceContext:
    """Container for evidence context - both string and structured formats"""

    text: str  # String format for LLM prompts
    items: list[dict[str, Any]]  # Structured format for intelligent retrieval


# =============================================================================
# AI Agent Classes
# =============================================================================


class BaseAgent:
    """
    Base class for all agents - supports 6 providers: OpenAI, Anthropic, Gemini, Bedrock, xAI, Perplexity.

    Uses centralized tool configuration from AISettings.DEFAULT_TOOL_CONFIGS["vericase_analysis"].
    """

    # Tool name for configuration lookup
    TOOL_NAME = "vericase_analysis"

    def __init__(self, db: Session, agent_name: str | None = None):
        self.db = db
        self.agent_name = agent_name

        # Load tool configuration
        self.tool_config = get_tool_config(self.TOOL_NAME, db)
        self.fallback_chain = get_tool_fallback_chain(self.TOOL_NAME, db)

        # Load agent-specific config if applicable
        if agent_name:
            self.agent_config = get_tool_agent_config(self.TOOL_NAME, agent_name, db)
        else:
            self.agent_config = {}

        # API keys for all providers
        self.openai_key = get_ai_api_key("openai", db)
        self.anthropic_key = get_ai_api_key("anthropic", db)
        self.gemini_key = get_ai_api_key("gemini", db)

        # Bedrock uses IAM credentials, not API keys
        self.bedrock_enabled = is_bedrock_enabled(db) and bedrock_available()
        self.bedrock_region = get_bedrock_region(db)
        self._bedrock_provider: BedrockProvider | None = None

        # Model selections - use agent config if available, else tool config, else provider default
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

        # Tool-specific settings from config
        self.max_tokens = self.tool_config.get("max_tokens", 8000)
        self.temperature = self.tool_config.get("temperature", 0.2)
        self.max_duration = self.tool_config.get("max_duration_seconds", 600)

    @property
    def bedrock_provider(self) -> BedrockProvider | None:
        """Lazy-load Bedrock provider"""
        if self._bedrock_provider is None and self.bedrock_enabled:
            try:
                self._bedrock_provider = BedrockProvider(region=self.bedrock_region)
            except Exception as e:
                logger.warning(f"Failed to initialize Bedrock provider: {e}")
        return self._bedrock_provider

    async def _call_llm(
        self, prompt: str, system_prompt: str = "", use_powerful: bool = False
    ) -> str:
        """Call the appropriate LLM based on configuration - Bedrock first for cost optimization"""
        errors: list[str] = []

        # Try Bedrock FIRST - uses AWS billing, more cost effective
        if self.bedrock_enabled:
            try:
                return await self._call_bedrock(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Bedrock call failed, trying fallback: {e}")
                errors.append(f"Bedrock: {e}")

        # Fallback to external APIs - each with error handling
        # Use Anthropic for powerful/complex tasks
        if use_powerful and self.anthropic_key:
            try:
                return await self._call_anthropic(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Anthropic (powerful) call failed: {e}")
                errors.append(f"Anthropic: {e}")

        # Try OpenAI
        if self.openai_key:
            try:
                return await self._call_openai(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"OpenAI call failed: {e}")
                errors.append(f"OpenAI: {e}")

        # Try Gemini
        if self.gemini_key:
            try:
                return await self._call_gemini(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Gemini call failed: {e}")
                errors.append(f"Gemini: {e}")

        # Final fallback to Anthropic
        if self.anthropic_key and "Anthropic" not in str(errors):
            try:
                return await self._call_anthropic(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Anthropic (fallback) call failed: {e}")
                errors.append(f"Anthropic: {e}")

        # If we got here, all providers failed or none configured
        if errors:
            error_summary = "; ".join(errors)
            raise HTTPException(500, f"All AI providers failed: {error_summary}")

        raise HTTPException(
            500, "No AI providers configured. Please add API keys in Admin Settings."
        )

    async def _call_openai(self, prompt: str, system_prompt: str = "") -> str:
        model_id = self.openai_model
        return await complete_chat(
            provider="openai",
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.openai_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_anthropic(self, prompt: str, system_prompt: str = "") -> str:
        model_id = self.anthropic_model
        return await complete_chat(
            provider="anthropic",
            model_id=model_id,
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
        model_id = self.gemini_model
        return await complete_chat(
            provider="gemini",
            model_id=model_id,
            prompt=prompt,
            system_prompt=system_prompt,
            api_key=self.gemini_key,
            max_tokens=4000,
            temperature=0.3,
        )

    async def _call_bedrock(self, prompt: str, system_prompt: str = "") -> str:
        """Call Amazon Bedrock via BedrockProvider"""
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
            temperature=0.3,
        )


class PlannerAgent(BaseAgent):
    """
    Creates the research blueprint as a DAG.

    Workflow:
    1. Analyze the research topic
    2. Identify key research angles
    3. Generate research questions with dependencies
    4. Structure as DAG for parallel execution
    """

    SYSTEM_PROMPT = """You are an expert legal research planner specializing in construction disputes.
Your role is to create comprehensive research plans that systematically investigate complex topics.

When creating a research plan:
1. Break down the topic into logical, sequential research questions
2. Identify dependencies between questions (what needs to be answered first)
3. Structure questions to enable parallel investigation where possible
4. Focus on evidence-based inquiry that can be answered from available documents
5. Consider chronology, causation, liability, and quantum aspects

Output your plan in the specified JSON format."""

    async def create_plan(
        self, topic: str, evidence_context: str, focus_areas: list[str] | None = None
    ) -> ResearchPlan:
        """Generate a research plan as a DAG"""

        focus_str = (
            "\n\nFocus areas to prioritize:\n"
            + "\n".join(f"- {f}" for f in focus_areas)
            if focus_areas
            else ""
        )

        prompt = f"""Create a comprehensive research plan for the following topic:

RESEARCH TOPIC: {topic}
{focus_str}

AVAILABLE EVIDENCE CONTEXT (sample of available documents):
{evidence_context[:3000]}

Generate a research plan with 6-10 interconnected research questions. Each question should:
1. Be specific and answerable from the evidence
2. Build logically on previous questions where appropriate
3. Cover different aspects: chronology, causation, responsibility, impact

Output as JSON with this exact structure:
{{
    "problem_statement": "Clear statement of what we're investigating",
    "key_angles": ["angle1", "angle2", "angle3"],
    "questions": [
        {{
            "id": "q1",
            "question": "The specific research question",
            "rationale": "Why this question matters",
            "dependencies": []
        }},
        {{
            "id": "q2",
            "question": "A question that builds on q1",
            "rationale": "Why this follows from q1",
            "dependencies": ["q1"]
        }}
    ],
    "estimated_time_minutes": 5
}}

Ensure questions form a valid DAG (no circular dependencies)."""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)

        # Parse JSON from response
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            plan_data = cast(PlanPayload, json.loads(json_str.strip()))

            questions = [
                ResearchQuestion(
                    id=q["id"],
                    question=q["question"],
                    rationale=q["rationale"],
                    dependencies=q.get("dependencies", []) or [],
                )
                for q in plan_data["questions"]
            ]

            return ResearchPlan(
                topic=topic,
                problem_statement=plan_data["problem_statement"],
                key_angles=plan_data["key_angles"],
                questions=questions,
                estimated_time_minutes=plan_data.get("estimated_time_minutes", 5) or 5,
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse plan: {e}")
            # Create a fallback simple plan
            return ResearchPlan(
                topic=topic,
                problem_statement=f"Investigate: {topic}",
                key_angles=["Chronology", "Causation", "Responsibility"],
                questions=[
                    ResearchQuestion(
                        id="q1",
                        question=f"What is the timeline of events related to {topic}?",
                        rationale="Establish chronological foundation",
                        dependencies=[],
                    ),
                    ResearchQuestion(
                        id="q2",
                        question="What were the key decisions and actions taken?",
                        rationale="Identify decision points",
                        dependencies=["q1"],
                    ),
                    ResearchQuestion(
                        id="q3",
                        question="What evidence supports or contradicts the claims?",
                        rationale="Assess evidence strength",
                        dependencies=["q1", "q2"],
                    ),
                ],
            )


class SearcherAgent(BaseAgent):
    """
    Information Gatherer Agent - handles search, reranking, and diversification.

    Integrates with VeriCase's 4-vector semantic engine for multi-faceted retrieval:
    - content_vec: Semantic meaning
    - participant_vec: Who's involved
    - temporal_vec: When things happened
    - attachment_vec: What's attached

    Workflow (based on Egnyte architecture):
    1. Fast k-NN retrieval from vector index (milliseconds, ~100 candidates)
    2. Cross-encoder reranking for relevance (top-N from candidates)
    3. MMR (Maximal Marginal Relevance) for diverse results
    4. Return high-quality, diverse results
    """

    _cross_encoder: Any | None = None
    _embedding_model: Any | None = None
    _vector_service: Any | None = None
    _multi_vector_service: Any | None = None

    @classmethod
    def get_cross_encoder(cls):
        """Lazy load cross-encoder model for reranking"""
        if cls._cross_encoder is None:
            try:
                from sentence_transformers import CrossEncoder

                cls._cross_encoder = CrossEncoder(
                    "cross-encoder/ms-marco-MiniLM-L-6-v2"
                )
                logger.info("Cross-encoder model loaded successfully")
            except Exception as e:
                logger.warning(f"Could not load cross-encoder: {e}")
        return cls._cross_encoder

    @classmethod
    def get_embedding_model(cls):
        """Lazy load embedding model for MMR"""
        if cls._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer

                cls._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.warning(f"Could not load embedding model: {e}")
        return cls._embedding_model

    @classmethod
    def get_vector_service(cls):
        """Lazy load vector index service for fast k-NN retrieval"""
        if cls._vector_service is None:
            try:
                from .semantic_engine import VectorIndexService

                cls._vector_service = VectorIndexService()
                logger.info("Vector index service loaded successfully")
            except ImportError:
                logger.warning("semantic_engine not available - k-NN disabled")
            except Exception as e:
                logger.warning(f"Could not load vector service: {e}")
        return cls._vector_service

    @classmethod
    def get_multi_vector_service(cls):
        """Lazy load multi-vector service for 4-vector semantic search"""
        if cls._multi_vector_service is None:
            try:
                from .semantic_engine import MultiVectorIndexService

                cls._multi_vector_service = MultiVectorIndexService()
                logger.info("Multi-vector index service loaded successfully")
            except ImportError:
                logger.warning("MultiVectorIndexService not available")
            except Exception as e:
                logger.warning(f"Could not load multi-vector service: {e}")
        return cls._multi_vector_service

    async def multi_vector_search(
        self,
        query: str,
        k: int = 50,
        case_id: str | None = None,
        project_id: str | None = None,
        fusion_weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """
        4-vector semantic search using content, participant, temporal, and attachment vectors.

        This provides more nuanced retrieval by considering multiple aspects of relevance.
        """
        multi_vector_service = self.get_multi_vector_service()
        if multi_vector_service is None:
            logger.warning(
                "Multi-vector service unavailable, falling back to standard k-NN"
            )
            return await self.fast_knn_retrieve(query, k, case_id, project_id)

        try:
            # Default fusion weights emphasize content but include other aspects
            weights = fusion_weights or {
                "content": 0.5,
                "participant": 0.25,
                "temporal": 0.15,
                "attachment": 0.10,
            }

            results = await multi_vector_service.search_multi_vector(
                query=query,
                k=k,
                case_id=case_id,
                project_id=project_id,
                fusion_weights=weights,
            )

            logger.info(f"Multi-vector search retrieved {len(results)} results")
            return results

        except Exception as e:
            logger.warning(f"Multi-vector search failed, falling back to k-NN: {e}")
            return await self.fast_knn_retrieve(query, k, case_id, project_id)

    async def fast_knn_retrieve(
        self,
        query: str,
        k: int = 100,
        case_id: str | None = None,
        project_id: str | None = None,
        source_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fast k-NN retrieval from vector index.

        This is the first stage of the retrieval pipeline - gets top-k candidates
        in milliseconds using approximate nearest neighbor search.
        """
        vector_service = self.get_vector_service()
        if vector_service is None:
            return []

        embedding_model = self.get_embedding_model()
        if embedding_model is None:
            return []

        try:
            # Generate query embedding
            raw_embedding = embedding_model.encode(query, convert_to_numpy=True)
            query_embedding: list[float] = cast(list[float], raw_embedding.tolist())

            # Fast k-NN search
            results: list[dict[str, Any]] = cast(
                list[dict[str, Any]],
                vector_service.search_similar(
                    query_embedding=query_embedding,
                    k=k,
                    case_id=case_id,
                    project_id=project_id,
                    source_types=source_types,
                ),
            )

            logger.info(f"k-NN retrieved {len(results)} candidates in fast search")
            return results

        except Exception as e:
            logger.warning(f"k-NN retrieval failed: {e}")
            return []

    def rerank_results(
        self, query: str, documents: list[dict[str, Any]], top_k: int = 10
    ) -> list[dict[str, Any]]:
        """
        Rerank documents using cross-encoder for better relevance.

        Cross-encoder processes query and document together for more accurate
        relevance scoring than simple vector similarity.
        """
        if not documents:
            return []

        cross_encoder: Any | None = self.get_cross_encoder()
        if cross_encoder is None:
            # Fallback: return documents as-is
            return documents[:top_k]

        try:
            # Create query-document pairs
            pairs = [
                (query, doc.get("content", doc.get("text", str(doc))))
                for doc in documents
            ]

            # Score all pairs
            scores: list[float] = cast(list[float], cross_encoder.predict(pairs))

            # Sort by score descending
            scored_docs: list[tuple[dict[str, Any], float]] = list(
                zip(documents, scores)
            )
            scored_docs.sort(key=lambda x: x[1], reverse=True)

            # Return top-k with scores
            result: list[dict[str, Any]] = []
            for doc, score in scored_docs[:top_k]:
                doc_copy = dict(doc)
                doc_copy["relevance_score"] = float(score)
                result.append(doc_copy)

            return result

        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return documents[:top_k]

    def apply_mmr(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
        diversity_weight: float = 0.3,
    ) -> list[dict[str, Any]]:
        """
        Apply Maximal Marginal Relevance to select diverse yet relevant documents.

        MMR balances relevance to query with diversity among selected documents,
        avoiding redundant information.
        """
        if not documents or len(documents) <= top_k:
            return documents

        embedding_model: Any | None = self.get_embedding_model()
        if embedding_model is None:
            return documents[:top_k]

        try:
            import numpy as np

            # Get document texts
            doc_texts: list[str] = [
                doc.get("content", doc.get("text", str(doc))) for doc in documents
            ]

            # Encode query and documents
            query_embedding: np.ndarray = cast(
                np.ndarray, embedding_model.encode([query])
            )[0]
            doc_embeddings: np.ndarray = cast(
                np.ndarray, embedding_model.encode(doc_texts)
            )

            # Calculate query-document similarities
            query_sims: np.ndarray = np.dot(doc_embeddings, query_embedding) / (
                np.linalg.norm(doc_embeddings, axis=1) * np.linalg.norm(query_embedding)
            )

            # MMR selection
            selected_indices: list[int] = []
            remaining_indices: list[int] = list(range(len(documents)))

            for _ in range(min(top_k, len(documents))):
                if not remaining_indices:
                    break

                mmr_scores: list[tuple[int, float]] = []
                for idx in remaining_indices:
                    # Relevance to query
                    relevance = float(query_sims[idx])

                    # Maximum similarity to already selected documents
                    if selected_indices:
                        selected_embeddings: np.ndarray = doc_embeddings[
                            selected_indices
                        ]
                        doc_vec: np.ndarray = doc_embeddings[idx]
                        similarities: np.ndarray = cast(
                            np.ndarray,
                            np.dot(selected_embeddings, doc_vec)
                            / (
                                np.linalg.norm(selected_embeddings, axis=1)
                                * np.linalg.norm(doc_vec)
                            ),
                        )
                        max_sim = (
                            float(np.max(similarities)) if similarities.size else 0.0
                        )
                    else:
                        max_sim = 0.0

                    # MMR score
                    mmr = (
                        1 - diversity_weight
                    ) * relevance - diversity_weight * max_sim
                    mmr_scores.append((idx, mmr))

                # Select document with highest MMR score
                best_idx = max(mmr_scores, key=lambda x: x[1])[0]
                selected_indices.append(best_idx)
                remaining_indices.remove(best_idx)

            # Return selected documents with MMR scores
            result: list[dict[str, Any]] = []
            for idx in selected_indices:
                doc_copy = dict(documents[idx])
                doc_copy["mmr_score"] = float(query_sims[idx])
                result.append(doc_copy)

            return result

        except Exception as e:
            logger.error(f"MMR failed: {e}")
            return documents[:top_k]

    async def search_and_retrieve(
        self,
        query: str,
        evidence_items: list[dict[str, Any]],
        top_k: int = 10,
        apply_diversity: bool = True,
        case_id: str | None = None,
        project_id: str | None = None,
        use_multi_vector: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Full search pipeline with intelligent retrieval:

        1. Multi-vector or k-NN: Fast ANN search (~100 candidates in ~10ms)
        2. Cross-encoder: Rerank candidates for precision
        3. MMR: Diversify final results

        Falls back to direct cross-encoder on evidence_items if vector search unavailable.
        """
        candidates: list[dict[str, Any]] = []

        # Step 1: Try multi-vector search first (4-vector semantic)
        if use_multi_vector:
            candidates = await self.multi_vector_search(
                query=query,
                k=100,
                case_id=case_id,
                project_id=project_id,
            )

        # Step 1b: Fall back to k-NN if multi-vector unavailable
        if not candidates:
            candidates = await self.fast_knn_retrieve(
                query=query,
                k=100,
                case_id=case_id,
                project_id=project_id,
            )

        if candidates:
            logger.info(
                f"Using {len(candidates)} vector search candidates for reranking"
            )
        elif evidence_items:
            # Fallback: use provided evidence items directly
            candidates = evidence_items
            logger.info(
                f"Vector search unavailable, using {len(candidates)} direct evidence items"
            )
        else:
            return []

        # Ensure workspace-scoped items are considered even when vector search returns results.
        # These may not be present in the vector index (workspace documents are not project/case-linked).
        if evidence_items:
            ws_types = {"WORKSPACE_DOCUMENT", "WORKSPACE_PURPOSE", "WORKSPACE_ABOUT"}
            ws_items = [
                e for e in evidence_items if str(e.get("type") or "") in ws_types
            ]
            if ws_items:
                existing_keys: set[str] = set()
                for c in candidates:
                    cid = c.get("id")
                    ctype = c.get("type")
                    if cid and ctype:
                        existing_keys.add(f"{ctype}:{cid}")

                added = 0
                for e in ws_items[:120]:
                    eid = e.get("id")
                    etype = e.get("type")
                    key = f"{etype}:{eid}" if etype and eid else ""
                    if key and key in existing_keys:
                        continue
                    candidates.append(e)
                    if key:
                        existing_keys.add(key)
                    added += 1

                if added:
                    logger.info(
                        f"Added {added} workspace-scoped items into candidate pool"
                    )

        # Step 2: Cross-encoder reranking on candidates
        reranked = self.rerank_results(query, candidates, top_k=top_k * 2)

        # Step 3: Apply MMR for diversity (if enabled)
        if apply_diversity and len(reranked) > top_k:
            final_results = self.apply_mmr(query, reranked, top_k=top_k)
        else:
            final_results = reranked[:top_k]

        return final_results


class ResearcherAgent(BaseAgent):
    """
    Investigates a single research question.

    Workflow:
    1. Read assigned question and prior findings
    2. Search evidence for relevant information (using SearcherAgent)
    3. Analyze and synthesize findings
    4. Identify gaps for next researcher
    """

    SYSTEM_PROMPT = """You are an expert evidence analyst for construction disputes.
Your role is to thoroughly investigate specific research questions using available evidence.

When analyzing evidence:
1. Cite specific emails, documents, or communications
2. Note dates, parties involved, and key statements
3. Identify patterns and connections
4. Acknowledge gaps or missing information
5. Be objective and evidence-based

Always provide citations in the format: [Source: email/document ID, date, sender]"""

    def __init__(self, db: Session):
        super().__init__(db)
        self.searcher = SearcherAgent(db)

    async def investigate(
        self,
        question: ResearchQuestion,
        evidence_context: str,
        prior_findings: dict[str, str] | None = None,
        evidence_items: list[dict[str, Any]] | None = None,
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Investigate a research question using intelligent evidence retrieval.

        Uses SearcherAgent for:
        - 4-vector semantic search (content, participant, temporal, attachment)
        - Cross-encoder reranking for relevance
        - MMR for diverse, non-redundant results
        """

        relevant_evidence: list[dict[str, Any]] = []

        # If structured evidence items provided, use intelligent retrieval
        if evidence_items:
            try:
                # Use multi-vector search + cross-encoder reranking + MMR
                relevant_evidence = await self.searcher.search_and_retrieve(
                    query=question.question,
                    evidence_items=evidence_items,
                    top_k=15,
                    apply_diversity=True,
                    case_id=case_id,
                    project_id=project_id,
                    use_multi_vector=True,
                )

                # Build context from ranked results
                evidence_context = "\n\n---\n\n".join(
                    [
                        "\n".join(
                            [
                                f"[{e.get('type', 'EVIDENCE')} {e.get('id', 'unknown')}]",
                                f"Relevance Score: {float(e.get('relevance_score', 0.0)):.2f}",
                                f"Content: {str(e.get('content', e.get('text', str(e))))[:800]}",
                            ]
                        )
                        for e in relevant_evidence
                    ]
                )

                logger.info(
                    f"Retrieved {len(relevant_evidence)} relevant evidence items using multi-vector + cross-encoder + MMR"
                )
            except Exception as e:
                logger.warning(f"Intelligent retrieval failed, using raw context: {e}")

        if not evidence_context or not evidence_context.strip():
            return {
                "findings": "Insufficient evidence retrieved to answer without speculation.",
                "citations": [],
                "gaps": [
                    "No relevant evidence retrieved for this question; refine the query or broaden scope."
                ],
                "confidence": "low",
                "key_entities": [],
            }

        prior_str = ""
        if prior_findings:
            prior_str = "\n\nPRIOR FINDINGS FROM RELATED QUESTIONS:\n"
            for qid, findings in prior_findings.items():
                prior_str += f"\n[{qid}]: {findings[:500]}...\n"

        prompt = f"""Investigate the following research question using the available evidence:

RESEARCH QUESTION: {question.question}

RATIONALE: {question.rationale}
{prior_str}

EVIDENCE TO ANALYZE (ranked by relevance):
{evidence_context}

Provide a comprehensive analysis with:
1. KEY FINDINGS: What the evidence shows (with specific citations)
2. SUPPORTING EVIDENCE: Direct quotes or references from documents
3. GAPS IDENTIFIED: What information is missing or unclear
4. CONFIDENCE LEVEL: How well-supported are the findings (high/medium/low)

Format your response as JSON:
{{
    "findings": "Detailed findings with citations",
    "citations": [
        {{"source_id": "id", "date": "date", "excerpt": "relevant quote", "relevance": "why it matters"}}
    ],
    "gaps": ["gap1", "gap2"],
    "confidence": "high|medium|low",
    "key_entities": ["person1", "company1", "date1"]
}}"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)

        try:
            # Parse JSON response
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            return cast(dict[str, Any], json.loads(json_str.strip()))
        except (json.JSONDecodeError, KeyError):
            # Return as plain findings
            return {
                "findings": response,
                "citations": [],
                "gaps": [],
                "confidence": "medium",
                "key_entities": [],
            }


class SynthesizerAgent(BaseAgent):
    """
    Synthesizes all findings into a comprehensive report.

    Workflow:
    1. Perform thematic analysis across all question analyses
    2. Identify emergent themes
    3. Generate report sections in parallel
    4. Assemble final report
    """

    SYSTEM_PROMPT = """You are an expert legal writer specializing in construction dispute reports.
Your role is to synthesize research findings into clear, compelling narratives.

When writing reports:
1. Organize by themes, not just questions
2. Build a coherent narrative arc
3. Highlight key evidence and turning points
4. Note strengths and weaknesses of the case
5. Provide actionable insights and recommendations

Write in a professional, authoritative tone suitable for legal proceedings."""

    last_model_used: str | None = None
    synthesizer_model: str | None = None

    async def synthesize(
        self,
        plan: ResearchPlan,
        question_analyses: dict[str, dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> tuple[str, list[str], list[dict[str, Any]], list[EvidenceCitation]]:
        """
        Synthesize all findings into a comprehensive report with numbered citations.

        Returns:
            tuple of (report_text, themes, evidence_used, cited_evidence)
            - report_text: The full markdown report with superscript citations
            - themes: List of identified themes
            - evidence_used: List of evidence items referenced
            - cited_evidence: List of EvidenceCitation objects for the appendix
        """

        # First, identify themes
        themes = await self._identify_themes(plan, question_analyses)

        # Collect evidence used from question analyses (needed for citation index)
        evidence_used = self._collect_evidence_used(question_analyses, evidence_items)

        # Generate report sections with numbered citations
        sections = await self._generate_sections(
            plan, question_analyses, themes, evidence_items
        )

        # Build citation registry from evidence used
        cited_evidence = self._build_citation_registry(evidence_used, evidence_items)

        # Assemble final report with evidence references
        report = self._assemble_report(plan, sections, themes, evidence_used, cited_evidence)

        return report, themes, evidence_used, cited_evidence

    def _collect_evidence_used(
        self,
        question_analyses: dict[str, dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Collect all evidence items that were referenced during analysis.
        Deduplicates and enriches with metadata.
        """

        def normalize_id(value: Any) -> str | None:
            if not value:
                return None
            text = str(value).strip()
            if not text:
                return None
            for prefix in ("EMAIL ", "EVIDENCE "):
                if text.upper().startswith(prefix):
                    return text[len(prefix) :].strip()
            return text

        evidence_map: dict[str, dict[str, Any]] = {}

        # Collect evidence IDs referenced in question analyses
        for q_id, analysis in question_analyses.items():
            # Check for citations
            citations = analysis.get("citations", [])
            for citation in citations:
                if isinstance(citation, dict):
                    raw_id = citation.get("source_id") or citation.get("id")
                    source_id = normalize_id(raw_id)
                    if source_id and source_id not in evidence_map:
                        evidence_map[source_id] = {
                            "id": source_id,
                            "type": citation.get("type", "evidence"),
                            "title": citation.get("title")
                            or citation.get("subject")
                            or citation.get("name")
                            or citation.get("source_name")
                            or citation.get("sender")
                            or "Unknown",
                            "subject": citation.get("subject"),
                            "sender": citation.get("sender"),
                            "date": citation.get("date"),
                            "relevance": citation.get("relevance", "cited"),
                        }

            # Check for cited sources
            sources = analysis.get("sources", [])
            for source in sources:
                if isinstance(source, dict):
                    raw_id = source.get("id") or source.get("source_id")
                    source_id = normalize_id(raw_id)
                    if source_id and source_id not in evidence_map:
                        evidence_map[source_id] = {
                            "id": source_id,
                            "type": source.get("type", "evidence"),
                            "title": source.get("title")
                            or source.get("name", "Unknown"),
                            "subject": source.get("subject"),
                            "sender": source.get("sender"),
                            "date": source.get("date"),
                            "relevance": source.get("relevance", "cited"),
                        }

            # Check for evidence_ids field
            evidence_ids = analysis.get("evidence_ids", [])
            for eid in evidence_ids:
                norm_id = normalize_id(eid)
                if norm_id and norm_id not in evidence_map:
                    evidence_map[norm_id] = {
                        "id": norm_id,
                        "type": "evidence",
                        "relevance": "analyzed",
                    }

        # Enrich with full evidence item data if available
        if evidence_items:
            for item in evidence_items:
                item_id = normalize_id(item.get("id") or item.get("evidence_id"))
                if item_id:
                    if item_id in evidence_map:
                        # Enrich existing entry
                        item_type = str(
                            item.get("type") or item.get("evidence_type") or ""
                        ).upper()
                        title = (
                            item.get("title")
                            or item.get("name")
                            or evidence_map[item_id].get("title")
                        )
                        if (
                            not title or str(title).strip().lower() == "unknown"
                        ) and item_type == "EMAIL":
                            subject = item.get("subject")
                            sender = item.get("sender")
                            title = subject or (
                                f"Email from {sender}" if sender else "Email"
                            )
                        evidence_map[item_id].update(
                            {
                                "title": title,
                                "subject": item.get("subject")
                                or evidence_map[item_id].get("subject"),
                                "sender": item.get("sender")
                                or evidence_map[item_id].get("sender"),
                                "type": item.get("type")
                                or item.get("evidence_type")
                                or evidence_map[item_id].get("type"),
                                "date": item.get("date")
                                or item.get("created_at")
                                or evidence_map[item_id].get("date"),
                                "filename": item.get("filename")
                                or item.get("file_name"),
                                "attachment_type": item.get("attachment_type")
                                or item.get("mime_type"),
                            }
                        )
                    elif len(evidence_map) < 100:  # Add considered evidence up to limit
                        item_type = str(
                            item.get("type") or item.get("evidence_type") or ""
                        ).upper()
                        title = item.get("title") or item.get("name") or "Unknown"
                        if (
                            not title or str(title).strip().lower() == "unknown"
                        ) and item_type == "EMAIL":
                            subject = item.get("subject")
                            sender = item.get("sender")
                            title = subject or (
                                f"Email from {sender}" if sender else "Email"
                            )
                        evidence_map[item_id] = {
                            "id": item_id,
                            "type": item.get("type")
                            or item.get("evidence_type", "evidence"),
                            "title": title,
                            "subject": item.get("subject"),
                            "sender": item.get("sender"),
                            "date": item.get("date") or item.get("created_at"),
                            "filename": item.get("filename") or item.get("file_name"),
                            "attachment_type": item.get("attachment_type")
                            or item.get("mime_type"),
                            "relevance": "considered",
                        }

        return list(evidence_map.values())

    def _unique_preserve_order(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for item in items:
            normalized = " ".join(str(item or "").split())
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        return unique

    def _clean_section_content(self, theme: str, content: str) -> str:
        if not content:
            return ""

        text = content.strip()
        lines = text.splitlines()
        cleaned_lines: list[str] = []
        theme_key = re.sub(r"\W+", "", theme).lower()
        started = False

        for line in lines:
            stripped = line.strip()
            if not started:
                if not stripped:
                    continue
                heading = re.sub(r"^#+\s*", "", stripped)
                heading_key = re.sub(r"\W+", "", heading).lower()
                if heading_key == theme_key:
                    continue
                started = True
            cleaned_lines.append(line)

        if cleaned_lines:
            first_line = cleaned_lines[0].strip()
            first_key = re.sub(r"\W+", "", first_line).lower()
            if first_key == theme_key:
                cleaned_lines = cleaned_lines[1:]

        text = "\n".join(cleaned_lines).strip()
        if not text:
            return ""

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        deduped: list[str] = []
        prev_norm = ""
        for paragraph in paragraphs:
            norm = re.sub(r"\s+", " ", paragraph).lower()
            if norm == prev_norm:
                continue
            deduped.append(paragraph)
            prev_norm = norm

        return "\n\n".join(deduped)

    async def _identify_themes(
        self, plan: ResearchPlan, analyses: dict[str, dict[str, Any]]
    ) -> list[str]:
        """Identify emergent themes from all analyses"""

        findings_summary = "\n\n".join(
            [
                f"Q: {q.question}\nFindings: {analyses.get(q.id, {}).get('findings', 'No findings')[:500]}"
                for q in plan.questions
            ]
        )

        prompt = f"""Analyze these research findings and identify 3-5 overarching themes:

RESEARCH TOPIC: {plan.topic}

PROBLEM STATEMENT: {plan.problem_statement}

FINDINGS SUMMARY:
{findings_summary}

Identify the key themes that emerge from this research. These themes will become the main sections of the final report.

Output as JSON:
{{
    "themes": [
        {{"title": "Theme Title", "description": "Brief description of this theme"}}
    ]
}}"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT, use_powerful=True)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = cast(dict[str, Any], json.loads(json_str.strip()))
            themes_data = cast(list[dict[str, Any]], data.get("themes", []))
            themes = [str(t.get("title", "")) for t in themes_data]
            return self._unique_preserve_order(themes)
        except Exception:
            return self._unique_preserve_order(
                plan.key_angles
            )  # Fallback to original angles

    async def _generate_sections(
        self,
        plan: ResearchPlan,
        analyses: dict[str, dict[str, Any]],
        themes: list[str],
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """Generate report sections for each theme with numbered citations"""

        all_findings = "\n\n".join(
            [
                f"## {q.question}\n{analyses.get(q.id, {}).get('findings', 'No findings')}"
                for q in plan.questions
            ]
        )

        sections: dict[str, str] = {}

        # Generate sections in parallel
        async def generate_section(theme: str) -> tuple[str, str]:
            # Build evidence citation index for this section
            evidence_index = ""
            if evidence_items:
                evidence_lines = []
                for idx, item in enumerate(evidence_items[:50], 1):
                    item_id = item.get("id") or item.get("evidence_id", f"doc_{idx}")
                    title = item.get("subject") or item.get("title") or item.get("filename", "Document")
                    date = item.get("date") or item.get("created_at", "")
                    if date and len(str(date)) >= 10:
                        date = str(date)[:10]
                    evidence_lines.append(f"[{idx}] ID:{item_id} | {title} | {date}")
                evidence_index = "\n".join(evidence_lines)

            prompt = f"""Write a detailed report section for the theme: "{theme}"

RESEARCH TOPIC: {plan.topic}

ALL RESEARCH FINDINGS:
{all_findings}

EVIDENCE INDEX (use these citation numbers):
{evidence_index if evidence_index else "No structured evidence index available"}

CRITICAL CITATION REQUIREMENTS:
- Every factual statement MUST include a superscript citation number
- Use format: "The contractor failed to respond¹" or "Payment was delayed by 45 days²³"
- Multiple citations can be combined: "The delay caused significant losses¹²⁵"
- Use these superscript characters: ¹²³⁴⁵⁶⁷⁸⁹¹⁰ (or [1], [2], etc. if superscript unavailable)
- Match citation numbers to the Evidence Index above
- Do NOT make statements without citations unless purely analytical

Write a concise section (300-600 words) that:
1. Introduces the theme and its significance
2. Presents relevant findings with NUMBERED CITATIONS
3. Analyzes implications (citations optional for pure analysis)
4. Notes any gaps or uncertainties

Avoid repeating the section title or duplicating headings. Do not repeat the same points.
Write in professional legal report style with proper evidence attribution."""

            content = await self._call_llm(
                prompt, self.SYSTEM_PROMPT, use_powerful=True
            )
            return theme, self._clean_section_content(theme, content)

        # Run section generation in parallel
        tasks = [generate_section(theme) for theme in themes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, tuple):
                theme, content = result
                sections[theme] = content
            else:
                logger.error(f"Section generation failed: {result}")

        return sections

    def _build_citation_registry(
        self,
        evidence_used: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> list[EvidenceCitation]:
        """
        Build a numbered citation registry from evidence used.
        
        Each evidence item gets a unique citation number that can be referenced
        in the report text as superscript footnotes.
        """
        citations: list[EvidenceCitation] = []
        
        # Use evidence_items if available (more complete), otherwise evidence_used
        source_items = evidence_items[:50] if evidence_items else evidence_used[:50]
        
        for idx, item in enumerate(source_items, 1):
            item_id = str(item.get("id") or item.get("evidence_id") or f"doc_{idx}")
            item_type = str(item.get("type") or item.get("evidence_type") or "document").lower()
            
            # Determine title
            title = item.get("subject") or item.get("title") or item.get("filename")
            if not title and item_type == "email":
                sender = item.get("sender", "Unknown")
                title = f"Email from {sender}"
            title = title or f"Evidence Item {idx}"
            
            # Get date
            date = item.get("date") or item.get("created_at")
            if date:
                if hasattr(date, "strftime"):
                    date = date.strftime("%Y-%m-%d")
                elif isinstance(date, str) and len(date) >= 10:
                    date = date[:10]
                else:
                    date = str(date)
            
            # Get excerpt from citations in evidence_used
            excerpt = ""
            relevance = item.get("relevance", "")
            for ev in evidence_used:
                if str(ev.get("id")) == item_id:
                    excerpt = ev.get("excerpt", "")
                    relevance = ev.get("relevance", relevance)
                    break
            
            citation = EvidenceCitation(
                citation_number=idx,
                evidence_id=item_id,
                evidence_type=item_type,
                title=str(title),
                date=date,
                excerpt=excerpt or "See original document",
                relevance=relevance or "Referenced in analysis",
            )
            citations.append(citation)
        
        return citations

    def _assemble_report(
        self,
        plan: ResearchPlan,
        sections: dict[str, str],
        themes: list[str],
        evidence_used: list[dict[str, Any]] | None = None,
        cited_evidence: list[EvidenceCitation] | None = None,
    ) -> str:
        """Assemble the final report with evidence references"""

        unique_themes = self._unique_preserve_order(themes)
        unique_angles = self._unique_preserve_order(plan.key_angles)

        report_parts = [
            f"# VeriCase Analysis Report: {plan.topic}",
            f"\n*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n",
            "---\n",
            "## Executive Summary\n",
            f"{plan.problem_statement}\n",
            "\n### Key Research Angles\n",
            "\n".join(f"- {angle}" for angle in unique_angles),
            "\n---\n",
        ]

        # Add themed sections
        for theme in unique_themes:
            if theme in sections:
                report_parts.append(f"\n## {theme}\n")
                report_parts.append(sections[theme])
                report_parts.append("\n---\n")

        # Add methodology note
        report_parts.append("\n## Research Methodology\n")
        report_parts.append(
            f"This report was generated through systematic analysis of {len(plan.questions)} research questions:\n"
        )
        for q in plan.questions:
            report_parts.append(f"- {q.question}\n")

        # Add Evidence Appendix with numbered citations
        report_parts.append("\n---\n")
        report_parts.append("\n## Evidence Appendix\n")
        report_parts.append(
            "\nThe following evidence items are referenced by superscript numbers "
            "throughout this report. Click the citation number to preview the source.\n\n"
        )

        if cited_evidence:
            # Display as numbered list matching superscript citations
            for citation in cited_evidence:
                superscript = self._to_superscript(citation.citation_number)
                date_str = f" ({citation.date})" if citation.date else ""
                type_badge = f"[{citation.evidence_type.upper()}]"
                
                report_parts.append(
                    f"**{superscript}** {type_badge} **{citation.title}**{date_str}\n"
                )
                if citation.excerpt and citation.excerpt != "See original document":
                    # Truncate long excerpts
                    excerpt = citation.excerpt[:200] + "..." if len(citation.excerpt) > 200 else citation.excerpt
                    report_parts.append(f"   > _{excerpt}_\n")
                report_parts.append(f"   `ID: {citation.evidence_id}`\n\n")
        elif evidence_used:
            # Fallback to old format if no citations built
            for idx, item in enumerate(evidence_used[:50], 1):
                title = item.get("title") or item.get("subject") or item.get("filename", "Unknown")
                date = item.get("date") or ""
                if date and len(str(date)) >= 10:
                    date = f" ({str(date)[:10]})"
                report_parts.append(f"**{self._to_superscript(idx)}** {title}{date}\n")
        else:
            report_parts.append("*No evidence items were captured during analysis.*\n")

        report_parts.append("\n---\n")
        report_parts.append(
            "\n*Download options: Use the Evidence Bundle button to download all cited "
            "evidence, or click individual citations to preview/download specific items.*\n"
        )

        return "\n".join(report_parts)

    @staticmethod
    def _to_superscript(num: int) -> str:
        """Convert a number to superscript characters for citations."""
        superscript_map = {
            "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
            "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"
        }
        return "".join(superscript_map.get(c, c) for c in str(num))


class ValidatorAgent(BaseAgent):
    """
    Validates synthesized output for accuracy, coherence, and proper citations.

    Workflow:
    1. Citation verification - check each claim against source evidence
    2. Coherence checking - ensure consistency between sections
    3. Completeness checking - verify all key angles are addressed
    4. Fact-checking - verify dates, parties, and facts match sources
    5. Generate validation report with confidence scores

    This agent is critical for ensuring quality and reducing hallucinations.
    Uses a secondary model (different from synthesizer) for cross-validation.
    """

    SYSTEM_PROMPT = """You are an expert quality assurance analyst for legal research reports.
Your role is to rigorously validate research outputs for accuracy, consistency, and completeness.

When validating:
1. Verify every factual claim has a supporting citation
2. Check that citations accurately represent the source material
3. Identify any logical inconsistencies or contradictions
4. Flag potential hallucinations or unsupported claims
5. Assess completeness - are all key aspects covered?
6. Evaluate coherence - does the narrative flow logically?

Be thorough and skeptical. Quality matters more than being polite about issues."""

    async def validate_report(
        self,
        report: str,
        plan: ResearchPlan,
        question_analyses: dict[str, dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Validate a synthesized report for accuracy and quality.

        Returns:
            Validation result with scores, issues, and recommendations
        """
        # Build evidence reference for validation
        evidence_summary = ""
        if evidence_items:
            evidence_summary = "\n".join(
                f"[{e.get('id', 'unknown')}] {e.get('type', 'EVIDENCE')}: {str(e.get('content', e.get('text', '')))[:300]}"
                for e in evidence_items[:50]  # Limit for context
            )

        # Build findings reference
        findings_summary = "\n\n".join(
            f"Question: {q.question}\nFindings: {question_analyses.get(q.id, {}).get('findings', 'No findings')[:500]}"
            for q in plan.questions
        )

        prompt = f"""Validate the following research report for accuracy and quality.

RESEARCH TOPIC: {plan.topic}

PROBLEM STATEMENT: {plan.problem_statement}

KEY ANGLES TO COVER: {", ".join(plan.key_angles)}

ORIGINAL RESEARCH FINDINGS:
{findings_summary}

AVAILABLE EVIDENCE REFERENCES:
{evidence_summary[:3000] if evidence_summary else "No structured evidence provided"}

REPORT TO VALIDATE:
{report}

Perform a thorough validation and output as JSON:
{{
    "overall_score": 0.0-1.0,
    "citation_accuracy": {{
        "score": 0.0-1.0,
        "verified_claims": 0,
        "unverified_claims": 0,
        "issues": ["list of citation issues"]
    }},
    "coherence": {{
        "score": 0.0-1.0,
        "issues": ["list of logical inconsistencies or contradictions"]
    }},
    "completeness": {{
        "score": 0.0-1.0,
        "covered_angles": ["angles that were covered"],
        "missing_angles": ["angles that were not addressed"]
    }},
    "factual_accuracy": {{
        "score": 0.0-1.0,
        "potential_hallucinations": ["claims that may be hallucinated"],
        "verified_facts": ["key facts that are well-supported"]
    }},
    "recommendations": ["specific improvements needed"],
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


class VeriCaseOrchestrator:
    """
    Master orchestrator for comprehensive VeriCase analysis.

    Workflow:
    1. Delegate to Planner Agent
    2. Wait for user approval (HITL - Human in the Loop)
    3. Execute research DAG with parallel Researcher Agents
    4. Run Timeline and Delay analysis (if FULL scope)
    5. Delegate to Synthesizer Agent
    6. Run ValidatorAgent for quality assurance
    7. Return final report with validation

    Multi-model orchestration: Different agents can use different models
    based on task requirements and performance metrics.
    """

    def __init__(self, db: Session, session: AnalysisSession):
        self.db = db
        self.session = session
        self.planner = PlannerAgent(db)
        self.synthesizer = SynthesizerAgent(db)
        self.validator = ValidatorAgent(db)

    async def run_planning_phase(
        self, evidence_context: EvidenceContext, focus_areas: list[str] | None = None
    ) -> ResearchPlan:
        """
        Phase 1: Create research plan.

        Two modes:
        1. DELIBERATIVE (default): Multi-phase analysis with AWS Comprehend,
           entity mapping, issue identification, and visible reasoning.
           Takes 5-25 minutes depending on evidence volume.
        2. QUICK (legacy): Single LLM call with 3K context sample.
           Takes ~5 seconds but may miss important connections.
        """
        use_deliberative = (
            self.session.use_deliberative_planning
            and DELIBERATIVE_PLANNER_AVAILABLE
            and DeliberativePlanner is not None
        )

        if use_deliberative:
            return await self._run_deliberative_planning(evidence_context, focus_areas)
        else:
            return await self._run_quick_planning(evidence_context, focus_areas)

    async def _run_quick_planning(
        self, evidence_context: EvidenceContext, focus_areas: list[str] | None = None
    ) -> ResearchPlan:
        """Legacy quick planning - single LLM call with truncated context."""
        self.session.status = AnalysisStatus.PLANNING
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        plan = await self.planner.create_plan(
            self.session.topic,
            evidence_context.text,
            focus_areas,
        )

        self.session.plan = plan
        self.session.status = AnalysisStatus.AWAITING_APPROVAL
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        return plan

    async def _run_deliberative_planning(
        self, evidence_context: EvidenceContext, focus_areas: list[str] | None = None
    ) -> ResearchPlan:
        """
        New deliberative planning - multi-phase analysis with visible reasoning.

        Phases:
        1. Corpus Scan - AWS Comprehend on ALL evidence
        2. Entity Mapping - Build relationship graphs
        3. Issue Identification - LLM analysis of patterns
        4. Angle Deliberation - Multi-pass reasoning (5 angles)
        5. Plan Synthesis - Evidence-grounded research DAG
        """
        import time
        from .aws_services import get_aws_services

        start_time = time.time()

        self.session.status = AnalysisStatus.DELIBERATING
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        try:
            # Get AWS services for Comprehend
            aws_services = get_aws_services()

            # Prepare evidence items as list of dicts
            evidence_items = []
            for item in evidence_context.items:
                evidence_items.append({
                    "id": item.get("id", str(uuid.uuid4())),
                    "subject": item.get("subject", ""),
                    "body_text": item.get("body_text", "") or item.get("content", ""),
                    "date": item.get("date"),
                    "sender": item.get("sender"),
                    "recipients": item.get("recipients", []),
                })

            # Create LLM caller function using the planner agent's provider
            # fallback chain (Bedrock → OpenAI → Gemini → Anthropic)
            async def llm_caller(prompt: str, system_prompt: str) -> str:
                """Call the AI model via the planner's provider chain."""
                return await self.planner._call_llm(prompt, system_prompt)

            # Initialize deliberative planner
            planner = DeliberativePlanner(
                session_id=self.session.id,
                topic=self.session.topic,
                evidence_items=evidence_items,
                aws_services=aws_services,
                db=self.db,
                llm_caller=llm_caller,
            )

            # Store event callback to capture deliberation events
            events_captured: list[dict[str, Any]] = []

            async def capture_event(event: "DeliberationEvent") -> None:
                event_dict = event.model_dump(exclude_none=True)
                events_captured.append(event_dict)
                # Update session with latest events
                self.session.deliberation_events = events_captured[-50:]  # Keep last 50
                self.session.updated_at = datetime.now(timezone.utc)
                save_session(self.session)

            # Monkey-patch the event queue to use our callback
            original_put = planner._event_queue.put

            async def capturing_put(event: "DeliberationEvent") -> None:
                await capture_event(event)
                await original_put(event)

            planner._event_queue.put = capturing_put  # type: ignore

            # Run the deliberative planning
            plan_data = await planner.run()

            # Convert to ResearchPlan
            questions = [
                ResearchQuestion(
                    id=q.get("id", f"q{i+1}"),
                    question=q.get("question", ""),
                    rationale=q.get("rationale", ""),
                    dependencies=q.get("dependencies", []),
                )
                for i, q in enumerate(plan_data.get("questions", []))
            ]

            processing_time = time.time() - start_time

            plan = ResearchPlan(
                topic=self.session.topic,
                problem_statement=plan_data.get("problem_statement", f"Investigate: {self.session.topic}"),
                key_angles=plan_data.get("key_angles", ["Chronology", "Causation", "Liability"]),
                questions=questions,
                estimated_time_minutes=plan_data.get("estimated_time_minutes", 15),
                deliberation_metadata=plan_data.get("deliberation_metadata", {
                    "documents_analyzed": len(evidence_items),
                    "processing_time_seconds": processing_time,
                }),
                deliberation_summary=plan_data.get("deliberation_summary"),
            )

            self.session.plan = plan
            self.session.status = AnalysisStatus.AWAITING_APPROVAL
            self.session.updated_at = datetime.now(timezone.utc)
            self.session.deliberation_events = events_captured
            save_session(self.session)

            logger.info(
                f"Deliberative planning complete for session {self.session.id} "
                f"in {processing_time:.1f}s with {len(questions)} questions"
            )

            return plan

        except Exception as e:
            logger.exception(f"Deliberative planning failed: {e}")
            # Fall back to quick planning
            logger.info("Falling back to quick planning...")
            self.session.use_deliberative_planning = False
            try:
                return await self._run_quick_planning(evidence_context, focus_areas)
            except Exception as fallback_err:
                logger.exception(
                    f"Quick planning fallback also failed: {fallback_err}"
                )
                raise RuntimeError(
                    f"Both deliberative and quick planning failed. "
                    f"Deliberative: {e}. Quick: {fallback_err}"
                ) from fallback_err

    async def run_research_phase(self, evidence_context: EvidenceContext) -> None:
        """
        Phase 2: Execute research DAG with intelligent evidence retrieval.

        Uses multi-vector semantic search, cross-encoder reranking, and MMR for each question.
        """
        if not self.session.plan:
            raise ValueError("No plan available")

        self.session.status = AnalysisStatus.RESEARCHING
        self.session.updated_at = datetime.now(timezone.utc)
        save_session(self.session)

        plan = self.session.plan
        completed: set[str] = set()

        # Topological sort and parallel execution
        while len(completed) < len(plan.questions):
            # Find questions ready to execute (all dependencies met)
            ready = [
                q
                for q in plan.questions
                if q.id not in completed and all(d in completed for d in q.dependencies)
            ]

            if not ready:
                logger.error("DAG has unresolvable dependencies")
                break

            # Execute ready questions in parallel with intelligent retrieval
            async def investigate_question(
                q: ResearchQuestion,
            ) -> tuple[str, dict[str, Any]]:
                researcher = ResearcherAgent(self.db)
                prior = {
                    dep: self.session.question_analyses.get(dep, {}).get("findings", "")
                    for dep in q.dependencies
                }
                # Pass both text context and structured items for intelligent retrieval
                result = await researcher.investigate(
                    q,
                    evidence_context.text,
                    prior,
                    evidence_items=evidence_context.items,
                    case_id=self.session.case_id,
                    project_id=self.session.project_id,
                )
                return q.id, result

            tasks = [investigate_question(q) for q in ready]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, tuple):
                    qid: str = result[0]
                    analysis: dict[str, Any] = result[1]
                    self.session.question_analyses[qid] = analysis
                    completed.add(qid)

                    # Update question status in plan
                    for q in plan.questions:
                        if q.id == qid:
                            q.status = "completed"
                            q.findings = analysis.get("findings", "")
                            q.citations = analysis.get("citations", [])
                            q.gaps = analysis.get("gaps", [])
                            q.completed_at = datetime.now(timezone.utc)
                else:
                    logger.error(f"Research failed: {result}")

            # Persist progress after each batch completes
            self.session.updated_at = datetime.now(timezone.utc)
            save_session(self.session)

    async def run_timeline_analysis(self, evidence_context: EvidenceContext) -> None:
        """Run timeline generation analysis (for FULL scope)."""
        self.session.status = AnalysisStatus.RUNNING_TIMELINE
        self.session.updated_at = datetime.now(timezone.utc)

        try:
            # Get chronology items from database
            if self.session.case_id:
                chronology_items = (
                    self.db.query(ChronologyItem)
                    .filter(ChronologyItem.case_id == self.session.case_id)
                    .order_by(ChronologyItem.event_date)
                    .limit(500)
                    .all()
                )

                if chronology_items:
                    events = [
                        {
                            "date": (
                                item.event_date.isoformat()
                                if item.event_date
                                else "Unknown"
                            ),
                            "event": item.description or "No description",
                            "significance": getattr(item, "significance", "medium")
                            or "medium",
                        }
                        for item in chronology_items
                    ]
                    self.session.timeline_result = {
                        "events": events,
                        "timeline_summary": f"{len(events)} chronology items found",
                        "status": "completed",
                    }
                    return

            # Generate timeline from evidence using LLM
            agent = BaseAgent(self.db)
            prompt = f"""Generate a timeline of key events for this case:

CASE DATA:
{evidence_context.text[:5000]}

Create a chronological timeline as JSON:
{{
    "events": [
        {{
            "date": "YYYY-MM-DD",
            "event": "description",
            "significance": "high|medium|low",
            "sources": ["source1", "source2"]
        }}
    ],
    "key_milestones": ["milestone1", "milestone2"],
    "timeline_summary": "brief summary"
}}"""

            response = await agent._call_llm(
                prompt,
                "You are an expert at reconstructing chronologies from evidence.",
            )

            try:
                timeline_str = response
                if "```json" in response:
                    timeline_str = response.split("```json")[1].split("```")[0]
                self.session.timeline_result = json.loads(timeline_str.strip())
                self.session.timeline_result["status"] = "completed"
            except Exception:
                self.session.timeline_result = {
                    "raw_timeline": response,
                    "status": "completed",
                }

        except Exception as e:
            logger.exception(f"Timeline analysis failed: {e}")
            self.session.timeline_result = {"error": str(e), "status": "failed"}

    async def run_delay_analysis(self, evidence_context: EvidenceContext) -> None:
        """Run delay and causation analysis (for FULL scope)."""
        self.session.status = AnalysisStatus.RUNNING_DELAY
        self.session.updated_at = datetime.now(timezone.utc)

        try:
            agent = BaseAgent(self.db)
            prompt = f"""Analyze delays and causation chains for this construction case:

CASE DATA:
{evidence_context.text[:5000]}

Analyze delays and causation as JSON:
{{
    "delay_events": [
        {{
            "event": "description",
            "cause": "root cause",
            "impact_days": 0,
            "responsible_party": "party name",
            "evidence": ["evidence1", "evidence2"]
        }}
    ],
    "causation_chains": [
        {{
            "trigger": "initial event",
            "sequence": ["event1 -> event2 -> outcome"],
            "total_impact": "description of impact"
        }}
    ],
    "critical_path_delays": ["delay1", "delay2"],
    "entitlement_summary": "summary of time/cost entitlements"
}}"""

            response = await agent._call_llm(
                prompt,
                "You are an expert in construction delay analysis and causation.",
            )

            try:
                delay_str = response
                if "```json" in response:
                    delay_str = response.split("```json")[1].split("```")[0]
                self.session.delay_result = json.loads(delay_str.strip())
                self.session.delay_result["status"] = "completed"
            except Exception:
                self.session.delay_result = {
                    "raw_analysis": response,
                    "status": "completed",
                }

        except Exception as e:
            logger.exception(f"Delay analysis failed: {e}")
            self.session.delay_result = {"error": str(e), "status": "failed"}

    async def run_synthesis_phase(
        self, evidence_context: EvidenceContext | None = None
    ) -> str:
        """Phase 3: Synthesize findings into report with evidence tracking"""
        if not self.session.plan:
            raise ValueError("No plan available")

        self.session.status = AnalysisStatus.SYNTHESIZING
        self.session.updated_at = datetime.now(timezone.utc)

        # Pass evidence items for tracking in the report
        evidence_items = evidence_context.items if evidence_context else None

        report, themes, evidence_used, cited_evidence = await self.synthesizer.synthesize(
            self.session.plan, self.session.question_analyses, evidence_items
        )

        self.session.final_report = report
        self.session.key_themes = themes
        self.session.evidence_used = evidence_used  # Track which evidence was used
        self.session.cited_evidence = cited_evidence  # Numbered citations for appendix
        self.session.models_used["synthesizer"] = (
            self.synthesizer.synthesizer_model or "default"
        )
        self.session.updated_at = datetime.now(timezone.utc)

        return report

    async def run_validation_phase(
        self,
        evidence_context: EvidenceContext | None = None,
    ) -> dict[str, Any]:
        """
        Phase 4: Validate the synthesized report for quality assurance.

        Uses a ValidatorAgent (typically with a different model) to:
        - Verify citations are accurate
        - Check coherence between sections
        - Identify potential hallucinations
        - Assess completeness
        """
        if not self.session.plan or not self.session.final_report:
            raise ValueError("No plan or report available for validation")

        self.session.status = AnalysisStatus.VALIDATING
        logger.info(f"Running validation phase for session {self.session.id}")

        validation_result = await self.validator.validate_report(
            report=self.session.final_report,
            plan=self.session.plan,
            question_analyses=self.session.question_analyses,
            evidence_items=evidence_context.items if evidence_context else None,
        )

        # Store validation results
        self.session.validation_result = validation_result
        self.session.validation_passed = validation_result.get(
            "validation_passed", True
        )
        self.session.models_used["validator"] = "claude"
        self.session.updated_at = datetime.now(timezone.utc)

        # Log validation outcome
        overall_score = validation_result.get("overall_score", 0)
        if overall_score >= 0.8:
            logger.info(f"Validation passed with high confidence: {overall_score}")
        elif overall_score >= 0.5:
            logger.warning(f"Validation passed with medium confidence: {overall_score}")
        else:
            logger.warning(f"Validation flagged issues: {overall_score}")

        if overall_score < 0.5:
            self.session.error_message = f"Validation score low ({overall_score:.2f}): {', '.join(validation_result.get('recommendations', [])[:2])}"

        return validation_result

    async def run_full_workflow(
        self,
        evidence_context: EvidenceContext,
        focus_areas: list[str] | None = None,
        skip_validation: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """
        Run the complete VeriCase analysis workflow end-to-end.

        This is useful for automated/batch processing where plan approval
        is not needed or has been pre-approved.
        """
        import time

        start_time = time.time()

        try:
            # Phase 1: Planning
            await self.run_planning_phase(evidence_context, focus_areas)

            # Phase 2: Research (with parallel execution)
            await self.run_research_phase(evidence_context)

            # Phase 2b: Timeline and Delay (if FULL scope)
            if self.session.scope == AnalysisScope.FULL:
                await asyncio.gather(
                    self.run_timeline_analysis(evidence_context),
                    self.run_delay_analysis(evidence_context),
                    return_exceptions=True,
                )

            # Phase 3: Synthesis (with evidence tracking)
            report = await self.run_synthesis_phase(evidence_context)

            # Phase 4: Validation (optional)
            validation_result = {}
            if not skip_validation:
                validation_result = await self.run_validation_phase(evidence_context)

            # Mark as completed
            self.session.status = AnalysisStatus.COMPLETED
            self.session.completed_at = datetime.now(timezone.utc)
            self.session.updated_at = datetime.now(timezone.utc)

            return report, validation_result

        except Exception as e:
            logger.exception(f"VeriCase analysis failed: {e}")
            self.session.status = AnalysisStatus.FAILED
            self.session.error_message = str(e)
            raise

        finally:
            self.session.processing_time_seconds = time.time() - start_time
            save_session(self.session)


# =============================================================================
# Evidence Context Builder
# =============================================================================


async def build_evidence_context(
    db: Session,
    user_id: str,
    project_id: str | None = None,
    case_id: str | None = None,
) -> EvidenceContext:
    """
    Build evidence context from ALL emails and documents in project/case.

    Returns both:
    - Text format for direct LLM consumption
    - Structured items for multi-vector semantic search, cross-encoder reranking, and MMR
    """

    context_parts: list[str] = []
    evidence_items: list[dict[str, Any]] = []

    intro_parts: list[str] = []
    intro_items: list[dict[str, Any]] = []

    def _clip(val: str | None, limit: int) -> str:
        s = (val or "").strip()
        if not s:
            return ""
        return s if len(s) <= limit else (s[:limit].rstrip() + "…")

    # If the analysis is scoped to a project/case, pull workspace-scoped context too.
    workspace_uuid: uuid.UUID | None = None
    try:
        if project_id:
            proj_uuid = uuid.UUID(str(project_id))
            proj = db.query(Project).filter(Project.id == proj_uuid).first()
            if proj is not None:
                workspace_uuid = getattr(proj, "workspace_id", None)
        elif case_id:
            case_uuid = uuid.UUID(str(case_id))
            cs = db.query(Case).filter(Case.id == case_uuid).first()
            if cs is not None:
                workspace_uuid = getattr(cs, "workspace_id", None)
    except Exception:
        workspace_uuid = None

    if workspace_uuid:
        try:
            about = (
                db.query(WorkspaceAbout)
                .filter(WorkspaceAbout.workspace_id == workspace_uuid)
                .first()
            )
            purpose = (
                db.query(WorkspacePurpose)
                .filter(WorkspacePurpose.workspace_id == workspace_uuid)
                .first()
            )

            # Authoritative user notes + cached summaries help steer analysis.
            if about:
                notes = _clip(getattr(about, "user_notes", None), 2200)
                summary = _clip(getattr(about, "summary_md", None), 3000)
                last_error = _clip(getattr(about, "last_error", None), 600)
                status = str(getattr(about, "status", "") or "").strip()
                if notes or summary or last_error:
                    intro_parts.append(
                        "\n".join(
                            [
                                "[WORKSPACE ABOUT]",
                                f"Status: {status or 'unknown'}",
                                *([f"User Notes: {notes}"] if notes else []),
                                *([f"Summary: {summary}"] if summary else []),
                                *([f"Last error: {last_error}"] if last_error else []),
                                "---",
                            ]
                        )
                    )
                    intro_items.append(
                        {
                            "id": f"workspace:{workspace_uuid}:about",
                            "type": "WORKSPACE_ABOUT",
                            "content": "\n\n".join(
                                [x for x in [notes, summary, last_error] if x]
                            )[:2000],
                            "text": f"Workspace About notes/summary: {notes or summary}",
                        }
                    )

            if purpose:
                goal = _clip(getattr(purpose, "purpose_text", None), 2200)
                summary = _clip(getattr(purpose, "summary_md", None), 3000)
                last_error = _clip(getattr(purpose, "last_error", None), 600)
                status = str(getattr(purpose, "status", "") or "").strip()
                if goal or summary or last_error:
                    intro_parts.append(
                        "\n".join(
                            [
                                "[WORKSPACE PURPOSE]",
                                f"Status: {status or 'unknown'}",
                                *([f"Baseline: {goal}"] if goal else []),
                                *([f"Summary: {summary}"] if summary else []),
                                *([f"Last error: {last_error}"] if last_error else []),
                                "---",
                            ]
                        )
                    )
                    intro_items.append(
                        {
                            "id": f"workspace:{workspace_uuid}:purpose",
                            "type": "WORKSPACE_PURPOSE",
                            "content": "\n\n".join(
                                [x for x in [goal, summary, last_error] if x]
                            )[:2000],
                            "text": f"Workspace purpose baseline: {goal or summary}",
                        }
                    )
        except Exception:
            # best-effort; analysis should still work without cached workspace context
            pass

    # Get emails - exclude spam/hidden/other_project (marked during PST ingestion)
    email_query = db.query(EmailMessage)

    # Filter out spam/hidden/other_project emails
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

    if project_id:
        email_query = email_query.filter(EmailMessage.project_id == project_id)
    elif case_id:
        email_query = email_query.filter(EmailMessage.case_id == case_id)
    else:
        # Get from user's projects
        projects = db.query(Project).filter(Project.owner_user_id == user_id).all()
        project_ids = [str(p.id) for p in projects]
        if project_ids:
            email_query = email_query.filter(EmailMessage.project_id.in_(project_ids))

    emails = email_query.order_by(EmailMessage.date_sent.desc()).all()

    for email in emails:
        # Build text content
        content = (email.body_text or email.body_preview or "")[:1000]
        date_str = (
            email.date_sent.strftime("%Y-%m-%d") if email.date_sent else "Unknown"
        )

        text_part = (
            f"[EMAIL {email.id}]\n"
            f"Date: {date_str}\n"
            f"From: {email.sender_name or email.sender_email or 'Unknown'}\n"
            f"To: {email.recipients_to or 'Unknown'}\n"
            f"Subject: {email.subject or 'No subject'}\n"
            f"Content: {content[:500]}\n"
            f"---"
        )
        context_parts.append(text_part)

        # Build structured item for intelligent retrieval
        evidence_items.append(
            {
                "id": str(email.id),
                "type": "EMAIL",
                "date": date_str,
                "sender": email.sender_name or email.sender_email or "Unknown",
                "recipients": email.recipients_to or [],
                "subject": email.subject or "No subject",
                "content": content,
                "text": f"Email from {email.sender_name or email.sender_email} on {date_str}: {email.subject}. {content}",
            }
        )

    # Get evidence items linked to project/case, plus workspace-scoped documents (if any).
    evidence_query = db.query(EvidenceItem).filter(
        or_(
            EvidenceItem.meta.is_(None),
            EvidenceItem.meta.op("->>")("spam").is_(None),
            EvidenceItem.meta.op("->")("spam").op("->>")("is_hidden") != "true",
        )
    )
    if project_id:
        evidence_query = evidence_query.filter(EvidenceItem.project_id == project_id)
    elif case_id:
        evidence_query = evidence_query.filter(EvidenceItem.case_id == case_id)

    project_case_docs = evidence_query.order_by(EvidenceItem.created_at.desc()).all()

    workspace_docs: list[EvidenceItem] = []
    if workspace_uuid:
        try:
            workspace_docs = (
                db.query(EvidenceItem)
                .filter(
                    EvidenceItem.meta.op("->>")("workspace_id") == str(workspace_uuid)
                )
                .order_by(EvidenceItem.created_at.desc())
                .limit(500)
                .all()
            )
        except Exception:
            workspace_docs = []

    # Deduplicate by id (workspace docs are stored in EvidenceItem too).
    combined_docs: list[EvidenceItem] = []
    seen_ids: set[str] = set()
    for doc in list(project_case_docs) + list(workspace_docs):
        doc_id = str(getattr(doc, "id", "") or "")
        if not doc_id or doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        combined_docs.append(doc)

    for evidence in combined_docs:
        content = evidence.extracted_text or evidence.description or ""
        if content:
            meta = evidence.meta if isinstance(evidence.meta, dict) else {}
            is_workspace_doc = (
                bool(workspace_uuid)
                and isinstance(meta, dict)
                and meta.get("workspace_id") == str(workspace_uuid)
                and getattr(evidence, "project_id", None) is None
                and getattr(evidence, "case_id", None) is None
            )
            ev_type = "WORKSPACE_DOCUMENT" if is_workspace_doc else "EVIDENCE"
            label = "WORKSPACE_DOC" if is_workspace_doc else "EVIDENCE"
            text_part = (
                f"[{label} {evidence.id}]\n"
                f"Filename: {evidence.filename or 'Unknown'}\n"
                f"Type: {evidence.evidence_type or 'Unknown'}\n"
                f"Content: {content[:500]}\n"
                f"---"
            )
            context_parts.append(text_part)

            evidence_items.append(
                {
                    "id": str(evidence.id),
                    "type": ev_type,
                    "filename": evidence.filename or "Unknown",
                    "content": content[:1500],
                    "text": f"Evidence {evidence.filename}: {content[:1500]}",
                    **(
                        {"workspace_id": str(workspace_uuid)}
                        if is_workspace_doc and workspace_uuid
                        else {}
                    ),
                }
            )

    if intro_parts:
        context_parts = intro_parts + context_parts
    if intro_items:
        evidence_items = intro_items + evidence_items

    return EvidenceContext(text="\n\n".join(context_parts), items=evidence_items)


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/start", response_model=StartAnalysisResponse)
async def start_vericase_analysis(
    request: StartAnalysisRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Start a new VeriCase analysis session.

    This initiates the planning phase and returns a session ID.
    The client should poll for status and approve the plan when ready.
    """
    session_id = str(uuid.uuid4())

    session = AnalysisSession(
        id=session_id,
        user_id=str(user.id),
        project_id=request.project_id,
        case_id=request.case_id,
        topic=request.topic,
        scope=request.scope,
        focus_areas=request.focus_areas,
        status=AnalysisStatus.PENDING,
        use_deliberative_planning=request.use_deliberative_planning,
    )

    save_session(session)

    # Capture values needed for background task
    user_id = str(user.id)
    project_id = request.project_id
    case_id = request.case_id
    focus_areas = request.focus_areas

    # Start planning in background with fresh DB session
    def sync_run_planning():
        import asyncio
        from .db import SessionLocal

        async def run_planning():
            # Maximum time allowed for the entire planning phase (10 minutes).
            # Deliberative planning can be slow but should never hang indefinitely.
            PLANNING_TIMEOUT_SECONDS = 600

            task_db = None
            try:
                # Step 1: Signal that the background task has started
                session.status = AnalysisStatus.PLANNING
                session.planning_step = "gathering_evidence"
                session.updated_at = datetime.now(timezone.utc)
                save_session(session)

                task_db = SessionLocal()
                evidence_context = await build_evidence_context(
                    task_db, user_id, project_id, case_id
                )

                # Step 2: Evidence gathered, now configuring agents
                session.planning_step = "configuring_agents"
                session.updated_at = datetime.now(timezone.utc)
                save_session(session)

                master = VeriCaseOrchestrator(task_db, session)

                # Step 3: Agents ready, formulating strategy
                session.planning_step = "formulating_strategy"
                session.updated_at = datetime.now(timezone.utc)
                save_session(session)

                try:
                    await asyncio.wait_for(
                        master.run_planning_phase(evidence_context, focus_areas),
                        timeout=PLANNING_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"Planning phase timed out after {PLANNING_TIMEOUT_SECONDS}s. "
                        "This may indicate an AI provider connectivity issue. "
                        "Please check your API key configuration and try again."
                    )

            except Exception as e:
                logger.exception(f"Planning failed for session {session.id}: {e}")
                session.status = AnalysisStatus.FAILED
                session.error_message = str(e)
            finally:
                if task_db is not None:
                    task_db.close()
                save_session(session)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_planning())
        except Exception as e:
            logger.exception(f"Background planning task crashed for session {session.id}: {e}")
            session.status = AnalysisStatus.FAILED
            session.error_message = f"Background task error: {e}"
            save_session(session)
        finally:
            loop.close()

    background_tasks.add_task(sync_run_planning)

    return StartAnalysisResponse(
        session_id=session_id,
        status="pending",
        message="VeriCase analysis started. Poll /status for updates.",
    )


@router.get("/status/{session_id}", response_model=AnalysisStatusResponse)
async def get_analysis_status(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """Get the current status of a VeriCase analysis session"""

    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized to view this session")

    # Calculate progress - count questions with completed status
    total_questions = len(session.plan.questions) if session.plan else 0
    completed_questions = sum(
        1 for q in (session.plan.questions if session.plan else [])
        if q.status == "completed"
    )
    # Fallback to question_analyses count if status tracking not used
    if completed_questions == 0 and session.question_analyses:
        completed_questions = len(session.question_analyses)
    
    progress = {
        "total_questions": total_questions,
        "completed_questions": completed_questions,
        "current_phase": session.status.value,
    }

    return AnalysisStatusResponse(
        session_id=session_id,
        status=session.status.value,
        scope=session.scope.value,
        plan=session.plan,
        progress=progress,
        timeline_status=session.timeline_result.get("status", "pending"),
        delay_status=session.delay_result.get("status", "pending"),
        research_status=(
            "completed"
            if len(session.question_analyses)
            == (len(session.plan.questions) if session.plan else 0)
            else "pending"
        ),
        final_report=session.final_report,
        executive_summary=session.executive_summary,
        key_themes=session.key_themes,
        processing_time_seconds=session.processing_time_seconds,
        report_available=session.final_report is not None,
        error_message=session.error_message,
        models_used=list(session.models_used.values()),
        # Include deliberation events for chain-of-thought visibility
        deliberation_events=session.deliberation_events[-20:] if session.deliberation_events else [],
        planning_step=session.planning_step,
    )


@router.get("/deliberation-stream/{session_id}")
async def stream_deliberation_events(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """
    Server-Sent Events (SSE) endpoint for real-time deliberation progress.

    Streams DeliberationEvents during the planning phase to show:
    - Corpus scan progress
    - Entity discovery
    - Issue identification
    - Research angle deliberation with visible reasoning
    - Plan synthesis

    Connect to this endpoint immediately after starting analysis
    to receive real-time chain-of-thought updates.
    """
    from fastapi.responses import StreamingResponse

    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized to view this session")

    async def event_generator():
        """Generate SSE events from session deliberation state."""
        import asyncio
        import json

        last_event_count = 0
        max_wait_iterations = 600  # 10 minutes max (at 1s intervals)
        iteration = 0

        while iteration < max_wait_iterations:
            # Reload session to get latest events
            current_session = load_session(session_id)
            if not current_session:
                yield f"data: {json.dumps({'phase': 'error', 'finding': 'Session not found'})}\n\n"
                break

            events = current_session.deliberation_events or []

            # Send any new events
            if len(events) > last_event_count:
                for event in events[last_event_count:]:
                    yield f"data: {json.dumps(event)}\n\n"
                last_event_count = len(events)

            # Check if planning is complete
            if current_session.status not in (
                AnalysisStatus.PENDING,
                AnalysisStatus.PLANNING,
                AnalysisStatus.DELIBERATING,
            ):
                # Send final event
                yield f"data: {json.dumps({'phase': 'complete', 'finding': 'Planning complete', 'status': current_session.status.value})}\n\n"
                break

            await asyncio.sleep(1)  # Poll every second
            iteration += 1

        # Timeout message
        if iteration >= max_wait_iterations:
            yield f"data: {json.dumps({'phase': 'timeout', 'finding': 'Stream timeout - check status endpoint'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/approve-plan")
async def approve_analysis_plan(
    request: ApprovePlanRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Approve or modify the research plan (Human-in-the-Loop).

    If approved, the research phase begins.
    If modifications are provided, the plan is regenerated.
    """
    session = load_session(request.session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Normalize status if plan exists but status is still pending
    if session.plan and session.status in {
        AnalysisStatus.PENDING,
        AnalysisStatus.PLANNING,
    }:
        session.status = AnalysisStatus.AWAITING_APPROVAL
        save_session(session)

    if session.status != AnalysisStatus.AWAITING_APPROVAL:
        raise HTTPException(
            400, f"Session not awaiting approval. Status: {session.status}"
        )

    if not request.approved:
        # User wants modifications - regenerate plan
        if request.modifications:
            session.topic = f"{session.topic}\n\nUser feedback: {request.modifications}"

        session.status = AnalysisStatus.PENDING
        save_session(session)

        user_id = str(user.id)
        project_id = session.project_id
        case_id = session.case_id

        def sync_regenerate_plan():
            import asyncio
            from .db import SessionLocal

            async def regenerate_plan():
                task_db = SessionLocal()
                try:
                    evidence_context = await build_evidence_context(
                        task_db, user_id, project_id, case_id
                    )
                    master = VeriCaseOrchestrator(task_db, session)
                    await master.run_planning_phase(evidence_context)
                except Exception as e:
                    logger.exception(f"Plan regeneration failed: {e}")
                    session.status = AnalysisStatus.FAILED
                    session.error_message = str(e)
                finally:
                    task_db.close()
                    save_session(session)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(regenerate_plan())
            finally:
                loop.close()

        background_tasks.add_task(sync_regenerate_plan)

        return {
            "status": "regenerating",
            "message": "Plan is being regenerated with your feedback",
        }

    # Approved - start research
    start_time = datetime.now(timezone.utc)

    session.status = AnalysisStatus.RESEARCHING
    session.updated_at = datetime.now(timezone.utc)
    save_session(session)

    user_id = str(user.id)
    project_id = session.project_id
    case_id = session.case_id

    def sync_run_research():
        import asyncio
        from .db import SessionLocal

        async def run_research():
            task_db = SessionLocal()
            try:
                evidence_context = await build_evidence_context(
                    task_db, user_id, project_id, case_id
                )

                master = VeriCaseOrchestrator(task_db, session)
                await master.run_research_phase(evidence_context)

                # Run timeline and delay analysis for FULL scope
                if session.scope == AnalysisScope.FULL:
                    await asyncio.gather(
                        master.run_timeline_analysis(evidence_context),
                        master.run_delay_analysis(evidence_context),
                        return_exceptions=True,
                    )

                await master.run_synthesis_phase(evidence_context)

                # Run validation
                await master.run_validation_phase(evidence_context)

                session.processing_time_seconds = (
                    datetime.now(timezone.utc) - start_time
                ).total_seconds()
                session.status = AnalysisStatus.COMPLETED
                session.completed_at = datetime.now(timezone.utc)

            except Exception as e:
                logger.exception(f"Research failed: {e}")
                session.status = AnalysisStatus.FAILED
                session.error_message = str(e)
            finally:
                task_db.close()
                save_session(session)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_research())
        finally:
            loop.close()

    background_tasks.add_task(sync_run_research)

    return {"status": "researching", "message": "VeriCase analysis phase started"}


@router.get("/report/{session_id}", response_model=AnalysisReportResponse)
async def get_analysis_report(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
):
    """Get the full VeriCase analysis report."""
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    if session.status != AnalysisStatus.COMPLETED:
        raise HTTPException(
            400, f"Analysis not complete. Status: {session.status.value}"
        )

    return AnalysisReportResponse(
        session_id=session_id,
        case_id=session.case_id,
        project_id=session.project_id,
        topic=session.topic,
        executive_summary=session.executive_summary,
        final_report=session.final_report,
        key_findings=session.key_findings,
        key_themes=session.key_themes,
        recommendations=session.recommendations,
        timeline_summary=session.timeline_result,
        delay_summary=session.delay_result,
        research_summary={
            "questions_analyzed": len(session.question_analyses),
            "questions_completed": sum(
                1 for q in (session.plan.questions if session.plan else [])
                if q.status == "completed"
            ),
        },
        evidence_used=session.evidence_used,  # Include evidence/attachments referenced
        cited_evidence=session.cited_evidence,  # Numbered citations for appendix
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
    
    Returns either preview metadata or a download URL for the evidence.
    Citation numbers correspond to the superscript numbers in the report.
    """
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Find the citation
    citation = next(
        (c for c in session.cited_evidence if c.citation_number == citation_number),
        None,
    )
    if not citation:
        raise HTTPException(404, f"Citation {citation_number} not found")

    # Try to find the actual evidence/attachment
    from .models import EmailAttachment, EvidenceItem

    evidence_item = None
    attachment = None

    # Check if it's an attachment ID or evidence item ID
    if citation.evidence_id:
        attachment = db.query(EmailAttachment).filter(
            EmailAttachment.id == citation.evidence_id
        ).first()
        if not attachment:
            # Try as evidence item ID
            evidence_item = db.query(EvidenceItem).filter(
                EvidenceItem.id == citation.evidence_id
            ).first()

    response_data = {
        "citation_number": citation.citation_number,
        "evidence_id": citation.evidence_id,
        "evidence_type": citation.evidence_type,
        "title": citation.title,
        "date": citation.date,
        "excerpt": citation.excerpt,
    }

    if download and (attachment or evidence_item):
        if attachment and attachment.s3_key:
            try:
                from .storage import presign_get
                url = presign_get(attachment.s3_key, expires=3600)
                response_data["download_url"] = url
                response_data["filename"] = attachment.filename
            except Exception as e:
                logger.warning(f"Could not generate download URL: {e}")
        elif evidence_item:
            content = evidence_item.extracted_text or evidence_item.description or ""
            response_data["content_preview"] = content[:2000] if content else None

    return response_data


@router.get("/{session_id}/evidence-bundle")
async def download_evidence_bundle(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get a manifest of all cited evidence with download URLs.
    
    Returns a list of all evidence items cited in the report with
    pre-signed URLs for downloading. Client can use this to create
    a ZIP bundle of all evidence.
    """
    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    if not session.cited_evidence:
        return {
            "session_id": session_id,
            "topic": session.topic,
            "evidence_count": 0,
            "items": [],
            "message": "No evidence was cited in this analysis",
        }

    from .models import EmailAttachment, EvidenceItem
    from .aws_services import get_aws_services
    aws = get_aws_services()

    items = []
    for citation in session.cited_evidence:
        item_data = {
            "citation_number": citation.citation_number,
            "evidence_id": citation.evidence_id,
            "evidence_type": citation.evidence_type,
            "title": citation.title,
            "date": citation.date,
            "download_url": None,
            "filename": None,
            "can_download": False,
        }

        # Try to find downloadable content
        if citation.evidence_id:
            attachment = db.query(EmailAttachment).filter(
                EmailAttachment.id == citation.evidence_id
            ).first()
            if attachment and attachment.s3_key:
                try:
                    from .storage import presign_get
                    item_data["download_url"] = presign_get(
                        attachment.s3_key, expires=3600
                    )
                    item_data["filename"] = attachment.filename
                    item_data["can_download"] = True
                except Exception as e:
                    logger.warning(f"Could not generate URL for {citation.evidence_id}: {e}")

        items.append(item_data)

    return {
        "session_id": session_id,
        "topic": session.topic,
        "evidence_count": len(items),
        "downloadable_count": sum(1 for i in items if i["can_download"]),
        "items": items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.delete("/{session_id}")
async def cancel_analysis(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """Cancel a VeriCase analysis session"""

    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    session.status = AnalysisStatus.CANCELLED
    save_session(session)

    return {"status": "cancelled", "message": "VeriCase analysis session cancelled"}


@router.get("/sessions")
async def list_analysis_sessions(
    user: Annotated[User, Depends(current_user)], limit: int = 20
):
    """List user's VeriCase analysis sessions"""

    user_sessions = [
        {
            "id": s.id,
            "topic": s.topic,
            "scope": s.scope.value,
            "status": s.status.value,
            "created_at": s.created_at.isoformat(),
            "has_report": s.final_report is not None,
        }
        for s in (
            list(_analysis_sessions.values())
            + [
                load_session(
                    key.decode().split(":")[-1]
                    if isinstance(key, (bytes, bytearray))
                    else str(key).split(":")[-1]
                )
                for key in (
                    _get_redis().scan_iter("vericase:session:*") if _get_redis() else []
                )
            ]
        )
        if s and s.user_id == str(user.id)
    ]

    # Sort by created_at descending
    user_sessions.sort(key=lambda x: x["created_at"], reverse=True)

    return {"sessions": user_sessions[:limit]}
