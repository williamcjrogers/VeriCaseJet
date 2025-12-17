"""
Delay Analysis Module - Specialized analysis of project delays and causation.

This module provides comprehensive delay analysis for construction disputes:
- Identification of delay events from evidence
- Causation chain analysis (what caused what)
- Impact quantification (time and cost)
- Claims narrative generation
- As-planned vs As-built comparison

Uses specialized AI agents optimized for delay analysis:
- Causation Agent (Claude) - Traces cause-effect relationships
- Quantification Agent (GPT-4) - Calculates impacts
- Narrative Agent (Claude/GPT-4) - Writes claims narratives

Architecture aligns with the AI Orchestration Blueprint's
Delay Analysis function specification.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .models import User, Case
from .db import get_db
from .security import current_user
from .ai_router import AdaptiveModelRouter, RoutingStrategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/delay-analysis", tags=["delay-analysis"])


class DelayType(str, Enum):
    """Types of delays."""

    EMPLOYER = "employer"
    CONTRACTOR = "contractor"
    NEUTRAL = "neutral"
    CONCURRENT = "concurrent"
    UNKNOWN = "unknown"


class DelayImpactType(str, Enum):
    """Types of delay impacts."""

    TIME_ONLY = "time_only"
    COST_ONLY = "cost_only"
    TIME_AND_COST = "time_and_cost"
    NO_IMPACT = "no_impact"


@dataclass
class CausationLink:
    """A single link in a causation chain."""

    cause_event: str
    effect_event: str
    relationship: str  # caused, contributed, led_to, resulted_in
    confidence: float = 0.8
    evidence: list[str] = field(default_factory=list)


@dataclass
class CausationChain:
    """A complete causation chain from trigger to impact."""

    id: str
    trigger_event: str
    links: list[CausationLink] = field(default_factory=list)
    final_impact: str = ""
    total_delay_days: int = 0
    responsible_party: str = ""
    entitlement_type: str = ""  # EOT, prolongation, disruption


@dataclass
class DelayEventAnalysis:
    """Analysis of a single delay event."""

    event_id: str
    description: str
    event_date: datetime | None = None
    delay_days: int = 0
    delay_type: DelayType = DelayType.UNKNOWN
    impact_type: DelayImpactType = DelayImpactType.TIME_ONLY

    # Causation analysis
    root_cause: str = ""
    causation_chains: list[CausationChain] = field(default_factory=list)
    contributing_factors: list[str] = field(default_factory=list)

    # Impact quantification
    planned_date: datetime | None = None
    actual_date: datetime | None = None
    cost_impact: float = 0.0
    critical_path_impact: bool = False

    # Evidence
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)

    # Narrative
    claim_narrative: str = ""
    confidence: float = 0.5


@dataclass
class DelayAnalysisSession:
    """Session state for delay analysis."""

    id: str
    user_id: str
    case_id: str
    status: str = "pending"

    # Input data
    delay_events_analyzed: list[DelayEventAnalysis] = field(default_factory=list)

    # Causation analysis
    causation_chains: list[CausationChain] = field(default_factory=list)
    critical_path_delays: list[str] = field(default_factory=list)

    # Summary outputs
    total_employer_delay_days: int = 0
    total_contractor_delay_days: int = 0
    total_neutral_delay_days: int = 0
    total_concurrent_days: int = 0

    # Entitlements
    eot_entitlement_days: int = 0
    prolongation_claim: float = 0.0
    disruption_claim: float = 0.0

    # Report
    executive_summary: str = ""
    claims_narrative: str = ""
    recommendations: list[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    models_used: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None


# Session storage
_delay_sessions: dict[str, DelayAnalysisSession] = {}


# =============================================================================
# Request/Response Models
# =============================================================================


class StartDelayAnalysisRequest(BaseModel):
    """Request to start delay analysis."""

    case_id: str
    focus_on_critical_path: bool = True
    include_cost_impact: bool = True
    analyze_concurrent_delays: bool = True


class DelayEventInput(BaseModel):
    """Input for a delay event to analyze."""

    description: str
    event_date: str | None = None
    planned_date: str | None = None
    actual_date: str | None = None
    delay_days: int = 0
    evidence_ids: list[str] = Field(default_factory=list)


class AnalyzeDelaysRequest(BaseModel):
    """Request to analyze specific delay events."""

    session_id: str
    delay_events: list[DelayEventInput]


class DelayAnalysisResponse(BaseModel):
    """Response with delay analysis results."""

    session_id: str
    status: str
    delay_events: list[dict[str, Any]] = Field(default_factory=list)
    causation_chains: list[dict[str, Any]] = Field(default_factory=list)
    total_delays: dict[str, int] = Field(default_factory=dict)
    entitlements: dict[str, Any] = Field(default_factory=dict)
    claims_narrative: str = ""
    recommendations: list[str] = Field(default_factory=list)


# =============================================================================
# Delay Analysis Agents
# =============================================================================


class CausationAnalyzer:
    """
    Agent for analyzing causation chains in delays.

    Uses Anthropic Claude for its strength in analytical,
    step-by-step reasoning about cause and effect.
    """

    SYSTEM_PROMPT = """You are an expert construction delay analyst specializing in causation analysis.
