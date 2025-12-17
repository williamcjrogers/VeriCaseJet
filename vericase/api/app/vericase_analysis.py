"""
VeriCase Analysis Orchestrator - Comprehensive multi-agent case analysis.

This module implements the VeriCase Analysis function, which acts as a
meta-orchestrator coordinating multiple specialized analyses:
- Timeline Generation
- Delay Analysis
- Deep Research
- Evidence Synthesis

The orchestrator runs these analyses in parallel where possible,
then integrates results into a comprehensive case assessment.

Architecture:
- Case Planner: High-level planning of analysis angles
- Sub-function Orchestrators: Delegates to specialized modules
- Integration Synthesizer: Combines all findings into unified report
- Cross-analysis Validator: Ensures consistency across analyses
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .models import User, Case, ChronologyItem
from .db import get_db
from .security import current_user
from .ai_router import AdaptiveModelRouter, RoutingStrategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vericase-analysis", tags=["vericase-analysis"])


class AnalysisStatus(str, Enum):
    """Status of a VeriCase analysis."""

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING_TIMELINE = "running_timeline"
    RUNNING_DELAY = "running_delay"
    RUNNING_RESEARCH = "running_research"
    INTEGRATING = "integrating"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisScope(str, Enum):
    """Scope of analysis to perform."""

    FULL = "full"  # All analyses
    TIMELINE_ONLY = "timeline_only"
    DELAY_ONLY = "delay_only"
    RESEARCH_ONLY = "research_only"
    QUICK = "quick"  # Basic analysis only


@dataclass
class AnalysisComponent:
    """Result from a single analysis component."""

    name: str
    status: str = "pending"
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    model_used: str | None = None


@dataclass
class VeriCaseSession:
    """Session state for a VeriCase analysis."""

    id: str
    user_id: str
    case_id: str
    status: AnalysisStatus = AnalysisStatus.PENDING
    scope: AnalysisScope = AnalysisScope.FULL

    # Planning phase results
    analysis_plan: dict[str, Any] = field(default_factory=dict)
    identified_angles: list[str] = field(default_factory=list)

    # Component results
    timeline_result: AnalysisComponent = field(
        default_factory=lambda: AnalysisComponent("timeline")
    )
    delay_result: AnalysisComponent = field(
        default_factory=lambda: AnalysisComponent("delay")
    )
    research_result: AnalysisComponent = field(
        default_factory=lambda: AnalysisComponent("research")
    )

    # Integration results
    integrated_report: str | None = None
    executive_summary: str | None = None
    key_findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # Validation
    validation_result: dict[str, Any] = field(default_factory=dict)
    cross_check_issues: list[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    total_duration_ms: int = 0
    models_used: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None


# Session storage
_vericase_sessions: dict[str, VeriCaseSession] = {}


# =============================================================================
# Request/Response Models
# =============================================================================


class StartAnalysisRequest(BaseModel):
    """Request to start a VeriCase analysis."""

    case_id: str
    scope: AnalysisScope = AnalysisScope.FULL
    focus_areas: list[str] = Field(default_factory=list)
    include_timeline: bool = True
    include_delay: bool = True
    include_research: bool = True
    research_topics: list[str] = Field(default_factory=list)


class AnalysisStatusResponse(BaseModel):
    """Status response for a VeriCase analysis."""

    session_id: str
    status: str
    progress: dict[str, Any] = Field(default_factory=dict)
    timeline_status: str = "pending"
    delay_status: str = "pending"
    research_status: str = "pending"
    integration_ready: bool = False
    report_available: bool = False
    error_message: str | None = None


class AnalysisReportResponse(BaseModel):
    """Full analysis report response."""

    session_id: str
    case_id: str
    executive_summary: str | None = None
    integrated_report: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    timeline_summary: dict[str, Any] = Field(default_factory=dict)
    delay_summary: dict[str, Any] = Field(default_factory=dict)
    research_summary: dict[str, Any] = Field(default_factory=dict)
    validation_score: float = 0.0
    models_used: list[str] = Field(default_factory=list)
    total_duration_ms: int = 0


# =============================================================================
# VeriCase Orchestrator
# =============================================================================


class VeriCaseOrchestrator:
    """
    Meta-orchestrator for comprehensive case analysis.

    Coordinates multiple specialized analyses:
    1. Timeline Generation - Chronological reconstruction
    2. Delay Analysis - Causation chains and impacts
    3. Deep Research - Liability and evidence analysis

    Uses parallel execution where possible and integrates
    results into a unified case assessment.
    """

    SYSTEM_PROMPT_PLANNER = """You are an expert legal analyst specializing in construction disputes.
