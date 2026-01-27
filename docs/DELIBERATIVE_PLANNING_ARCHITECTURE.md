# VeriCase Deliberative Research Planning Architecture

## Executive Summary

This document outlines a best-in-class enhancement to VeriCase Analysis's research planning phase. The current implementation generates research plans too quickly (seconds) with only 3,000 characters of evidence context - insufficient for meaningful analysis. This redesign implements **visible deliberation** over 10-20 minutes, ensuring users see and trust that their evidence has been thoroughly analyzed.

**Industry Benchmark**: Thomson Reuters CoCounsel "Deep Research" and LexisNexis Protégé both use multi-agent architectures with visible reasoning processes. VeriCase will match and exceed these capabilities.

---

## Problem Statement

### Current Implementation Issues

```
Current Flow (vericase_analysis.py):
User Request → Single LLM Call (3000 chars) → Research Plan (5-10 seconds)
```

| Issue | Impact |
|-------|--------|
| Only 3,000 characters of evidence passed to planner | Ignores 99%+ of evidence |
| Single LLM call for planning | No deliberation or analysis |
| Instant response | Users don't trust superficial analysis |
| Hardcoded `estimated_time_minutes: 5` | Not based on evidence volume |
| No visible reasoning process | Black box to users |

### User Expectation

> "A proper research plan for thousands of documents should take at least 10 minutes of visible analysis"

---

## Architecture Overview

### New Deliberative Planning Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DELIBERATIVE PLANNING PIPELINE                       │
│                              (12-25 minutes)                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
    ┌─────────────────────────────────┼─────────────────────────────────┐
    │                                 │                                 │
    ▼                                 ▼                                 ▼
┌─────────┐                    ┌─────────────┐                   ┌──────────┐
│ Phase 1 │                    │   Phase 2   │                   │ Phase 3  │
│ CORPUS  │─────────────────▶  │   ENTITY    │─────────────────▶ │  ISSUE   │
│  SCAN   │                    │   MAPPING   │                   │   ID     │
│ (3-5m)  │                    │   (2-3m)    │                   │  (2-3m)  │
└─────────┘                    └─────────────┘                   └──────────┘
     │                               │                                 │
     │ AWS Comprehend                │ Graph Building                  │ LLM Analysis
     │ Entity Extraction             │ Relationship Detection          │ Issue Detection
     │                               │                                 │
     ▼                               ▼                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            STREAMING EVENTS TO FRONTEND                      │
│  "Scanning document 127/2341..." │ "Found 47 parties..." │ "8 issues..."   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
    ┌─────────────────────────────────┼─────────────────────────────────┐
    │                                 │                                 │
    ▼                                 ▼                                 ▼
┌─────────┐                    ┌─────────────┐                   ┌──────────┐
│ Phase 4 │                    │   Phase 5   │                   │ HUMAN IN │
│  ANGLE  │─────────────────▶  │    PLAN     │─────────────────▶ │THE LOOP  │
│ DELIB.  │                    │  SYNTHESIS  │                   │ APPROVAL │
│ (3-5m)  │                    │   (2-3m)    │                   │          │
└─────────┘                    └─────────────┘                   └──────────┘
     │                               │                                 │
     │ Multi-Angle LLM               │ Evidence-Grounded              │ Full Context
     │ Reasoning Passes              │ Question Generation            │ + Edit Option