Your role is to trace cause-and-effect relationships between events.

When analyzing causation:
1. Identify the triggering event (root cause)
2. Trace the chain of events that followed
3. Distinguish between direct causes and contributing factors
4. Identify which party is responsible for each link
5. Note where evidence supports or contradicts the chain

Be rigorous and evidence-based. Avoid speculation without evidence."""

    def __init__(self, db: Session, router: AdaptiveModelRouter):
        self.db = db
        self.router = router

    async def analyze_causation(
        self,
        delay_event: str,
        evidence_context: str,
    ) -> dict[str, Any]:
        """Analyze causation for a delay event."""
        prompt = f"""Analyze the causation chain for this delay event:

DELAY EVENT: {delay_event}

EVIDENCE CONTEXT:
{evidence_context[:5000]}

Trace the causation chain and output as JSON:
{{
    "root_cause": "the triggering event or condition",
    "causation_chain": [
        {{
            "cause": "event or action",
            "effect": "resulting event or condition",
            "relationship": "caused|contributed|led_to",
            "responsible_party": "employer|contractor|third_party|neutral",
            "evidence": "evidence supporting this link"
        }}
    ],
    "final_impact": "the ultimate delay impact",
    "contributing_factors": ["factor1", "factor2"],
    "confidence": 0.0-1.0,
    "gaps_in_evidence": ["gap1", "gap2"]
}}"""

        response, decision = await self.router.execute(
            task_type="causation_analysis",
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            strategy=RoutingStrategy.QUALITY,
        )

        # Parse response
        import json

        try:
            result_str = response
            if "```json" in response:
                result_str = response.split("```json")[1].split("```")[0]
            return json.loads(result_str.strip())
        except Exception:
            return {"raw_analysis": response, "error": "Failed to parse"}


class ImpactQuantifier:
    """
    Agent for quantifying delay impacts.

    Calculates time and cost impacts based on
    planned vs actual dates and rates.
    """

    SYSTEM_PROMPT = """You are an expert quantity surveyor specializing in delay impact quantification.
Your role is to calculate time and cost impacts of delays.

When quantifying:
1. Calculate actual delay in calendar/working days
2. Determine if delay is on critical path
3. Assess cost impacts (prolongation, disruption, acceleration)
4. Consider concurrent delays and apportionment
5. Apply relevant contract provisions

Be precise and show your calculations."""

    def __init__(self, db: Session, router: AdaptiveModelRouter):
        self.db = db
        self.router = router

    async def quantify_impact(
        self,
        delay_event: DelayEventAnalysis,
        contract_context: str = "",
    ) -> dict[str, Any]:
        """Quantify the impact of a delay event."""
        prompt = f"""Quantify the impact of this delay:

DELAY EVENT: {delay_event.description}
PLANNED DATE: {delay_event.planned_date}
ACTUAL DATE: {delay_event.actual_date}
CURRENT DELAY ESTIMATE: {delay_event.delay_days} days

CAUSATION ANALYSIS:
Root cause: {delay_event.root_cause}
Responsible party: {delay_event.delay_type.value}

CONTRACT CONTEXT:
{contract_context[:2000] if contract_context else "Standard construction contract terms apply"}

Quantify impact as JSON:
{{
    "delay_days": 0,
    "is_critical_path": true/false,
    "time_impact": {{
        "gross_delay": 0,
        "float_consumed": 0,
        "net_critical_delay": 0
    }},
    "cost_impact": {{
        "prolongation": 0.0,
        "disruption": 0.0,
        "acceleration": 0.0,
        "total": 0.0
    }},
    "entitlement": {{
        "eot_days": 0,
        "cost_recoverable": true/false,
        "basis": "reason for entitlement"
    }},
    "calculations": "show your working"
}}"""

        response, decision = await self.router.execute(
            task_type="synthesis",
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            strategy=RoutingStrategy.BALANCED,
        )

        # Parse response
        import json

        try:
            result_str = response
            if "```json" in response:
                result_str = response.split("```json")[1].split("```")[0]
            return json.loads(result_str.strip())
        except Exception:
            return {"raw_quantification": response}


class NarrativeGenerator:
    """
    Agent for generating claims narratives.

    Writes professional delay claim narratives
    suitable for submissions or reports.
    """

    SYSTEM_PROMPT = """You are an expert legal writer specializing in construction delay claims.