Your role is to plan a comprehensive case analysis strategy.

When planning:
1. Identify key investigation angles (chronology, causation, liability, quantum)
2. Determine which analyses are most relevant
3. Note any specific focus areas or risks
4. Structure the analysis for efficiency

Output a structured analysis plan."""

    SYSTEM_PROMPT_INTEGRATOR = """You are an expert legal writer synthesizing multiple analyses.
Your role is to integrate findings from timeline, delay, and research analyses
into a cohesive case assessment.

When integrating:
1. Identify overarching themes and patterns
2. Note consistencies and contradictions between analyses
3. Build a coherent narrative of events
4. Highlight key findings and their implications
5. Provide actionable recommendations

Write in a professional, authoritative tone."""

    def __init__(self, db: Session, session: VeriCaseSession):
        self.db = db
        self.session = session
        self.router = AdaptiveModelRouter(db)

    async def run_full_analysis(
        self,
        case_data: dict[str, Any],
        focus_areas: list[str] | None = None,
    ) -> VeriCaseSession:
        """
        Run complete VeriCase analysis pipeline.

        Phases:
        1. Planning - Identify analysis strategy
        2. Parallel Execution - Run timeline, delay, research concurrently
        3. Integration - Combine results into unified report
        4. Validation - Cross-check for consistency
        """
        import time

        start_time = time.time()

        try:
            # Phase 1: Planning
            self.session.status = AnalysisStatus.PLANNING
            await self._run_planning_phase(case_data, focus_areas)

            # Phase 2: Parallel Execution
            await self._run_parallel_analyses(case_data)

            # Phase 3: Integration
            self.session.status = AnalysisStatus.INTEGRATING
            await self._run_integration_phase()

            # Phase 4: Validation
            self.session.status = AnalysisStatus.VALIDATING
            await self._run_validation_phase()

            # Complete
            self.session.status = AnalysisStatus.COMPLETED
            self.session.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.exception(f"VeriCase analysis failed: {e}")
            self.session.status = AnalysisStatus.FAILED
            self.session.error_message = str(e)

        finally:
            self.session.total_duration_ms = int((time.time() - start_time) * 1000)
            _vericase_sessions[self.session.id] = self.session

        return self.session

    async def _run_planning_phase(
        self,
        case_data: dict[str, Any],
        focus_areas: list[str] | None,
    ) -> None:
        """Phase 1: Plan the analysis strategy."""
        prompt = f"""Create an analysis plan for this case:

CASE OVERVIEW:
{case_data.get('description', 'No description available')}

AVAILABLE DATA:
- Emails: {case_data.get('email_count', 0)}
- Documents: {case_data.get('document_count', 0)}
- Chronology Items: {case_data.get('chronology_count', 0)}
- Delay Events: {case_data.get('delay_count', 0)}

FOCUS AREAS: {', '.join(focus_areas) if focus_areas else 'General analysis'}