```

---

## Phase Specifications

### Phase 1: Corpus Scan (3-5 minutes)

**Purpose**: Systematically analyze ALL evidence items with AWS Comprehend and multi-vector semantic indexing.

**AWS Services Used**:
- Amazon Comprehend for entity extraction (people, organizations, dates, locations, quantities)
- Amazon Comprehend for key phrase extraction
- Amazon Comprehend for sentiment analysis (per document)

**Implementation**:

```python
class CorpusScanPhase:
    """
    Phase 1: Comprehensive corpus analysis using AWS Comprehend.
    
    Streams progress events as each document is analyzed.
    """
    
    async def execute(
        self,
        evidence_items: list[dict],
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]]
    ) -> CorpusScanResult:
        total = len(evidence_items)
        entities_collected = []
        
        for i, item in enumerate(evidence_items):
            # Stream progress
            await progress_callback(DeliberationEvent(
                phase="corpus_scan",
                phase_display="Corpus Analysis",
                progress=i + 1,
                total=total,
                current_action=f"Analyzing: {item.get('subject', 'Document')}",
                elapsed_seconds=self._elapsed(),
                estimated_remaining=self._estimate_remaining(i, total),
            ))
            
            # AWS Comprehend entity extraction
            text = item.get("body_text", "")[:5000]  # Comprehend limit
            comprehend_result = await self.aws_services.analyze_document_entities(text)
            
            entities_collected.append({
                "document_id": item["id"],
                "entities": comprehend_result["entities"],
                "key_phrases": comprehend_result["key_phrases"],
                "sentiment": comprehend_result["sentiment"],
            })
            
            # Stream significant findings as they're discovered
            for entity in comprehend_result["entities"][:3]:
                if entity["score"] > 0.9:
                    await progress_callback(DeliberationEvent(
                        phase="corpus_scan",
                        finding=f"Found: {entity['text']} ({entity['type']})",
                    ))
        
        return CorpusScanResult(
            documents_analyzed=total,
            entities=self._deduplicate_entities(entities_collected),
            key_phrases=self._aggregate_phrases(entities_collected),
        )
```

**Streaming Events**:
```json
{
  "phase": "corpus_scan",
  "phase_display": "Corpus Analysis",
  "progress": 127,
  "total": 2341,
  "percentage": 5.4,
  "current_action": "Analyzing: RE: Delay Claim Notice - March 2019",
  "finding": "Found: John Smith (PERSON, Project Manager)",
  "elapsed_seconds": 45,
  "estimated_remaining_seconds": 180
}
```

---

### Phase 2: Entity Mapping (2-3 minutes)

**Purpose**: Build a relationship graph of all discovered entities, identifying connections, communication patterns, and clusters.

**Implementation**:

```python
class EntityMappingPhase:
    """
    Phase 2: Build entity relationship graph.
    
    Uses co-occurrence analysis and semantic similarity to map relationships.
    """
    
    async def execute(
        self,
        corpus_result: CorpusScanResult,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]]
    ) -> EntityGraph:
        
        # Group entities by type
        parties = [e for e in corpus_result.entities if e["type"] in ("PERSON", "ORGANIZATION")]
        dates = [e for e in corpus_result.entities if e["type"] == "DATE"]
        locations = [e for e in corpus_result.entities if e["type"] == "LOCATION"]
        quantities = [e for e in corpus_result.entities if e["type"] == "QUANTITY"]
        
        await progress_callback(DeliberationEvent(
            phase="entity_mapping",
            phase_display="Building Relationship Map",
            finding=f"Mapping {len(parties)} parties, {len(dates)} dates, {len(quantities)} quantities",
        ))
        
        # Build relationship graph using co-occurrence
        graph = EntityGraph()
        for doc in corpus_result.documents:
            doc_entities = self._get_entities_for_doc(doc["id"])
            # Entities in same document are related
            for e1, e2 in itertools.combinations(doc_entities, 2):
                graph.add_edge(e1, e2, weight=1, via_document=doc["id"])
        
        # Identify clusters (e.g., "Contractor team", "Client team")
        clusters = self._detect_clusters(graph)
        
        await progress_callback(DeliberationEvent(
            phase="entity_mapping",
            finding=f"Identified {len(clusters)} party clusters",
            clusters=clusters,
        ))
        
        return graph
