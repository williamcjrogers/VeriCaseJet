# pyright: reportMissingTypeStubs=false
"""
AI Evidence Assistant - Multi-Model Deep Research
Helps users understand their evidence, build chronologies, and develop narratives
Uses GPT-5.1, Gemini 3 Pro, Claude Opus 4.5, and Amazon Bedrock for comprehensive analysis
"""

import logging
import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from enum import Enum
from html import unescape

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session, load_only
from sqlalchemy import or_

try:
    # OpenSearch is optional in some deployments.
    from .search import client as _get_opensearch_client
except Exception:  # pragma: no cover
    _get_opensearch_client = None  # type: ignore

from .models import User, EmailMessage, Project, Case
from .db import get_db
from .config import settings
from .security import current_user
from .ai_settings import (
    AISettings,
    get_ai_api_key,
    get_ai_model,
    is_bedrock_enabled,
    get_bedrock_region,
    is_fallback_enabled,
    get_function_config,
)
from .ai_models import (
    AIModelService,
    TaskComplexity,
    log_model_selection,
)
from .ai_providers import BedrockProvider, bedrock_available

try:
    from .aws_services import get_aws_services  # Optional KB augmentation
except Exception:  # pragma: no cover
    get_aws_services = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-chat", tags=["ai-chat"])


# Guardrails: keep AI requests responsive even on very large projects.
#
# IMPORTANT: Even if you have 100k+ emails, you still cannot send them all to an LLM in
# a single prompt. The scalable approach is retrieval: search the full corpus to select
# the most relevant subset for the question.
#
# These values are *context limits* (what we send to the model), not dataset limits.
_AI_CONTEXT_MAX_EMAILS_QUICK = 250
_AI_CONTEXT_MAX_EMAILS_DEEP = 600

# For DB-only fallback retrieval (when OpenSearch is unavailable), bound the initial
# candidate pool to avoid loading the entire corpus into memory.
_AI_DB_CANDIDATE_POOL_CAP = 20000

# For OpenSearch retrieval, we may need to scan many hits (then filter by project_id)
# when the email index does not contain project_id.
_AI_OPENSEARCH_SCAN_CAP = 10000


def _tokenize_query_for_scoring(query: str) -> list[str]:
    """Extract lightweight tokens from user query for simple relevance scoring."""
    if not query:
        return []

    # Keep simple, fast, and DB-agnostic: no full-text search assumptions.
    tokens = re.findall(r"[a-zA-Z0-9]{3,}", query.lower())
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "what",
        "when",
        "where",
        "who",
        "why",
        "how",
        "about",
        "into",
        "over",
        "under",
        "between",
        "within",
        "their",
        "there",
        "which",
        "would",
        "could",
        "should",
    }
    filtered: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if t in stop:
            continue
        if t in seen:
            continue
        seen.add(t)
        filtered.append(t)
        if len(filtered) >= 12:
            break
    return filtered


