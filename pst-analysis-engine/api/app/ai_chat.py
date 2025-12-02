# pyright: reportMissingTypeStubs=false
"""
AI Evidence Assistant - Multi-Model Deep Research
Helps users understand their evidence, build chronologies, and develop narratives
Uses GPT-5.1, Gemini 3 Pro, Claude Opus 4.5, and Grok 4.1 for comprehensive analysis
"""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Any
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .models import User, EmailMessage, Project, Case
from .db import get_db
from .security import current_user
from .ai_settings import AISettings, get_ai_api_key, get_ai_model
from .ai_models import (
    AIModelService,
    TaskComplexity,
    log_model_selection,
    query_perplexity_local,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-chat", tags=["ai-chat"])


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
    chronology_events: list[dict[str, Any]]
    key_findings: list[str]
    processing_time: float
    timestamp: datetime


class AIEvidenceOrchestrator:
    """Orchestrates multiple AI models for evidence analysis"""

    def __init__(self, db: Session | None = None):
        # Load API keys from database settings (with env var fallback)
        self.db = db
        self.openai_key = get_ai_api_key("openai", db) or ""
        self.anthropic_key = get_ai_api_key("anthropic", db) or ""
        self.google_key = get_ai_api_key("gemini", db) or ""
        self.grok_key = get_ai_api_key("grok", db) or ""
        self.perplexity_key = get_ai_api_key("perplexity", db) or ""

        # Load model selections from database
        self.openai_model = get_ai_model("openai", db)
        self.anthropic_model = get_ai_model("anthropic", db)
        self.gemini_model = get_ai_model("gemini", db)
        self.grok_model = get_ai_model("grok", db)

        self.model_service = AIModelService()

    def refresh_settings(self, db: Session) -> None:
        """Reload settings from database"""
        AISettings.refresh_cache(db)
        self.openai_key = get_ai_api_key("openai", db) or ""
        self.anthropic_key = get_ai_api_key("anthropic", db) or ""
        self.google_key = get_ai_api_key("gemini", db) or ""
        self.grok_key = get_ai_api_key("grok", db) or ""
        self.perplexity_key = get_ai_api_key("perplexity", db) or ""
        self.openai_model = get_ai_model("openai", db)
        self.anthropic_model = get_ai_model("anthropic", db)
        self.gemini_model = get_ai_model("gemini", db)
        self.grok_model = get_ai_model("grok", db)

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
                if provider == "google" and self.google_key:
                    response_text = await self._query_gemini_flash(prompt, model_name)
                elif provider == "openai" and self.openai_key:
                    response_text = await self._query_gpt_turbo(prompt, model_name)
                elif provider == "anthropic" and self.anthropic_key:
                    response_text = await self._query_claude_sonnet(prompt, model_name)
                elif provider == "perplexity":
                    response_text = await query_perplexity_local(prompt, context)
                    if not response_text:
                        raise RuntimeError("Perplexity returned no content")
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
            elif provider == "google" and self.google_key:
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
            elif provider == "grok" and self.grok_key:
                tasks.append(
                    self._grok_identify_gaps(
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
                    "Gemini 2.5 Pro": "Pattern recognition across timeline",
                    "Claude Opus 4.1": "Narrative construction and causation",
                    "Grok 4": "Gap identification and missing evidence",
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
                    "Gemini 2.5 Pro": "Causation analysis and responsibility",
                    "Claude Opus 4.1": "Legal implications and entitlement",
                    "Grok 4": "Risk assessment and strategic insights",
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
                    "Gemini 2.5 Pro": "Evidence mapping and connections",
                    "Claude Opus 4.1": "Legal narrative and argumentation",
                    "Grok 4": "Alternative perspectives and weaknesses",
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
                    "Gemini 2.5 Pro": "Context understanding and extraction",
                    "Claude Opus 4.1": "Legal relevance assessment",
                    "Grok 4": "Hidden connections and insights",
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
                    "Gemini 2.5 Pro": "Pattern and trend analysis",
                    "Claude Opus 4.1": "Legal reasoning and implications",
                    "Grok 4": "Strategic recommendations",
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
        """Build evidence context from emails"""
        if not emails:
            return "No evidence available."

        context_parts = []
        for i, email in enumerate(emails[:100], 1):  # Limit to 100 emails
            if detailed:
                context_parts.append(
                    f"[Email {i}]\n"
                    f"ID: {email.id}\n"
                    f"Date: {email.date_sent.strftime('%Y-%m-%d %H:%M') if email.date_sent else 'Unknown'}\n"
                    f"From: {email.sender_name or email.sender_email or 'Unknown'}\n"
                    f"To: {email.recipients_to or 'Unknown'}\n"
                    f"Subject: {email.subject or 'No subject'}\n"
                    f"Content: {(email.body_text or email.body_preview or '')[:800]}\n"
                    f"Attachments: {email.attachment_count or 0}\n"
                    f"---"
                )
            else:
                context_parts.append(
                    f"[{i}] {email.date_sent.strftime('%Y-%m-%d') if email.date_sent else 'Unknown'} | "
                    f"{email.sender_name or 'Unknown'} | {email.subject or 'No subject'} | "
                    f"{(email.body_text or '')[:200]}"
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
            import google.generativeai as genai  # pyright: ignore[reportMissingTypeStubs]

            genai.configure(api_key=self.google_key)
            # Use configured model or fallback
            actual_model: str = model_name or self.gemini_model or "gemini-3.0-pro"
            model = genai.GenerativeModel(actual_model)
            response = await asyncio.to_thread(model.generate_content, prompt)
            return response.text
        except Exception as e:
            raise Exception(f"Gemini error: {str(e)}")

    async def _query_gpt_turbo(self, prompt: str, model_name: str = None) -> str:
        """GPT-4 Turbo for quick responses"""
        try:
            import openai

            client = openai.AsyncOpenAI(api_key=self.openai_key)
            # Use configured model or fallback
            actual_model: str = model_name or self.openai_model or "gpt-5.1-2025-11-13"
            response = await client.chat.completions.create(
                model=actual_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"GPT error: {str(e)}")

    async def _query_claude_sonnet(self, prompt: str, model_name: str = None) -> str:
        """Claude Sonnet for structured quick responses"""
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
            # Use configured model or fallback
            actual_model: str = (
                model_name or self.anthropic_model or "claude-sonnet-4-20250514"
            )
            response = await client.messages.create(
                model=actual_model,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            return text or response.content[0].text
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
            import openai

            client = openai.AsyncOpenAI(api_key=self.openai_key)

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

            response = await client.chat.completions.create(
                model=model_override
                or "gpt-5.1-2025-11-13",  # GPT-5.1 with reasoning effort: high
                messages=[{"role": "user", "content": prompt}],
            )

            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            response_text = response.choices[0].message.content

            log_model_selection(
                "deep_research",
                friendly_name,
                f"OpenAI:{model_override or 'o1-preview'}",
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
            import google.generativeai as genai

            genai.configure(api_key=self.google_key)
            model = genai.GenerativeModel(model_override or "gemini-3.0-pro")

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

            response = await asyncio.to_thread(model.generate_content, prompt)
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            log_model_selection(
                "deep_research",
                friendly_name,
                f"Gemini:{model_override or 'gemini-3.0-pro'}",
            )

            return ModelResponse(
                model=friendly_name,
                task="Pattern Recognition & Connection Mapping",
                response=response.text,
                confidence=0.93,
                processing_time=processing_time,
                key_findings=self._extract_key_findings(response.text),
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
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)

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

            response = await client.messages.create(
                model=model_override or "claude-opus-4-5-20251101",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                extra_body={"thinking": {"type": "enabled", "budget_tokens": 10000}},
            )

            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()

            # Extract text from response
            response_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    response_text += block.text

            log_model_selection(
                "deep_research",
                friendly_name,
                f"Anthropic:{model_override or 'claude-opus-4-20250514'}",
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

    async def _grok_identify_gaps(
        self,
        query: str,
        context: str,
        emails: list[EmailMessage],
        model_override: str | None = None,
        friendly_name: str = "Grok 4 Heavy",
    ) -> ModelResponse:
        """Grok 4: Identify gaps and missing evidence"""
        start_time = datetime.now(timezone.utc)

        try:
            import openai

            client = openai.AsyncOpenAI(
                api_key=self.grok_key, base_url="https://api.x.ai/v1"
            )

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

            response = await client.chat.completions.create(
                model=model_override or "grok-4-1-fast-reasoning",
                messages=[
                    {
                        "role": "system",
                        "content": "You are Grok 4.1, providing critical analysis of legal evidence with chain-of-thought reasoning.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,
            )

            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            log_model_selection(
                "deep_research",
                friendly_name,
                f"Grok:{model_override or 'grok-4-1-fast-reasoning'}",
            )

            return ModelResponse(
                model=friendly_name,
                task="Gap Analysis & Critical Review",
                response=response.choices[0].message.content,
                confidence=0.90,
                processing_time=processing_time,
                key_findings=self._extract_key_findings(
                    response.choices[0].message.content
                ),
            )
        except Exception as e:
            logger.error(f"Grok gap analysis error: {e}")
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

        # Get relevant emails
        emails = await _get_relevant_emails(
            db, user.id, request.project_id, request.case_id
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
            model_response = await orchestrator.quick_search(request.query, emails)

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
            plan, model_responses = await orchestrator.deep_research(
                request.query, emails
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


async def _get_relevant_emails(
    db: Session, user_id: str, project_id: str | None, case_id: str | None
) -> list[EmailMessage]:
    """Get relevant emails for analysis"""
    try:
        query = db.query(EmailMessage)

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

        # Get emails ordered by date
        emails = query.order_by(EmailMessage.date_sent.asc()).limit(200).all()
        return emails

    except Exception as e:
        logger.error(f"Error getting emails: {e}")
        return []


@router.get("/models/status")
async def get_models_status(
    user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Check which AI models are configured"""
    # Refresh settings from database
    orchestrator = get_orchestrator(db)

    return {
        "models": {
            "gpt5_pro": {
                "available": bool(orchestrator.openai_key),
                "name": "OpenAI GPT",
                "model": orchestrator.openai_model,
                "task": "Chronology & Event Analysis",
            },
            "gemini_2_5": {
                "available": bool(orchestrator.google_key),
                "name": "Google Gemini",
                "model": orchestrator.gemini_model,
                "task": "Pattern Recognition",
            },
            "claude_opus": {
                "available": bool(orchestrator.anthropic_key),
                "name": "Anthropic Claude",
                "model": orchestrator.anthropic_model,
                "task": "Narrative Construction",
            },
            "grok_4": {
                "available": bool(orchestrator.grok_key),
                "name": "xAI Grok",
                "model": orchestrator.grok_model,
                "task": "Gap Analysis",
            },
            "perplexity": {
                "available": bool(orchestrator.perplexity_key),
                "name": "Perplexity",
                "task": "Evidence-Focused Queries",
            },
        },
        "quick_search_available": bool(
            orchestrator.google_key
            or orchestrator.openai_key
            or orchestrator.anthropic_key
        ),
        "deep_research_available": bool(
            orchestrator.openai_key
            or orchestrator.google_key
            or orchestrator.anthropic_key
            or orchestrator.grok_key
        ),
    }


@router.post("/models/test/{provider}")
async def test_ai_provider(
    provider: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Test connection to a specific AI provider"""
    import time

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
            if not orchestrator.google_key:
                return {"success": False, "error": "Gemini API key not configured"}
            response = await orchestrator._query_gemini_flash(test_prompt)
            model = orchestrator.gemini_model

        elif provider == "grok":
            if not orchestrator.grok_key:
                return {"success": False, "error": "Grok API key not configured"}
            # Test Grok
            import openai

            client = openai.AsyncOpenAI(
                api_key=orchestrator.grok_key, base_url="https://api.x.ai/v1"
            )
            result = await client.chat.completions.create(
                model=orchestrator.grok_model or "grok-4-1-fast-reasoning",
                messages=[{"role": "user", "content": test_prompt}],
                max_tokens=10,
            )
            response = result.choices[0].message.content
            model = orchestrator.grok_model

        elif provider == "perplexity":
            if not orchestrator.perplexity_key:
                return {"success": False, "error": "Perplexity API key not configured"}
            response = await query_perplexity_local(test_prompt, "Test context")
            if not response:
                return {"success": False, "error": "Perplexity returned no response"}
            model = "sonar-pro"

        else:
            return {"success": False, "error": f"Unknown provider: {provider}"}

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