```

**Streaming Events**:
```json
{
  "phase": "entity_mapping",
  "phase_display": "Building Relationship Map",
  "finding": "Mapping 47 parties, 156 dates, 23 monetary amounts",
  "clusters": [
    {"name": "Contractor Team", "members": ["ABC Construction", "John Smith", "Jane Doe"]},
    {"name": "Client Team", "members": ["XYZ Corp", "Bob Johnson"]}
  ]
}
```

---

### Phase 3: Issue Identification (2-3 minutes)

**Purpose**: Use LLM analysis of the entity graph combined with the research topic to identify potential legal issues.

**Implementation**:

```python
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
    
    async def execute(
        self,
        topic: str,
        entity_graph: EntityGraph,
        corpus_result: CorpusScanResult,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]]
    ) -> list[Issue]:
        
        await progress_callback(DeliberationEvent(
            phase="issue_identification",
            phase_display="Identifying Legal Issues",
            current_action="Analyzing entity relationships for legal significance...",
        ))
        
        # Prepare context for LLM
        graph_summary = entity_graph.to_summary_text()
        key_phrases_summary = "\n".join(corpus_result.key_phrases[:100])
        
        prompt = f"""Research Topic: {topic}

Entity Relationship Summary:
{graph_summary}

Key Phrases Found in Evidence:
{key_phrases_summary}

Document Date Range: {corpus_result.date_range}
Total Documents: {corpus_result.documents_analyzed}

Identify the key legal issues that emerge from this evidence corpus."""

        response = await self._call_llm(prompt, self.SYSTEM_PROMPT)
        issues = self._parse_issues(response)
        
        for issue in issues:
            await progress_callback(DeliberationEvent(
                phase="issue_identification",
                finding=f"Issue identified: {issue.name} ({issue.evidence_strength} evidence)",
            ))
        
        return issues
```

---

### Phase 4: Angle Deliberation (3-5 minutes)

**Purpose**: Consider multiple research angles (causation, liability, quantum, etc.) through separate LLM passes, showing visible "thinking" for each angle.

**This is the key "deliberation" phase that builds user trust.**

**Implementation**:

```python
class AngleDeliberationPhase:
    """
    Phase 4: Multi-angle deliberation.
    
    Makes multiple LLM calls, each focusing on a different research angle.
    Streams the reasoning process to show visible deliberation.
    """
    
    RESEARCH_ANGLES = [
        {
            "id": "chronology",
            "name": "Chronological Analysis",
            "prompt": "Focus on the timeline of events. What happened when? What is the sequence of cause and effect?",
            "icon": "fa-clock",
        },
        {
            "id": "causation",
            "name": "Causation Analysis", 
            "prompt": "Focus on cause and effect. What caused the issues? Can we establish a causal chain from breach to damage?",
            "icon": "fa-link",
        },
        {
            "id": "liability",
            "name": "Liability & Responsibility",
            "prompt": "Focus on who is responsible. What are the contractual obligations? Who breached what duty?",
            "icon": "fa-balance-scale",
        },
        {
            "id": "quantum",
            "name": "Quantum & Damages",
            "prompt": "Focus on financial impact. What are the claimed amounts? What evidence supports quantum?",
            "icon": "fa-calculator",
        },
        {
            "id": "mitigation",
            "name": "Mitigation & Procedural",
            "prompt": "Focus on mitigation efforts and procedural compliance. Were notices given? Were mitigation steps taken?",
            "icon": "fa-shield-alt",
        },
    ]
    
    async def execute(
        self,
        topic: str,
        issues: list[Issue],
        entity_graph: EntityGraph,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]]
    ) -> list[AngleDeliberation]:
        
        deliberations = []
        
        for angle in self.RESEARCH_ANGLES:
            await progress_callback(DeliberationEvent(
                phase="deliberation",
                phase_display="Research Angle Deliberation",
                current_action=f"Considering {angle['name']} angle...",
                angle_id=angle["id"],
                angle_name=angle["name"],
                angle_icon=angle["icon"],
            ))
            
            # Deliberate on this angle
            prompt = f"""Research Topic: {topic}

Identified Issues:
{self._format_issues(issues)}

Entity Relationships:
{entity_graph.to_summary_text()[:3000]}

RESEARCH ANGLE: {angle['name']}
{angle['prompt']}

Analyze this angle and identify:
1. Key research questions that should be investigated from this angle
2. Relevant evidence pointers (reference document IDs where applicable)
3. Potential findings or hypotheses
4. Gaps that need further investigation

Think step-by-step and show your reasoning."""

            response = await self._call_llm_with_reasoning(prompt)
            
            # Stream the reasoning steps as they're generated
            for reasoning_step in response.reasoning_steps:
                await progress_callback(DeliberationEvent(
                    phase="deliberation",
                    angle_id=angle["id"],
                    reasoning_step=reasoning_step,
                ))
            
            deliberations.append(AngleDeliberation(
                angle_id=angle["id"],
                angle_name=angle["name"],
                research_questions=response.questions,
                evidence_pointers=response.evidence_refs,
                hypotheses=response.hypotheses,
                gaps=response.gaps,
                reasoning_trace=response.reasoning_steps,
            ))
            
            await progress_callback(DeliberationEvent(
                phase="deliberation",
                angle_id=angle["id"],
                finding=f"Identified {len(response.questions)} questions from {angle['name']} angle",
            ))
        
        return deliberations
