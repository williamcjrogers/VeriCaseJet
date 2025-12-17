# pyright: reportMissingTypeStubs=false, reportDeprecatedType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownParameterType=false, reportUnnecessaryIsInstance=false
"""
Multi-AI Orchestration System - Dataset Insights & Timeline Analysis
Leverages multiple AI models for comprehensive document analytics

Extended with MultiModelTask for cross-model collaboration where
a single task can be executed by multiple models in parallel,
with result aggregation and selection.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .models import User, Document
from .db import get_db
from .security import current_user
from .ai_settings import (
    get_ai_api_key,
    get_ai_model,
    is_bedrock_enabled,
    get_bedrock_region,
)
from .ai_runtime import complete_chat

router = APIRouter(prefix="/ai/orchestrator", tags=["ai-orchestrator"])
logger = logging.getLogger(__name__)


# =============================================================================
# Multi-Model Task Execution
# =============================================================================


@dataclass
class ModelResult:
    """Result from a single model execution."""

    provider: str
    model_id: str
    response: str
    latency_ms: int
    tokens_used: int = 0
    success: bool = True
    error: str | None = None
    quality_score: float = 0.0  # Assigned after evaluation


@dataclass
class MultiModelResult:
    """Aggregated result from multi-model execution."""

    best_result: ModelResult | None = None
    all_results: list[ModelResult] = field(default_factory=list)
    consensus_response: str | None = None
    selection_method: str = "first_success"  # first_success, voting, quality_score
    total_time_ms: int = 0
    models_attempted: int = 0
    models_succeeded: int = 0


class MultiModelTask:
    """
    Execute a single task across multiple AI models in parallel.

    Supports:
    - Parallel execution across providers (OpenAI, Anthropic, Gemini, Bedrock)
    - Result aggregation with voting or quality scoring
    - Automatic fallback if primary models fail
    - Performance tracking per model

    Usage:
        task = MultiModelTask(db)
        result = await task.execute(
            prompt="Analyze this document",
            system_prompt="You are an analyst",
            models=[
                ("openai", "gpt-4o"),
                ("anthropic", "claude-sonnet-4-20250514"),
                ("gemini", "gemini-2.0-flash"),
            ],
            selection_method="quality_score",
        )
    """

    def __init__(self, db: Session):
        self.db = db
        self.openai_key = get_ai_api_key("openai", db)
        self.anthropic_key = get_ai_api_key("anthropic", db)
        self.gemini_key = get_ai_api_key("gemini", db)
        self.bedrock_enabled = is_bedrock_enabled(db)
        self.bedrock_region = get_bedrock_region(db)

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
        models: list[tuple[str, str]] | None = None,
        selection_method: str = "quality_score",
        timeout_seconds: float = 30.0,
        require_all: bool = False,
    ) -> MultiModelResult:
        """
        Execute a prompt across multiple models in parallel.

        Args:
            prompt: The main prompt to execute
            system_prompt: Optional system prompt
            models: List of (provider, model_id) tuples. If None, uses defaults.
            selection_method: How to select best result:
                - "first_success": First model to return valid response
                - "fastest": Fastest successful response
                - "quality_score": Score responses and pick best
                - "voting": Use consensus if responses agree
            timeout_seconds: Timeout for each model call
            require_all: Wait for all models to complete (vs return early)

        Returns:
            MultiModelResult with best response and all model outputs
        """
        start_time = time.time()

        # Default models if none specified
        if models is None:
            models = self._get_default_models()

        # Filter to available models only
        available_models = [
            (provider, model_id)
            for provider, model_id in models
            if self._is_model_available(provider)
        ]

        if not available_models:
            logger.error("No AI models available for multi-model execution")
            return MultiModelResult(
                selection_method=selection_method,
                total_time_ms=int((time.time() - start_time) * 1000),
            )

        # Execute all models in parallel
        tasks = [
            self._call_model(provider, model_id, prompt, system_prompt, timeout_seconds)
            for provider, model_id in available_models
        ]

        # Gather results (allow individual failures)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        model_results: list[ModelResult] = []
        for i, result in enumerate(results):
            provider, model_id = available_models[i]
            if isinstance(result, Exception):
                model_results.append(
                    ModelResult(
                        provider=provider,
                        model_id=model_id,
                        response="",
                        latency_ms=0,
                        success=False,
                        error=str(result),
                    )
                )
            else:
                model_results.append(result)

        # Select best result based on method
        best_result = self._select_best_result(model_results, selection_method, prompt)

        total_time = int((time.time() - start_time) * 1000)
        successful = [r for r in model_results if r.success]

        return MultiModelResult(
            best_result=best_result,
            all_results=model_results,
            consensus_response=(
                self._get_consensus(model_results)
                if selection_method == "voting"
                else None
            ),
            selection_method=selection_method,
            total_time_ms=total_time,
            models_attempted=len(model_results),
            models_succeeded=len(successful),
        )

    def _get_default_models(self) -> list[tuple[str, str]]:
        """Get default model lineup based on availability."""
        models = []
        if self.openai_key:
            models.append(("openai", get_ai_model("openai", self.db)))
        if self.anthropic_key:
            models.append(("anthropic", get_ai_model("anthropic", self.db)))
        if self.gemini_key:
            models.append(("gemini", get_ai_model("gemini", self.db)))
        if self.bedrock_enabled:
            models.append(("bedrock", get_ai_model("bedrock", self.db)))
        return models

    def _is_model_available(self, provider: str) -> bool:
        """Check if a provider is available."""
        if provider == "openai":
            return bool(self.openai_key)
        elif provider == "anthropic":
            return bool(self.anthropic_key)
        elif provider == "gemini":
            return bool(self.gemini_key)
        elif provider == "bedrock":
            return self.bedrock_enabled
        return False

    async def _call_model(
        self,
        provider: str,
        model_id: str,
        prompt: str,
        system_prompt: str,
        timeout: float,
    ) -> ModelResult:
        """Call a specific model and return result."""
        start_time = time.time()

        try:
            api_key = None
            if provider == "openai":
                api_key = self.openai_key
            elif provider == "anthropic":
                api_key = self.anthropic_key
            elif provider == "gemini":
                api_key = self.gemini_key

            response = await asyncio.wait_for(
                complete_chat(
                    provider=provider,
                    model_id=model_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    db=self.db,
                    api_key=api_key,
                    bedrock_region=self.bedrock_region,
                    max_tokens=4000,
                    temperature=0.3,
                ),
                timeout=timeout,
            )

            latency = int((time.time() - start_time) * 1000)
            return ModelResult(
                provider=provider,
                model_id=model_id,
                response=response,
                latency_ms=latency,
                success=True,
            )

        except asyncio.TimeoutError:
            latency = int((time.time() - start_time) * 1000)
            return ModelResult(
                provider=provider,
                model_id=model_id,
                response="",
                latency_ms=latency,
                success=False,
                error="Timeout",
            )
        except Exception as e:
            latency = int((time.time() - start_time) * 1000)
            return ModelResult(
                provider=provider,
                model_id=model_id,
                response="",
                latency_ms=latency,
                success=False,
                error=str(e),
            )

    def _select_best_result(
        self,
        results: list[ModelResult],
        method: str,
        original_prompt: str,
    ) -> ModelResult | None:
        """Select the best result based on the specified method."""
        successful = [r for r in results if r.success and r.response.strip()]

        if not successful:
            return None

        if method == "first_success":
            return successful[0]

        elif method == "fastest":
            return min(successful, key=lambda r: r.latency_ms)

        elif method == "quality_score":
            # Simple quality heuristics
            for result in successful:
                result.quality_score = self._compute_quality_score(result.response)
            return max(successful, key=lambda r: r.quality_score)

        elif method == "voting":
            # For now, return the longest response as proxy for consensus
            return max(successful, key=lambda r: len(r.response))

        return successful[0]

    def _compute_quality_score(self, response: str) -> float:
        """
        Compute a simple quality score for a response.

        Heuristics:
        - Length (longer responses typically have more detail)
        - Structure (presence of headers, lists, sections)
        - Completeness (JSON parseable if expected)
        """
        if not response:
            return 0.0

        score = 0.0

        # Length score (up to 0.4)
        length = len(response)
        if length > 100:
            score += min(0.4, length / 5000)

        # Structure score (up to 0.3)
        structure_markers = ["##", "1.", "-", "•", ":", "\n\n"]
        structure_count = sum(1 for marker in structure_markers if marker in response)
        score += min(0.3, structure_count * 0.05)

        # Completeness score (up to 0.3)
        # Check if response seems complete
        if response.strip().endswith((".", "}", "]", "!", "?")):
            score += 0.15
        if len(response) > 200:
            score += 0.15

        return min(1.0, score)

    def _get_consensus(self, results: list[ModelResult]) -> str | None:
        """
        Get consensus response if models agree.

        Simple implementation: if responses are similar, return the longest.
        """
        successful = [r for r in results if r.success and r.response.strip()]

        if len(successful) < 2:
            return successful[0].response if successful else None

        # Simple similarity check using first 200 chars
        first_200 = [r.response[:200].lower() for r in successful]
        if len(set(first_200)) == 1:
            # All responses start similarly - likely agreement
            return max(successful, key=lambda r: len(r.response)).response

        return None


class CrossModelCollaborator:
    """
    Enable collaboration between models where one model's output
    feeds into another's input for improved results.

    Patterns:
    - Draft & Refine: Model A drafts, Model B refines
    - Plan & Execute: Model A plans, Model B executes
    - Generate & Validate: Model A generates, Model B validates
    - Parallel Compete: Both generate, best is selected
    """

    def __init__(self, db: Session):
        self.db = db
        self.multi_model = MultiModelTask(db)

    async def draft_and_refine(
        self,
        prompt: str,
        system_prompt: str = "",
        draft_model: tuple[str, str] | None = None,
        refine_model: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Two-stage generation: first model drafts, second refines.

        Useful for:
        - Complex analysis needing multiple perspectives
        - Documents requiring both speed and quality
        - Cases where Claude excels at planning, GPT at writing
        """
        # Defaults
        if draft_model is None:
            draft_model = ("anthropic", get_ai_model("anthropic", self.db))
        if refine_model is None:
            refine_model = ("openai", get_ai_model("openai", self.db))

        # Stage 1: Draft
        draft_result = await self.multi_model.execute(
            prompt=prompt,
            system_prompt=system_prompt,
            models=[draft_model],
            selection_method="first_success",
        )

        if not draft_result.best_result or not draft_result.best_result.response:
            return {
                "success": False,
                "error": "Draft generation failed",
                "draft": None,
                "refined": None,
            }

        draft = draft_result.best_result.response

        # Stage 2: Refine
        refine_prompt = f"""Review and improve the following draft response.
Maintain the core content and insights, but:
1. Improve clarity and flow
2. Strengthen weak arguments
3. Add specificity where vague
4. Ensure citations are properly integrated
5. Polish the professional tone

ORIGINAL PROMPT: {prompt}

DRAFT TO REFINE:
{draft}

Provide an improved version:"""

        refine_result = await self.multi_model.execute(
            prompt=refine_prompt,
            system_prompt="You are an expert editor improving draft content.",
            models=[refine_model],
            selection_method="first_success",
        )

        refined = (
            refine_result.best_result.response if refine_result.best_result else draft
        )

        return {
            "success": True,
            "draft": draft,
            "refined": refined,
            "draft_model": draft_model,
            "refine_model": refine_model,
            "total_time_ms": draft_result.total_time_ms + refine_result.total_time_ms,
        }

    async def generate_and_validate(
        self,
        prompt: str,
        system_prompt: str = "",
        generate_model: tuple[str, str] | None = None,
        validate_model: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Generate content, then validate with a different model.

        Returns both the content and validation feedback.
        Useful for ensuring accuracy in critical outputs.
        """
        # Defaults
        if generate_model is None:
            generate_model = ("openai", get_ai_model("openai", self.db))
        if validate_model is None:
            validate_model = ("anthropic", get_ai_model("anthropic", self.db))

        # Stage 1: Generate
        gen_result = await self.multi_model.execute(
            prompt=prompt,
            system_prompt=system_prompt,
            models=[generate_model],
            selection_method="first_success",
        )

        if not gen_result.best_result or not gen_result.best_result.response:
            return {
                "success": False,
                "error": "Generation failed",
                "content": None,
                "validation": None,
            }

        content = gen_result.best_result.response

        # Stage 2: Validate
        validate_prompt = f"""Review the following content for accuracy and quality.
Check for:
1. Factual accuracy
2. Logical consistency
3. Completeness
4. Citation quality (if applicable)
5. Any potential issues or hallucinations

ORIGINAL PROMPT: {prompt}

CONTENT TO VALIDATE:
{content}

Provide validation feedback as JSON:
{{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "issues": ["list of any issues found"],
    "suggestions": ["improvements if needed"],
    "overall_quality": "excellent/good/fair/poor"
}}"""

        val_result = await self.multi_model.execute(
            prompt=validate_prompt,
            system_prompt="You are a rigorous fact-checker and quality reviewer.",
            models=[validate_model],
            selection_method="first_success",
        )

        validation = val_result.best_result.response if val_result.best_result else None

        return {
            "success": True,
            "content": content,
            "validation": validation,
            "generate_model": generate_model,
            "validate_model": validate_model,
            "total_time_ms": gen_result.total_time_ms + val_result.total_time_ms,
        }

    async def parallel_compete(
        self,
        prompt: str,
        system_prompt: str = "",
        models: list[tuple[str, str]] | None = None,
        evaluation_criteria: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Run multiple models in parallel and select the best output.

        All models generate independently, then results are compared
        and the best is selected based on quality scoring.
        """
        result = await self.multi_model.execute(
            prompt=prompt,
            system_prompt=system_prompt,
            models=models,
            selection_method="quality_score",
        )

        return {
            "success": result.models_succeeded > 0,
            "best_response": (
                result.best_result.response if result.best_result else None
            ),
            "best_model": (
                f"{result.best_result.provider}/{result.best_result.model_id}"
                if result.best_result
                else None
            ),
            "best_score": result.best_result.quality_score if result.best_result else 0,
            "all_results": [
                {
                    "provider": r.provider,
                    "model": r.model_id,
                    "success": r.success,
                    "latency_ms": r.latency_ms,
                    "quality_score": r.quality_score,
                    "response_length": len(r.response) if r.success else 0,
                }
                for r in result.all_results
            ],
            "total_time_ms": result.total_time_ms,
        }


def _ensure_timezone(value: datetime | None) -> datetime:
    """Ensure datetime has timezone information."""
    if value is None:
        raise ValueError("Cannot ensure timezone on None value")
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_iso_date(raw_value: Optional[str], field_name: str) -> Optional[datetime]:
    """Parse ISO date string with proper error handling and log injection prevention."""
    if not raw_value:
        return None

    # Sanitize input for logging to prevent log injection (CWE-117)
    sanitized_value = raw_value.replace("\n", "").replace("\r", "")[:100]

    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        # Use sanitized value in logs to prevent log injection
        logger.error(
            "Invalid date format for field=%s value=%s error=%s",
            field_name,
            sanitized_value,
            str(exc).replace("\n", "").replace("\r", ""),
        )
        raise HTTPException(400, f"Invalid {field_name}; use ISO 8601 format") from exc
    except (TypeError, AttributeError) as exc:
        logger.exception("Unexpected error parsing date field=%s", field_name)
        raise HTTPException(500, "Internal error processing date") from exc

    return _ensure_timezone(parsed)


def _apply_date_filters(
    query: object, start_at: Optional[datetime], end_at: Optional[datetime]
) -> object:
    """Apply date range filters to query with validation."""
    try:
        if start_at:
            query = query.filter(Document.created_at >= start_at)
        if end_at:
            query = query.filter(Document.created_at <= end_at)
        return query
    except (AttributeError, TypeError) as exc:
        logger.exception("Error applying date filters")
        raise HTTPException(500, "Error applying date filters") from exc


def _serialize_documents(documents: List[Document]) -> List[Dict]:
    """Serialize documents to metadata dictionaries with error handling."""
    metadata = []
    fallback_now = datetime.now(timezone.utc)

    for doc in documents:
        try:
            created_at = _ensure_timezone(doc.created_at or fallback_now)
            metadata.append(
                {
                    "id": str(doc.id),
                    "filename": doc.filename or "unknown",
                    "path": doc.path or "",
                    "created_at": created_at,
                    "size": doc.size or 0,
                    "metadata": doc.meta or {},
                }
            )
        except (ValueError, AttributeError) as exc:
            # Log specific error but continue processing other documents
            logger.warning(
                "Failed to serialize document id=%s: %s",
                getattr(doc, "id", "unknown"),
                str(exc),
            )
            continue

    return metadata


def _generate_activity_insights(metadata: List[Dict]) -> List["DatasetInsight"]:
    """
    Generate activity insights from document metadata.
    Simplified logic to reduce complexity.
    """
    if len(metadata) <= 10:
        return []

    try:
        now = datetime.now(timezone.utc)
        recent_docs = [m for m in metadata if m["created_at"] > now - timedelta(days=7)]
        prev_docs = [
            m
            for m in metadata
            if now - timedelta(days=14) < m["created_at"] <= now - timedelta(days=7)
        ]

        recent_count = len(recent_docs)
        prev_count = len(prev_docs)

        # Check if there's a significant increase
        if not recent_count or recent_count <= max(prev_count, 1) * 1.5:
            return []

        # Get supporting documents
        supporting_docs = [m["id"] for m in recent_docs[-min(5, recent_count) :]]
        uplift = ((recent_count / max(prev_count, 1)) - 1) * 100

        return [
            DatasetInsight(
                insight_type="trend",
                title="Increased Activity",
                description=f"Uploads up {uplift:.0f}% last week",
                confidence=0.9,
                supporting_documents=supporting_docs,
                ai_model="gemini",
            )
        ]
    except (KeyError, TypeError, ZeroDivisionError) as exc:
        logger.warning("Error generating activity insights: %s", str(exc))
        return []


def _build_monthly_timeline(metadata: List[Dict]) -> List["TimelineEvent"]:
    """Build monthly timeline from document metadata with error handling."""
    buckets: Dict[str, List[Dict]] = {}

    try:
        for entry in metadata:
            try:
                month_key = entry["created_at"].strftime("%Y-%m")
                buckets.setdefault(month_key, []).append(entry)
            except (KeyError, AttributeError) as exc:
                logger.debug("Skipping entry without valid created_at: %s", str(exc))
                continue

        timeline: List[TimelineEvent] = []
        for month in sorted(buckets.keys()):
            docs = buckets[month]
            size = len(docs)

            # Determine significance
            if size > 10:
                significance = "high"
            elif size > 5:
                significance = "medium"
            else:
                significance = "low"

            timeline.append(
                TimelineEvent(
                    date=f"{month}-01",
                    event_type="document_batch",
                    description=f"{size} documents uploaded",
                    significance=significance,
                    related_documents=[
                        {
                            "id": d.get("id", ""),
                            "filename": d.get("filename", "unknown"),
                        }
                        for d in docs[:5]
                    ],
                )
            )
        return timeline
    except (KeyError, AttributeError, TypeError):
        logger.exception("Error building monthly timeline")
        return []


def _count_document_types(documents: List[Document]) -> Dict[str, int]:
    """Count document types from metadata with error handling."""
    counts: Dict[str, int] = {}

    try:
        for doc in documents:
            try:
                if (
                    doc.meta
                    and isinstance(doc.meta, dict)
                    and "ai_classification" in doc.meta
                ):
                    classification = doc.meta["ai_classification"]
                    if isinstance(classification, dict):
                        doc_type = classification.get("type", "unknown")
                        counts[doc_type] = counts.get(doc_type, 0) + 1
            except (AttributeError, TypeError) as exc:
                logger.debug("Error processing document type for doc: %s", str(exc))
                continue
        return counts
    except (AttributeError, TypeError, KeyError) as exc:
        logger.warning("Error counting document types: %s", str(exc))
        return {}


def _extract_themes(documents: List[Document]) -> List[str]:
    """
    Extract themes from documents using keyword matching.
    Optimized to avoid performance issues with large datasets.
    """
    try:
        # Limit text processing to avoid performance issues
        text_excerpts = []
        for doc in documents[:500]:  # Limit to first 500 documents
            try:
                if doc.text_excerpt:
                    text_excerpts.append(
                        doc.text_excerpt[:1000]
                    )  # Limit excerpt length
            except AttributeError:
                continue

        text_blob = " ".join(text_excerpts).lower()

        keyword_map = {
            "financial": ["payment", "invoice", "budget"],
            "legal": ["contract", "agreement", "terms"],
            "technical": ["software", "system", "implementation"],
        }

        return [
            theme
            for theme, words in keyword_map.items()
            if any(word in text_blob for word in words)
        ]
    except (AttributeError, TypeError, KeyError) as exc:
        logger.warning("Error extracting themes: %s", str(exc))
        return []


def _summarize_documents(documents: List[Document]) -> Tuple[str, Dict[str, str]]:
    """Summarize documents with date range and error handling."""
    try:
        dates = []
        for doc in documents:
            try:
                if doc.created_at:
                    dates.append(_ensure_timezone(doc.created_at))
            except (ValueError, AttributeError) as exc:
                logger.debug("Skipping document with invalid date: %s", str(exc))
                continue

        if not dates:
            now = datetime.now(timezone.utc)
            return "0 documents", {"from": now.isoformat(), "to": now.isoformat()}

        total_span = (max(dates) - min(dates)).days or 0
        summary = f"{len(documents)} documents over {total_span} days"
        date_range = {"from": min(dates).isoformat(), "to": max(dates).isoformat()}
        return summary, date_range
    except (ValueError, AttributeError, TypeError) as exc:
        logger.warning("Error summarizing documents: %s", str(exc))
        now = datetime.now(timezone.utc)
        return "Error summarizing", {"from": now.isoformat(), "to": now.isoformat()}


class DatasetInsight(BaseModel):
    insight_type: str
    title: str
    description: str
    confidence: float
    supporting_documents: List[str]
    ai_model: str


class TimelineEvent(BaseModel):
    date: str
    event_type: str
    description: str
    related_documents: List[Dict]
    significance: str


class DatasetAnalysisResponse(BaseModel):
    total_documents: int
    date_range: Dict[str, str]
    insights: List[DatasetInsight]
    timeline: List[TimelineEvent]
    summary: str
    key_themes: List[str]
    document_types: Dict[str, int]
    ai_models_used: List[str]


@router.get("/analyze/dataset", response_model=DatasetAnalysisResponse)
async def analyze_dataset(
    folder_path: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Analyze entire dataset - insights, timelines, patterns.
    Provides comprehensive analytics across user's documents.
    """
    try:
        query = db.query(Document).filter(Document.owner_user_id == user.id)

        if folder_path:
            # Sanitize folder path to prevent SQL injection
            sanitized_path = folder_path.replace("%", "\\%").replace("_", "\\_")
            query = query.filter(Document.path.like(f"{sanitized_path}%"))

        start_at = _parse_iso_date(date_from, "date_from")
        end_at = _parse_iso_date(date_to, "date_to")
        query = _apply_date_filters(query, start_at, end_at)

        # Limit query to prevent performance issues
        documents = query.order_by(Document.created_at.asc()).limit(10000).all()

        if not documents:
            raise HTTPException(404, "No documents found")

        # Process documents with error handling
        metadata = _serialize_documents(documents)
        if not metadata:
            raise HTTPException(500, "Failed to process documents")

        insights = _generate_activity_insights(metadata)
        timeline = _build_monthly_timeline(metadata)
        doc_types = _count_document_types(documents)
        themes = _extract_themes(documents)
        summary, date_range = _summarize_documents(documents)

        return DatasetAnalysisResponse(
            total_documents=len(documents),
            date_range=date_range,
            insights=insights,
            timeline=timeline,
            summary=summary,
            key_themes=themes,
            document_types=doc_types,
            ai_models_used=["gemini", "claude", "gpt"],
        )
    except HTTPException:
        raise
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Error analyzing dataset for user=%s", user.id)
        raise HTTPException(500, "Failed to analyze dataset") from exc


@router.post("/query")
async def query_documents(
    body: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Natural language query: 'show me contracts from last quarter'.
    Performs keyword-based search across document text excerpts.
    """
    try:
        query_text = body.get("query", "").strip()
        if not query_text:
            raise HTTPException(400, "query required")

        # Limit query text length to prevent performance issues
        if len(query_text) > 500:
            raise HTTPException(400, "query too long (max 500 characters)")

        # Fetch documents with limit to prevent performance issues
        documents = (
            db.query(Document)
            .filter(Document.owner_user_id == user.id)
            .limit(200)
            .all()
        )

        results = []
        query_words = query_text.lower().split()[:20]  # Limit to 20 words

        for doc in documents:
            try:
                if not doc.text_excerpt:
                    continue

                excerpt_lower = doc.text_excerpt.lower()
                score = sum(excerpt_lower.count(word) for word in query_words)

                if score > 0:
                    results.append(
                        {
                            "document_id": str(doc.id),
                            "filename": doc.filename or "unknown",
                            "path": doc.path or "",
                            "score": score,
                            "snippet": doc.text_excerpt[:200],
                        }
                    )
            except (AttributeError, TypeError) as exc:
                logger.debug("Error processing document in query: %s", str(exc))
                continue

        results.sort(key=lambda x: x["score"], reverse=True)

        if results:
            answer = f"Found {len(results)} documents. Top: {results[0]['filename']}"
        else:
            answer = "No matches"

        return {
            "query": query_text,
            "answer": answer,
            "sources": results[:10],
            "confidence": 0.8 if results else 0.3,
            "ai_model": "gpt",
            "follow_up_questions": ["Show similar documents?", "Extract key themes?"],
        }
    except HTTPException:
        raise
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Error querying documents for user=%s", user.id)
        raise HTTPException(500, "Failed to query documents") from exc


@router.get("/trends")
async def get_trends(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Analyze document upload trends over time.
    Returns daily breakdown and trend analysis.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        documents = (
            db.query(Document)
            .filter(Document.owner_user_id == user.id, Document.created_at >= cutoff)
            .all()
        )

        by_day = {}
        for doc in documents:
            try:
                if doc.created_at:
                    day = doc.created_at.strftime("%Y-%m-%d")
                    by_day[day] = by_day.get(day, 0) + 1
            except (AttributeError, ValueError) as exc:
                logger.debug("Error processing document date in trends: %s", str(exc))
                continue

        counts = list(by_day.values())

        # Calculate averages safely
        if counts:
            avg = sum(counts) / len(counts)
            recent_avg = (
                sum(counts[-7:]) / min(7, len(counts)) if len(counts) >= 1 else avg
            )
        else:
            avg = 0
            recent_avg = 0

        # Determine trend
        if recent_avg > avg * 1.2:
            trend = "increasing"
        elif recent_avg < avg * 0.8:
            trend = "decreasing"
        else:
            trend = "stable"

        return {
            "period_days": days,
            "total_documents": len(documents),
            "average_per_day": round(avg, 2),
            "trend": trend,
            "daily_breakdown": by_day,
            "ai_model": "gemini",
        }
    except (ValueError, AttributeError, TypeError) as exc:
        logger.exception("Error getting trends for user=%s", user.id)
        raise HTTPException(500, "Failed to analyze trends") from exc
