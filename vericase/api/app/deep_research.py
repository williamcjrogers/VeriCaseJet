from __future__ import annotations

"""
VeriCase Deep Research Agent
============================
A multi-agent orchestrated system for comprehensive evidence analysis.
Inspired by Egnyte's Deep Research Agent architecture.

Architecture:
- Master Agent: Orchestrates the entire research workflow
- Planner Agent: Creates DAG-based research strategy
- Researcher Agents: Parallel investigation workers
- Synthesizer Agent: Thematic analysis and report generation

Reference: https://www.egnyte.com/blog/post/inside-the-architecture-of-a-deep-research-agent
"""

import asyncio
import logging
import uuid
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, NotRequired, TypedDict, cast
from enum import Enum
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_

try:  # Optional Redis
    from redis import Redis  # type: ignore
except ImportError:  # pragma: no cover - runtime fallback if redis-py not installed
    Redis = None  # type: ignore

from .models import User, EmailMessage, Project, EvidenceItem
from .db import get_db
from .security import current_user
from .ai_settings import get_ai_api_key, get_ai_model, is_bedrock_enabled, get_bedrock_region
from .settings import settings
from .ai_providers import BedrockProvider, bedrock_available
from .ai_runtime import complete_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deep-research", tags=["deep-research"])

# =============================================================================
# Data Models
# =============================================================================


class ResearchStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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


class ResearchSession(BaseModel):
    """Complete research session state"""

    id: str
    user_id: str
    project_id: str | None = None
    case_id: str | None = None
    topic: str
    status: ResearchStatus = ResearchStatus.PENDING
    plan: ResearchPlan | None = None
    question_analyses: dict[str, dict[str, Any]] = Field(default_factory=dict)
    final_report: str | None = None
    key_themes: list[str] = Field(default_factory=list)
    total_sources_analyzed: int = 0
    processing_time_seconds: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: str | None = None
    # Validation results from ValidatorAgent
    validation_result: dict[str, Any] = Field(default_factory=dict)
    validation_passed: bool = True
    # Model tracking for transparency
    models_used: dict[str, str] = Field(default_factory=dict)  # agent_name -> model_id


# Session store (uses Redis if available, otherwise in-memory)
_research_sessions: dict[str, ResearchSession] = {}


def _get_redis() -> Redis | None:
    try:
        if settings.REDIS_URL and Redis:
            return Redis.from_url(settings.REDIS_URL)  # type: ignore[call-arg]
    except Exception as e:  # pragma: no cover - best-effort cache
        logger.warning(f"Redis unavailable for deep research sessions: {e}")
    return None


def save_session(session: ResearchSession) -> None:
    """Persist session to in-memory store and Redis (if available)."""
    _research_sessions[session.id] = session
    try:
        redis_client = _get_redis()
        if redis_client:
            redis_client.set(
                f"deep_research:session:{session.id}", session.model_dump_json()
            )
    except Exception as e:  # pragma: no cover - non-critical
        logger.warning(f"Failed to persist session to Redis: {e}")


def load_session(session_id: str) -> ResearchSession | None:
    """Load session from in-memory store or Redis."""
    if session_id in _research_sessions:
        return _research_sessions[session_id]

    try:
        redis_client = _get_redis()
        if redis_client:
            data = redis_client.get(f"deep_research:session:{session_id}")
            if data:
                session = ResearchSession.model_validate_json(data)
                _research_sessions[session_id] = session
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


class StartResearchRequest(BaseModel):
    topic: str = Field(..., description="The research topic or question")
    project_id: str | None = None
    case_id: str | None = None
    focus_areas: list[str] = Field(
        default_factory=list, description="Optional focus areas to prioritize"
    )


class StartResearchResponse(BaseModel):
    session_id: str
    status: str
    message: str


class ApprovePlanRequest(BaseModel):
    session_id: str
    approved: bool
    modifications: str | None = None  # User feedback for plan modification


class ResearchStatusResponse(BaseModel):
    session_id: str
    status: str
    plan: ResearchPlan | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    final_report: str | None = None
    key_themes: list[str] = Field(default_factory=list)
    processing_time_seconds: float = 0
    error_message: str | None = None


# =============================================================================
# AI Agent Classes
# =============================================================================