def _safe_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def _strip_highlight(text: str) -> str:
    """Remove typical OpenSearch highlight tags and decode HTML entities."""
    if not text:
        return ""
    # OpenSearch typically uses <em> tags; also handle any stray HTML entities.
    cleaned = re.sub(r"</?em>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return unescape(cleaned)


def _opensearch_email_candidates(
    *,
    query_text: str,
    project_id: str | None,
    case_id: str | None,
    size: int,
) -> list[dict[str, Any]]:
    """Retrieve candidate email IDs (and optional snippets) from OpenSearch.

    We *prefer* a project-scoped query when project_id is provided. However, older
    deployments may have an "emails" index that lacks project_id for historical docs.
    In that case, we transparently fall back to an unscoped OpenSearch query and
    apply project/case filtering at the DB layer.
    """
    if _get_opensearch_client is None:
        return []

    query_text = (query_text or "").strip()
    if not query_text:
        return []

    def _build_query(*, include_project_filter: bool) -> dict[str, Any]:
        must: list[dict[str, Any]] = [
            {
                "multi_match": {
                    "query": query_text,
                    "fields": [
                        "subject^5",
                        "body_clean^4",
                        "body^3",
                        "sender_name^1",
                    ],
                    "type": "best_fields",
                    "operator": "and",
                    "fuzziness": "AUTO",
                }
            }
        ]

        # Phrase boosts help precision for short or exact questions.
        should: list[dict[str, Any]] = [
            {"match_phrase": {"subject": {"query": query_text, "slop": 2, "boost": 6}}},
            {
                "match_phrase": {
                    "body_clean": {"query": query_text, "slop": 6, "boost": 3}
                }
            },
        ]

        # If the query contains an email address, strongly boost sender/recipient matches.
        for addr in set(
            re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", query_text)
        ):
            should.append(
                {"term": {"sender_email": {"value": addr.lower(), "boost": 10}}}
            )
            should.append({"term": {"recipients": {"value": addr.lower(), "boost": 6}}})

        filters: list[dict[str, Any]] = []
        if case_id:
            filters.append({"term": {"case_id": case_id}})
        if include_project_filter and project_id:
            filters.append({"term": {"project_id": project_id}})

        return {
            "size": size,
            "track_total_hits": False,
            "_source": [
                "id",
                "case_id",
                "project_id",
                "thread_group_id",
                "thread_id",
                "date_sent",
            ],
            "query": {
                "function_score": {
                    "query": {
                        "bool": {
                            "must": must,
                            "filter": filters,
                            "should": should,
                        }
                    },
                    # Small recency preference without swamping relevance.
                    "score_mode": "sum",
                    "boost_mode": "sum",
                    "functions": [
                        {
                            "gauss": {
                                "date_sent": {
                                    "origin": "now",
                                    "scale": "365d",
                                    "decay": 0.5,
                                }
                            },
                            "weight": 0.15,
                        }
                    ],
                }
            },
            "highlight": {
                "fields": {
                    "subject": {
                        "fragment_size": 160,
                        "number_of_fragments": 1,
                        "no_match_size": 0,
                    },
                    "body_clean": {
                        "fragment_size": 240,
                        "number_of_fragments": 2,
                        "no_match_size": 0,
                    },
                    "body": {
                        "fragment_size": 240,
                        "number_of_fragments": 2,
                        "no_match_size": 0,
                    },
                },
                "max_analyzed_offset": 1000000,
            },
        }

    def _run(include_project_filter: bool) -> list[dict[str, Any]]:
        client = _get_opensearch_client()
        body = _build_query(include_project_filter=include_project_filter)
        try:
            res = client.search(index="emails", body=body)
        except Exception as e:
            # Retry without highlighting if highlighting is unsupported / fails.
            logger.debug("OpenSearch query failed (with highlights): %s", e)
            body.pop("highlight", None)
            res = client.search(index="emails", body=body)

        hits = (res or {}).get("hits", {}).get("hits", [])
        out: list[dict[str, Any]] = []
        for h in hits:
            src = h.get("_source") or {}
            email_id = src.get("id") or h.get("_id")
            if not email_id:
                continue

            hl = h.get("highlight") or {}
            fragments: list[str] = []
            for field in ("body_clean", "body", "subject"):
                frag_list = hl.get(field) or []
                if frag_list:
                    fragments.extend([_strip_highlight(f) for f in frag_list if f])

            snippet = " ".join([f for f in fragments if f])[:800]
            out.append({"id": str(email_id), "snippet": snippet})
        return out

    try:
        # Prefer project-scoped search when project_id provided.
        if project_id:
            candidates = _run(include_project_filter=True)
            if candidates:
                return candidates
            # Fallback: older indices may not have project_id populated.
            return _run(include_project_filter=False)
        return _run(include_project_filter=False)
    except Exception as e:
        logger.debug("OpenSearch email retrieval failed; falling back to DB: %s", e)
        return []


class ResearchMode(str, Enum):
    QUICK = "quick"
    DEEP = "deep"


class ResearchPlan(BaseModel):
    """Research plan for deep analysis"""

    objective: str
    analysis_steps: list[str]
    models_assigned: dict[str, str]  # model -> task
    estimated_time: str


class ModelResponse(BaseModel):
    """Response from a single AI model"""

    model: str
    task: str
    response: str
    confidence: float
    processing_time: float
    key_findings: list[str]


class EvidenceSource(BaseModel):
    """Source email or document referenced"""

    email_id: str
    subject: str
    date: datetime
    sender: str
    relevance: str


class KBSource(BaseModel):
    """Source item from Bedrock Knowledge Base retrieval"""

    content: str
    score: float | None = None
    metadata: dict[str, Any] = {}
    location: dict[str, Any] = {}


class ChatRequest(BaseModel):
    query: str
    mode: ResearchMode
    project_id: str | None = None
    case_id: str | None = None


class ChatResponse(BaseModel):
    query: str
    mode: str
    plan: ResearchPlan | None = None
    answer: str
    model_responses: list[ModelResponse]
    sources: list[EvidenceSource]
    kb_sources: list[KBSource] = []
    chronology_events: list[dict[str, Any]]
    key_findings: list[str]
    processing_time: float
    timestamp: datetime


class AIEvidenceOrchestrator:
    """Orchestrates multiple AI models for evidence analysis"""

    def __init__(self, db: Session | None = None):
        # Load API keys from database settings (with env var fallback)
        # Supports 6 providers: OpenAI, Anthropic, Gemini, Amazon Bedrock, xAI (Grok), Perplexity
        self.db = db
        self.openai_key = get_ai_api_key("openai", db) or ""
        self.anthropic_key = get_ai_api_key("anthropic", db) or ""
        self.gemini_key = get_ai_api_key("gemini", db) or ""
        self.xai_key = get_ai_api_key("xai", db) or ""
        self.perplexity_key = get_ai_api_key("perplexity", db) or ""

        # Bedrock uses IAM credentials, not API keys
        self.bedrock_enabled = is_bedrock_enabled(db) and bedrock_available()
        self.bedrock_region = get_bedrock_region(db)
        self._bedrock_provider: BedrockProvider | None = None

        # Load model selections from database
        self.openai_model = get_ai_model("openai", db)
        self.anthropic_model = get_ai_model("anthropic", db)
        self.gemini_model = get_ai_model("gemini", db)
        self.bedrock_model = get_ai_model("bedrock", db)
        self.xai_model = get_ai_model("xai", db) or "grok-3-latest"
        self.perplexity_model = get_ai_model("perplexity", db) or "sonar-pro"

        self.model_service = AIModelService()

    @property
    def google_key(self) -> str:
        """Backwards-compatible alias for Gemini API key."""
        return self.gemini_key

    @google_key.setter
    def google_key(self, value: str) -> None:
        self.gemini_key = value or ""

    @property
    def bedrock_provider(self) -> BedrockProvider | None:
        """Lazy-load Bedrock provider"""
        if self._bedrock_provider is None and self.bedrock_enabled:
            try:
                self._bedrock_provider = BedrockProvider(region=self.bedrock_region)
            except Exception as e:
                logger.warning(f"Failed to initialize Bedrock provider: {e}")
        return self._bedrock_provider

    def refresh_settings(self, db: Session) -> None:
        """Reload settings from database"""
        AISettings.refresh_cache(db)
        self.openai_key = get_ai_api_key("openai", db) or ""
        self.anthropic_key = get_ai_api_key("anthropic", db) or ""
        self.gemini_key = get_ai_api_key("gemini", db) or ""
        self.xai_key = get_ai_api_key("xai", db) or ""
        self.perplexity_key = get_ai_api_key("perplexity", db) or ""
        self.bedrock_enabled = is_bedrock_enabled(db) and bedrock_available()
        self.bedrock_region = get_bedrock_region(db)
        self._bedrock_provider = None  # Reset to reload
        self.openai_model = get_ai_model("openai", db)
        self.anthropic_model = get_ai_model("anthropic", db)
        self.gemini_model = get_ai_model("gemini", db)
        self.bedrock_model = get_ai_model("bedrock", db)
        self.xai_model = get_ai_model("xai", db) or "grok-3-latest"
        self.perplexity_model = get_ai_model("perplexity", db) or "sonar-pro"

    async def quick_search(
        self, query: str, emails: list[EmailMessage]
    ) -> ModelResponse:
        """Quick evidence search using fastest model"""
        start_time = datetime.now(timezone.utc)

        context = self._build_evidence_context(emails)

        prompt = f"""You are an expert legal evidence analyst. Answer this question based ONLY on the evidence provided.

EVIDENCE:
{context}

QUESTION: {query}

Provide a clear, concise answer citing specific emails. If the evidence doesn't support an answer, say so."""

        model_config = self.model_service.select_model(
            "quick_search", TaskComplexity.BASIC
        )
        candidate_models = self.model_service.build_priority_queue(
            "quick_search", TaskComplexity.BASIC, model_config
        )

        attempts: list[str] = []

        for candidate in candidate_models:
            resolved = AIModelService.resolve_model(candidate)
            if not resolved:
                continue

            provider = resolved["provider"]
            model_name = resolved["model"]
            display_name = AIModelService.display_name(candidate)

            try:
                if provider in ("gemini", "google") and self.gemini_key:
                    response_text = await self._query_gemini_flash(prompt, model_name)
                elif provider == "openai" and self.openai_key:
                    response_text = await self._query_gpt_turbo(prompt, model_name)
                elif provider == "anthropic" and self.anthropic_key:
                    response_text = await self._query_claude_sonnet(prompt, model_name)
                elif provider == "bedrock" and self.bedrock_enabled:
                    response_text = await self._query_bedrock(prompt, model_name)
                else:
                    continue

                processing_time = (
                    datetime.now(timezone.utc) - start_time
                ).total_seconds()
                log_model_selection(
                    "quick_search", display_name, f"{provider}:{model_name}"
                )

                return ModelResponse(
                    model=display_name,
                    task="Quick Evidence Search",
                    response=response_text,
                    confidence=0.87,
                    processing_time=processing_time,
                    key_findings=self._extract_key_findings(response_text),
                )
            except Exception as exc:
                attempts.append(f"{display_name}: {exc}")
                logger.debug("Quick search candidate %s failed: %s", display_name, exc)
                continue

        error_detail = attempts or ["No AI models configured. Add API keys to .env"]
        raise HTTPException(500, f"Quick search failed -> {', '.join(error_detail)}")

    async def deep_research(
        self, query: str, emails: list[EmailMessage]
    ) -> tuple[ResearchPlan, list[ModelResponse]]:
        """
        Deep multi-model evidence research:
        1. Create research plan
        2. Assign tasks to different models
        3. Execute in parallel
        4. Synthesize findings
        """
        # Build comprehensive evidence context
        context = self._build_evidence_context(emails, detailed=True)

        # Step 1: Create research plan
        plan = await self._create_evidence_plan(query, emails)

        # Step 2: Execute research across models with specific tasks
        model_config = self.model_service.select_model(
            "deep_research", TaskComplexity.DEEP_RESEARCH
        )
        prioritized = self.model_service.build_priority_queue(
            "deep_research", TaskComplexity.DEEP_RESEARCH, model_config
        )

        tasks = []
        scheduled: set[str] = set()

        for candidate in prioritized:
            if candidate in scheduled:
                continue
            resolved = AIModelService.resolve_model(candidate)
            if not resolved:
                continue

            provider = resolved["provider"]
            model_name = resolved["model"]
            display_name = AIModelService.display_name(candidate)

            if provider == "openai" and self.openai_key:
                tasks.append(
                    self._gpt5_analyze_chronology(
                        query, context, emails, model_name, display_name
                    )
                )
            elif provider in ("gemini", "google") and self.gemini_key:
                tasks.append(
                    self._gemini_find_patterns(
                        query, context, emails, model_name, display_name
                    )
                )
            elif provider == "anthropic" and self.anthropic_key:
                tasks.append(
                    self._claude_build_narrative(
                        query, context, emails, model_name, display_name
                    )
                )
            elif provider == "bedrock" and self.bedrock_enabled:
                tasks.append(
                    self._bedrock_identify_gaps(
                        query, context, emails, model_name, display_name
                    )
                )
            else:
                continue

            scheduled.add(candidate)

        if not tasks:
            raise HTTPException(500, "No AI models configured. Add API keys to .env")

        # Execute all in parallel
        model_responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter valid responses
        valid_responses = [r for r in model_responses if isinstance(r, ModelResponse)]

        if not valid_responses:
            raise HTTPException(500, "All AI models failed")

        return plan, valid_responses

    async def _create_evidence_plan(
        self, query: str, emails: list[EmailMessage]
    ) -> ResearchPlan:
        """Create strategic research plan for evidence analysis"""

        # Analyze query type
        query_lower = query.lower()

        if any(
            word in query_lower
            for word in ["chronology", "timeline", "sequence", "when"]
        ):
            focus = "chronology"
        elif any(
            word in query_lower
            for word in ["delay", "critical", "programme", "schedule"]
        ):
            focus = "delay_analysis"
        elif any(
            word in query_lower
            for word in ["narrative", "story", "explain", "what happened"]
        ):
            focus = "narrative"
        elif any(
            word in query_lower for word in ["find", "search", "locate", "show me"]
        ):
            focus = "document_retrieval"
        else:
            focus = "general_analysis"

        plans = {
            "chronology": {
                "steps": [
                    "Extract all dated events from emails",
                    "Identify causal relationships",
                    "Build sequential timeline",
                    "Highlight critical path events",
                ],
                "models": {
                    "GPT-5 Pro": "Chronological sequencing and event extraction",
                    "Gemini 3.0 Pro": "Pattern recognition across timeline",
                    "Claude Opus 4.5": "Narrative construction and causation",
                    "Amazon Nova Pro": "Gap identification and missing evidence",
                },
            },
            "delay_analysis": {
                "steps": [
                    "Identify delay events and causes",
                    "Map delays to responsible parties",
                    "Calculate time impacts",
                    "Assess liability and entitlement",
                ],
                "models": {
                    "GPT-5 Pro": "Delay event identification and quantification",
                    "Gemini 3.0 Pro": "Causation analysis and responsibility",
                    "Claude Opus 4.5": "Legal implications and entitlement",
                    "Amazon Nova Pro": "Risk assessment and strategic insights",
                },
            },
            "narrative": {
                "steps": [
                    "Identify key events and actors",
                    "Map relationships and communications",
                    "Build coherent narrative arc",
                    "Highlight supporting evidence",
                ],
                "models": {
                    "GPT-5 Pro": "Narrative structure and flow",
                    "Gemini 3.0 Pro": "Evidence mapping and connections",
                    "Claude Opus 4.5": "Legal narrative and argumentation",
                    "Amazon Nova Pro": "Alternative perspectives and weaknesses",
                },
            },
            "document_retrieval": {
                "steps": [
                    "Search across all correspondence",
                    "Identify relevant emails and attachments",
                    "Rank by relevance",
                    "Extract key passages",
                ],
                "models": {
                    "GPT-5 Pro": "Semantic search and relevance ranking",
                    "Gemini 3.0 Pro": "Context understanding and extraction",
                    "Claude Opus 4.5": "Legal relevance assessment",
                    "Amazon Nova Pro": "Hidden connections and insights",
                },
            },
            "general_analysis": {
                "steps": [
                    "Understand the question",
                    "Review all relevant evidence",
                    "Synthesize findings",
                    "Provide actionable insights",
                ],
                "models": {
                    "GPT-5 Pro": "Comprehensive evidence review",
                    "Gemini 3.0 Pro": "Pattern and trend analysis",
                    "Claude Opus 4.5": "Legal reasoning and implications",
                    "Amazon Nova Pro": "Strategic recommendations",
                },
            },
        }

        plan_data = plans.get(focus, plans["general_analysis"])
        steps = plan_data["steps"]
        models = plan_data["models"]

        return ResearchPlan(
            objective=query,
            analysis_steps=steps if isinstance(steps, list) else [],
            models_assigned=models if isinstance(models, dict) else {},
            estimated_time="30-60 seconds",
        )

    def _build_evidence_context(
        self, emails: list[EmailMessage], detailed: bool = False
    ) -> str:
        """Build evidence context from emails.

        NOTE: This must remain bounded. Sending tens of thousands of emails
        into a single prompt can exceed practical context limits and can also
        lead to upstream proxy 502s/timeouts.
        """
        if not emails:
            return "No evidence available."

        total = len(emails)
        max_emails = (
            _AI_CONTEXT_MAX_EMAILS_DEEP if detailed else _AI_CONTEXT_MAX_EMAILS_QUICK
        )

        # Sort by date (most recent first) then cap.
        emails = sorted(
            emails,
            key=lambda e: e.date_sent or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        if len(emails) > max_emails:
            emails = emails[:max_emails]

        context_parts = []
        if total > len(emails):
            context_parts.append(
                f"NOTE: Evidence truncated for performance. Using {len(emails)} of {total} emails."
            )

        for i, email in enumerate(emails, 1):
            # Prefer query-focused snippets (e.g., OpenSearch highlights) if present.
            content = (
                getattr(email, "_ai_retrieval_snippet", None)
                or getattr(email, "body_preview", None)
                or ""
            )
            if not content and detailed:
                # Fall back to full text only in detailed mode; may be absent if not loaded.
                content = getattr(email, "body_text", None) or ""
            if detailed:
                context_parts.append(
                    f"[Email {i}]\n"
                    f"ID: {email.id}\n"
                    f"Date: {email.date_sent.strftime('%Y-%m-%d %H:%M') if email.date_sent else 'Unknown'}\n"
                    f"From: {email.sender_name or email.sender_email or 'Unknown'}\n"
                    f"To: {email.recipients_to or 'Unknown'}\n"
                    f"Subject: {email.subject or 'No subject'}\n"
                    f"Content: {content[:800]}\n"
                    f"Attachments: {getattr(email, 'attachment_count', 0) or 0}\n"
                    f"---"
                )
            else:
                context_parts.append(
                    f"[{i}] {email.date_sent.strftime('%Y-%m-%d') if email.date_sent else 'Unknown'} | "
                    f"{email.sender_name or 'Unknown'} | {email.subject or 'No subject'} | "
                    f"{content[:200]}"
                )

        return "\n\n".join(context_parts)

    def _extract_key_findings(self, text: str) -> list[str]:
        """Extract key findings from AI response"""
        # Simple extraction - look for bullet points or numbered lists
        findings = []
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith(("- ", "* ", "• ")) or (
                len(line) > 0 and line[0].isdigit() and ". " in line
            ):
                findings.append(line.lstrip("-*•0123456789. "))

        return findings[:5]  # Top 5 findings

    # Model-specific methods with evidence focus

    async def _query_gemini_flash(self, prompt: str, model_name: str = None) -> str:
        """Gemini Flash for quick responses"""
        try:
            from .ai_runtime import complete_chat

            actual_model: str = model_name or self.gemini_model or "gemini-2.5-flash"
            return await complete_chat(
                provider="gemini",
                model_id=actual_model,
                prompt=prompt,
                api_key=self.gemini_key,
                max_tokens=1000,
                temperature=0.7,
            )
        except Exception as e:
            raise Exception(f"Gemini error: {str(e)}")

    async def _query_gpt_turbo(self, prompt: str, model_name: str = None) -> str:
        """GPT-4 Turbo for quick responses"""
        try:
            from .ai_runtime import complete_chat

            actual_model: str = model_name or self.openai_model or "gpt-5.2-instant"
            return await complete_chat(
                provider="openai",
                model_id=actual_model,
                prompt=prompt,
                api_key=self.openai_key,
                max_tokens=1000,
                temperature=0.3,
            )
        except Exception as e:
            raise Exception(f"GPT error: {str(e)}")

    async def _query_claude_sonnet(self, prompt: str, model_name: str = None) -> str:
        """Claude Sonnet for structured quick responses"""
        try:
            from .ai_runtime import complete_chat

            actual_model: str = (
                model_name or self.anthropic_model or "claude-sonnet-4.5"
            )
            return await complete_chat(
                provider="anthropic",
                model_id=actual_model,
                prompt=prompt,
                api_key=self.anthropic_key,
                max_tokens=1200,
                temperature=0.3,
            )
        except Exception as e:
            raise Exception(f"Claude error: {str(e)}")

    async def _gpt5_analyze_chronology(
        self,
        query: str,
        context: str,
        emails: list[EmailMessage],
        model_override: str | None = None,
        friendly_name: str = "ChatGPT 5 Pro Deep Research",
    ) -> ModelResponse:
        """GPT-5 Pro: Build chronology and identify key events"""
        start_time = datetime.now(timezone.utc)

        try:
            from .ai_runtime import complete_chat

            prompt = f"""You are a construction dispute expert analyzing email evidence to build a chronology.

EVIDENCE:
{context}

TASK: {query}

Focus on:
1. Extracting dated events in chronological order
2. Identifying cause-and-effect relationships
3. Highlighting critical path events
4. Noting delays and their causes

Provide a structured chronology with dates, events, and responsible parties."""

            response_text = await complete_chat(
                provider="openai",
                model_id=model_override or "gpt-5.2-thinking",
                prompt=prompt,
                api_key=self.openai_key,
                max_tokens=2000,
                temperature=0.2,
            )

            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            log_model_selection(
                "deep_research",
                friendly_name,
                f"OpenAI:{model_override or 'gpt-5.2-thinking'}",
            )

            return ModelResponse(
                model=friendly_name,
                task="Chronology Analysis & Event Sequencing",
                response=response_text,
                confidence=0.95,
                processing_time=processing_time,
                key_findings=self._extract_key_findings(response_text),
            )
        except Exception as e:
            logger.error(f"GPT-5 chronology error: {e}")
            return ModelResponse(
                model=friendly_name,
                task="Chronology Analysis",
                response=f"Model unavailable: {str(e)}",
                confidence=0.0,
                processing_time=0.0,
                key_findings=[],
            )

    async def _gemini_find_patterns(
        self,
        query: str,
        context: str,
        emails: list[EmailMessage],
        model_override: str | None = None,
        friendly_name: str = "Gemini 2.5 Pro Deep Think",
    ) -> ModelResponse:
        """Gemini 2.5 Pro: Find patterns and connections in evidence"""
        start_time = datetime.now(timezone.utc)

        try:
            from .ai_runtime import complete_chat

            prompt = f"""You are analyzing construction dispute evidence to find patterns and connections.

EVIDENCE:
{context}

TASK: {query}

Focus on:
1. Recurring themes and patterns
2. Relationships between parties
3. Communication breakdowns
4. Evidence of delays or issues
5. Contractual obligations mentioned

Identify patterns that tell the story of what happened."""

            response_text = await complete_chat(
                provider="gemini",
                model_id=model_override or "gemini-2.5-pro",
                prompt=prompt,
                api_key=self.gemini_key,
                max_tokens=2500,
                temperature=0.5,
            )
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            log_model_selection(
                "deep_research",
                friendly_name,
                f"Gemini:{model_override or 'gemini-2.5-pro'}",
            )

            return ModelResponse(
                model=friendly_name,
                task="Pattern Recognition & Connection Mapping",
                response=response_text,
                confidence=0.93,
                processing_time=processing_time,
                key_findings=self._extract_key_findings(response_text),
            )
        except Exception as e:
            logger.error(f"Gemini pattern error: {e}")
            return ModelResponse(
                model=friendly_name,
                task="Pattern Recognition",
                response=f"Model unavailable: {str(e)}",
                confidence=0.0,
                processing_time=0.0,
                key_findings=[],
            )

    async def _claude_build_narrative(
        self,
        query: str,
        context: str,
        emails: list[EmailMessage],
        model_override: str | None = None,
        friendly_name: str = "Sonnet 4.5 Extended Thinking",
    ) -> ModelResponse:
        """Claude Opus 4.1: Build coherent narrative from evidence"""
        start_time = datetime.now(timezone.utc)

        try:
            from .ai_runtime import complete_chat

            prompt = f"""You are a legal narrative expert helping build a dispute case from email evidence.

EVIDENCE:
{context}

TASK: {query}

Focus on:
1. Constructing a clear, compelling narrative
2. Identifying key actors and their roles
3. Establishing causation and liability
4. Highlighting evidence strengths and weaknesses
5. Suggesting narrative structure for legal argument

Build a narrative that explains what happened and why it matters."""

            response_text = await complete_chat(
                provider="anthropic",
                model_id=model_override or "claude-sonnet-4.5",
                prompt=prompt,
                api_key=self.anthropic_key,
                max_tokens=4096,
                temperature=0.3,
            )
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            log_model_selection(
                "deep_research",
                friendly_name,
                f"Anthropic:{model_override or 'claude-sonnet-4.5'}",
            )

            return ModelResponse(
                model=friendly_name,
                task="Narrative Construction & Legal Reasoning",
                response=response_text,
                confidence=0.96,
                processing_time=processing_time,
                key_findings=self._extract_key_findings(response_text),
            )
        except Exception as e:
            logger.error(f"Claude narrative error: {e}")
            return ModelResponse(
                model=friendly_name,
                task="Narrative Construction",
                response=f"Model unavailable: {str(e)}",
                confidence=0.0,
                processing_time=0.0,
                key_findings=[],
            )

    async def _query_bedrock(self, prompt: str, model_name: str | None = None) -> str:
        """Query Amazon Bedrock for quick responses"""
        if not self.bedrock_provider:
            raise RuntimeError("Bedrock provider not available")

        from .ai_runtime import complete_chat

        actual_model = model_name or self.bedrock_model or "amazon.nova-pro-v1:0"
        return await complete_chat(
            provider="bedrock",
            model_id=actual_model,
            prompt=prompt,
            bedrock_provider=self.bedrock_provider,
            bedrock_region=self.bedrock_region,
            max_tokens=1500,
            temperature=0.7,
        )

    async def _bedrock_identify_gaps(
        self,
        query: str,
        context: str,
        emails: list[EmailMessage],
        model_override: str | None = None,
        friendly_name: str = "Amazon Nova Pro",
    ) -> ModelResponse:
        """Amazon Bedrock: Identify gaps and missing evidence using Nova or Claude"""
        start_time = datetime.now(timezone.utc)

        try:
            if not self.bedrock_provider:
                raise RuntimeError("Bedrock provider not available")

            prompt = f"""You are analyzing construction dispute evidence with a critical eye.

EVIDENCE:
{context}

TASK: {query}

Focus on:
1. What evidence is missing or incomplete?
2. What questions remain unanswered?
3. Where are the gaps in the chronology?
4. What additional evidence would strengthen the case?
5. What are the risks and weaknesses?

Provide a critical analysis identifying gaps and suggesting what's needed."""

            from .ai_runtime import complete_chat

            actual_model = (
                model_override or self.bedrock_model or "amazon.nova-pro-v1:0"
            )
            response_text = await complete_chat(
                provider="bedrock",
                model_id=actual_model,
                prompt=prompt,
                system_prompt="You are an expert legal analyst providing critical analysis of evidence with thorough reasoning.",
                bedrock_provider=self.bedrock_provider,
                bedrock_region=self.bedrock_region,
                max_tokens=3000,
                temperature=0.7,
            )

            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            log_model_selection(
                "deep_research",
                friendly_name,
                f"Bedrock:{actual_model}",
            )

            return ModelResponse(
                model=friendly_name,
                task="Gap Analysis & Critical Review",
                response=response_text,
                confidence=0.90,
                processing_time=processing_time,
                key_findings=self._extract_key_findings(response_text),
            )
        except Exception as e:
            logger.error(f"Bedrock gap analysis error: {e}")
            return ModelResponse(
                model=friendly_name,
                task="Gap Analysis",
                response=f"Model unavailable: {str(e)}",
                confidence=0.0,
                processing_time=0.0,
                key_findings=[],
            )

    def synthesize_evidence_analysis(
        self, model_responses: list[ModelResponse], query: str
    ) -> str:
        """Synthesize multiple model analyses into comprehensive answer"""
        valid_responses = [r for r in model_responses if r.confidence > 0]

        if not valid_responses:
            return (
                "❌ All AI models failed. Please check your API keys in the .env file."
            )

        if len(valid_responses) == 1:
            return f"## {valid_responses[0].task}\n\n{valid_responses[0].response}"

        # Build comprehensive synthesis
        synthesis = "# Comprehensive Evidence Analysis\n\n"
        synthesis += f"**Question:** {query}\n\n"
        synthesis += f"**Analysis from {len(valid_responses)} AI Models:**\n\n"
        synthesis += "---\n\n"

        # Add each model's analysis
        for response in valid_responses:
            synthesis += f"## {response.model}: {response.task}\n\n"
            synthesis += f"{response.response}\n\n"

            if response.key_findings:
                synthesis += "**Key Findings:**\n"
                for finding in response.key_findings:
                    synthesis += f"- {finding}\n"
                synthesis += "\n"

            synthesis += f"*Processing time: {response.processing_time:.1f}s | Confidence: {response.confidence:.0%}*\n\n"
            synthesis += "---\n\n"

        # Add synthesis summary
        all_findings = []
        for r in valid_responses:
            all_findings.extend(r.key_findings)

        if all_findings:
            synthesis += "## 🎯 Synthesized Key Findings\n\n"
            for i, finding in enumerate(all_findings[:10], 1):
                synthesis += f"{i}. {finding}\n"

        return synthesis


def get_orchestrator(db: Session) -> AIEvidenceOrchestrator:
    """Get orchestrator with fresh settings from database"""
    orchestrator = AIEvidenceOrchestrator(db)
    return orchestrator


async def _augment_query_with_kb(query: str) -> tuple[str, list[KBSource]]:
    """Optionally augment the user query with Bedrock Knowledge Base context."""
    if not settings.USE_KNOWLEDGE_BASE or not settings.BEDROCK_KB_ID:
        return query, []
    if get_aws_services is None:
        return query, []

    try:
        aws = get_aws_services()
        kb_results = await aws.query_knowledge_base(query, settings.BEDROCK_KB_ID)
        kb_sources = [KBSource(**r) for r in kb_results[:5] if r.get("content")]
        context = "\n".join(s.content for s in kb_sources if s.content)
        if context:
            augmented = f"{query}\n\nRelevant legal knowledge base context:\n{context}"
            return augmented, kb_sources
        return query, kb_sources
    except Exception as e:
        logger.debug("KB augmentation failed: %s", e)
        return query, []


@router.post("/query", response_model=ChatResponse)
async def ai_evidence_query(
    request: ChatRequest = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """
    AI Evidence Assistant - Analyze correspondence and build chronologies

    Quick Mode: Fast single-model analysis (3-5 seconds)
    Deep Mode: Multi-model comprehensive research (30-60 seconds)
    """
    start_time = datetime.now(timezone.utc)

    try:
        # Get orchestrator with fresh settings
        orchestrator = get_orchestrator(db)

        # Get relevant emails.
        # NOTE: For very large corpora (100k+ emails), we retrieve a relevant subset.
        context_limit = (
            _AI_CONTEXT_MAX_EMAILS_QUICK
            if request.mode == ResearchMode.QUICK
            else _AI_CONTEXT_MAX_EMAILS_DEEP
        )
        emails = await _get_relevant_emails(
            db,
            user.id,
            request.project_id,
            request.case_id,
            query_text=request.query,
            max_emails=context_limit,
            include_full_text=(request.mode == ResearchMode.DEEP),
        )

        if not emails:
            raise HTTPException(404, "No evidence found. Upload PST files first.")

        # Extract sources for response
        sources = [
            EvidenceSource(
                email_id=str(email.id),
                subject=email.subject or "No subject",
                date=email.date_sent or datetime.now(timezone.utc),
                sender=email.sender_name or email.sender_email or "Unknown",
                relevance="Referenced in analysis",
            )
            for email in emails[:10]
        ]

        if request.mode == ResearchMode.QUICK:
            # Quick search
            function_cfg = get_function_config("quick_search", db)
            timeout_s = int(function_cfg.get("max_duration_seconds", 30) or 30)
            try:
                model_response = await asyncio.wait_for(
                    orchestrator.quick_search(request.query, emails),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    504,
                    f"Quick Search timed out after {timeout_s}s. Try narrowing your question or using filters.",
                )

            return ChatResponse(
                query=request.query,
                mode="quick",
                plan=None,
                answer=model_response.response,
                model_responses=[model_response],
                sources=sources,
                chronology_events=[],
                key_findings=model_response.key_findings,
                processing_time=(
                    datetime.now(timezone.utc) - start_time
                ).total_seconds(),
                timestamp=datetime.now(timezone.utc),
            )

        else:  # Deep research
            function_cfg = get_function_config("deep_analysis", db)
            timeout_s = int(function_cfg.get("max_duration_seconds", 60) or 60)
            try:
                plan, model_responses = await asyncio.wait_for(
                    orchestrator.deep_research(request.query, emails),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    504,
                    f"Deep Research timed out after {timeout_s}s. Try narrowing your question or reducing scope.",
                )

            # Synthesize
            synthesized = orchestrator.synthesize_evidence_analysis(
                model_responses, request.query
            )

            # Extract all key findings
            all_findings = []
            for r in model_responses:
                all_findings.extend(r.key_findings)

            return ChatResponse(
                query=request.query,
                mode="deep",
                plan=plan,
                answer=synthesized,
                model_responses=model_responses,
                sources=sources,
                chronology_events=[],
                key_findings=all_findings[:10],
                processing_time=(
                    datetime.now(timezone.utc) - start_time
                ).total_seconds(),
                timestamp=datetime.now(timezone.utc),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"AI evidence query failed: {e}")
        raise HTTPException(500, f"AI analysis failed: {str(e)}")


@router.post("/query-enhanced", response_model=ChatResponse)
async def ai_evidence_query_enhanced(
    request: ChatRequest = Body(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """
    Same as `/query`, but augments the question with Bedrock Knowledge Base context
    when configured (`USE_KNOWLEDGE_BASE` and `BEDROCK_KB_ID`).
    """
    start_time = datetime.now(timezone.utc)

    try:
        orchestrator = get_orchestrator(db)

        augmented_query, kb_sources = await _augment_query_with_kb(request.query)

        context_limit = (
            _AI_CONTEXT_MAX_EMAILS_QUICK
            if request.mode == ResearchMode.QUICK
            else _AI_CONTEXT_MAX_EMAILS_DEEP
        )
        emails = await _get_relevant_emails(
            db,
            user.id,
            request.project_id,
            request.case_id,
            query_text=request.query,
            max_emails=context_limit,
            include_full_text=(request.mode == ResearchMode.DEEP),
        )
        if not emails:
            raise HTTPException(404, "No evidence found. Upload PST files first.")

        sources = [
            EvidenceSource(
                email_id=str(email.id),
                subject=email.subject or "No subject",
                date=email.date_sent or datetime.now(timezone.utc),
                sender=email.sender_name or email.sender_email or "Unknown",
                relevance="Referenced in analysis",
            )
            for email in emails[:10]
        ]

        if request.mode == ResearchMode.QUICK:
            function_cfg = get_function_config("quick_search", db)
            timeout_s = int(function_cfg.get("max_duration_seconds", 30) or 30)
            try:
                model_response = await asyncio.wait_for(
                    orchestrator.quick_search(augmented_query, emails),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                raise HTTPException(
                    504,
                    f"Quick Search timed out after {timeout_s}s. Try narrowing your question or using filters.",
                )
            return ChatResponse(
                query=request.query,
                mode="quick",
                plan=None,
                answer=model_response.response,
                model_responses=[model_response],
                sources=sources,
                kb_sources=kb_sources,
                chronology_events=[],
                key_findings=model_response.key_findings,
                processing_time=(
                    datetime.now(timezone.utc) - start_time
                ).total_seconds(),
                timestamp=datetime.now(timezone.utc),
            )

        function_cfg = get_function_config("deep_analysis", db)
        timeout_s = int(function_cfg.get("max_duration_seconds", 60) or 60)
        try:
            plan, model_responses = await asyncio.wait_for(
                orchestrator.deep_research(augmented_query, emails),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                504,
                f"Deep Research timed out after {timeout_s}s. Try narrowing your question or reducing scope.",
            )
        synthesized = orchestrator.synthesize_evidence_analysis(
            model_responses, request.query
        )

        all_findings = []
        for r in model_responses:
            all_findings.extend(r.key_findings)

        return ChatResponse(
            query=request.query,
            mode="deep",
            plan=plan,
            answer=synthesized,
            model_responses=model_responses,
            sources=sources,
            kb_sources=kb_sources,
            chronology_events=[],
            key_findings=all_findings[:10],
            processing_time=(datetime.now(timezone.utc) - start_time).total_seconds(),
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Enhanced AI evidence query failed: {e}")
        raise HTTPException(500, f"AI analysis failed: {str(e)}")


async def _get_relevant_emails(
    db: Session,
    user_id: str,
    project_id: str | None,
    case_id: str | None,
    *,
    query_text: str | None = None,
    max_emails: int = _AI_CONTEXT_MAX_EMAILS_QUICK,
    include_full_text: bool = False,
) -> list[EmailMessage]:
    """Get relevant emails for analysis.

    IMPORTANT: this function must remain bounded. Large projects can contain
    tens of thousands of emails; attempting to load them all can cause request
    timeouts and upstream 502s.
    """
    try:
        from .visibility import build_email_visibility_filter

        # Load only the fields we need for prompting.
        load_cols = [
            EmailMessage.id,
            EmailMessage.project_id,
            EmailMessage.case_id,
            EmailMessage.thread_id,
            EmailMessage.thread_group_id,
            EmailMessage.message_id,
            EmailMessage.subject,
            EmailMessage.date_sent,
            EmailMessage.sender_name,
            EmailMessage.sender_email,
            EmailMessage.recipients_to,
            EmailMessage.body_preview,
            EmailMessage.meta,
        ]
        if include_full_text:
            load_cols.append(EmailMessage.body_text)

        query = db.query(EmailMessage).options(load_only(*load_cols))

        # Never use excluded/hidden emails as AI evidence.
        # Reuse the same visibility convention as the Correspondence Enterprise grid.
        query = query.filter(build_email_visibility_filter(EmailMessage))

        # Also exclude Outlook activity items (IPM.*) which are not real emails.
        query = query.filter(
            or_(EmailMessage.subject.is_(None), ~EmailMessage.subject.like("IPM.%"))
        )

        if project_id:
            query = query.filter(EmailMessage.project_id == project_id)
        elif case_id:
            query = query.filter(EmailMessage.case_id == case_id)
        else:
            # Get all user's emails
            projects = db.query(Project).filter(Project.owner_id == user_id).all()
            cases = db.query(Case).filter(Case.owner_id == user_id).all()

            project_ids = [str(p.id) for p in projects]
            case_ids = [str(c.id) for c in cases]

            if project_ids or case_ids:
                filters = []
                if project_ids:
                    filters.append(EmailMessage.project_id.in_(project_ids))
                if case_ids:
                    filters.append(EmailMessage.case_id.in_(case_ids))
                query = query.filter(or_(*filters))

        # Prefer scalable retrieval via OpenSearch when we have a query.
        # This allows corpora of 100k+ emails while keeping prompts bounded.
        if query_text and query_text.strip():
            scan_size = min(_AI_OPENSEARCH_SCAN_CAP, max(max_emails * 20, 500))
            os_candidates = _opensearch_email_candidates(
                query_text=query_text,
                project_id=project_id,
                case_id=case_id,
                size=scan_size,
            )

            os_ids: list[str] = [c.get("id") for c in os_candidates if c.get("id")]
            os_snippets: dict[str, str] = {
                str(c.get("id")): str(c.get("snippet") or "")
                for c in os_candidates
                if c.get("id")
            }

            if os_ids:
                # Convert IDs to UUIDs and fetch from DB, filtering to the requested scope.
                uuid_ids: list[uuid.UUID] = []
                for s in os_ids:
                    u = _safe_uuid(s)
                    if u is not None:
                        uuid_ids.append(u)

                if uuid_ids:
                    q2 = (
                        db.query(EmailMessage)
                        .options(load_only(*load_cols))
                        .filter(EmailMessage.id.in_(uuid_ids))
                    )

                    # Apply visibility filtering again because OpenSearch may contain
                    # historical docs that should not be exposed to AI.
                    q2 = q2.filter(build_email_visibility_filter(EmailMessage))
                    q2 = q2.filter(
                        or_(
                            EmailMessage.subject.is_(None),
                            ~EmailMessage.subject.like("IPM.%"),
                        )
                    )
                    if project_id:
                        q2 = q2.filter(EmailMessage.project_id == project_id)
                    if case_id:
                        q2 = q2.filter(EmailMessage.case_id == case_id)

                    rows = q2.all()
                    if rows:
                        by_id = {str(r.id): r for r in rows}
                        ordered: list[EmailMessage] = []
                        per_thread: dict[str, int] = {}
                        for s in os_ids:
                            r = by_id.get(s)
                            if r is not None:
                                # Simple diversity: avoid letting a single long thread dominate.
                                tg = getattr(r, "thread_group_id", None) or ""
                                if tg:
                                    n = per_thread.get(tg, 0)
                                    if n >= 4:
                                        continue
                                    per_thread[tg] = n + 1

                                snippet = os_snippets.get(s) or ""
                                if snippet:
                                    setattr(r, "_ai_retrieval_snippet", snippet)
                                ordered.append(r)
                                if len(ordered) >= max_emails:
                                    break
                        if ordered:
                            # Chronological order helps the downstream prompts.
                            return sorted(
                                ordered, key=lambda e: e.date_sent or datetime.min
                            )

        # Fallback: pull a bounded candidate pool (still not the full corpus), then score in Python.
        candidate_pool = min(
            max(_AI_CONTEXT_MAX_EMAILS_QUICK * 10, max_emails * 20),
            _AI_DB_CANDIDATE_POOL_CAP,
        )
        candidates = (
            query.order_by(EmailMessage.date_sent.desc().nullslast())
            .limit(candidate_pool)
            .all()
        )

        if not candidates:
            return []

        tokens = _tokenize_query_for_scoring(query_text or "")
        if not tokens:
            return sorted(
                candidates[:max_emails], key=lambda e: e.date_sent or datetime.min
            )

        def _score_email(e: EmailMessage) -> int:
            hay = f"{e.subject or ''} {getattr(e, 'body_preview', '') or ''}".lower()
            return sum(1 for t in tokens if t in hay)

        candidates_sorted = sorted(
            candidates,
            key=lambda e: (
                _score_email(e),
                e.date_sent or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

        selected = candidates_sorted[:max_emails]
        return sorted(selected, key=lambda e: e.date_sent or datetime.min)

    except Exception as e:
        logger.error(f"Error getting emails: {e}")
        return []


@router.get("/models/status")
async def get_models_status(
    user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Check which AI models are configured (6 providers: OpenAI, Anthropic, Gemini, Bedrock, xAI, Perplexity)"""
    # Refresh settings from database
    orchestrator = get_orchestrator(db)

    return {
        "models": {
            "openai": {
                "available": bool(orchestrator.openai_key),
                "name": "OpenAI GPT",
                "model": orchestrator.openai_model,
                "task": "Chronology & Event Analysis",
            },
            "gemini": {
                "available": bool(orchestrator.gemini_key),
                "name": "Google Gemini",
                "model": orchestrator.gemini_model,
                "task": "Pattern Recognition",
            },
            "anthropic": {
                "available": bool(orchestrator.anthropic_key),
                "name": "Anthropic Claude",
                "model": orchestrator.anthropic_model,
                "task": "Narrative Construction",
            },
            "bedrock": {
                "available": orchestrator.bedrock_enabled,
                "name": "Amazon Bedrock",
                "model": orchestrator.bedrock_model,
                "region": orchestrator.bedrock_region,
                "task": "Gap Analysis & Enterprise AI",
            },
            "xai": {
                "available": bool(orchestrator.xai_key),
                "name": "xAI Grok",
                "model": orchestrator.xai_model,
                "task": "Real-time Analysis & Reasoning",
            },
            "perplexity": {
                "available": bool(orchestrator.perplexity_key),
                "name": "Perplexity Sonar",
                "model": orchestrator.perplexity_model,
                "task": "Research & Web Search",
            },
        },
        "quick_search_available": bool(
            orchestrator.gemini_key
            or orchestrator.openai_key
            or orchestrator.anthropic_key
            or orchestrator.bedrock_enabled
            or orchestrator.xai_key
            or orchestrator.perplexity_key
        ),
        "deep_research_available": bool(
            orchestrator.openai_key
            or orchestrator.gemini_key
            or orchestrator.anthropic_key
            or orchestrator.bedrock_enabled
            or orchestrator.xai_key
            or orchestrator.perplexity_key
        ),
    }


@router.post("/models/test/{provider}")
async def test_ai_provider(
    provider: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Test connection to a specific AI provider (OpenAI, Anthropic, Gemini, Bedrock, xAI, Perplexity)"""
    import time
    from .ai_runtime import complete_chat

    orchestrator = get_orchestrator(db)

    test_prompt = "Reply with just 'OK' to confirm the connection works."
    start_time = time.time()

    try:
        if provider == "openai":
            if not orchestrator.openai_key:
                return {"success": False, "error": "OpenAI API key not configured"}
            response = await orchestrator._query_gpt_turbo(test_prompt)
            model = orchestrator.openai_model

        elif provider == "anthropic":
            if not orchestrator.anthropic_key:
                return {"success": False, "error": "Anthropic API key not configured"}
            response = await orchestrator._query_claude_sonnet(test_prompt)
            model = orchestrator.anthropic_model

        elif provider == "gemini":
            if not orchestrator.gemini_key:
                return {"success": False, "error": "Gemini API key not configured"}
            response = await orchestrator._query_gemini_flash(test_prompt)
            model = orchestrator.gemini_model

        elif provider == "bedrock":
            if not orchestrator.bedrock_enabled:
                return {"success": False, "error": "Amazon Bedrock not enabled"}
            if not orchestrator.bedrock_provider:
                return {
                    "success": False,
                    "error": "Bedrock provider initialization failed",
                }
            # Test Bedrock connection
            test_result = await orchestrator.bedrock_provider.test_connection()
            if test_result.get("success"):
                return {
                    "success": True,
                    "provider": "bedrock",
                    "model": test_result.get("model", orchestrator.bedrock_model),
                    "region": orchestrator.bedrock_region,
                    "response_time": int((time.time() - start_time) * 1000),
                    "response_preview": test_result.get("response", "OK")[:100],
                }
            else:
                return {
                    "success": False,
                    "error": test_result.get("error", "Bedrock test failed"),
                }

        elif provider == "xai":
            if not orchestrator.xai_key:
                return {"success": False, "error": "xAI (Grok) API key not configured"}
            response = await complete_chat(
                provider="xai",
                model_id=orchestrator.xai_model or "grok-3-latest",
                prompt=test_prompt,
                api_key=orchestrator.xai_key,
                max_tokens=50,
                temperature=0.3,
            )
            model = orchestrator.xai_model or "grok-3-latest"

        elif provider == "perplexity":
            if not orchestrator.perplexity_key:
                return {"success": False, "error": "Perplexity API key not configured"}
            response = await complete_chat(
                provider="perplexity",
                model_id=orchestrator.perplexity_model or "sonar-pro",
                prompt=test_prompt,
                api_key=orchestrator.perplexity_key,
                max_tokens=50,
                temperature=0.3,
            )
            model = orchestrator.perplexity_model or "sonar-pro"

        else:
            return {
                "success": False,
                "error": f"Unknown provider: {provider}. Supported: openai, anthropic, gemini, bedrock, xai, perplexity",
            }

        elapsed = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "provider": provider,
            "model": model,
            "response_time": elapsed,
            "response_preview": response[:100] if response else "OK",
        }

    except Exception as e:
        logger.error(f"AI provider test failed for {provider}: {e}")
        return {"success": False, "provider": provider, "error": str(e)}


@router.get("/health")
async def ai_health_check(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Check health of all configured AI providers.

    Returns status, latency, and any errors for each provider.
    Use this to verify providers are working before running analysis.
    """
    import time

    orchestrator = get_orchestrator(db)
    results: dict[str, dict[str, Any]] = {}

    # Define test functions for each provider
    async def test_openai() -> dict[str, Any]:
        if not orchestrator.openai_key:
            return {"healthy": False, "error": "Not configured"}
        start = time.time()
        try:
            _ = await orchestrator._query_gpt_turbo("Reply OK")  # noqa: SLF001
            return {
                "healthy": True,
                "latency_ms": int((time.time() - start) * 1000),
                "model": orchestrator.openai_model,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def test_anthropic() -> dict[str, Any]:
        if not orchestrator.anthropic_key:
            return {"healthy": False, "error": "Not configured"}
        start = time.time()
        try:
            _ = await orchestrator._query_claude_sonnet("Reply OK")  # noqa: SLF001
            return {
                "healthy": True,
                "latency_ms": int((time.time() - start) * 1000),
                "model": orchestrator.anthropic_model,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def test_gemini() -> dict[str, Any]:
        if not orchestrator.gemini_key:
            return {"healthy": False, "error": "Not configured"}
        start = time.time()
        try:
            _ = await orchestrator._query_gemini_flash("Reply OK")  # noqa: SLF001
            return {
                "healthy": True,
                "latency_ms": int((time.time() - start) * 1000),
                "model": orchestrator.gemini_model,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def test_bedrock() -> dict[str, Any]:
        if not orchestrator.bedrock_enabled:
            return {"healthy": False, "error": "Not enabled"}
        if not orchestrator.bedrock_provider:
            return {"healthy": False, "error": "Provider initialization failed"}
        start = time.time()
        try:
            result = await orchestrator.bedrock_provider.test_connection()
            if result.get("success"):
                return {
                    "healthy": True,
                    "latency_ms": int((time.time() - start) * 1000),
                    "model": orchestrator.bedrock_model,
                    "region": orchestrator.bedrock_region,
                }
            else:
                return {"healthy": False, "error": result.get("error", "Test failed")}
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    # Run health checks in parallel
    checks = await asyncio.gather(
        test_openai(),
        test_anthropic(),
        test_gemini(),
        test_bedrock(),
        return_exceptions=True,
    )

    provider_names = ["openai", "anthropic", "gemini", "bedrock"]
    for name, check in zip(provider_names, checks):
        if isinstance(check, BaseException):
            results[name] = {"healthy": False, "error": str(check)}
        else:
            results[name] = check

    # Calculate overall health
    healthy_count = sum(1 for r in results.values() if r.get("healthy"))
    total_configured = sum(
        1
        for r in results.values()
        if r.get("error") != "Not configured" and r.get("error") != "Not enabled"
    )

    # Get fallback and routing settings
    fallback_enabled = is_fallback_enabled(db)
    function_config = get_function_config("quick_search", db)

    return {
        "overall": "healthy" if healthy_count > 0 else "unhealthy",
        "providers_healthy": healthy_count,
        "providers_configured": total_configured,
        "providers_total": 4,
        "fallback_ready": healthy_count >= 2 and fallback_enabled,
        "fallback_enabled": fallback_enabled,
        "default_provider": function_config.get("provider", "gemini"),
        "providers": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