```

**Streaming Events** (showing visible reasoning):
```json
{
  "phase": "deliberation",
  "phase_display": "Research Angle Deliberation",
  "angle_id": "causation",
  "angle_name": "Causation Analysis",
  "angle_icon": "fa-link",
  "reasoning_step": "Looking at the delay events, I can see that the site access delay on 2019-03-15 preceded the foundation work delay by exactly 14 days...",
  "finding": null
}
```

```json
{
  "phase": "deliberation",
  "angle_id": "causation",
  "finding": "Identified 3 questions from Causation Analysis angle",
  "questions_preview": [
    "What is the causal link between the delayed site access and the foundation delays?",
    "Did concurrent delays by other parties break the chain of causation?"
  ]
}
```

---

### Phase 5: Plan Synthesis (2-3 minutes)

**Purpose**: Synthesize all deliberation results into a coherent, evidence-grounded research plan as a DAG.

**Implementation**:

```python
class PlanSynthesisPhase:
    """
    Phase 5: Synthesize deliberations into research plan.
    
    Creates an evidence-grounded DAG of research questions.
    """
    
    async def execute(
        self,
        topic: str,
        issues: list[Issue],
        deliberations: list[AngleDeliberation],
        corpus_result: CorpusScanResult,
        progress_callback: Callable[[DeliberationEvent], Awaitable[None]]
    ) -> ResearchPlan:
        
        await progress_callback(DeliberationEvent(
            phase="synthesis",
            phase_display="Synthesizing Research Plan",
            current_action="Combining findings from all angles...",
        ))
        
        # Collect all candidate questions from deliberations
        all_questions = []
        for delib in deliberations:
            for q in delib.research_questions:
                all_questions.append({
                    "question": q.text,
                    "angle": delib.angle_name,
                    "evidence_refs": q.evidence_refs,
                    "priority": q.priority,
                })
        
        await progress_callback(DeliberationEvent(
            phase="synthesis",
            finding=f"Collected {len(all_questions)} candidate questions from deliberation",
        ))
        
        # Use LLM to synthesize into coherent DAG
        prompt = f"""You have conducted a thorough analysis of evidence for this research topic:

TOPIC: {topic}

IDENTIFIED ISSUES:
{self._format_issues(issues)}

CANDIDATE RESEARCH QUESTIONS (from multi-angle deliberation):
{self._format_questions(all_questions)}

EVIDENCE STATISTICS:
- Documents analyzed: {corpus_result.documents_analyzed}
- Parties identified: {len(corpus_result.entities_by_type.get('PERSON', []))}
- Organizations: {len(corpus_result.entities_by_type.get('ORGANIZATION', []))}
- Date range: {corpus_result.date_range}

Now synthesize these into a coherent research plan with 6-10 interconnected questions.

Requirements:
1. Each question MUST reference specific evidence (by document ID or entity name)
2. Questions should form a DAG (some depend on others)
3. Prioritize questions with strong evidence support
4. Cover all major angles but avoid redundancy
5. Estimate research time based on evidence volume

Output as JSON:
{{
  "problem_statement": "Clear statement based on analysis",
  "key_angles": ["angle1", "angle2"],
  "questions": [
    {{
      "id": "q1",
      "question": "The specific research question",
      "rationale": "Why this matters - reference specific evidence",
      "evidence_refs": ["doc_123", "doc_456"],
      "dependencies": [],
      "estimated_minutes": 5
    }}
  ],
  "total_estimated_minutes": 45,
  "deliberation_summary": "Brief summary of deliberation process"
}}"""

        response = await self._call_llm(prompt)
        plan = self._parse_plan(response, topic)
        
        for q in plan.questions:
            await progress_callback(DeliberationEvent(
                phase="synthesis",
                finding=f"Research question: {q.question[:80]}...",
            ))
        
        return plan
