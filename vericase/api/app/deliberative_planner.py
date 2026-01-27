"""
Deliberative Research Planner for VeriCase Analysis.

This module implements a multi-phase, visible deliberation process for generating
research plans. Unlike the simple PlannerAgent that makes a single LLM call with
3,000 characters of context, this system:

1. Scans the ENTIRE evidence corpus with AWS Comprehend
2. Builds entity relationship graphs
3. Identifies legal issues through LLM analysis
4. Deliberates on multiple research angles with visible reasoning
5. Synthesizes an evidence-grounded research plan

Each phase streams progress events to the frontend for real-time visibility.

References:
- Thomson Reuters CoCounsel "Deep Research" architecture
- AWS Bedrock Agent Traces for step-by-step reasoning visibility
- LangGraph human-in-the-loop patterns

Author: VeriCase AI Team
Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from vericase.api.app.aws_services import AWSServices
    from vericase.api.app.vericase_analysis import ResearchPlan, ResearchQuestion

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════


class DeliberationPhase(str, Enum):
    """Phases of the deliberative planning process."""

    INITIALIZING = "initializing"
    CORPUS_SCAN = "corpus_scan"
    ENTITY_MAPPING = "entity_mapping"
    ISSUE_IDENTIFICATION = "issue_identification"
    DELIBERATION = "deliberation"
    SYNTHESIS = "synthesis"
    COMPLETE = "complete"


class DeliberationEvent(BaseModel):
    """
    Event streamed during deliberative planning.

    These events are sent via SSE to the frontend to show real-time progress.
    """

    phase: str
    phase_display: str | None = None
    progress: int | None = None
    total: int | None = None
    percentage: float | None = None
    current_action: str | None = None
    finding: str | None = None

    # Phase 4 (deliberation) specific
    angle_id: str | None = None
    angle_name: str | None = None
    angle_icon: str | None = None
    reasoning_step: str | None = None

    # Timing
    elapsed_seconds: int | None = None
    estimated_remaining_seconds: int | None = None

    # Rich data
    entities: list[dict[str, Any]] | None = None
    clusters: list[dict[str, Any]] | None = None
    issues: list[dict[str, Any]] | None = None


class ExtractedEntity(BaseModel):
    """Entity extracted from evidence via Comprehend."""

    text: str
    entity_type: str  # PERSON, ORGANIZATION, DATE, LOCATION, QUANTITY, etc.
    score: float
    document_id: str
    document_subject: str | None = None


class CorpusScanResult(BaseModel):
    """Result of Phase 1: Corpus Scan."""

    documents_analyzed: int
    entities: list[ExtractedEntity]
    entities_by_type: dict[str, list[ExtractedEntity]] = {}
    key_phrases: list[str] = []
    date_range: dict[str, str | None] = {"start": None, "end": None}
    sentiment_distribution: dict[str, int] = {}
    elapsed_seconds: float = 0


class EntityRelationship(BaseModel):
    """Relationship between two entities."""

    from_entity: str
    to_entity: str
    weight: int = 1
    via_documents: list[str] = []


class EntityCluster(BaseModel):
    """Cluster of related entities."""

    name: str
    entity_type: str
    members: list[str]
    central_entity: str | None = None


class EntityGraph(BaseModel):
    """Result of Phase 2: Entity Mapping."""

    nodes: list[dict[str, Any]] = []
    edges: list[EntityRelationship] = []
    clusters: list[EntityCluster] = []

    def to_summary_text(self, max_chars: int = 5000) -> str:
        """Convert graph to text summary for LLM context."""
        lines = ["ENTITY RELATIONSHIP MAP:", ""]

        # Group by type
        type_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in self.nodes:
            type_groups[node.get("type", "OTHER")].append(node)

        for entity_type, entities in type_groups.items():
            lines.append(f"## {entity_type}S:")
            for e in entities[:10]:  # Limit per type
                lines.append(f"  - {e.get('text', 'Unknown')}")
            if len(entities) > 10:
                lines.append(f"  ... and {len(entities) - 10} more")
            lines.append("")

        if self.clusters:
            lines.append("## IDENTIFIED CLUSTERS:")
            for cluster in self.clusters[:5]:
                members_str = ", ".join(cluster.members[:5])
                if len(cluster.members) > 5:
                    members_str += f" (+{len(cluster.members) - 5} more)"
                lines.append(f"  - {cluster.name}: {members_str}")

        summary = "\n".join(lines)
        return summary[:max_chars]


class LegalIssue(BaseModel):
    """A legal issue identified in Phase 3."""

    id: str
    name: str
    description: str
    parties_involved: list[str] = []
    date_range: dict[str, str | None] | None = None
    evidence_strength: str = "moderate"  # strong, moderate, weak
    key_evidence_refs: list[str] = []
    gaps: list[str] = []


class AngleDeliberation(BaseModel):
    """Result of deliberation on one research angle (Phase 4)."""

    angle_id: str
    angle_name: str
    research_questions: list[dict[str, Any]] = []
    evidence_pointers: list[str] = []
    hypotheses: list[str] = []
    gaps: list[str] = []
    reasoning_trace: list[str] = []


# ═══════════════════════════════════════════════════════════════════════════
# RESEARCH ANGLES CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

RESEARCH_ANGLES = [
    {
        "id": "chronology",
        "name": "Chronological Analysis",
        "icon": "fa-clock",
        "prompt": """Focus on the TIMELINE OF EVENTS.