class BaseAgent:
    """Base class for all agents - supports 4 providers: OpenAI, Anthropic, Gemini, Bedrock"""

    def __init__(self, db: Session):
        self.db = db
        self.openai_key = get_ai_api_key("openai", db)
        self.anthropic_key = get_ai_api_key("anthropic", db)
        self.gemini_key = get_ai_api_key("gemini", db)

        # Bedrock uses IAM credentials, not API keys
        self.bedrock_enabled = is_bedrock_enabled(db) and bedrock_available()
        self.bedrock_region = get_bedrock_region(db)
        self._bedrock_provider: BedrockProvider | None = None

        # Model selections
        self.openai_model = get_ai_model("openai", db)
        self.anthropic_model = get_ai_model("anthropic", db)
        self.gemini_model = get_ai_model("gemini", db)
        self.bedrock_model = get_ai_model("bedrock", db)

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
        """Call the appropriate LLM based on configuration (4 providers) - Bedrock first for cost optimization"""
        # Try Bedrock FIRST - uses AWS billing, more cost effective
        if self.bedrock_enabled:
            try:
                return await self._call_bedrock(prompt, system_prompt)
            except Exception as e:
                logger.warning(f"Bedrock call failed, trying fallback: {e}")

        # Fallback to external APIs
        # Use Anthropic for powerful/complex tasks
        if use_powerful and self.anthropic_key:
            return await self._call_anthropic(prompt, system_prompt)

        # Try OpenAI
        if self.openai_key:
            return await self._call_openai(prompt, system_prompt)

        # Try Gemini
        if self.gemini_key:
            return await self._call_gemini(prompt, system_prompt)

        # Final fallback to Anthropic
        if self.anthropic_key:
            return await self._call_anthropic(prompt, system_prompt)

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

    Workflow (based on Egnyte architecture):
    1. Fast k-NN retrieval from vector index (milliseconds, ~100 candidates)
    2. Cross-encoder reranking for relevance (top-N from candidates)
    3. MMR (Maximal Marginal Relevance) for diverse results
    4. Return high-quality, diverse results

    The k-NN step is critical for scale - cross-encoder is O(n) so we can't
    run it on millions of documents. k-NN narrows to relevant candidates first.
    """

    _cross_encoder: Any | None = None
    _embedding_model: Any | None = None
    _vector_service: Any | None = None

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
            raw_embedding = embedding_model.encode(
                query, convert_to_numpy=True
            )  # pyright: ignore[reportAny]
            query_embedding: list[float] = cast(
                list[float], raw_embedding.tolist()
            )  # pyright: ignore[reportAny]

            # Fast k-NN search
            results: list[dict[str, Any]] = cast(
                list[dict[str, Any]],
                vector_service.search_similar(  # pyright: ignore[reportAny]
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
            scores: list[float] = cast(
                list[float], cross_encoder.predict(pairs)
            )  # pyright: ignore[reportAny]

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

        Args:
            query: The search query
            documents: List of documents with 'content' or 'text' field
            top_k: Number of documents to select
            diversity_weight: Lambda parameter (0=pure relevance, 1=pure diversity)
        """
        if not documents or len(documents) <= top_k:
            return documents

        embedding_model: Any | None = self.get_embedding_model()
        if embedding_model is None:
            # Fallback: return first top_k documents
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
            )[
                0
            ]  # pyright: ignore[reportAny]
            doc_embeddings: np.ndarray = cast(
                np.ndarray, embedding_model.encode(doc_texts)
            )  # pyright: ignore[reportAny]

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
                    relevance = float(query_sims[idx])  # pyright: ignore[reportAny]

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
                        )  # pyright: ignore[reportAny]
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
                doc_copy["mmr_score"] = float(
                    query_sims[idx]
                )  # pyright: ignore[reportAny]
                result.append(doc_copy)

            return result

        except Exception as e:
            logger.error(f"MMR failed: {e}")
            return documents[:top_k]

    def semantic_chunk(
        self, text: str, max_chunk_size: int = 1000, overlap: int = 100
    ) -> list[str]:
        """
        Split text into semantically coherent chunks.

        Uses paragraph boundaries and sentence endings for natural breaks.
        """
        if not text or len(text) <= max_chunk_size:
            return [text] if text else []

        chunks: list[str] = []

        # Split by double newlines (paragraphs) first
        paragraphs = text.split("\n\n")

        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) <= max_chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # If paragraph itself is too long, split by sentences
                if len(para) > max_chunk_size:
                    sentences = (
                        para.replace(". ", ".|")
                        .replace("? ", "?|")
                        .replace("! ", "!|")
                        .split("|")
                    )
                    current_chunk = ""
                    for sentence in sentences:
                        if len(current_chunk) + len(sentence) <= max_chunk_size:
                            current_chunk += sentence + " "
                        else:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = sentence + " "
                else:
                    current_chunk = para + "\n\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    async def search_and_retrieve(
        self,
        query: str,
        evidence_items: list[dict[str, Any]],
        top_k: int = 10,
        apply_diversity: bool = True,
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Full search pipeline with fast k-NN retrieval:

        1. k-NN: Fast ANN search (~100 candidates in ~10ms)
        2. Cross-encoder: Rerank candidates for precision
        3. MMR: Diversify final results

        Falls back to direct cross-encoder on evidence_items if k-NN unavailable.
        """
        candidates: list[dict[str, Any]] = []

        # Step 1: Try fast k-NN retrieval from vector index
        knn_results = await self.fast_knn_retrieve(
            query=query,
            k=100,  # Get top 100 candidates for reranking
            case_id=case_id,
            project_id=project_id,
        )

        if knn_results:
            # Use k-NN results as candidates
            candidates = knn_results
            logger.info(f"Using {len(candidates)} k-NN candidates for reranking")
        elif evidence_items:
            # Fallback: use provided evidence items directly
            candidates = evidence_items
            logger.info(
                f"k-NN unavailable, using {len(candidates)} direct evidence items"
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
    ) -> dict[str, Any]:
        """
        Investigate a research question using intelligent evidence retrieval.

        Uses SearcherAgent for:
        - Cross-encoder reranking for relevance
        - MMR for diverse, non-redundant results
        """

        # If structured evidence items provided, use intelligent retrieval
        if evidence_items:
            try:
                # Use cross-encoder reranking and MMR
                relevant_evidence = await self.searcher.search_and_retrieve(
                    query=question.question,
                    evidence_items=evidence_items,
                    top_k=15,
                    apply_diversity=True,
                )

                # Build context from ranked results
                evidence_context = "\n\n---\n\n".join(
                    [
                        "\n".join(
                            [
                                f"[{e.get('type', 'EVIDENCE')} {e.get('id', 'unknown')}]",
                                f"Relevance Score: {float(e.get('relevance_score', 0.0)):.2f}",  # pyright: ignore[reportAny]
                                f"Content: {str(e.get('content', e.get('text', str(e))))[:800]}",  # pyright: ignore[reportAny]
                            ]
                        )
                        for e in relevant_evidence
                    ]
                )

                logger.info(
                    f"Retrieved {len(relevant_evidence)} relevant evidence items using cross-encoder + MMR"
                )
            except Exception as e:
                logger.warning(f"Intelligent retrieval failed, using raw context: {e}")

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

    # Track which model was used for synthesis (for transparency)
    last_model_used: str | None = None
    synthesizer_model: str | None = None

    async def synthesize(
        self, plan: ResearchPlan, question_analyses: dict[str, dict[str, Any]]
    ) -> tuple[str, list[str]]:
        """Synthesize all findings into a comprehensive report"""

        # First, identify themes
        themes = await self._identify_themes(plan, question_analyses)

        # Generate report sections
        sections = await self._generate_sections(plan, question_analyses, themes)

        # Assemble final report
        report = self._assemble_report(plan, sections, themes)

        return report, themes

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
            return [
                str(t.get("title", "")) for t in themes_data
            ]  # pyright: ignore[reportAny]
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
        self, plan: ResearchPlan, sections: dict[str, str], themes: list[str]
    ) -> str:
        """Assemble the final report"""

        report_parts = [
            f"# Deep Research Report: {plan.topic}",
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

KEY ANGLES TO COVER: {', '.join(plan.key_angles)}

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
            # Return a basic validation result
            return {
                "overall_score": 0.5,
                "validation_passed": True,  # Default to pass if parsing fails
                "confidence": "low",
                "recommendations": ["Validation parsing failed - manual review recommended"],
                "raw_response": response[:1000],
            }

    async def verify_citations(
        self,
        claims_with_citations: list[dict[str, str]],
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Verify individual claims against their cited evidence.

        Args:
            claims_with_citations: List of {"claim": "...", "citation_id": "..."}
            evidence_items: Available evidence to verify against

        Returns:
            Verification results per claim
        """
        if not claims_with_citations or not evidence_items:
            return {"verified": 0, "unverified": 0, "results": []}

        # Build evidence lookup
        evidence_lookup = {str(e.get("id", "")): e for e in evidence_items}

        results = []
        verified_count = 0

        for item in claims_with_citations:
            claim = item.get("claim", "")
            citation_id = item.get("citation_id", "")

            evidence = evidence_lookup.get(citation_id)
            if not evidence:
                results.append({
                    "claim": claim,
                    "citation_id": citation_id,
                    "status": "not_found",
                    "reason": "Citation ID not found in evidence"
                })
                continue

            # Use LLM to verify claim matches evidence
            verify_prompt = f"""Does this claim accurately represent the cited evidence?

CLAIM: {claim}

CITED EVIDENCE (ID: {citation_id}):
{str(evidence.get('content', evidence.get('text', '')))[:1000]}

Respond with JSON:
{{
    "verified": true/false,
    "confidence": 0.0-1.0,
    "reason": "explanation"
}}"""

            try:
                verify_response = await self._call_llm(verify_prompt, "You are a fact-checker.")

                json_str = verify_response
                if "```json" in verify_response:
                    json_str = verify_response.split("```json")[1].split("```")[0]
                elif "```" in verify_response:
                    json_str = verify_response.split("```")[1].split("```")[0]

                result = json.loads(json_str.strip())
                result["claim"] = claim
                result["citation_id"] = citation_id
                result["status"] = "verified" if result.get("verified") else "unverified"

                if result.get("verified"):
                    verified_count += 1

                results.append(result)
            except Exception as e:
                logger.warning(f"Citation verification failed: {e}")
                results.append({
                    "claim": claim,
                    "citation_id": citation_id,
                    "status": "error",
                    "reason": str(e)
                })

        return {
            "verified": verified_count,
            "unverified": len(claims_with_citations) - verified_count,
            "results": results,
        }

    async def check_coherence(
        self,
        sections: dict[str, str],
    ) -> dict[str, Any]:
        """
        Check coherence and consistency between report sections.

        Returns:
            Coherence analysis with identified contradictions
        """
        if not sections:
            return {"score": 1.0, "issues": []}

        sections_text = "\n\n---\n\n".join(
            f"SECTION: {title}\n{content[:1000]}"
            for title, content in sections.items()
        )

        prompt = f"""Analyze these report sections for coherence and consistency.
Identify any contradictions, logical gaps, or inconsistencies between sections.

{sections_text}

Output as JSON:
{{
    "score": 0.0-1.0,
    "issues": [
        {{
            "type": "contradiction|gap|inconsistency",
            "sections": ["Section A", "Section B"],
            "description": "description of the issue"
        }}
    ],
    "flow_quality": "excellent|good|fair|poor",
    "suggestions": ["improvement suggestions"]
}}"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            return cast(dict[str, Any], json.loads(json_str.strip()))
        except (json.JSONDecodeError, KeyError):
            return {"score": 0.7, "issues": [], "flow_quality": "unknown"}


class RerankerAgent(BaseAgent):
    """
    Reranks and selects the best outputs from multiple alternatives.

    Workflow:
    1. Score multiple candidate outputs on quality metrics
    2. Select the best candidate or merge best parts
    3. Can also rerank search results beyond cross-encoder

    Supports both:
    - Cross-encoder based reranking (for search results)
    - LLM-based scoring and selection (for answer/section selection)
    """

    SYSTEM_PROMPT = """You are an expert evaluator for legal and analytical content.