```

---

## Frontend Implementation

### Chain-of-Thought Visualization Component

```html
<!-- Deliberation Progress Panel -->
<div id="deliberation-panel" class="deliberation-panel">
  
  <!-- Phase Progress Bar -->
  <div class="phase-progress">
    <div class="phase-indicator active" data-phase="corpus_scan">
      <i class="fas fa-search"></i>
      <span>Corpus Scan</span>
    </div>
    <div class="phase-connector"></div>
    <div class="phase-indicator" data-phase="entity_mapping">
      <i class="fas fa-project-diagram"></i>
      <span>Entity Mapping</span>
    </div>
    <div class="phase-connector"></div>
    <div class="phase-indicator" data-phase="issue_identification">
      <i class="fas fa-exclamation-triangle"></i>
      <span>Issue ID</span>
    </div>
    <div class="phase-connector"></div>
    <div class="phase-indicator" data-phase="deliberation">
      <i class="fas fa-brain"></i>
      <span>Deliberation</span>
    </div>
    <div class="phase-connector"></div>
    <div class="phase-indicator" data-phase="synthesis">
      <i class="fas fa-magic"></i>
      <span>Synthesis</span>
    </div>
  </div>
  
  <!-- Current Phase Detail -->
  <div class="current-phase-detail">
    <div class="phase-header">
      <h3 id="phase-title">Corpus Analysis</h3>
      <div class="phase-timer">
        <span id="elapsed-time">0:00</span> / 
        <span id="estimated-time">~3:00</span>
      </div>
    </div>
    
    <div class="phase-progress-bar">
      <div id="phase-progress-fill" class="progress-fill" style="width: 0%"></div>
    </div>
    <div class="progress-text">
      <span id="progress-current">0</span> / <span id="progress-total">0</span>
    </div>
    
    <!-- Current Action -->
    <div id="current-action" class="current-action">
      <i class="fas fa-spinner fa-spin"></i>
      <span>Initializing analysis...</span>
    </div>
  </div>
  
  <!-- Findings Stream (Chain of Thought) -->
  <div class="findings-stream">
    <h4>Discoveries</h4>
    <div id="findings-list" class="findings-list">
      <!-- Findings will be appended here -->
    </div>
  </div>
  
  <!-- Angle Deliberation Cards (Phase 4) -->
  <div id="angle-cards" class="angle-cards" style="display: none;">
    <!-- Generated dynamically for each angle -->
  </div>
  