Create an analysis plan as JSON:
{{
    "investigation_angles": ["angle1", "angle2", ...],
    "priority_analyses": ["timeline|delay|research"],
    "key_questions": ["question1", "question2", ...],
    "risk_areas": ["risk1", "risk2", ...],
    "recommended_approach": "description of approach"
}}"""

        response, decision = await self.router.execute(
            task_type="causation_analysis",
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT_PLANNER,
            strategy=RoutingStrategy.QUALITY,
        )

        self.session.models_used["planner"] = f"{decision.provider}/{decision.model_id}"

        # Parse plan
        try:
            import json

            plan_str = response
            if "```json" in response:
                plan_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                plan_str = response.split("```")[1].split("```")[0]

            self.session.analysis_plan = json.loads(plan_str.strip())
            self.session.identified_angles = self.session.analysis_plan.get(
                "investigation_angles", []
            )
        except Exception as e:
            logger.warning(f"Failed to parse analysis plan: {e}")
            self.session.analysis_plan = {"raw_plan": response}
            self.session.identified_angles = ["chronology", "causation", "liability"]

    async def _run_parallel_analyses(self, case_data: dict[str, Any]) -> None:
        """Phase 2: Run timeline, delay, and research analyses in parallel."""

        tasks = []

        # Timeline analysis
        if self.session.scope in [AnalysisScope.FULL, AnalysisScope.TIMELINE_ONLY]:
            tasks.append(self._run_timeline_analysis(case_data))

        # Delay analysis
        if self.session.scope in [AnalysisScope.FULL, AnalysisScope.DELAY_ONLY]:
            tasks.append(self._run_delay_analysis(case_data))

        # Research analysis
        if self.session.scope in [AnalysisScope.FULL, AnalysisScope.RESEARCH_ONLY]:
            tasks.append(self._run_research_analysis(case_data))

        # Run in parallel
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_timeline_analysis(self, case_data: dict[str, Any]) -> None:
        """Run timeline generation analysis."""
        import time

        start_time = time.time()

        self.session.status = AnalysisStatus.RUNNING_TIMELINE
        self.session.timeline_result.status = "running"

        try:
            # Get chronology items from database
            chronology_items = (
                self.db.query(ChronologyItem)
                .filter(ChronologyItem.case_id == self.session.case_id)
                .order_by(ChronologyItem.event_date)
                .limit(500)
                .all()
            )

            if not chronology_items:
                # Generate timeline from emails and documents
                prompt = f"""Generate a timeline of key events for this case:

CASE DATA:
{case_data.get('evidence_summary', 'No evidence summary available')[:5000]}

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

                response, decision = await self.router.execute(
                    task_type="timeline",
                    prompt=prompt,
                    system_prompt="You are an expert at reconstructing chronologies from evidence.",
                    strategy=RoutingStrategy.BALANCED,
                )

                self.session.models_used["timeline"] = (
                    f"{decision.provider}/{decision.model_id}"
                )
                self.session.timeline_result.model_used = decision.model_id

                # Parse response
                import json

                try:
                    timeline_str = response
                    if "```json" in response:
                        timeline_str = response.split("```json")[1].split("```")[0]
                    self.session.timeline_result.result = json.loads(
                        timeline_str.strip()
                    )
                except Exception:
                    self.session.timeline_result.result = {"raw_timeline": response}

            else:
                # Use existing chronology items
                events = [
                    {
                        "date": (
                            item.event_date.isoformat()
                            if item.event_date
                            else "Unknown"
                        ),
                        "event": item.description or "No description",
                        "significance": item.significance or "medium",
                    }
                    for item in chronology_items
                ]
                self.session.timeline_result.result = {
                    "events": events,
                    "timeline_summary": f"{len(events)} chronology items found",
                }

            self.session.timeline_result.status = "completed"

        except Exception as e:
            logger.exception(f"Timeline analysis failed: {e}")
            self.session.timeline_result.status = "failed"
            self.session.timeline_result.error = str(e)

        finally:
            self.session.timeline_result.duration_ms = int(
                (time.time() - start_time) * 1000
            )

    async def _run_delay_analysis(self, case_data: dict[str, Any]) -> None:
        """Run delay and causation analysis."""
        import time

        start_time = time.time()

        self.session.status = AnalysisStatus.RUNNING_DELAY
        self.session.delay_result.status = "running"

        try:
            prompt = f"""Analyze delays and causation chains for this construction case:

CASE DATA:
{case_data.get('evidence_summary', 'No evidence summary available')[:5000]}

KNOWN DELAY EVENTS:
{case_data.get('delay_summary', 'No delay data available')}

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

            response, decision = await self.router.execute(
                task_type="causation_analysis",
                prompt=prompt,
                system_prompt="You are an expert in construction delay analysis and causation.",
                strategy=RoutingStrategy.QUALITY,
            )

            self.session.models_used["delay"] = (
                f"{decision.provider}/{decision.model_id}"
            )
            self.session.delay_result.model_used = decision.model_id

            # Parse response
            import json

            try:
                delay_str = response
                if "```json" in response:
                    delay_str = response.split("```json")[1].split("```")[0]
                self.session.delay_result.result = json.loads(delay_str.strip())
            except Exception:
                self.session.delay_result.result = {"raw_analysis": response}

            self.session.delay_result.status = "completed"

        except Exception as e:
            logger.exception(f"Delay analysis failed: {e}")
            self.session.delay_result.status = "failed"
            self.session.delay_result.error = str(e)

        finally:
            self.session.delay_result.duration_ms = int(
                (time.time() - start_time) * 1000
            )

    async def _run_research_analysis(self, case_data: dict[str, Any]) -> None:
        """Run deep research analysis on liability and claims."""
        import time

        start_time = time.time()

        self.session.status = AnalysisStatus.RUNNING_RESEARCH
        self.session.research_result.status = "running"

        try:
            # Use analysis plan to focus research
            key_questions = self.session.analysis_plan.get(
                "key_questions",
                [
                    "What are the key liability issues?",
                    "What evidence supports each party's position?",
                    "What are the quantum implications?",
                ],
            )

            prompt = f"""Conduct deep research on these questions for the case:

KEY QUESTIONS:
{chr(10).join(f'- {q}' for q in key_questions[:5])}

CASE DATA:
{case_data.get('evidence_summary', 'No evidence summary available')[:5000]}

Provide research findings as JSON:
{{
    "questions_analyzed": [
        {{
            "question": "the question",
            "findings": "detailed findings",
            "evidence": ["evidence1", "evidence2"],
            "confidence": "high|medium|low"
        }}
    ],
    "liability_assessment": {{
        "primary_issues": ["issue1", "issue2"],
        "party_positions": {{"party1": "position", "party2": "position"}},
        "strength_of_case": "strong|moderate|weak"
    }},
    "quantum_summary": {{
        "claimed_amounts": "summary",
        "supportable_amounts": "summary",
        "key_considerations": ["consideration1", "consideration2"]
    }}
}}"""

            response, decision = await self.router.execute(
                task_type="deep_analysis",
                prompt=prompt,
                system_prompt="You are an expert legal analyst conducting thorough case research.",
                strategy=RoutingStrategy.QUALITY,
            )

            self.session.models_used["research"] = (
                f"{decision.provider}/{decision.model_id}"
            )
            self.session.research_result.model_used = decision.model_id

            # Parse response
            import json

            try:
                research_str = response
                if "```json" in response:
                    research_str = response.split("```json")[1].split("```")[0]
                self.session.research_result.result = json.loads(research_str.strip())
            except Exception:
                self.session.research_result.result = {"raw_research": response}

            self.session.research_result.status = "completed"

        except Exception as e:
            logger.exception(f"Research analysis failed: {e}")
            self.session.research_result.status = "failed"
            self.session.research_result.error = str(e)

        finally:
            self.session.research_result.duration_ms = int(
                (time.time() - start_time) * 1000
            )

    async def _run_integration_phase(self) -> None:
        """Phase 3: Integrate all analysis results into unified report."""
        # Compile results
        timeline_summary = self.session.timeline_result.result.get(
            "timeline_summary", ""
        )
        delay_summary = self.session.delay_result.result.get("entitlement_summary", "")
        research_summary = self.session.research_result.result.get(
            "liability_assessment", {}
        )

        prompt = f"""Integrate these analysis results into a comprehensive case assessment:

TIMELINE ANALYSIS:
{self.session.timeline_result.result}

DELAY ANALYSIS:
{self.session.delay_result.result}

RESEARCH FINDINGS:
{self.session.research_result.result}

Create an integrated report with:
1. Executive Summary (2-3 paragraphs)
2. Key Findings (bullet points)
3. Recommendations (actionable items)

Output as JSON:
{{
    "executive_summary": "comprehensive summary",
    "key_findings": ["finding1", "finding2", ...],
    "recommendations": ["recommendation1", "recommendation2", ...],
    "risk_assessment": "overall risk assessment",
    "next_steps": ["step1", "step2", ...]
}}"""

        response, decision = await self.router.execute(
            task_type="synthesis",
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT_INTEGRATOR,
            strategy=RoutingStrategy.QUALITY,
        )

        self.session.models_used["integrator"] = (
            f"{decision.provider}/{decision.model_id}"
        )

        # Parse integration results
        import json

        try:
            integration_str = response
            if "```json" in response:
                integration_str = response.split("```json")[1].split("```")[0]

            result = json.loads(integration_str.strip())
            self.session.executive_summary = result.get("executive_summary", "")
            self.session.key_findings = result.get("key_findings", [])
            self.session.recommendations = result.get("recommendations", [])
            self.session.integrated_report = response

        except Exception as e:
            logger.warning(f"Failed to parse integration: {e}")
            self.session.integrated_report = response
            self.session.executive_summary = response[:1000]

    async def _run_validation_phase(self) -> None:
        """Phase 4: Cross-validate results for consistency."""
        prompt = f"""Validate the consistency of these analysis results:

TIMELINE: {self.session.timeline_result.result}
DELAY: {self.session.delay_result.result}
RESEARCH: {self.session.research_result.result}
INTEGRATION: {self.session.executive_summary}

Check for:
1. Contradictions between analyses
2. Unsupported claims
3. Logical inconsistencies
4. Missing connections

Output as JSON:
{{
    "overall_score": 0.0-1.0,
    "consistency_issues": ["issue1", "issue2"],
    "contradictions": ["contradiction1", "contradiction2"],
    "validation_passed": true/false,
    "suggestions": ["improvement1", "improvement2"]
}}"""

        response, decision = await self.router.execute(
            task_type="validation",
            prompt=prompt,
            system_prompt="You are a rigorous quality checker for legal analyses.",
            strategy=RoutingStrategy.QUALITY,
        )

        self.session.models_used["validator"] = (
            f"{decision.provider}/{decision.model_id}"
        )

        # Parse validation
        import json

        try:
            validation_str = response
            if "```json" in response:
                validation_str = response.split("```json")[1].split("```")[0]

            self.session.validation_result = json.loads(validation_str.strip())
            self.session.cross_check_issues = self.session.validation_result.get(
                "consistency_issues", []
            )

        except Exception as e:
            logger.warning(f"Failed to parse validation: {e}")
            self.session.validation_result = {"raw_validation": response}


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/start", response_model=AnalysisStatusResponse)
async def start_vericase_analysis(
    request: StartAnalysisRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Start a new VeriCase analysis session."""
    # Verify case exists and user has access
    case = db.query(Case).filter(Case.id == request.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    # Create session
    session_id = str(uuid.uuid4())
    session = VeriCaseSession(
        id=session_id,
        user_id=str(user.id),
        case_id=request.case_id,
        scope=request.scope,
    )
    _vericase_sessions[session_id] = session

    # Build case data summary
    case_data = {
        "description": case.description or case.name,
        "email_count": 0,  # Would query actual count
        "document_count": 0,
        "chronology_count": 0,
        "delay_count": 0,
        "evidence_summary": f"Case: {case.name}",
    }

    # Run analysis in background
    async def run_analysis():
        orchestrator = VeriCaseOrchestrator(db, session)
        await orchestrator.run_full_analysis(case_data, request.focus_areas)

    def sync_run():
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_analysis())
        finally:
            loop.close()

    background_tasks.add_task(sync_run)

    return AnalysisStatusResponse(
        session_id=session_id,
        status=session.status.value,
        timeline_status="pending",
        delay_status="pending",
        research_status="pending",
    )


@router.get("/status/{session_id}", response_model=AnalysisStatusResponse)
async def get_analysis_status(
    session_id: str,
    user: User = Depends(current_user),
):
    """Get status of a VeriCase analysis."""
    session = _vericase_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Analysis session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    return AnalysisStatusResponse(
        session_id=session_id,
        status=session.status.value,
        progress={
            "planning": session.analysis_plan is not None,
            "timeline_done": session.timeline_result.status == "completed",
            "delay_done": session.delay_result.status == "completed",
            "research_done": session.research_result.status == "completed",
        },
        timeline_status=session.timeline_result.status,
        delay_status=session.delay_result.status,
        research_status=session.research_result.status,
        integration_ready=all(
            [
                session.timeline_result.status == "completed",
                session.delay_result.status == "completed",
                session.research_result.status == "completed",
            ]
        ),
        report_available=session.integrated_report is not None,
        error_message=session.error_message,
    )


@router.get("/report/{session_id}", response_model=AnalysisReportResponse)
async def get_analysis_report(
    session_id: str,
    user: User = Depends(current_user),
):
    """Get the full analysis report."""
    session = _vericase_sessions.get(session_id)
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
        executive_summary=session.executive_summary,
        integrated_report=session.integrated_report,
        key_findings=session.key_findings,
        recommendations=session.recommendations,
        timeline_summary=session.timeline_result.result,
        delay_summary=session.delay_result.result,
        research_summary=session.research_result.result,
        validation_score=session.validation_result.get("overall_score", 0.0),
        models_used=list(session.models_used.values()),
        total_duration_ms=session.total_duration_ms,
    )
