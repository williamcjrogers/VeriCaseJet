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

from .models import User, EmailMessage, Project, Document
from .db import get_db
from .security import current_user
from .ai_settings import get_ai_api_key, get_ai_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deep-research", tags=["deep-research"])

# Latest model defaults used when no explicit model is configured in Admin Settings
LATEST_MODEL_DEFAULTS = {
    "openai": "gpt-5.1",
    "anthropic": "claude-4.5-opus",
    "gemini": "gemini-3.0-pro",
}


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
    dependencies: list[str] = Field(default_factory=list)  # IDs of questions that must complete first
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


# In-memory session store (in production, use Redis or database)
_research_sessions: dict[str, ResearchSession] = {}


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
        default_factory=list,
        description="Optional focus areas to prioritize"
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
    """Base class for all agents"""
    
    def __init__(self, db: Session):
        self.db = db
        self.openai_key = get_ai_api_key('openai', db)
        self.anthropic_key = get_ai_api_key('anthropic', db)
        self.gemini_key = get_ai_api_key('gemini', db)
        
        # Model selections
        self.openai_model = get_ai_model('openai', db)
        self.anthropic_model = get_ai_model('anthropic', db)
        self.gemini_model = get_ai_model('gemini', db)
    
    async def _call_llm(self, prompt: str, system_prompt: str = "", use_powerful: bool = False) -> str:
        """Call the appropriate LLM based on configuration"""
        # Try Anthropic first for powerful tasks
        if use_powerful and self.anthropic_key:
            return await self._call_anthropic(prompt, system_prompt)
        
        # Try OpenAI
        if self.openai_key:
            return await self._call_openai(prompt, system_prompt)
        
        # Try Gemini
        if self.gemini_key:
            return await self._call_gemini(prompt, system_prompt)
        
        # Fallback to Anthropic
        if self.anthropic_key:
            return await self._call_anthropic(prompt, system_prompt)
        
        raise HTTPException(500, "No AI providers configured. Please add API keys in Admin Settings.")
    
    async def _call_openai(self, prompt: str, system_prompt: str = "") -> str:
        import openai
        client = openai.AsyncOpenAI(api_key=self.openai_key)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = await client.chat.completions.create(
            model=self.openai_model or LATEST_MODEL_DEFAULTS["openai"],
            messages=messages,
            max_tokens=4000,
            temperature=0.3
        )
        content = response.choices[0].message.content
        return content or ""
    
    async def _call_anthropic(self, prompt: str, system_prompt: str = "") -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
        
        response = await client.messages.create(
            model=self.anthropic_model or LATEST_MODEL_DEFAULTS["anthropic"],
            max_tokens=4000,
            system=system_prompt if system_prompt else "You are an expert legal and construction dispute analyst.",
            messages=[{"role": "user", "content": prompt}]
        )
        
        text = ""
        for block in response.content:
            text_piece = getattr(block, "text", "")
            if text_piece:
                text += str(text_piece)
        return text
    
    async def _call_gemini(self, prompt: str, system_prompt: str = "") -> str:
        import google.generativeai as genai  # type: ignore[reportMissingTypeStubs]
        genai.configure(api_key=self.gemini_key)  # type: ignore[attr-defined]
        
        model = genai.GenerativeModel(self.gemini_model or LATEST_MODEL_DEFAULTS["gemini"])
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        generate_fn = cast(Callable[[str], Any], model.generate_content)  # type: ignore[attr-defined]
        response = await asyncio.to_thread(generate_fn, full_prompt)
        return str(getattr(response, "text", ""))


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
        self,
        topic: str,
        evidence_context: str,
        focus_areas: list[str] | None = None
    ) -> ResearchPlan:
        """Generate a research plan as a DAG"""
        
        focus_str = f"\n\nFocus areas to prioritize:\n" + "\n".join(f"- {f}" for f in focus_areas) if focus_areas else ""
        
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
                    dependencies=q.get("dependencies", []) or []
                )
                for q in plan_data["questions"]
            ]
            
            return ResearchPlan(
                topic=topic,
                problem_statement=plan_data["problem_statement"],
                key_angles=plan_data["key_angles"],
                questions=questions,
                estimated_time_minutes=plan_data.get("estimated_time_minutes", 5) or 5
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
                        dependencies=[]
                    ),
                    ResearchQuestion(
                        id="q2",
                        question=f"What were the key decisions and actions taken?",
                        rationale="Identify decision points",
                        dependencies=["q1"]
                    ),
                    ResearchQuestion(
                        id="q3",
                        question=f"What evidence supports or contradicts the claims?",
                        rationale="Assess evidence strength",
                        dependencies=["q1", "q2"]
                    )
                ]
            )