</div>
```

### JavaScript Event Handler

```javascript
class DeliberationStreamHandler {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.eventSource = null;
    this.startTime = Date.now();
  }
  
  start() {
    this.eventSource = new EventSource(
      `/api/vericase-analysis/deliberate/stream/${this.sessionId}`
    );
    
    this.eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleEvent(data);
    };
    
    this.eventSource.onerror = (error) => {
      console.error("Deliberation stream error:", error);
      this.eventSource.close();
    };
  }
  
  handleEvent(event) {
    // Update phase indicator
    this.updatePhaseIndicator(event.phase);
    
    // Update progress
    if (event.progress !== undefined) {
      this.updateProgress(event.progress, event.total);
    }
    
    // Update current action
    if (event.current_action) {
      this.updateCurrentAction(event.current_action);
    }
    
    // Add finding to stream
    if (event.finding) {
      this.addFinding(event);
    }
    
    // Handle reasoning steps (Phase 4)
    if (event.reasoning_step) {
      this.addReasoningStep(event);
    }
    
    // Update time estimates
    this.updateTimeEstimates(event.elapsed_seconds, event.estimated_remaining_seconds);
  }
  
  addFinding(event) {
    const findingsList = document.getElementById("findings-list");
    const findingEl = document.createElement("div");
    findingEl.className = `finding-item finding-${event.phase}`;
    findingEl.innerHTML = `
      <i class="${this.getPhaseIcon(event.phase)}"></i>
      <span class="finding-text">${event.finding}</span>
      <span class="finding-time">${this.formatElapsed()}</span>
    `;
    findingsList.appendChild(findingEl);
    findingEl.scrollIntoView({ behavior: "smooth" });
  }
  
  addReasoningStep(event) {
    // For Phase 4: Show visible thinking
    const angleCard = document.querySelector(`[data-angle="${event.angle_id}"]`);
    if (angleCard) {
      const reasoningArea = angleCard.querySelector(".reasoning-area");
      const stepEl = document.createElement("div");
      stepEl.className = "reasoning-step";
      stepEl.innerHTML = `
        <i class="fas fa-lightbulb"></i>
        <span>${event.reasoning_step}</span>
      `;
      reasoningArea.appendChild(stepEl);
    }
  }
}
```

---

## Time Estimation Algorithm

```python
def estimate_deliberation_time(evidence_count: int) -> dict:
    """
    Estimate total deliberation time based on evidence volume.
    
    Returns phase-by-phase estimates.
    """
    
    # Base times in seconds
    base_times = {
        "corpus_scan": 60,      # 1 minute base
        "entity_mapping": 90,   # 1.5 minutes base
        "issue_identification": 120,  # 2 minutes base
        "deliberation": 180,    # 3 minutes base
        "synthesis": 120,       # 2 minutes base
    }
    
    # Scaling factors per 100 documents
    scaling_per_100 = {
        "corpus_scan": 30,      # +30s per 100 docs
        "entity_mapping": 15,   # +15s per 100 docs  
        "issue_identification": 10,  # +10s per 100 docs
        "deliberation": 20,     # +20s per 100 docs
        "synthesis": 10,        # +10s per 100 docs
    }
    
    estimates = {}
    doc_hundreds = evidence_count / 100
    
    for phase, base in base_times.items():
        scaling = scaling_per_100[phase] * doc_hundreds
        estimates[phase] = min(base + scaling, base * 5)  # Cap at 5x base
    
    estimates["total"] = sum(estimates.values())
    
    return estimates


