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

from .models import User, EmailMessage, Project, EvidenceItem, ChronologyItem
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

# Flagship VeriCase Analysis API
router = APIRouter(prefix="/api/vericase-analysis", tags=["vericase-analysis"])

# =============================================================================
# Data Models
# =============================================================================


class AnalysisStatus(str, Enum):
    """Status of a VeriCase analysis session."""

    PENDING = "pending"
    PLANNING = "planning"
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

    # Metadata
    total_sources_analyzed: int = 0
    processing_time_seconds: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None

    # Model tracking for transparency
    models_used: dict[str, str] = Field(default_factory=dict)


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
    if session_id in _analysis_sessions:
        return _analysis_sessions[session_id]

    try:
        redis_client = _get_redis()
        if redis_client:
            data = redis_client.get(f"vericase:session:{session_id}")
            if data:
                session = AnalysisSession.model_validate_json(data)
                _analysis_sessions[session_id] = session
                return session
    except Exception as e:  # pragma: no cover - non-critical
        logger.warning(f"Failed to load session from Redis: {e}")

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
    ) -> tuple[str, list[str], list[dict[str, Any]]]:
        """
        Synthesize all findings into a comprehensive report.

        Returns:
            tuple of (report_text, themes, evidence_used)
        """

        # First, identify themes
        themes = await self._identify_themes(plan, question_analyses)

        # Generate report sections
        sections = await self._generate_sections(plan, question_analyses, themes)

        # Collect evidence used from question analyses
        evidence_used = self._collect_evidence_used(question_analyses, evidence_items)

        # Assemble final report with evidence references
        report = self._assemble_report(plan, sections, themes, evidence_used)

        return report, themes, evidence_used

    def _collect_evidence_used(
        self,
        question_analyses: dict[str, dict[str, Any]],
        evidence_items: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Collect all evidence items that were referenced during analysis.
        Deduplicates and enriches with metadata.
        """
        evidence_map: dict[str, dict[str, Any]] = {}

        # Collect evidence IDs referenced in question analyses
        for q_id, analysis in question_analyses.items():
            # Check for cited sources
            sources = analysis.get("sources", [])
            for source in sources:
                if isinstance(source, dict):
                    source_id = source.get("id") or source.get("source_id")
                    if source_id and source_id not in evidence_map:
                        evidence_map[source_id] = {
                            "id": source_id,
                            "type": source.get("type", "evidence"),
                            "title": source.get("title")
                            or source.get("name", "Unknown"),
                            "date": source.get("date"),
                            "relevance": source.get("relevance", "cited"),
                        }

            # Check for evidence_ids field
            evidence_ids = analysis.get("evidence_ids", [])
            for eid in evidence_ids:
                if eid and eid not in evidence_map:
                    evidence_map[eid] = {
                        "id": eid,
                        "type": "evidence",
                        "relevance": "analyzed",
                    }

        # Enrich with full evidence item data if available
        if evidence_items:
            for item in evidence_items:
                item_id = item.get("id") or item.get("evidence_id")
                if item_id:
                    if item_id in evidence_map:
                        # Enrich existing entry
                        evidence_map[item_id].update(
                            {
                                "title": item.get("title")
                                or item.get("name")
                                or evidence_map[item_id].get("title"),
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
                    elif len(evidence_map) < 100:  # Add primary evidence up to limit
                        evidence_map[item_id] = {
                            "id": item_id,
                            "type": item.get("type")
                            or item.get("evidence_type", "evidence"),
                            "title": item.get("title") or item.get("name", "Unknown"),
                            "date": item.get("date") or item.get("created_at"),
                            "filename": item.get("filename") or item.get("file_name"),
                            "attachment_type": item.get("attachment_type")
                            or item.get("mime_type"),
                            "relevance": "primary",
                        }

        return list(evidence_map.values())

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
            return [str(t.get("title", "")) for t in themes_data]
        except Exception:
            return plan.key_angles  # Fallback to original angles

    async def _generate_sections(
        self, plan: ResearchPlan, analyses: dict[str, dict[str, Any]], themes: list[str]
    ) -> dict[str, str]:
        """Generate report sections for each theme"""

        all_findings = "\n\n".join(
            [
                f"## {q.question}\n{analyses.get(q.id, {}).get('findings', 'No findings')}"
                for q in plan.questions
            ]
        )

        sections: dict[str, str] = {}

        # Generate sections in parallel
        async def generate_section(theme: str) -> tuple[str, str]:
            prompt = f"""Write a detailed report section for the theme: "{theme}"

RESEARCH TOPIC: {plan.topic}

ALL RESEARCH FINDINGS:
{all_findings}

Write a comprehensive section (500-1000 words) that:
1. Introduces the theme and its significance
2. Presents relevant findings with citations
3. Analyzes implications
4. Notes any gaps or uncertainties

Write in professional legal report style."""

            content = await self._call_llm(
                prompt, self.SYSTEM_PROMPT, use_powerful=True
            )
            return theme, content

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

    def _assemble_report(
        self,
        plan: ResearchPlan,
        sections: dict[str, str],
        themes: list[str],
        evidence_used: list[dict[str, Any]] | None = None,
    ) -> str:
        """Assemble the final report with evidence references"""

        report_parts = [
            f"# VeriCase Analysis Report: {plan.topic}",
            f"\n*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n",
            "---\n",
            "## Executive Summary\n",
            f"{plan.problem_statement}\n",
            "\n### Key Research Angles\n",
            "\n".join(f"- {angle}" for angle in plan.key_angles),
            "\n---\n",
        ]

        # Add themed sections
        for theme in themes:
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

        # Add Evidence & Attachments Referenced section
        if evidence_used:
            report_parts.append("\n---\n")
            report_parts.append("\n## Evidence & Attachments Referenced\n")
            report_parts.append(
                f"\nThis analysis referenced {len(evidence_used)} evidence items:\n\n"
            )

            # Group by type
            by_type: dict[str, list[dict[str, Any]]] = {}
            for item in evidence_used:
                item_type = item.get("type", "Other")
                if item_type not in by_type:
                    by_type[item_type] = []
                by_type[item_type].append(item)

            for evidence_type, items in sorted(by_type.items()):
                type_label = evidence_type.replace("_", " ").title()
                report_parts.append(f"\n### {type_label} ({len(items)})\n\n")
                for item in items:
                    title = (
                        item.get("title")
                        or item.get("filename")
                        or item.get("id", "Unknown")
                    )
                    date = item.get("date", "")
                    if date:
                        if hasattr(date, "strftime"):
                            date = f" ({date.strftime('%Y-%m-%d')})"
                        elif isinstance(date, str) and len(date) >= 10:
                            date = f" ({date[:10]})"
                        else:
                            date = ""
                    filename = item.get("filename", "")
                    if filename:
                        filename = f" - `{filename}`"
                    report_parts.append(f"- **{title}**{date}{filename}\n")

            report_parts.append("\n---\n")
            report_parts.append(
                "\n*Note: This evidence listing reflects materials analyzed during the research process. "
                "Original documents should be consulted for verification.*\n"
            )

        return "\n".join(report_parts)


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
        """Phase 1: Create research plan"""
        self.session.status = AnalysisStatus.PLANNING
        self.session.updated_at = datetime.now(timezone.utc)

        plan = await self.planner.create_plan(
            self.session.topic,
            evidence_context.text,
            focus_areas,
        )

        self.session.plan = plan
        self.session.status = AnalysisStatus.AWAITING_APPROVAL
        self.session.updated_at = datetime.now(timezone.utc)

        return plan

    async def run_research_phase(self, evidence_context: EvidenceContext) -> None:
        """
        Phase 2: Execute research DAG with intelligent evidence retrieval.

        Uses multi-vector semantic search, cross-encoder reranking, and MMR for each question.
        """
        if not self.session.plan:
            raise ValueError("No plan available")

        self.session.status = AnalysisStatus.RESEARCHING
        self.session.updated_at = datetime.now(timezone.utc)

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

            self.session.updated_at = datetime.now(timezone.utc)

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

        report, themes, evidence_used = await self.synthesizer.synthesize(
            self.session.plan, self.session.question_analyses, evidence_items
        )

        self.session.final_report = report
        self.session.key_themes = themes
        self.session.evidence_used = evidence_used  # Track which evidence was used
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

    # Get evidence items (documents/attachments linked to project)
    evidence_query = db.query(EvidenceItem).filter(
        or_(
            EvidenceItem.meta.is_(None),
            EvidenceItem.meta.op("->>")("spam").is_(None),
            EvidenceItem.meta.op("->")("spam").op("->>")("is_hidden") != "true",
        )
    )
    if project_id:
        evidence_query = evidence_query.filter(EvidenceItem.project_id == project_id)

    evidence_docs = evidence_query.all()

    for evidence in evidence_docs:
        content = evidence.extracted_text or evidence.description or ""
        if content:
            text_part = (
                f"[EVIDENCE {evidence.id}]\n"
                f"Filename: {evidence.filename or 'Unknown'}\n"
                f"Type: {evidence.evidence_type or 'Unknown'}\n"
                f"Content: {content[:500]}\n"
                f"---"
            )
            context_parts.append(text_part)

            evidence_items.append(
                {
                    "id": str(evidence.id),
                    "type": "EVIDENCE",
                    "filename": evidence.filename or "Unknown",
                    "content": content[:1500],
                    "text": f"Evidence {evidence.filename}: {content[:1500]}",
                }
            )

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
            task_db = SessionLocal()
            try:
                evidence_context = await build_evidence_context(
                    task_db, user_id, project_id, case_id
                )

                master = VeriCaseOrchestrator(task_db, session)
                await master.run_planning_phase(evidence_context, focus_areas)

            except Exception as e:
                logger.exception(f"Planning failed: {e}")
                session.status = AnalysisStatus.FAILED
                session.error_message = str(e)
            finally:
                task_db.close()
                save_session(session)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_planning())
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

    # Calculate progress
    progress = {
        "total_questions": len(session.plan.questions) if session.plan else 0,
        "completed_questions": len(session.question_analyses),
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
        research_summary={"questions_analyzed": len(session.question_analyses)},
        evidence_used=session.evidence_used,  # Include evidence/attachments referenced
        validation_score=session.validation_result.get("overall_score", 0.0),
        validation_passed=session.validation_passed,
        models_used=list(session.models_used.values()),
        total_duration_seconds=session.processing_time_seconds,
    )


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