Analyze:
- What happened and when?
- What is the sequence of cause and effect?
- Are there any gaps in the timeline?
- What events are contemporaneous?
- What are the key milestone dates?

Consider: project milestones, notice dates, instruction dates, completion dates.""",
    },
    {
        "id": "causation",
        "name": "Causation Analysis",
        "icon": "fa-link",
        "prompt": """Focus on CAUSE AND EFFECT relationships.

Analyze:
- What caused the issues identified?
- Can we establish a causal chain from breach to damage?
- Are there concurrent causes or intervening events?
- What evidence supports causation?
- Are there any breaks in the chain of causation?

Consider: delay events, instructed changes, external factors.""",
    },
    {
        "id": "liability",
        "name": "Liability & Responsibility",
        "icon": "fa-balance-scale",
        "prompt": """Focus on WHO IS RESPONSIBLE.

Analyze:
- What were the contractual obligations of each party?
- Who breached what duty or obligation?
- What are the relevant contract clauses?
- Are there any limitation or exclusion clauses?
- What is the standard of care required?

Consider: contract terms, specifications, industry standards.""",
    },
    {
        "id": "quantum",
        "name": "Quantum & Damages",
        "icon": "fa-calculator",
        "prompt": """Focus on FINANCIAL IMPACT AND DAMAGES.

Analyze:
- What are the claimed amounts and their basis?
- What evidence supports the quantum claimed?
- How are damages calculated?
- Are there any mitigation issues?
- What are the heads of claim?

Consider: cost records, invoices, valuations, delay costs, lost profit.""",
    },
    {
        "id": "procedural",
        "name": "Procedural & Notice",
        "icon": "fa-clipboard-check",
        "prompt": """Focus on PROCEDURAL COMPLIANCE.

Analyze:
- Were proper notices given?
- Were time bars complied with?
- What is the claims procedure in the contract?
- Were instructions properly given and recorded?
- Is there evidence of waiver or estoppel?