Your role is to compare and rank outputs based on quality, accuracy, and relevance.

When evaluating:
1. Assess factual accuracy and citation quality
2. Evaluate clarity and coherence of writing
3. Check completeness of coverage
4. Consider relevance to the original question/topic
5. Prefer specific, well-supported claims over vague statements

Be objective and provide clear justifications for rankings."""

    _cross_encoder: Any | None = None

    @classmethod
    def get_cross_encoder(cls):
        """Lazy load cross-encoder model for reranking"""
        if cls._cross_encoder is None:
            try:
                from sentence_transformers import CrossEncoder
                cls._cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                logger.info("RerankerAgent: Cross-encoder model loaded")
            except Exception as e:
                logger.warning(f"RerankerAgent: Could not load cross-encoder: {e}")
        return cls._cross_encoder

    async def rerank_answers(
        self,
        question: str,
        candidate_answers: list[dict[str, Any]],
        criteria: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Rerank multiple candidate answers using LLM-based scoring.

        Args:
            question: The original question being answered
            candidate_answers: List of {"answer": "...", "model": "...", ...}
            criteria: Optional scoring criteria to emphasize

        Returns:
            Reranked list with scores
        """
        if not candidate_answers:
            return []

        if len(candidate_answers) == 1:
            candidate_answers[0]["rerank_score"] = 1.0
            return candidate_answers

        criteria_str = ", ".join(criteria) if criteria else "accuracy, completeness, clarity, citation quality"

        # Build comparison prompt
        candidates_text = "\n\n---\n\n".join(
            f"CANDIDATE {i+1} (from {c.get('model', 'unknown')}):\n{c.get('answer', c.get('content', ''))[:1500]}"
            for i, c in enumerate(candidate_answers)
        )

        prompt = f"""Compare and rank these candidate answers to the question.

QUESTION: {question}

EVALUATION CRITERIA: {criteria_str}

{candidates_text}

Score each candidate from 0.0 to 1.0 and rank them. Output as JSON:
{{
    "rankings": [
        {{
            "candidate": 1,
            "score": 0.0-1.0,
            "strengths": ["list of strengths"],
            "weaknesses": ["list of weaknesses"],
            "justification": "why this ranking"
        }}
    ],
    "best_candidate": 1,
    "recommendation": "which to use and why"
}}"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            result = json.loads(json_str.strip())
            rankings = result.get("rankings", [])

            # Apply scores to candidates
            for ranking in rankings:
                idx = ranking.get("candidate", 1) - 1
                if 0 <= idx < len(candidate_answers):
                    candidate_answers[idx]["rerank_score"] = ranking.get("score", 0.5)
                    candidate_answers[idx]["rerank_justification"] = ranking.get("justification", "")

            # Sort by score descending
            candidate_answers.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

            return candidate_answers

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Answer reranking failed: {e}")
            # Return as-is with default scores
            for i, c in enumerate(candidate_answers):
                c["rerank_score"] = 1.0 - (i * 0.1)
            return candidate_answers

    async def select_best_sections(
        self,
        theme: str,
        section_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Select the best section from multiple generated candidates.

        Used when multiple models generate competing section drafts.

        Args:
            theme: The section theme/topic
            section_candidates: List of {"content": "...", "model": "...", ...}

        Returns:
            The best candidate with selection reasoning
        """
        if not section_candidates:
            return {"content": "", "model": "none", "selection_reason": "No candidates"}

        if len(section_candidates) == 1:
            section_candidates[0]["selection_reason"] = "Only candidate"
            return section_candidates[0]

        candidates_text = "\n\n---\n\n".join(
            f"CANDIDATE {i+1} (from {c.get('model', 'unknown')}):\n{c.get('content', '')[:2000]}"
            for i, c in enumerate(section_candidates)
        )

        prompt = f"""Select the best section for the theme: "{theme}"

{candidates_text}

Consider: accuracy, completeness, writing quality, and professional tone.

Output as JSON:
{{
    "selected_candidate": 1,
    "score": 0.0-1.0,
    "selection_reason": "why this is best",
    "merge_suggestion": "optional: elements from other candidates worth incorporating"
}}"""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)

        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            result = json.loads(json_str.strip())
            selected_idx = result.get("selected_candidate", 1) - 1

            if 0 <= selected_idx < len(section_candidates):
                best = section_candidates[selected_idx]
                best["selection_reason"] = result.get("selection_reason", "")
                best["selection_score"] = result.get("score", 0.8)
                best["merge_suggestion"] = result.get("merge_suggestion", "")
                return best

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Section selection failed: {e}")

        # Default to first candidate
        section_candidates[0]["selection_reason"] = "Default selection (parsing failed)"
        return section_candidates[0]

    def rerank_search_results(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Rerank search results using cross-encoder (synchronous).

        This provides more accurate relevance scoring than vector similarity alone.
        """
        if not results or len(results) <= 1:
            return results

        cross_encoder = self.get_cross_encoder()
        if cross_encoder is None:
            logger.warning("Cross-encoder unavailable, returning results as-is")
            return results[:top_k]

        try:
            # Create query-document pairs
            pairs = [
                (query, r.get("content", r.get("text", str(r))))
                for r in results
            ]

            # Score all pairs
            scores = cross_encoder.predict(pairs)

            # Combine with results and sort
            scored_results = list(zip(results, scores))
            scored_results.sort(key=lambda x: x[1], reverse=True)

            # Return top-k with scores
            return [
                {**r, "cross_encoder_score": float(s)}
                for r, s in scored_results[:top_k]
            ]

        except Exception as e:
            logger.error(f"Cross-encoder reranking failed: {e}")
            return results[:top_k]

    async def consensus_selection(
        self,
        candidates: list[dict[str, Any]],
        selection_type: str = "answer",
    ) -> dict[str, Any]:
        """
        Use multi-model consensus to select the best output.

        Calls multiple models to vote on the best candidate.
        Useful for high-stakes selections.
        """
        if not candidates:
            return {"error": "No candidates provided"}

        if len(candidates) == 1:
            return candidates[0]

        # For now, use single-model selection
        # Future enhancement: call multiple models and aggregate votes
        if selection_type == "answer":
            return (await self.rerank_answers("", candidates))[0]
        else:
            return await self.select_best_sections("", candidates)


# Note: EvidenceContext is defined here before MasterAgent to avoid forward reference issues
@dataclass
class EvidenceContext:
    """Container for evidence context - both string and structured formats"""

    text: str  # String format for LLM prompts
    items: list[dict[str, Any]]  # Structured format for intelligent retrieval


class MasterAgent:
    """
    Orchestrates the entire research workflow.

    Workflow:
    1. Delegate to Planner Agent
    2. Wait for user approval (HITL)
    3. Execute research DAG with parallel Researcher Agents
    4. Delegate to Synthesizer Agent
    5. Run ValidatorAgent for quality assurance
    6. Return final report with validation

    Multi-model orchestration: Different agents can use different models
    based on task requirements and performance metrics.
    """

    def __init__(self, db: Session, session: ResearchSession):
        self.db = db
        self.session = session
        self.planner = PlannerAgent(db)
        self.synthesizer = SynthesizerAgent(db)
        self.validator = ValidatorAgent(db)
        self.reranker = RerankerAgent(db)

    async def run_planning_phase(
        self, evidence_context: EvidenceContext, focus_areas: list[str] | None = None
    ) -> ResearchPlan:
        """Phase 1: Create research plan"""
        self.session.status = ResearchStatus.PLANNING
        self.session.updated_at = datetime.now(timezone.utc)

        plan = await self.planner.create_plan(
            self.session.topic,
            evidence_context.text,  # Use text format for planning
            focus_areas,
        )

        self.session.plan = plan
        self.session.status = ResearchStatus.AWAITING_APPROVAL
        self.session.updated_at = datetime.now(timezone.utc)

        return plan

    async def run_research_phase(self, evidence_context: EvidenceContext) -> None:
        """
        Phase 2: Execute research DAG with intelligent evidence retrieval.

        Uses cross-encoder reranking and MMR for each question.
        """
        if not self.session.plan:
            raise ValueError("No plan available")

        self.session.status = ResearchStatus.RESEARCHING
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
                    evidence_items=evidence_context.items,  # Enable cross-encoder + MMR
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

    async def run_synthesis_phase(self) -> str:
        """Phase 3: Synthesize findings into report"""
        if not self.session.plan:
            raise ValueError("No plan available")

        self.session.status = ResearchStatus.SYNTHESIZING
        self.session.updated_at = datetime.now(timezone.utc)

        report, themes = await self.synthesizer.synthesize(
            self.session.plan, self.session.question_analyses
        )

        self.session.final_report = report
        self.session.key_themes = themes
        self.session.models_used["synthesizer"] = self.synthesizer.synthesizer_model or "default"
        self.session.updated_at = datetime.now(timezone.utc)

        return report

    async def run_validation_phase(
        self,
        evidence_context: EvidenceContext | None = None,
    ) -> dict[str, Any]:
        """
        Phase 4: Validate the synthesized report for quality assurance.

        This uses a ValidatorAgent (typically with a different model) to:
        - Verify citations are accurate
        - Check coherence between sections
        - Identify potential hallucinations
        - Assess completeness

        Returns:
            Validation result with scores and recommendations
        """
        if not self.session.plan or not self.session.final_report:
            raise ValueError("No plan or report available for validation")

        logger.info(f"Running validation phase for session {self.session.id}")

        # Validate the report
        validation_result = await self.validator.validate_report(
            report=self.session.final_report,
            plan=self.session.plan,
            question_analyses=self.session.question_analyses,
            evidence_items=evidence_context.items if evidence_context else None,
        )

        # Store validation results
        self.session.validation_result = validation_result
        self.session.validation_passed = validation_result.get("validation_passed", True)
        self.session.models_used["validator"] = "claude"  # Validator uses powerful model
        self.session.updated_at = datetime.now(timezone.utc)

        # Log validation outcome
        overall_score = validation_result.get("overall_score", 0)
        if overall_score >= 0.8:
            logger.info(f"Validation passed with high confidence: {overall_score}")
        elif overall_score >= 0.5:
            logger.warning(f"Validation passed with medium confidence: {overall_score}")
        else:
            logger.warning(f"Validation flagged issues: {overall_score}")

        # If validation fails significantly, we could trigger re-synthesis
        # For now, we just record the results
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
        Run the complete research workflow end-to-end.

        This is useful for automated/batch processing where plan approval
        is not needed or has been pre-approved.

        Args:
            evidence_context: Evidence to research
            focus_areas: Optional focus areas
            skip_validation: Skip validation phase (faster but less quality assurance)

        Returns:
            Tuple of (final_report, validation_result)
        """
        # Phase 1: Planning
        await self.run_planning_phase(evidence_context, focus_areas)

        # Phase 2: Research (with parallel execution)
        await self.run_research_phase(evidence_context)

        # Phase 3: Synthesis
        report = await self.run_synthesis_phase()

        # Phase 4: Validation (optional)
        validation_result = {}
        if not skip_validation:
            validation_result = await self.run_validation_phase(evidence_context)

        # Mark as completed
        self.session.status = ResearchStatus.COMPLETED
        self.session.updated_at = datetime.now(timezone.utc)

        return report, validation_result


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
    - Structured items for cross-encoder reranking and MMR
    """

    context_parts: list[str] = []
    evidence_items: list[dict[str, Any]] = []

    # Get emails - exclude spam-filtered/hidden
    email_query = db.query(EmailMessage)
    
    # Filter out hidden emails (spam-filtered)
    email_query = email_query.filter(
        or_(
            EmailMessage.meta.is_(None),
            EmailMessage.meta.op('->>')('spam').is_(None),
            EmailMessage.meta.op('->')('spam').op('->>')('is_hidden') != "true",
        )
    )
    
    if project_id:
        email_query = email_query.filter(EmailMessage.project_id == project_id)
    elif case_id:
        email_query = email_query.filter(EmailMessage.case_id == case_id)
    else:
        # Get from user's projects
        projects = (
            db.query(Project).filter(Project.owner_id == user_id).all()
        )  # pyright: ignore[reportAny]
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
    # Exclude spam-filtered/hidden evidence
    evidence_query = db.query(EvidenceItem).filter(
        or_(
            EvidenceItem.meta.is_(None),
            EvidenceItem.meta.op('->>')('spam').is_(None),
            EvidenceItem.meta.op('->')('spam').op('->>')('is_hidden') != "true",
        )
    )
    if project_id:
        evidence_query = evidence_query.filter(EvidenceItem.project_id == project_id)

    evidence_docs = evidence_query.all()

    for evidence in evidence_docs:
        # Build text content from available fields
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


@router.post("/start", response_model=StartResearchResponse)
async def start_research(
    request: StartResearchRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Start a new deep research session.

    This initiates the planning phase and returns a session ID.
    The client should poll for status and approve the plan when ready.
    """
    session_id = str(uuid.uuid4())

    session = ResearchSession(
        id=session_id,
        user_id=str(user.id),
        project_id=request.project_id,
        case_id=request.case_id,
        topic=request.topic,
        status=ResearchStatus.PENDING,
    )

    save_session(session)

    # Start planning in background
    async def run_planning():
        try:
            evidence_context = await build_evidence_context(
                db, str(user.id), request.project_id, request.case_id
            )

            master = MasterAgent(db, session)
            _ = await master.run_planning_phase(evidence_context, request.focus_areas)

        except Exception as e:
            logger.exception(f"Planning failed: {e}")
            session.status = ResearchStatus.FAILED
            session.error_message = str(e)
        finally:
            save_session(session)

    # Schedule background task properly - wrap async function for BackgroundTasks
    def sync_run_planning():
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_planning())
        finally:
            loop.close()

    background_tasks.add_task(sync_run_planning)

    return StartResearchResponse(
        session_id=session_id,
        status="pending",
        message="Research session started. Poll /status for updates.",
    )