Your role is to write clear, persuasive claims narratives.

When writing:
1. Present facts chronologically and logically
2. Link causes to effects with evidence
3. Quantify impacts clearly
4. State entitlements and their basis
5. Use professional, formal language

Write for a legal/arbitration audience."""

    def __init__(self, db: Session, router: AdaptiveModelRouter):
        self.db = db
        self.router = router

    async def generate_narrative(
        self,
        delay_analyses: list[DelayEventAnalysis],
        entitlements: dict[str, Any],
    ) -> str:
        """Generate a claims narrative from analyses."""
        # Compile analyses summary
        analyses_text = "\n\n".join(
            [
                f"""DELAY EVENT: {a.description}
Root Cause: {a.root_cause}
Delay Days: {a.delay_days}
Responsible Party: {a.delay_type.value}
Impact: {a.impact_type.value}
Critical Path: {a.critical_path_impact}
Supporting Evidence: {', '.join(a.supporting_evidence[:3])}"""
                for a in delay_analyses
            ]
        )

        prompt = f"""Write a professional claims narrative for these delay events:

DELAY ANALYSES:
{analyses_text}

ENTITLEMENT SUMMARY:
- EOT Entitlement: {entitlements.get('eot_days', 0)} days
- Prolongation Claim: ${entitlements.get('prolongation', 0):,.2f}
- Disruption Claim: ${entitlements.get('disruption', 0):,.2f}

Write a comprehensive claims narrative that:
1. Introduces the claim
2. Presents each delay event with causation
3. Quantifies the impact
4. States the entitlement and basis
5. Concludes with the claim amount