Consider: notice provisions, time bars, claims procedures, variations clauses.""",
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# TIME ESTIMATION
# ═══════════════════════════════════════════════════════════════════════════


def estimate_deliberation_time(evidence_count: int) -> dict[str, int]:
    """
    Estimate total deliberation time based on evidence volume.

    Returns phase-by-phase estimates in seconds.
    """
    # Base times in seconds
    base_times = {
        "corpus_scan": 60,  # 1 minute base
        "entity_mapping": 90,  # 1.5 minutes base
        "issue_identification": 120,  # 2 minutes base
        "deliberation": 180,  # 3 minutes base (total for all angles)
        "synthesis": 120,  # 2 minutes base
    }

    # Scaling factors per 100 documents
    scaling_per_100 = {
        "corpus_scan": 30,  # +30s per 100 docs
        "entity_mapping": 15,  # +15s per 100 docs
        "issue_identification": 10,  # +10s per 100 docs
        "deliberation": 20,  # +20s per 100 docs
        "synthesis": 10,  # +10s per 100 docs
    }

    estimates: dict[str, int] = {}
    doc_hundreds = evidence_count / 100

    for phase, base in base_times.items():
        scaling = int(scaling_per_100[phase] * doc_hundreds)
        # Cap at 5x base time
        estimates[phase] = min(base + scaling, base * 5)

    estimates["total"] = sum(estimates.values())

    return estimates


# ═══════════════════════════════════════════════════════════════════════════
# PHASE IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class PhaseContext:
    """Shared context across deliberation phases."""

    session_id: str
    topic: str
    evidence_items: list[dict[str, Any]]
    aws_services: AWSServices
    db: Session
    start_time: float = field(default_factory=time.time)
    time_estimates: dict[str, int] = field(default_factory=dict)

    def elapsed_seconds(self) -> int:
        """Get elapsed time since start."""
        return int(time.time() - self.start_time)


class CorpusScanPhase:
    """
    Phase 1: Comprehensive corpus analysis using AWS Comprehend.

    Scans ALL evidence items, extracting:
    - Named entities (people, organizations, dates, locations)
    - Key phrases
    - Sentiment per document

    Streams progress events as each document batch is analyzed.
    """

    BATCH_SIZE = 10  # Process documents in batches for efficiency

    def __init__(self, ctx: PhaseContext):
        self.ctx = ctx

    async def execute(
        self,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]],
    ) -> CorpusScanResult:
        """Execute the corpus scan phase."""
        phase_start = time.time()
        total = len(self.ctx.evidence_items)

        await progress_callback(
            DeliberationEvent(
                phase="corpus_scan",
                phase_display="Corpus Analysis",
                current_action=f"Preparing to analyze {total} evidence items...",
                progress=0,
                total=total,
                elapsed_seconds=self.ctx.elapsed_seconds(),
                estimated_remaining_seconds=self.ctx.time_estimates.get("corpus_scan", 300),
            )
        )

        all_entities: list[ExtractedEntity] = []
        all_phrases: list[str] = []
        sentiment_counts: dict[str, int] = defaultdict(int)
        dates_found: list[str] = []

        # Process in batches
        for batch_start in range(0, total, self.BATCH_SIZE):
            batch_end = min(batch_start + self.BATCH_SIZE, total)
            batch = self.ctx.evidence_items[batch_start:batch_end]

            # Process batch concurrently
            tasks = [self._analyze_document(doc, progress_callback) for doc in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for doc, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to analyze document {doc.get('id')}: {result}")
                    continue

                if result:
                    all_entities.extend(result.get("entities", []))
                    all_phrases.extend(result.get("key_phrases", []))
                    sentiment_counts[result.get("sentiment", "NEUTRAL")] += 1

                    # Collect date entities for range calculation
                    for e in result.get("entities", []):
                        if e.entity_type == "DATE":
                            dates_found.append(e.text)

            # Stream progress update
            progress = batch_end
            estimated_remaining = self._estimate_remaining(
                batch_end, total, phase_start
            )

            await progress_callback(
                DeliberationEvent(
                    phase="corpus_scan",
                    phase_display="Corpus Analysis",
                    progress=progress,
                    total=total,
                    percentage=round(100 * progress / total, 1),
                    current_action=f"Analyzed batch {batch_start // self.BATCH_SIZE + 1}",
                    elapsed_seconds=self.ctx.elapsed_seconds(),
                    estimated_remaining_seconds=estimated_remaining,
                )
            )

        # Deduplicate and group entities
        entities_by_type = self._group_entities(all_entities)

        # Stream key findings
        for entity_type, entities in entities_by_type.items():
            if entities:
                sample = [e.text for e in entities[:3]]
                await progress_callback(
                    DeliberationEvent(
                        phase="corpus_scan",
                        finding=f"Found {len(entities)} {entity_type}s: {', '.join(sample)}...",
                    )
                )

        return CorpusScanResult(
            documents_analyzed=total,
            entities=all_entities,
            entities_by_type=entities_by_type,
            key_phrases=list(set(all_phrases))[:200],  # Top 200 unique phrases
            date_range=self._compute_date_range(dates_found),
            sentiment_distribution=dict(sentiment_counts),
            elapsed_seconds=time.time() - phase_start,
        )

    async def _analyze_document(
        self,
        doc: dict[str, Any],
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]],
    ) -> dict[str, Any] | None:
        """Analyze a single document with Comprehend."""
        text = doc.get("body_text", "") or doc.get("content", "") or ""
        if not text or len(text.strip()) < 10:
            return None

        doc_id = doc.get("id", str(uuid.uuid4()))
        subject = doc.get("subject", "")[:100]

        # Stream what we're analyzing
        await progress_callback(
            DeliberationEvent(
                phase="corpus_scan",
                current_action=f"Analyzing: {subject or 'Document'}",
            )
        )

        try:
            # Use AWS Comprehend via our existing integration
            result = await self.ctx.aws_services.analyze_document_entities(text[:5000])

            # Convert to our entity format
            entities = [
                ExtractedEntity(
                    text=e["text"],
                    entity_type=e["type"],
                    score=e.get("score", 0.9),
                    document_id=doc_id,
                    document_subject=subject,
                )
                for e in result.get("entities", [])
            ]

            return {
                "entities": entities,
                "key_phrases": result.get("key_phrases", []),
                "sentiment": result.get("sentiment", "NEUTRAL"),
            }

        except Exception as e:
            logger.warning(f"Comprehend analysis failed for {doc_id}: {e}")
            return None

    def _group_entities(
        self, entities: list[ExtractedEntity]
    ) -> dict[str, list[ExtractedEntity]]:
        """Group and deduplicate entities by type."""
        grouped: dict[str, list[ExtractedEntity]] = defaultdict(list)
        seen: dict[str, set[str]] = defaultdict(set)

        for entity in entities:
            # Normalize text for deduplication
            normalized = entity.text.strip().lower()
            if normalized not in seen[entity.entity_type]:
                seen[entity.entity_type].add(normalized)
                grouped[entity.entity_type].append(entity)

        return dict(grouped)

    def _estimate_remaining(
        self, current: int, total: int, phase_start: float
    ) -> int:
        """Estimate remaining time based on progress."""
        if current == 0:
            return self.ctx.time_estimates.get("corpus_scan", 300)

        elapsed = time.time() - phase_start
        rate = current / elapsed
        remaining_items = total - current

        if rate > 0:
            return int(remaining_items / rate)
        return 0

    def _compute_date_range(
        self, dates: list[str]
    ) -> dict[str, str | None]:
        """Attempt to compute date range from found dates."""
        # Simple implementation - could be enhanced with date parsing
        return {"start": None, "end": None}


class EntityMappingPhase:
    """
    Phase 2: Build entity relationship graph.

    Uses co-occurrence analysis to map relationships between entities.
    Identifies clusters of related entities (e.g., "Contractor team", "Client team").
    """

    def __init__(self, ctx: PhaseContext):
        self.ctx = ctx

    async def execute(
        self,
        corpus_result: CorpusScanResult,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]],
    ) -> EntityGraph:
        """Execute the entity mapping phase."""
        await progress_callback(
            DeliberationEvent(
                phase="entity_mapping",
                phase_display="Building Relationship Map",
                current_action="Analyzing entity co-occurrences...",
                elapsed_seconds=self.ctx.elapsed_seconds(),
            )
        )

        # Build co-occurrence map
        doc_entities: dict[str, list[ExtractedEntity]] = defaultdict(list)
        for entity in corpus_result.entities:
            doc_entities[entity.document_id].append(entity)

        # Create edges based on co-occurrence
        edges: list[EntityRelationship] = []
        edge_weights: dict[tuple[str, str], EntityRelationship] = {}

        for doc_id, entities in doc_entities.items():
            # Only use high-value entity types for relationships
            valuable_entities = [
                e for e in entities if e.entity_type in ("PERSON", "ORGANIZATION")
            ]

            for e1, e2 in itertools.combinations(valuable_entities, 2):
                key = tuple(sorted([e1.text, e2.text]))
                if key not in edge_weights:
                    edge_weights[key] = EntityRelationship(
                        from_entity=key[0],
                        to_entity=key[1],
                        weight=1,
                        via_documents=[doc_id],
                    )
                else:
                    edge_weights[key].weight += 1
                    if doc_id not in edge_weights[key].via_documents:
                        edge_weights[key].via_documents.append(doc_id)

        edges = list(edge_weights.values())

        # Create nodes
        nodes: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        for entity in corpus_result.entities:
            if entity.text not in seen_nodes and entity.entity_type in (
                "PERSON",
                "ORGANIZATION",
            ):
                seen_nodes.add(entity.text)
                nodes.append(
                    {
                        "text": entity.text,
                        "type": entity.entity_type,
                        "document_count": len(
                            [
                                e
                                for e in corpus_result.entities
                                if e.text == entity.text
                            ]
                        ),
                    }
                )

        # Identify clusters (simple: group by common documents)
        clusters = self._identify_clusters(edges, corpus_result.entities)

        await progress_callback(
            DeliberationEvent(
                phase="entity_mapping",
                finding=f"Mapped {len(nodes)} parties with {len(edges)} relationships",
                clusters=[c.model_dump() for c in clusters],
            )
        )

        for cluster in clusters:
            await progress_callback(
                DeliberationEvent(
                    phase="entity_mapping",
                    finding=f"Identified cluster: {cluster.name} ({len(cluster.members)} members)",
                )
            )

        return EntityGraph(nodes=nodes, edges=edges, clusters=clusters)

    def _identify_clusters(
        self,
        edges: list[EntityRelationship],
        entities: list[ExtractedEntity],
    ) -> list[EntityCluster]:
        """Identify clusters of closely related entities."""
        # Simple clustering: entities with >5 co-occurrences
        strong_connections: dict[str, list[str]] = defaultdict(list)

        for edge in edges:
            if edge.weight >= 3:  # At least 3 co-occurrences
                strong_connections[edge.from_entity].append(edge.to_entity)
                strong_connections[edge.to_entity].append(edge.from_entity)

        # Find connected components
        visited: set[str] = set()
        clusters: list[EntityCluster] = []

        for entity in strong_connections:
            if entity not in visited:
                cluster_members = self._bfs_cluster(
                    entity, strong_connections, visited
                )
                if len(cluster_members) >= 2:  # At least 2 members
                    # Determine entity type (majority)
                    entity_types = [
                        e.entity_type
                        for e in entities
                        if e.text in cluster_members
                    ]
                    majority_type = max(
                        set(entity_types), key=entity_types.count, default="PERSON"
                    )

                    clusters.append(
                        EntityCluster(
                            name=f"Cluster {len(clusters) + 1}",
                            entity_type=majority_type,
                            members=cluster_members,
                            central_entity=entity,
                        )
                    )

        return clusters[:10]  # Limit to top 10 clusters

    def _bfs_cluster(
        self,
        start: str,
        connections: dict[str, list[str]],
        visited: set[str],
    ) -> list[str]:
        """BFS to find connected cluster."""
        cluster = []
        queue = [start]

        while queue:
            node = queue.pop(0)
            if node not in visited:
                visited.add(node)
                cluster.append(node)
                queue.extend(
                    [n for n in connections.get(node, []) if n not in visited]
                )

        return cluster


class IssueIdentificationPhase:
    """
    Phase 3: LLM-powered issue identification.

    Analyzes entity graph and topic to surface potential legal issues.
    """

    SYSTEM_PROMPT = """You are an expert legal analyst specializing in construction disputes.