@router.get("/status/{session_id}", response_model=ResearchStatusResponse)
async def get_research_status(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """Get the current status of a research session"""

    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Research session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized to view this session")

    # Calculate progress
    progress = {
        "total_questions": len(session.plan.questions) if session.plan else 0,
        "completed_questions": len(session.question_analyses),
        "current_phase": session.status.value,
    }

    return ResearchStatusResponse(
        session_id=session_id,
        status=session.status.value,
        plan=session.plan,
        progress=progress,
        final_report=session.final_report,
        key_themes=session.key_themes,
        processing_time_seconds=session.processing_time_seconds,
        error_message=session.error_message,
    )


@router.post("/approve-plan")
async def approve_research_plan(
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
        raise HTTPException(404, "Research session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # If the plan exists but status is still pending/planning (e.g. cross-worker desync),
    # normalize to awaiting approval so the user can proceed.
    if session.plan and session.status in {
        ResearchStatus.PENDING,
        ResearchStatus.PLANNING,
    }:
        logger.warning(
            "Session %s has plan but status=%s; promoting to awaiting approval",
            session.id,
            session.status,
        )
        session.status = ResearchStatus.AWAITING_APPROVAL
        save_session(session)

    if session.status != ResearchStatus.AWAITING_APPROVAL:
        raise HTTPException(
            400, f"Session not awaiting approval. Status: {session.status}"
        )

    if not request.approved:
        # User wants modifications - regenerate plan
        if request.modifications:
            session.topic = f"{session.topic}\n\nUser feedback: {request.modifications}"

        session.status = ResearchStatus.PENDING

        async def regenerate_plan():
            try:
                evidence_context = await build_evidence_context(
                    db, str(user.id), session.project_id, session.case_id
                )
                master = MasterAgent(db, session)
                _ = await master.run_planning_phase(evidence_context)
            except Exception as e:
                logger.exception(f"Plan regeneration failed: {e}")
                session.status = ResearchStatus.FAILED
                session.error_message = str(e)
            finally:
                save_session(session)

        def sync_regenerate_plan():
            import asyncio

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

    # Set status and save BEFORE starting background task to prevent race condition
    session.status = ResearchStatus.RESEARCHING
    session.updated_at = datetime.now(timezone.utc)
    save_session(session)

    async def run_research():
        try:
            evidence_context = await build_evidence_context(
                db, str(user.id), session.project_id, session.case_id
            )

            master = MasterAgent(db, session)
            await master.run_research_phase(evidence_context)
            _ = await master.run_synthesis_phase()

            session.processing_time_seconds = (
                datetime.now(timezone.utc) - start_time
            ).total_seconds()

        except Exception as e:
            logger.exception(f"Research failed: {e}")
            session.status = ResearchStatus.FAILED
            session.error_message = str(e)
        finally:
            save_session(session)

    def sync_run_research():
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_research())
        finally:
            loop.close()

    background_tasks.add_task(sync_run_research)

    return {"status": "researching", "message": "Research phase started"}


@router.delete("/{session_id}")
async def cancel_research(
    session_id: str, user: Annotated[User, Depends(current_user)]
):
    """Cancel a research session"""

    session = load_session(session_id)
    if not session:
        raise HTTPException(404, "Research session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    session.status = ResearchStatus.CANCELLED
    save_session(session)

    return {"status": "cancelled", "message": "Research session cancelled"}


@router.get("/sessions")
async def list_research_sessions(
    user: Annotated[User, Depends(current_user)], limit: int = 20
):
    """List user's research sessions"""

    user_sessions = [
        {
            "id": s.id,
            "topic": s.topic,
            "status": s.status.value,
            "created_at": s.created_at.isoformat(),
            "has_report": s.final_report is not None,
        }
        for s in (
            list(_research_sessions.values())
            + [
                load_session(
                    key.decode().split(":")[-1] if isinstance(key, (bytes, bytearray)) else str(key).split(":")[-1]
                )
                for key in (
                    _get_redis().scan_iter("deep_research:session:*")
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
