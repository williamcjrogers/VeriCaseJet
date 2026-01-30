# VeriCase Agent Page Blueprint

## Objective
Create a dedicated **VeriCase Agent** page inside each Workspace / Project / Case that lets users define long‑running, high‑volume document analysis tasks (email + evidence + files), run them in parallel, and return later to comprehensive, defensible outputs.

The design is intentionally **task‑centric**, **expectation‑managed**, and **cost‑predictable**, while staying flexible for future workflows beyond email/document trawling.

---

## 1) User Experience (UX) Flow

### Entry Points
- **Workspace / Project / Case sidebar:** “Agents” item.
- **Empty state CTA:** “Create your first agent task.”

### Main Screen Layout
1. **Header**
   - Title: “VeriCase Agent”
   - Short explainer: “Automate large‑scale evidence review with traceable, defensible outputs.”
   - Indicators: Active agents, queued agents, total estimated cost, estimated completion times.

2. **Task Builder**
   - Prompt: “What would you like your agent to do?”
   - Template chips (quick‑start):
     - **Timeline Builder** (chronology by topic/event/issue)
     - **Key Actors & Relationships**
     - **Issue Matrix** (facts vs. issues)
     - **Email Thread Synthesis**
     - **Evidence Index & Summary**
   - Inputs:
     - **Scope**: All documents / selected folders / custodian set / date range / tag filters.
     - **Goal**: Freeform text + structured selections (issue/claim).
     - **Output format**: Timeline table, memo, CSV, chart, report.
     - **Depth level**: Quick / Standard / Exhaustive.
     - **Budget limit**: Optional cap.
     - **Runtime expectation**: “May run for hours; results delivered incrementally.”

3. **Agent Queue**
   - Each row: Name, scope, status, ETA, cost‑so‑far, model tier, progress bar.
   - Actions: Pause, resume, cancel, duplicate, export.

4. **Agent Results**
   - Delivered outputs with versioning, confidence notes, citations, and export links.
   - “Continue” action to run follow‑up tasks on the generated output.

---

## 2) Task Types (Initial Set)

1. **Timeline Builder**
   - Input: issue/topic, custodians, date range.
   - Output: chronological events with citations, key evidence, confidence markers.

2. **Issue Matrix**
   - Input: list of issues/questions.
   - Output: table mapping evidence to each issue, with summary narrative.

3. **Key Actors & Relationships**
   - Output: entity list, relationship graph, supporting evidence references.

4. **Email Thread Synthesis**
   - Output: structured summaries of large threads, highlighting decisions.

5. **Evidence Index & Summary**
   - Output: document‑level summaries, tags, and key excerpt references.

---

## 3) Model Routing + Cost Controls

### Routing Principles
- **Extraction tasks** → cheaper, fast models.
- **Synthesis tasks** → higher‑quality reasoning models.
- **Multi‑phase** pipeline (extract → cluster → synthesize) to control cost.

### User Controls
- Model tier: **Fast**, **Balanced**, **Deep‑Dive**.
- Budget caps per task + estimated cost shown before run.
- Toggle: “Only proceed if confidence >= threshold.”

---

## 4) Long‑Running Workflows

### Execution Strategy
- **Chunking**: split by custodian/date/time buckets.
- **Parallelization**: run per shard and merge later.
- **Incremental delivery**: publish partial output slices as they complete.

### Progress + Trust
- Show **source coverage** (% of docs scanned).
- Display **evidence counts** and **exceptions**.
- Provide **audit trail** of processing steps.

---

## 5) Output Quality + Defensibility

### Output Structure
- **Executive Summary** (1‑page)
- **Detailed Evidence Matrix**
- **Citation Footnotes** (doc IDs + excerpts)
- **Confidence / Gaps** (explicitly flagged)

### Defensibility Features
- Every claim linked to evidence citations.
- Exports: PDF, CSV, XLSX, JSON.
- “Explain How This Was Derived” view (pipeline trace).

---

## 6) Key UX Messaging

### Expectation Management
- “Agent tasks are comprehensive and may run for hours.”
- “Outputs are evidence‑grounded and targeted to your instruction.”

### Transparency
- Cost estimate range + per‑step visibility.
- Clear distinctions: fact vs inference vs uncertainty.

---

## 7) Backend Requirements (High‑Level)

- **Agent task orchestration service**
  - Job creation, chunking, routing, and merging.
- **Evidence retrieval engine**
  - Filter by custodian/date/tag + semantic retrieval.
- **Model router**
  - Task‑aware dispatch by complexity and cost tier.
- **Result store + versioning**
  - Durable outputs with revisions and exports.
- **Progress tracking + audit logs**
  - A detailed “what happened when” ledger.

---

## 8) MVP Build‑Out (Suggested Sequence)

1. **Agent Page UI** (task builder + queue + results)
2. **Timeline Builder** as first workflow
3. **Task orchestration + progress tracking**
4. **Cost + runtime estimation**
5. **Citation + audit logging**

---

## 9) Future Enhancements

- Multi‑agent “Batch Runs” with a single master spec.
- “Human‑in‑the‑loop” checkpoints for critical outputs.
- Visual dashboards for entity networks and event maps.
- Cross‑case query support with permission safeguards.

---

## 10) Open Questions (To Finalize)

1. What are the top 3 “first output” types (timeline, matrix, summary)?
2. Do users prefer templates or a blank prompt first?
3. Which roles (case manager, partner, investigator) are primary?
4. What’s an acceptable target cost per 10k docs for a baseline run?