Given an entity relationship map and a research topic, identify the key legal issues that should be investigated.

For each issue:
1. Name the issue clearly (e.g., "Delayed access to site", "Variation instruction disputes")
2. Identify the key parties involved
3. Reference the date range where relevant evidence appears
4. Estimate the strength of evidence (strong/moderate/weak)
5. Note any gaps in evidence that should be investigated

Output as JSON with structure:
{
  "issues": [
    {
      "id": "issue_1",
      "name": "string",
      "description": "string",
      "parties_involved": ["string"],
      "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
      "evidence_strength": "strong|moderate|weak",
      "key_evidence_refs": ["doc_id_1", "doc_id_2"],
      "gaps": ["string"]
    }
  ]
}"""

    def __init__(self, ctx: PhaseContext, llm_caller: Callable[..., Awaitable[str]]):
        self.ctx = ctx
        self._call_llm = llm_caller

    async def execute(
        self,
        entity_graph: EntityGraph,
        corpus_result: CorpusScanResult,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]],
    ) -> list[LegalIssue]:
        """Execute issue identification phase."""
        await progress_callback(
            DeliberationEvent(
                phase="issue_identification",
                phase_display="Identifying Legal Issues",
                current_action="Analyzing entity relationships for legal significance...",
                elapsed_seconds=self.ctx.elapsed_seconds(),
            )
        )

        # Prepare context for LLM
        graph_summary = entity_graph.to_summary_text()
        key_phrases_summary = "\n".join(
            f"- {phrase}" for phrase in corpus_result.key_phrases[:50]
        )

        prompt = f"""Research Topic: {self.ctx.topic}