Write approximately 1000-1500 words."""

        response, decision = await self.router.execute(
            task_type="synthesis",
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            strategy=RoutingStrategy.QUALITY,
        )

        return response


# =============================================================================
# Delay Analysis Orchestrator
# =============================================================================


class DelayAnalysisOrchestrator:
    """
    Orchestrates comprehensive delay analysis.

    Coordinates:
    1. Causation analysis for each delay event
    2. Impact quantification
    3. Claims narrative generation
    4. Summary and recommendations
    """

    def __init__(self, db: Session, session: DelayAnalysisSession):
        self.db = db
        self.session = session
        self.router = AdaptiveModelRouter(db)
        self.causation_analyzer = CausationAnalyzer(db, self.router)
        self.impact_quantifier = ImpactQuantifier(db, self.router)
        self.narrative_generator = NarrativeGenerator(db, self.router)

    async def analyze_delays(
        self,
        delay_events: list[dict[str, Any]],
        evidence_context: str = "",
    ) -> DelayAnalysisSession:
        """
        Run comprehensive delay analysis.

        Steps:
        1. Analyze causation for each delay event
        2. Quantify impacts
        3. Identify concurrent delays
        4. Calculate entitlements
        5. Generate claims narrative
        """
        import time

        start_time = time.time()

        self.session.status = "analyzing"

        try:
            # Step 1: Analyze each delay event
            for event_data in delay_events:
                event_analysis = await self._analyze_single_delay(
                    event_data, evidence_context
                )
                self.session.delay_events_analyzed.append(event_analysis)

            # Step 2: Build causation chains
            await self._build_causation_chains()

            # Step 3: Identify concurrent delays
            await self._analyze_concurrent_delays()

            # Step 4: Calculate entitlements
            self._calculate_entitlements()

            # Step 5: Generate narrative
            entitlements = {
                "eot_days": self.session.eot_entitlement_days,
                "prolongation": self.session.prolongation_claim,
                "disruption": self.session.disruption_claim,
            }
            self.session.claims_narrative = (
                await self.narrative_generator.generate_narrative(
                    self.session.delay_events_analyzed,
                    entitlements,
                )
            )

            # Step 6: Generate summary
            await self._generate_summary()

            self.session.status = "completed"
            self.session.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.exception(f"Delay analysis failed: {e}")
            self.session.status = "failed"
            self.session.error_message = str(e)

        finally:
            _delay_sessions[self.session.id] = self.session

        return self.session

    async def _analyze_single_delay(
        self,
        event_data: dict[str, Any],
        evidence_context: str,
    ) -> DelayEventAnalysis:
        """Analyze a single delay event."""
        # Create analysis object
        analysis = DelayEventAnalysis(
            event_id=str(uuid.uuid4()),
            description=event_data.get("description", ""),
            delay_days=event_data.get("delay_days", 0),
        )

        # Parse dates
        if event_data.get("event_date"):
            try:
                analysis.event_date = datetime.fromisoformat(event_data["event_date"])
            except ValueError:
                pass

        if event_data.get("planned_date"):
            try:
                analysis.planned_date = datetime.fromisoformat(
                    event_data["planned_date"]
                )
            except ValueError:
                pass

        if event_data.get("actual_date"):
            try:
                analysis.actual_date = datetime.fromisoformat(event_data["actual_date"])
            except ValueError:
                pass

        # Calculate delay if dates available
        if analysis.planned_date and analysis.actual_date:
            delta = analysis.actual_date - analysis.planned_date
            analysis.delay_days = max(0, delta.days)

        # Analyze causation
        causation_result = await self.causation_analyzer.analyze_causation(
            analysis.description,
            evidence_context,
        )

        analysis.root_cause = causation_result.get("root_cause", "")
        analysis.contributing_factors = causation_result.get("contributing_factors", [])
        analysis.confidence = causation_result.get("confidence", 0.5)

        # Determine delay type from causation
        chain = causation_result.get("causation_chain", [])
        if chain:
            parties = [link.get("responsible_party", "").lower() for link in chain]
            if "employer" in parties and "contractor" not in parties:
                analysis.delay_type = DelayType.EMPLOYER
            elif "contractor" in parties and "employer" not in parties:
                analysis.delay_type = DelayType.CONTRACTOR
            elif "employer" in parties and "contractor" in parties:
                analysis.delay_type = DelayType.CONCURRENT
            else:
                analysis.delay_type = DelayType.NEUTRAL

        # Quantify impact
        impact_result = await self.impact_quantifier.quantify_impact(analysis)

        analysis.critical_path_impact = impact_result.get("is_critical_path", False)
        analysis.cost_impact = impact_result.get("cost_impact", {}).get("total", 0.0)

        if impact_result.get("cost_impact", {}).get("total", 0) > 0:
            if analysis.delay_days > 0:
                analysis.impact_type = DelayImpactType.TIME_AND_COST
            else:
                analysis.impact_type = DelayImpactType.COST_ONLY
        elif analysis.delay_days > 0:
            analysis.impact_type = DelayImpactType.TIME_ONLY

        # Store evidence references
        analysis.supporting_evidence = event_data.get("evidence_ids", [])

        return analysis

    async def _build_causation_chains(self) -> None:
        """Build comprehensive causation chains from individual analyses."""
        # Group related delays
        for analysis in self.session.delay_events_analyzed:
            if analysis.root_cause:
                chain = CausationChain(
                    id=str(uuid.uuid4()),
                    trigger_event=analysis.root_cause,
                    final_impact=f"{analysis.delay_days} days delay",
                    total_delay_days=analysis.delay_days,
                    responsible_party=analysis.delay_type.value,
                )
                self.session.causation_chains.append(chain)

    async def _analyze_concurrent_delays(self) -> None:
        """Identify and analyze concurrent delays."""
        # Sort by date
        dated_events = [a for a in self.session.delay_events_analyzed if a.event_date]
        dated_events.sort(key=lambda a: a.event_date)

        # Find overlapping delays
        concurrent_count = 0
        for i, event in enumerate(dated_events):
            if event.delay_type == DelayType.CONCURRENT:
                concurrent_count += 1

        self.session.total_concurrent_days = concurrent_count

    def _calculate_entitlements(self) -> None:
        """Calculate total entitlements from analyzed delays."""
        for analysis in self.session.delay_events_analyzed:
            if analysis.delay_type == DelayType.EMPLOYER:
                self.session.total_employer_delay_days += analysis.delay_days
                self.session.eot_entitlement_days += analysis.delay_days
                self.session.prolongation_claim += analysis.cost_impact

            elif analysis.delay_type == DelayType.CONTRACTOR:
                self.session.total_contractor_delay_days += analysis.delay_days

            elif analysis.delay_type == DelayType.NEUTRAL:
                self.session.total_neutral_delay_days += analysis.delay_days
                # Typically entitled to EOT but not costs
                self.session.eot_entitlement_days += analysis.delay_days

            elif analysis.delay_type == DelayType.CONCURRENT:
                self.session.total_concurrent_days += analysis.delay_days
                # Complex apportionment needed

    async def _generate_summary(self) -> None:
        """Generate executive summary of delay analysis."""
        prompt = f"""Summarize this delay analysis:

DELAYS ANALYZED: {len(self.session.delay_events_analyzed)}

BY TYPE:
- Employer delays: {self.session.total_employer_delay_days} days
- Contractor delays: {self.session.total_contractor_delay_days} days
- Neutral delays: {self.session.total_neutral_delay_days} days
- Concurrent: {self.session.total_concurrent_days} days

ENTITLEMENTS:
- EOT: {self.session.eot_entitlement_days} days
- Prolongation: ${self.session.prolongation_claim:,.2f}
- Disruption: ${self.session.disruption_claim:,.2f}

Provide:
1. Executive summary (2-3 sentences)
2. Key findings (3-5 bullet points)
3. Recommendations (3-5 actionable items)

Output as JSON:
{{
    "executive_summary": "summary text",
    "key_findings": ["finding1", "finding2"],
    "recommendations": ["rec1", "rec2"]
}}"""

        response, decision = await self.router.execute(
            task_type="synthesis",
            prompt=prompt,
            system_prompt="You are an expert in summarizing delay analyses.",
            strategy=RoutingStrategy.BALANCED,
        )

        self.session.models_used["summary"] = f"{decision.provider}/{decision.model_id}"

        # Parse response
        import json

        try:
            result_str = response
            if "```json" in response:
                result_str = response.split("```json")[1].split("```")[0]
            result = json.loads(result_str.strip())
            self.session.executive_summary = result.get("executive_summary", "")
            self.session.recommendations = result.get("recommendations", [])
        except Exception:
            self.session.executive_summary = response[:500]


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/start")
async def start_delay_analysis(
    request: StartDelayAnalysisRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Start a new delay analysis session."""
    # Verify case exists
    case = db.query(Case).filter(Case.id == request.case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    # Create session
    session_id = str(uuid.uuid4())
    session = DelayAnalysisSession(
        id=session_id,
        user_id=str(user.id),
        case_id=request.case_id,
    )
    _delay_sessions[session_id] = session

    return {
        "session_id": session_id,
        "status": "created",
        "message": "Session created. Use /analyze to submit delay events.",
    }


@router.post("/analyze", response_model=DelayAnalysisResponse)
async def analyze_delays(
    request: AnalyzeDelaysRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Analyze submitted delay events."""
    session = _delay_sessions.get(request.session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    # Convert request to dict format
    delay_events = [
        {
            "description": e.description,
            "event_date": e.event_date,
            "planned_date": e.planned_date,
            "actual_date": e.actual_date,
            "delay_days": e.delay_days,
            "evidence_ids": e.evidence_ids,
        }
        for e in request.delay_events
    ]

    # Run analysis
    orchestrator = DelayAnalysisOrchestrator(db, session)
    result = await orchestrator.analyze_delays(delay_events)

    return DelayAnalysisResponse(
        session_id=session.id,
        status=result.status,
        delay_events=[
            {
                "event_id": a.event_id,
                "description": a.description,
                "delay_days": a.delay_days,
                "delay_type": a.delay_type.value,
                "root_cause": a.root_cause,
                "confidence": a.confidence,
            }
            for a in result.delay_events_analyzed
        ],
        causation_chains=[
            {
                "id": c.id,
                "trigger": c.trigger_event,
                "impact": c.final_impact,
                "days": c.total_delay_days,
                "responsible": c.responsible_party,
            }
            for c in result.causation_chains
        ],
        total_delays={
            "employer": result.total_employer_delay_days,
            "contractor": result.total_contractor_delay_days,
            "neutral": result.total_neutral_delay_days,
            "concurrent": result.total_concurrent_days,
        },
        entitlements={
            "eot_days": result.eot_entitlement_days,
            "prolongation": result.prolongation_claim,
            "disruption": result.disruption_claim,
        },
        claims_narrative=result.claims_narrative,
        recommendations=result.recommendations,
    )


@router.get("/session/{session_id}")
async def get_delay_session(
    session_id: str,
    user: User = Depends(current_user),
):
    """Get delay analysis session status and results."""
    session = _delay_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    if session.user_id != str(user.id):
        raise HTTPException(403, "Not authorized")

    return {
        "session_id": session.id,
        "status": session.status,
        "events_analyzed": len(session.delay_events_analyzed),
        "causation_chains": len(session.causation_chains),
        "eot_entitlement": session.eot_entitlement_days,
        "prolongation_claim": session.prolongation_claim,
        "executive_summary": session.executive_summary,
        "has_narrative": session.claims_narrative is not None,
    }