class SearcherAgent(BaseAgent):
    """
    Information Gatherer Agent - handles search, reranking, and diversification.
    
    Workflow (based on Egnyte architecture):
    1. Formulate search queries
    2. Execute queries against evidence sources
    3. Cross-encoder reranking for relevance
    4. Semantic chunking of documents
    5. MMR (Maximal Marginal Relevance) for diverse results
    6. Evaluate and loop if more information needed
    """
    
    _cross_encoder: Any | None = None
    _embedding_model: Any | None = None
    
    @classmethod
    def get_cross_encoder(cls):
        """Lazy load cross-encoder model for reranking"""
        if cls._cross_encoder is None:
            try:
                from sentence_transformers import CrossEncoder
                cls._cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
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
                cls._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.warning(f"Could not load embedding model: {e}")
        return cls._embedding_model
    
    def rerank_results(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 10
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
            pairs = [(query, doc.get('content', doc.get('text', str(doc)))) for doc in documents]
            
            # Score all pairs
            scores: list[float] = cast(list[float], cross_encoder.predict(pairs))
            
            # Sort by score descending
            scored_docs: list[tuple[dict[str, Any], float]] = list(zip(documents, scores))
            scored_docs.sort(key=lambda x: x[1], reverse=True)
            
            # Return top-k with scores
            result: list[dict[str, Any]] = []
            for doc, score in scored_docs[:top_k]:
                doc_copy = dict(doc)
                doc_copy['relevance_score'] = float(score)
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
        diversity_weight: float = 0.3
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
            doc_texts: list[str] = [doc.get('content', doc.get('text', str(doc))) for doc in documents]
            
            # Encode query and documents
            query_embedding = cast(np.ndarray, embedding_model.encode([query]))[0]
            doc_embeddings = cast(np.ndarray, embedding_model.encode(doc_texts))
            
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
                        selected_embeddings = doc_embeddings[selected_indices]
                        similarities = cast(np.ndarray, np.dot(selected_embeddings, doc_embeddings[idx]) / (
                            np.linalg.norm(selected_embeddings, axis=1) * np.linalg.norm(doc_embeddings[idx])
                        ))
                        max_sim = float(np.max(similarities)) if similarities.size else 0.0
                    else:
                        max_sim = 0.0
                    
                    # MMR score
                    mmr = (1 - diversity_weight) * relevance - diversity_weight * max_sim
                    mmr_scores.append((idx, mmr))
                
                # Select document with highest MMR score
                best_idx = max(mmr_scores, key=lambda x: x[1])[0]
                selected_indices.append(best_idx)
                remaining_indices.remove(best_idx)
            
            # Return selected documents with MMR scores
            result: list[dict[str, Any]] = []
            for idx in selected_indices:
                doc_copy = dict(documents[idx])
                doc_copy['mmr_score'] = float(query_sims[idx])
                result.append(doc_copy)
            
            return result
            
        except Exception as e:
            logger.error(f"MMR failed: {e}")
            return documents[:top_k]
    
    def semantic_chunk(
        self,
        text: str,
        max_chunk_size: int = 1000,
        overlap: int = 100
    ) -> list[str]:
        """
        Split text into semantically coherent chunks.
        
        Uses paragraph boundaries and sentence endings for natural breaks.
        """
        if not text or len(text) <= max_chunk_size:
            return [text] if text else []
        
        chunks: list[str] = []
        
        # Split by double newlines (paragraphs) first
        paragraphs = text.split('\n\n')
        
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) <= max_chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                
                # If paragraph itself is too long, split by sentences
                if len(para) > max_chunk_size:
                    sentences = para.replace('. ', '.|').replace('? ', '?|').replace('! ', '!|').split('|')
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
        apply_diversity: bool = True
    ) -> list[dict[str, Any]]:
        """
        Full search pipeline: rerank -> chunk -> MMR diversify
        """
        if not evidence_items:
            return []
        
        # Step 1: Cross-encoder reranking
        reranked = self.rerank_results(query, evidence_items, top_k=top_k * 2)
        
        # Step 2: Apply MMR for diversity (if enabled)
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
        evidence_items: list[dict[str, Any]] | None = None
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
                    apply_diversity=True
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
                
                logger.info(f"Retrieved {len(relevant_evidence)} relevant evidence items using cross-encoder + MMR")
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
                "key_entities": []
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

    async def synthesize(
        self,
        plan: ResearchPlan,
        question_analyses: dict[str, dict[str, Any]]
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
        self,
        plan: ResearchPlan,
        analyses: dict[str, dict[str, Any]]
    ) -> list[str]:
        """Identify emergent themes from all analyses"""
        
        findings_summary = "\n\n".join([
            f"Q: {q.question}\nFindings: {analyses.get(q.id, {}).get('findings', 'No findings')[:500]}"
            for q in plan.questions
        ])
        
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
        self,
        plan: ResearchPlan,
        analyses: dict[str, dict[str, Any]],
        themes: list[str]
    ) -> dict[str, str]:
        """Generate report sections for each theme"""
        
        all_findings = "\n\n".join([
            f"## {q.question}\n{analyses.get(q.id, {}).get('findings', 'No findings')}"
            for q in plan.questions
        ])
        
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

            content = await self._call_llm(prompt, self.SYSTEM_PROMPT, use_powerful=True)
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
        themes: list[str]
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
            "\n---\n"
        ]
        
        # Add themed sections
        for theme in themes:
            if theme in sections:
                report_parts.append(f"\n## {theme}\n")
                report_parts.append(sections[theme])
                report_parts.append("\n---\n")
        
        # Add methodology note
        report_parts.append("\n## Research Methodology\n")
        report_parts.append(f"This report was generated through systematic analysis of {len(plan.questions)} research questions:\n")
        for q in plan.questions:
            report_parts.append(f"- {q.question}\n")
        
        return "\n".join(report_parts)


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
    5. Return final report
    """
    
    def __init__(self, db: Session, session: ResearchSession):
        self.db = db
        self.session = session
        self.planner = PlannerAgent(db)
        self.synthesizer = SynthesizerAgent(db)
    
    async def run_planning_phase(self, evidence_context: EvidenceContext, focus_areas: list[str] | None = None) -> ResearchPlan:
        """Phase 1: Create research plan"""
        self.session.status = ResearchStatus.PLANNING
        self.session.updated_at = datetime.now(timezone.utc)
        
        plan = await self.planner.create_plan(
            self.session.topic,
            evidence_context.text,  # Use text format for planning
            focus_areas
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
                q for q in plan.questions
                if q.id not in completed and all(d in completed for d in q.dependencies)
            ]
            
            if not ready:
                logger.error("DAG has unresolvable dependencies")
                break
            
            # Execute ready questions in parallel with intelligent retrieval
            async def investigate_question(q: ResearchQuestion) -> tuple[str, dict[str, Any]]:
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
                    evidence_items=evidence_context.items  # Enable cross-encoder + MMR
                )
                return q.id, result
            
            tasks = [investigate_question(q) for q in ready]  # pyright: ignore[reportUnknownVariableType]
            results = await asyncio.gather(*tasks, return_exceptions=True)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]

            for result in results:  # pyright: ignore[reportUnknownVariableType]
                if isinstance(result, tuple):
                    qid: str = result[0]
                    analysis: dict[str, Any] = result[1]  # pyright: ignore[reportUnknownVariableType]
                    self.session.question_analyses[qid] = analysis
                    completed.add(qid)

                    # Update question status in plan
                    for q in plan.questions:
                        if q.id == qid:
                            q.status = "completed"
                            q.findings = analysis.get("findings", "")  # pyright: ignore[reportUnknownMemberType]
                            q.citations = analysis.get("citations", [])  # pyright: ignore[reportUnknownMemberType]
                            q.gaps = analysis.get("gaps", [])  # pyright: ignore[reportUnknownMemberType]
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
            self.session.plan,
            self.session.question_analyses
        )
        
        self.session.final_report = report
        self.session.key_themes = themes
        self.session.status = ResearchStatus.COMPLETED
        self.session.updated_at = datetime.now(timezone.utc)
        
        return report


# =============================================================================
# Evidence Context Builder
# =============================================================================

async def build_evidence_context(
    db: Session,
    user_id: str,
    project_id: str | None = None,
    case_id: str | None = None,
    max_items: int = 100
) -> EvidenceContext:
    """
    Build evidence context from emails and documents.
    
    Returns both:
    - Text format for direct LLM consumption
    - Structured items for cross-encoder reranking and MMR
    """
    
    context_parts: list[str] = []
    evidence_items: list[dict[str, Any]] = []
    
    # Get emails
    email_query = db.query(EmailMessage)
    if project_id:
        email_query = email_query.filter(EmailMessage.project_id == project_id)
    elif case_id:
        email_query = email_query.filter(EmailMessage.case_id == case_id)
    else:
        # Get from user's projects
        projects = db.query(Project).filter(Project.owner_id == user_id).all()  # pyright: ignore[reportAny]
        project_ids = [str(p.id) for p in projects]
        if project_ids:
            email_query = email_query.filter(EmailMessage.project_id.in_(project_ids))
    
    emails = email_query.order_by(EmailMessage.date_sent.desc()).limit(max_items).all()
    
    for email in emails:
        # Build text content
        content = (email.body_text or email.body_preview or '')[:1000]
        date_str = email.date_sent.strftime('%Y-%m-%d') if email.date_sent else 'Unknown'
        
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
        evidence_items.append({
            'id': str(email.id),
            'type': 'EMAIL',
            'date': date_str,
            'sender': email.sender_name or email.sender_email or 'Unknown',
            'recipients': email.recipients_to or [],
            'subject': email.subject or 'No subject',
            'content': content,
            'text': f"Email from {email.sender_name or email.sender_email} on {date_str}: {email.subject}. {content}"
        })
    
    # Get documents
    doc_query = db.query(Document)
    if project_id:
        doc_query = doc_query.filter(Document.project_id == project_id)  # pyright: ignore[reportAny]
    
    documents = doc_query.limit(50).all()
    
    for doc in documents:
        if doc.text_excerpt:
            text_part = (
                f"[DOCUMENT {doc.id}]\n"
                f"Filename: {doc.filename or 'Unknown'}\n"
                f"Content: {doc.text_excerpt[:500]}\n"
                f"---"
            )
            context_parts.append(text_part)
            
            evidence_items.append({
                'id': str(doc.id),
                'type': 'DOCUMENT',
                'filename': doc.filename or 'Unknown',
                'content': doc.text_excerpt[:1500],
                'text': f"Document {doc.filename}: {doc.text_excerpt[:1500]}"
            })
    
    return EvidenceContext(
        text="\n\n".join(context_parts),
        items=evidence_items
    )


# =============================================================================
# API Endpoints
# =============================================================================

@router.post("/start", response_model=StartResearchResponse)
async def start_research(
    request: StartResearchRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)]
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
        status=ResearchStatus.PENDING
    )
    
    _research_sessions[session_id] = session
    
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
    
    background_tasks.add_task(asyncio.create_task, run_planning())
    
    return StartResearchResponse(
        session_id=session_id,
        status="pending",
        message="Research session started. Poll /status for updates."
    )


@router.get("/status/{session_id}", response_model=ResearchStatusResponse)
async def get_research_status(
    session_id: str,
    user: Annotated[User, Depends(current_user)]
):
    """Get the current status of a research session"""
    
    session = _research_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Research session not found")
    
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized to view this session")
    
    # Calculate progress
    progress = {
        "total_questions": len(session.plan.questions) if session.plan else 0,
        "completed_questions": len(session.question_analyses),
        "current_phase": session.status.value
    }
    
    return ResearchStatusResponse(
        session_id=session_id,
        status=session.status.value,
        plan=session.plan,
        progress=progress,
        final_report=session.final_report,
        key_themes=session.key_themes,
        processing_time_seconds=session.processing_time_seconds,
        error_message=session.error_message
    )


@router.post("/approve-plan")
async def approve_research_plan(
    request: ApprovePlanRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Approve or modify the research plan (Human-in-the-Loop).
    
    If approved, the research phase begins.
    If modifications are provided, the plan is regenerated.
    """
    session = _research_sessions.get(request.session_id)
    if not session:
        raise HTTPException(404, "Research session not found")
    
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    if session.status != ResearchStatus.AWAITING_APPROVAL:
        raise HTTPException(400, f"Session not awaiting approval. Status: {session.status}")
    
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
        
        background_tasks.add_task(asyncio.create_task, regenerate_plan())
        
        return {"status": "regenerating", "message": "Plan is being regenerated with your feedback"}
    
    # Approved - start research
    start_time = datetime.now(timezone.utc)
    
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
    
    background_tasks.add_task(asyncio.create_task, run_research())
    
    return {"status": "researching", "message": "Research phase started"}


@router.delete("/{session_id}")
async def cancel_research(
    session_id: str,
    user: Annotated[User, Depends(current_user)]
):
    """Cancel a research session"""
    
    session = _research_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Research session not found")
    
    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    session.status = ResearchStatus.CANCELLED
    
    return {"status": "cancelled", "message": "Research session cancelled"}


@router.get("/sessions")
async def list_research_sessions(
    user: Annotated[User, Depends(current_user)],
    limit: int = 20
):
    """List user's research sessions"""
    
    user_sessions = [
        {
            "id": s.id,
            "topic": s.topic,
            "status": s.status.value,
            "created_at": s.created_at.isoformat(),
            "has_report": s.final_report is not None
        }
        for s in _research_sessions.values()
        if s.user_id == str(user.id)
    ]
    
    # Sort by created_at descending
    user_sessions.sort(key=lambda x: x["created_at"], reverse=True)
    
    return {"sessions": user_sessions[:limit]}