Entity Relationship Summary:
{graph_summary}

Key Phrases Found in Evidence:
{key_phrases_summary}

Documents Analyzed: {corpus_result.documents_analyzed}
Sentiment Distribution: {corpus_result.sentiment_distribution}

Based on this evidence analysis, identify the key legal issues that should be investigated.
Consider: delay claims, variation disputes, payment issues, defects, instructions, notices.

Output as JSON."""

        try:
            response = await self._call_llm(prompt, self.SYSTEM_PROMPT)
            issues = self._parse_issues(response)
        except Exception as e:
            logger.error(f"Issue identification LLM call failed: {e}")
            issues = self._create_fallback_issues()

        for issue in issues:
            await progress_callback(
                DeliberationEvent(
                    phase="issue_identification",
                    finding=f"Issue identified: {issue.name} ({issue.evidence_strength} evidence)",
                )
            )

        return issues

    def _parse_issues(self, response: str) -> list[LegalIssue]:
        """Parse issues from LLM response."""
        try:
            # Extract JSON
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())
            issues = []

            for issue_data in data.get("issues", []):
                issues.append(
                    LegalIssue(
                        id=issue_data.get("id", f"issue_{len(issues)+1}"),
                        name=issue_data.get("name", "Unknown Issue"),
                        description=issue_data.get("description", ""),
                        parties_involved=issue_data.get("parties_involved", []),
                        date_range=issue_data.get("date_range"),
                        evidence_strength=issue_data.get(
                            "evidence_strength", "moderate"
                        ),
                        key_evidence_refs=issue_data.get("key_evidence_refs", []),
                        gaps=issue_data.get("gaps", []),
                    )
                )

            return issues

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse issues: {e}")
            return self._create_fallback_issues()

    def _create_fallback_issues(self) -> list[LegalIssue]:
        """Create fallback issues if parsing fails."""
        return [
            LegalIssue(
                id="issue_1",
                name="Primary Dispute",
                description=f"Investigation of: {self.ctx.topic}",
                evidence_strength="moderate",
            )
        ]


class AngleDeliberationPhase:
    """
    Phase 4: Multi-angle deliberation.

    Makes multiple LLM calls, each focusing on a different research angle.
    Streams the reasoning process to show visible deliberation.

    This is the KEY phase that builds user trust through visible thinking.
    """

    def __init__(self, ctx: PhaseContext, llm_caller: Callable[..., Awaitable[str]]):
        self.ctx = ctx
        self._call_llm = llm_caller

    async def execute(
        self,
        issues: list[LegalIssue],
        entity_graph: EntityGraph,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]],
    ) -> list[AngleDeliberation]:
        """Execute angle deliberation phase."""
        deliberations: list[AngleDeliberation] = []

        for angle in RESEARCH_ANGLES:
            await progress_callback(
                DeliberationEvent(
                    phase="deliberation",
                    phase_display="Research Angle Deliberation",
                    current_action=f"Considering {angle['name']} angle...",
                    angle_id=angle["id"],
                    angle_name=angle["name"],
                    angle_icon=angle["icon"],
                    elapsed_seconds=self.ctx.elapsed_seconds(),
                )
            )

            # Deliberate on this angle
            issues_summary = "\n".join(
                f"- {issue.name}: {issue.description}" for issue in issues
            )

            prompt = f"""Research Topic: {self.ctx.topic}