# Example outputs:
# 50 documents:   ~8 minutes total
# 500 documents:  ~15 minutes total
# 2000 documents: ~25 minutes total
```

---

## API Endpoints

### New Streaming Endpoint

```python
@router.get("/deliberate/stream/{session_id}")
async def stream_deliberation(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    SSE stream for deliberation progress.
    
    Streams DeliberationEvent objects as the system analyzes evidence.
    """
    session = load_session(session_id)
    if not session or session.user_id != str(user.id):
        raise HTTPException(404, "Session not found")
    
    async def event_generator():
        async for event in session.deliberation_stream:
            yield f"data: {event.model_dump_json()}\n\n"
        yield "data: {\"phase\": \"complete\"}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

### Modified Start Endpoint

```python
@router.post("/start", response_model=StartAnalysisResponse)
async def start_vericase_analysis(
    request: StartAnalysisRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """
    Start a new VeriCase analysis session with deliberative planning.
    """
    # Create session
    session = AnalysisSession(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        project_id=request.project_id,
        case_id=request.case_id,
        topic=request.topic,
        scope=request.scope,
        status=AnalysisStatus.PENDING,
    )
    
    # Calculate time estimate based on evidence volume
    evidence_count = await count_evidence_items(db, request.project_id, request.case_id)
    time_estimates = estimate_deliberation_time(evidence_count)
    
    session.estimated_planning_time = time_estimates["total"]
    save_session(session)
    
    # Start deliberative planning in background
    background_tasks.add_task(
        run_deliberative_planning,
        session.id,
        db,
    )
    
    return StartAnalysisResponse(
        session_id=session.id,
        status=session.status.value,
        message=f"Deliberative planning started. Estimated time: {time_estimates['total'] // 60} minutes.",
        estimated_planning_minutes=time_estimates["total"] // 60,
        evidence_count=evidence_count,
        stream_url=f"/api/vericase-analysis/deliberate/stream/{session.id}",
    )
```

---

## Data Models

```python
class DeliberationEvent(BaseModel):
    """Event streamed during deliberative planning."""
    
    phase: str  # corpus_scan, entity_mapping, issue_identification, deliberation, synthesis
    phase_display: str | None = None
    progress: int | None = None
    total: int | None = None
    percentage: float | None = None
    current_action: str | None = None
    finding: str | None = None
    
    # Phase 4 specific
    angle_id: str | None = None
    angle_name: str | None = None
    angle_icon: str | None = None
    reasoning_step: str | None = None
    
    # Timing
    elapsed_seconds: int | None = None
    estimated_remaining_seconds: int | None = None
    
    # Rich data
    entities: list[dict] | None = None
    clusters: list[dict] | None = None
    issues: list[dict] | None = None


class CorpusScanResult(BaseModel):
    """Result of Phase 1: Corpus Scan."""
    
    documents_analyzed: int
    entities: list[dict]
    entities_by_type: dict[str, list[dict]]
    key_phrases: list[str]
    date_range: dict[str, str]
    sentiment_distribution: dict[str, int]


class EntityGraph(BaseModel):
    """Result of Phase 2: Entity Mapping."""
    
    nodes: list[dict]
    edges: list[dict]
    clusters: list[dict]
    
    def to_summary_text(self) -> str:
        """Convert graph to text summary for LLM context."""
        ...


class Issue(BaseModel):
    """A legal issue identified in Phase 3."""
    
    id: str
    name: str
    description: str
    parties_involved: list[str]
    date_range: dict[str, str] | None
    evidence_strength: str  # strong, moderate, weak
    key_evidence_refs: list[str]
    gaps: list[str]


class AngleDeliberation(BaseModel):
    """Result of deliberation on one research angle (Phase 4)."""
    
    angle_id: str
    angle_name: str
    research_questions: list[dict]
    evidence_pointers: list[str]
    hypotheses: list[str]
    gaps: list[str]
    reasoning_trace: list[str]


class EnhancedResearchPlan(ResearchPlan):
    """Enhanced research plan with evidence grounding."""
    
    # All original fields plus:
    evidence_refs: dict[str, list[str]]  # question_id -> [doc_ids]
    deliberation_summary: str
    corpus_statistics: dict[str, Any]
    issues_identified: list[Issue]
    angles_considered: list[str]
    total_deliberation_time_seconds: int
```

---

## Configuration

### ai_settings.py Additions

```python
DEFAULT_TOOL_CONFIGS = {
    # ... existing configs ...
    
    "deliberative_planning": {
        "enabled": True,
        "display_name": "Deliberative Research Planning",
        "description": "Multi-phase evidence analysis with visible reasoning",
        "category": "analysis",
        
        "phases": {
            "corpus_scan": {
                "enabled": True,
                "use_comprehend": True,
                "max_documents_per_batch": 50,
                "timeout_seconds": 600,  # 10 minutes max
            },
            "entity_mapping": {
                "enabled": True,
                "min_cooccurrence": 2,
                "cluster_threshold": 0.7,
                "timeout_seconds": 300,
            },
            "issue_identification": {
                "enabled": True,
                "max_issues": 15,
                "timeout_seconds": 300,
            },
            "deliberation": {
                "enabled": True,
                "angles": ["chronology", "causation", "liability", "quantum", "mitigation"],
                "timeout_per_angle_seconds": 120,
            },
            "synthesis": {
                "enabled": True,
                "max_questions": 12,
                "timeout_seconds": 300,
            },
        },
        
        "agent_models": {
            "corpus_scan": {
                "primary": "claude-3-5-sonnet",  # For entity classification
                "fallback": "claude-3-haiku",
            },
            "issue_identification": {
                "primary": "claude-3-5-sonnet",
                "fallback": "claude-3-haiku",
            },
            "deliberation": {
                "primary": "claude-3-opus",  # Best reasoning for deliberation
                "fallback": "claude-3-5-sonnet",
            },
            "synthesis": {
                "primary": "claude-3-5-sonnet",
                "fallback": "claude-3-haiku",
            },
        },
        
        "time_estimation": {
            "min_total_minutes": 5,
            "max_total_minutes": 30,
            "base_times": {
                "corpus_scan": 60,
                "entity_mapping": 90,
                "issue_identification": 120,
                "deliberation": 180,
                "synthesis": 120,
            },
            "scaling_per_100_docs": {
                "corpus_scan": 30,
                "entity_mapping": 15,
                "issue_identification": 10,
                "deliberation": 20,
                "synthesis": 10,
            },
        },
    },
}
```

---

## Implementation Checklist

### Phase 1: Backend Foundation
- [ ] Create `DeliberationEvent` model
- [ ] Create `CorpusScanResult`, `EntityGraph`, `Issue`, `AngleDeliberation` models
- [ ] Create `DeliberativePlannerAgent` class
- [ ] Implement Phase 1: Corpus Scan with Comprehend integration
- [ ] Implement Phase 2: Entity Mapping
- [ ] Implement Phase 3: Issue Identification
- [ ] Implement Phase 4: Angle Deliberation
- [ ] Implement Phase 5: Plan Synthesis
- [ ] Add SSE streaming endpoint
- [ ] Add time estimation algorithm
- [ ] Add configuration to `ai_settings.py`

### Phase 2: Frontend Visualization
- [ ] Create Chain-of-Thought panel component
- [ ] Implement phase progress indicators
- [ ] Implement findings stream
- [ ] Implement angle deliberation cards
- [ ] Implement reasoning step visualization
- [ ] Add time elapsed/remaining display
- [ ] Add smooth animations and transitions

### Phase 3: Integration & Testing
- [ ] Integrate with existing VeriCase Analysis flow
- [ ] Update `/start` endpoint
- [ ] Update status polling to use SSE
- [ ] Test with various evidence volumes
- [ ] Performance testing
- [ ] Error handling and recovery

### Phase 4: Observability
- [ ] Add CloudWatch logging for each phase
- [ ] Add metrics for phase durations
- [ ] Add tracing for debugging
- [ ] Create dashboard for monitoring

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Planning phase duration | 5-10 seconds | 10-25 minutes |
| Evidence context used | 3,000 chars | 100% of corpus |
| User visibility into reasoning | None | Full chain-of-thought |
| Evidence references in plan | 0 | 5+ per question |
| User trust score (NPS) | Unknown | Measure baseline |

---

## References

1. **Thomson Reuters CoCounsel Deep Research** - Multi-agent legal research architecture
2. **LexisNexis Protégé** - Four-agent orchestration (orchestrator, research, web, document)
3. **AWS Bedrock Agents Trace** - Step-by-step reasoning visibility
4. **LangGraph** - State machine patterns for human-in-the-loop
5. **AI-SDK Chain of Thought Component** - Visual reasoning display
6. **AWS Prescriptive Guidance** - Workflow orchestration agents
7. **Amazon Comprehend** - Entity extraction and document analysis

---

*Document Version: 1.0*  
*Last Updated: January 2026*  
*Author: VeriCase AI Team*