Identified Issues:
{issues_summary}

Entity Relationships:
{entity_graph.to_summary_text(3000)}

RESEARCH ANGLE: {angle['name']}
{angle['prompt']}

Analyze this angle and identify:
1. Key research questions that should be investigated from this angle
2. Relevant evidence pointers (reference document types where applicable)
3. Potential findings or hypotheses
4. Gaps that need further investigation

Think step-by-step and show your reasoning.
Output as JSON with structure:
{{
  "reasoning_steps": ["step1", "step2", ...],
  "questions": [{{"text": "...", "priority": "high|medium|low", "evidence_type": "..."}}],
  "hypotheses": ["..."],
  "gaps": ["..."]
}}"""

            try:
                response = await self._call_llm(prompt, "You are an expert legal analyst.")
                result = self._parse_deliberation(response, angle)
            except Exception as e:
                logger.warning(f"Deliberation failed for angle {angle['id']}: {e}")
                result = AngleDeliberation(
                    angle_id=angle["id"],
                    angle_name=angle["name"],
                    research_questions=[],
                )

            # Stream reasoning steps
            for step in result.reasoning_trace[:3]:  # Limit to 3 steps for UI
                await progress_callback(
                    DeliberationEvent(
                        phase="deliberation",
                        angle_id=angle["id"],
                        reasoning_step=step,
                    )
                )
                await asyncio.sleep(0.5)  # Brief pause for visual effect

            deliberations.append(result)

            await progress_callback(
                DeliberationEvent(
                    phase="deliberation",
                    angle_id=angle["id"],
                    finding=f"Identified {len(result.research_questions)} questions from {angle['name']} angle",
                )
            )

        return deliberations

    def _parse_deliberation(
        self, response: str, angle: dict[str, Any]
    ) -> AngleDeliberation:
        """Parse deliberation result from LLM response."""
        try:
            # Extract JSON
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())

            return AngleDeliberation(
                angle_id=angle["id"],
                angle_name=angle["name"],
                research_questions=data.get("questions", []),
                hypotheses=data.get("hypotheses", []),
                gaps=data.get("gaps", []),
                reasoning_trace=data.get("reasoning_steps", []),
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse deliberation: {e}")
            # Try to extract any reasoning from the text
            reasoning = []
            for line in response.split("\n")[:5]:
                if line.strip():
                    reasoning.append(line.strip()[:200])

            return AngleDeliberation(
                angle_id=angle["id"],
                angle_name=angle["name"],
                reasoning_trace=reasoning,
            )


class PlanSynthesisPhase:
    """
    Phase 5: Synthesize deliberations into research plan.

    Creates an evidence-grounded DAG of research questions.
    """

    def __init__(self, ctx: PhaseContext, llm_caller: Callable[..., Awaitable[str]]):
        self.ctx = ctx
        self._call_llm = llm_caller

    async def execute(
        self,
        issues: list[LegalIssue],
        deliberations: list[AngleDeliberation],
        corpus_result: CorpusScanResult,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]],
    ) -> dict[str, Any]:
        """Execute plan synthesis phase."""
        await progress_callback(
            DeliberationEvent(
                phase="synthesis",
                phase_display="Synthesizing Research Plan",
                current_action="Combining findings from all angles...",
                elapsed_seconds=self.ctx.elapsed_seconds(),
            )
        )

        # Collect all candidate questions
        all_questions = []
        for delib in deliberations:
            for q in delib.research_questions:
                if isinstance(q, dict):
                    all_questions.append(
                        {
                            "question": q.get("text", str(q)),
                            "angle": delib.angle_name,
                            "priority": q.get("priority", "medium"),
                        }
                    )

        await progress_callback(
            DeliberationEvent(
                phase="synthesis",
                finding=f"Collected {len(all_questions)} candidate questions from deliberation",
            )
        )

        # Format for LLM
        questions_str = "\n".join(
            f"- [{q['angle']}] {q['question']} (priority: {q['priority']})"
            for q in all_questions[:30]  # Limit for context
        )

        issues_str = "\n".join(f"- {issue.name}: {issue.description}" for issue in issues)

        # Get entity summary
        persons = corpus_result.entities_by_type.get("PERSON", [])
        orgs = corpus_result.entities_by_type.get("ORGANIZATION", [])

        prompt = f"""You have conducted a thorough analysis of evidence for this research topic:

TOPIC: {self.ctx.topic}

IDENTIFIED ISSUES:
{issues_str}

CANDIDATE RESEARCH QUESTIONS (from multi-angle deliberation):
{questions_str}

EVIDENCE STATISTICS:
- Documents analyzed: {corpus_result.documents_analyzed}
- Key parties: {len(persons)} people, {len(orgs)} organizations
- Date range: {corpus_result.date_range}

Now synthesize these into a coherent research plan with 6-10 interconnected questions.

Requirements:
1. Each question MUST be specific and evidence-focused
2. Questions should form a DAG (some depend on others)
3. Prioritize questions covering different angles
4. Cover: chronology, causation, liability, quantum where relevant
5. Estimate research time based on evidence volume

Output as JSON:
{{
    "problem_statement": "Clear statement based on analysis",
    "key_angles": ["angle1", "angle2"],
    "questions": [
        {{
            "id": "q1",
            "question": "The specific research question",
            "rationale": "Why this matters",
            "dependencies": [],
            "estimated_minutes": 5
        }}
    ],
    "estimated_time_minutes": {max(30, corpus_result.documents_analyzed // 20)},
    "deliberation_summary": "Brief summary of deliberation process"
}}"""

        try:
            response = await self._call_llm(
                prompt, "You are an expert legal research planner."
            )
            plan_data = self._parse_plan(response)
        except Exception as e:
            logger.error(f"Plan synthesis failed: {e}")
            plan_data = self._create_fallback_plan()

        # Stream final questions
        for q in plan_data.get("questions", [])[:5]:
            await progress_callback(
                DeliberationEvent(
                    phase="synthesis",
                    finding=f"Research question: {q.get('question', '')[:80]}...",
                )
            )

        # Add deliberation metadata
        plan_data["deliberation_metadata"] = {
            "documents_analyzed": corpus_result.documents_analyzed,
            "entities_found": len(corpus_result.entities),
            "issues_identified": len(issues),
            "angles_considered": [d.angle_name for d in deliberations],
            "total_deliberation_seconds": self.ctx.elapsed_seconds(),
        }

        return plan_data

    def _parse_plan(self, response: str) -> dict[str, Any]:
        """Parse plan from LLM response."""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            return json.loads(json_str.strip())

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse plan: {e}")
            return self._create_fallback_plan()

    def _create_fallback_plan(self) -> dict[str, Any]:
        """Create fallback plan if parsing fails."""
        return {
            "problem_statement": f"Investigate: {self.ctx.topic}",
            "key_angles": ["Chronology", "Causation", "Liability"],
            "questions": [
                {
                    "id": "q1",
                    "question": f"What is the timeline of events related to {self.ctx.topic}?",
                    "rationale": "Establish chronological foundation",
                    "dependencies": [],
                },
                {
                    "id": "q2",
                    "question": "What were the key decisions and actions taken?",
                    "rationale": "Identify decision points",
                    "dependencies": ["q1"],
                },
                {
                    "id": "q3",
                    "question": "What evidence supports or contradicts the claims?",
                    "rationale": "Assess evidence strength",
                    "dependencies": ["q1", "q2"],
                },
            ],
            "estimated_time_minutes": 30,
            "deliberation_summary": "Standard analysis pattern applied",
        }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════


class DeliberativePlanner:
    """
    Orchestrates the full deliberative planning process.

    Coordinates all phases and manages streaming events to frontend.
    """

    def __init__(
        self,
        session_id: str,
        topic: str,
        evidence_items: list[dict[str, Any]],
        aws_services: AWSServices,
        db: Session,
        llm_caller: Callable[..., Awaitable[str]],
    ):
        self.ctx = PhaseContext(
            session_id=session_id,
            topic=topic,
            evidence_items=evidence_items,
            aws_services=aws_services,
            db=db,
            time_estimates=estimate_deliberation_time(len(evidence_items)),
        )
        self._call_llm = llm_caller
        self._event_queue: asyncio.Queue[DeliberationEvent] = asyncio.Queue()

    async def run(self) -> dict[str, Any]:
        """
        Run the full deliberative planning process.

        Returns the synthesized research plan with deliberation metadata.
        """
        logger.info(
            f"Starting deliberative planning for session {self.ctx.session_id} "
            f"with {len(self.ctx.evidence_items)} evidence items"
        )

        async def emit_event(event: DeliberationEvent) -> None:
            await self._event_queue.put(event)

        # Phase 1: Corpus Scan
        corpus_scanner = CorpusScanPhase(self.ctx)
        corpus_result = await corpus_scanner.execute(emit_event)

        # Phase 2: Entity Mapping
        entity_mapper = EntityMappingPhase(self.ctx)
        entity_graph = await entity_mapper.execute(corpus_result, emit_event)

        # Phase 3: Issue Identification
        issue_identifier = IssueIdentificationPhase(self.ctx, self._call_llm)
        issues = await issue_identifier.execute(entity_graph, corpus_result, emit_event)

        # Phase 4: Angle Deliberation
        deliberator = AngleDeliberationPhase(self.ctx, self._call_llm)
        deliberations = await deliberator.execute(issues, entity_graph, emit_event)

        # Phase 5: Plan Synthesis
        synthesizer = PlanSynthesisPhase(self.ctx, self._call_llm)
        plan = await synthesizer.execute(issues, deliberations, corpus_result, emit_event)

        # Final event
        await emit_event(
            DeliberationEvent(
                phase="complete",
                phase_display="Planning Complete",
                finding=f"Research plan ready with {len(plan.get('questions', []))} questions",
                elapsed_seconds=self.ctx.elapsed_seconds(),
            )
        )

        logger.info(
            f"Deliberative planning complete for session {self.ctx.session_id} "
            f"in {self.ctx.elapsed_seconds()} seconds"
        )

        return plan

    async def get_event_stream(self):
        """
        Generator yielding deliberation events for SSE streaming.
        """
        while True:
            event = await self._event_queue.get()
            yield event
            if event.phase == "complete":
                break
