# VeriCase Agent Page Blueprint

## Objective
Create a dedicated **VeriCase Agent** page inside each Workspace / Project / Case that lets users define long‑running, high‑volume document analysis tasks (email + evidence + files), run them in parallel, and return later to comprehensive, defensible outputs.

The design is intentionally **task‑centric**, **expectation‑managed**, and **cost‑predictable**, while staying flexible for future workflows beyond email/document trawling.

---

## 0) Core Concepts (Make Runs Defensible)

- **Agent Task (spec):** the saved instructions + scope + constraints (can be duplicated/re-run).
- **Agent Run (execution):** a single attempt of a task, with immutable inputs + config snapshot (model IDs, prompts, retrieval settings, timestamps).
- **Artifacts:** the outputs produced by a run (timeline table, memo, CSV), plus a **run manifest** (what ran, on which evidence, and why).

Key principle: **A run should be reproducible enough to explain** (inputs, prompts, model versions, retrieval set, and any human edits/acceptance).

Also:

- **Traceability over chain-of-thought**: store *tool calls, retrieval IDs, citations, and validation outputs* — avoid storing model “rationales” as a defensibility mechanism.
- **Evidence Set Snapshot (per run)**: record the deterministic evidence query/filters + a stable list of document IDs/versions (and a hash) so “what was scanned” is auditable even if the case changes later.
- **Run manifest (minimum fields)**:
  - **Identity**: `run_id`, `task_id`, workspace/project/case IDs, initiated_by, timestamps, status + final disposition (completed/failed/cancelled)
  - **Scope**: query + filters, evidence counts, exclusions, evidence set hash, sampling plan (if any)
  - **Configuration**: model/provider IDs per phase, prompt template IDs/versions, chunking/dedupe/threading settings, retrieval settings (index, top-k, reranker), OCR/extraction mode + tool versions
  - **Lineage**: artifact IDs + checksums, citation coverage stats, validation report pointer, human approvals/edits/publish actions
  - **Cost + runtime**: per-phase cost breakdown + totals, worker/runtime metadata, retry counts and exceptions summary

---

## 1) User Experience (UX) Flow

### Entry Points
- **Workspace / Project / Case sidebar:** “Agents” item.
- **Empty state CTA:** “Create your first agent task.”

### Critical UX Addition: Plan → Approve → Run
For long-running/costly work, enforce a deliberate flow:
1. **Draft task** (user defines goal/scope/outputs).
2. **Generate plan** (system returns: what will be scanned, phases, time/cost range, risks, and a small “sample preview”).
3. **User approval** (explicit “Start run” acknowledgement; optional org-level approval thresholds).
4. **Run + stream progress** (phased progress, partial artifacts, exceptions).

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
     - **Data handling**: dedupe on/off, include attachments, OCR mode (fast/accurate), language options.
     - **Goal**: Freeform text + structured selections (issue/claim).
     - **Output format**: Timeline table, memo, CSV, chart, report.
     - **Depth level**: Quick / Standard / Exhaustive.
     - **Budget limit**: Optional cap.
     - **Runtime expectation**: “May run for hours; results delivered incrementally.”
     - **Approval gating** (optional): “Require approval if estimate exceeds $X or Y hours.”

3. **Plan Preview (before running)**
   - Scope summary: evidence counts, exclusions, and sampling plan.
   - Proposed phases: extract → cluster → synthesize → validate → publish artifacts.
   - Estimates: time range, cost range, model tiers per phase.
   - Risk notes: low-OCR quality, missing date metadata, foreign language, etc.
   - Cost drivers: OCR-heavy PDFs, long email threads, multilingual content, high rerank/top‑k.

4. **Agent Queue**
   - Each row: Name, scope, status, ETA, cost‑so‑far, model tier, progress bar.
   - Status phases: Draft, Planning, Awaiting Approval, Running, Paused, Completed, Failed, Cancelled.
   - Actions: Pause, resume, cancel, duplicate, export.
   - Click-through: opens run detail (phase log, partial artifacts, and exceptions).

5. **Agent Results**
   - Delivered outputs with versioning, confidence notes, citations, and export links.
   - “Continue” action to run follow‑up tasks on the generated output.
   - “Publish” action (where relevant): accept/reject/edit suggestions before writing to canonical case objects.

6. **Run Detail (single run page / drawer)**
   - Overview (who/when/config snapshot), live phase timeline, shard progress and exceptions.
   - Evidence set snapshot (filters + counts + deterministically listed documents).
   - Artifacts (with versions + checksums), Validation report, Cost breakdown.
   - “Export manifest” button (JSON) + “Export bundle” (ZIP with artifacts + manifest).

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
- Show **model/provider identifiers** used per phase (for auditability), plus a “rerun with same versions” option when available.
- Cost breakdown: retrieval, OCR/extraction, synthesis, validation, export.
- Hard limits: per-run max runtime, max documents, and max tokens per phase (fail fast with a clear message).
- Concurrency controls: per-tenant and per-case limits to prevent runaway parallelism (and surprise spend).
- Include **guardrail policy costs** (if enabled) in the estimate and breakdown.

---

## 4) Long‑Running Workflows

### Execution Strategy
- **Chunking**: split by custodian/date/time buckets.
- **Parallelization**: run per shard and merge later.
- **Incremental delivery**: publish partial output slices as they complete.
- **Checkpointing**: persist phase outputs so runs can resume after worker restarts.
- **Idempotency**: shard retries should not duplicate artifacts or double-bill.
- **Dead-letter + retry strategy**: poison shards go to DLQ with a human-readable exception summary and “retry shard” action.
- **Backpressure**: pause/slow ingestion when downstream (OCR/LLM) throttles; surface provider throttling in the run log.

### Sequential Phase Model (Recommended)
Use explicit phases to keep progress meaningful and results explainable:
1. **Plan** (scope + estimates + sampling preview)
2. **Retrieve** (deterministic evidence set + coverage report)
3. **Extract** (entities/dates/threads/tables)
4. **Cluster** (topic buckets, conversation threads, custodian clusters)
5. **Synthesize** (task-specific output generation)
6. **Validate** (citation coverage, contradiction checks, “unsupported claims” list)
7. **Package** (exports + manifest)

### Progress + Trust
- Show **source coverage** (% of docs scanned).
- Display **evidence counts** and **exceptions**.
- Provide **audit trail** of processing steps.
- Provide a “Run manifest” export: inputs, retrieval filters, model IDs, prompts/templates used, timestamps, and human edits.

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
- Citation UX: clicking a citation opens the source document at the relevant excerpt (page/line/offset), with highlight and surrounding context.
- Validation report: unsupported statements, low-confidence items, and coverage gaps presented as a first-class artifact.
- Artifact integrity: store checksums (and optionally signature) for exported artifacts + manifest.

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
- **Event stream**
  - Push phase + shard progress to the UI (SSE/WebSocket) with resumable cursors.
- **Evidence retrieval engine**
  - Filter by custodian/date/tag + semantic retrieval.
- **Extraction services**
  - OCR/table extraction, entity extraction, threading/deduplication.
- **Model router**
  - Task‑aware dispatch by complexity and cost tier.
- **Result store + versioning**
  - Durable outputs with revisions and exports.
- **Progress tracking + audit logs**
  - A detailed “what happened when” ledger.
- **Prompt template registry**
  - Versioned templates (and per-run pinning) for plan, extraction, synthesis, validation, and post-processing.
- **Evals + scoring**
  - Offline and CI evaluation harness; store per-run quality metrics (citation coverage, unsupported-claim rate, contradiction rate).
- **Permissions enforcement**
  - Evidence set must respect workspace/project/case RBAC and legal hold/visibility flags.

---

## 8) MVP Build‑Out (Suggested Sequence)

1. **Agent Page UI** (task builder + queue + results + run detail)
2. **Plan → Approve → Run** flow (including estimates + sampling preview)
3. **Timeline Builder** as first workflow (draft outputs + publish accepted items)
4. **Task orchestration + progress tracking** (phased progress events)
5. **Cost + runtime estimation** (per-phase breakdown)
6. **Citation UX + audit logging** (manifest export)

---

## 9) Future Enhancements

- Multi‑agent “Batch Runs” with a single master spec.
- “Human‑in‑the‑loop” checkpoints for critical outputs.
- Visual dashboards for entity networks and event maps.
- Cross‑case query support with permission safeguards.
- Web capture as evidence (optional): snapshot external pages with hashing + timestamping, stored alongside case evidence.

---

## 10) Open Questions (To Finalize)

1. What are the top 3 “first output” types (timeline, matrix, summary)?
2. Do users prefer templates or a blank prompt first?
3. Which roles (case manager, partner, investigator) are primary?
4. What’s an acceptable target cost per 10k docs for a baseline run?
5. What is the required reproducibility standard (store prompts? store retrieval sets? store model IDs?) per jurisdiction/client?
6. Do we require per-run approval thresholds (by role, by spend, by evidence volume)?
7. How should “external sources” be handled (disabled by default vs. whitelisted, and clearly separated from case evidence)?

---

## 11) AWS-First Reference Architecture (Suggested)

- **Storage:** S3 (evidence + artifacts) with KMS encryption; optional **S3 Object Lock (WORM)** + versioning for finalized exports and retention/legal hold.
- **Search/Retrieval:** OpenSearch (keyword + vector) or Aurora Postgres + pgvector; document metadata in RDS/DynamoDB.
- **Orchestration:** Step Functions for phased workflows; SQS for shard queues; ECS/Fargate (or Batch) workers.
- **LLM + AI services:** Amazon Bedrock (models + **Agents** + **Knowledge Bases** + **Guardrails**); Textract for OCR/tables; Comprehend for entity/key phrase extraction.
  - If you want managed RAG primitives: Bedrock Knowledge Bases can include citations, reranking, multimodal retrieval, and structured query generation.
  - For productionizing agent deployments: consider **Amazon Bedrock AgentCore** for secure operation at scale.
- **Observability:** CloudWatch logs/metrics + OpenTelemetry traces (W3C trace context propagation end-to-end); alarms on failure rates and runaway cost.
- **Notifications:** SNS/EventBridge + in-app notifications (and optional Slack/email).
- **Reference docs (for the above primitives):**
  - [How Amazon Bedrock Agents works](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-how.html)
  - [Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
  - [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-how.html)
  - [S3 Object Lock (WORM)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)

---

## 12) Developer Tooling (Context7 / Brave / Puppeteer)

If you want agent development to stay current and testable:
- **Context7**: fetch up-to-date docs for any framework/library used in the agent pipeline (router/orchestrator, vector DB, UI components).
- **Brave Search**: controlled web research for non-evidence product questions (keep it separate from case evidence by default).
- **Browser E2E tests (Playwright or Puppeteer)**:
  - Prefer **Playwright** for reliable cross-browser E2E and screenshot diffs (e.g., `toHaveScreenshot()`); when waiting on navigation prefer `waitForURL()` patterns.
  - Use **Puppeteer** where you already have existing Chromium-only infra.
  - Automate UI regression flows for the Agent page (create task → plan → approve → run → view artifacts), and optionally create page snapshots when explicitly enabled.

---

## 13) Security, Governance, and Safety (Must-Haves)

- **RBAC everywhere**: runs can only read evidence the initiator (and the run’s service identity) is authorized to access.
- **Tenant isolation**: hard boundaries per workspace/project/case in storage, retrieval, and logs.
- **Run data retention**: configurable retention windows; legal hold should override deletion; WORM retention for finalized exports if required.
- **Encryption**: in transit (TLS) and at rest (KMS-managed keys), including artifacts and logs that may contain excerpts.
- **PII/PHI controls**: detect and optionally redact sensitive data in artifacts/exports; record redaction decisions in the run manifest.
- **Prompt-injection defenses**: treat documents as untrusted data; strict tool allowlists; isolate “instructions” from “evidence”; log when content attempts instruction hijacking.
- **Guardrails**: apply input/output safety policies (and prompt-attack filters where relevant) at the boundaries of model calls; include interventions in the run log/manifest.
- **No chain-of-thought storage**: do not rely on model rationales for auditability; rely on citations, deterministic evidence sets, and action traces.
- **Evidence vs. external research**: keep external sources disabled by default and clearly labeled; never mix external text into “evidence-grounded” claims without explicit attribution and user opt-in.

---

## 14) Evaluation + Observability (Ship-With Requirements)

### Quality metrics to record per run (minimum)
- Citation coverage (% of claims with citations; % of output rows with at least one citation).
- Unsupported claims rate (from the validation phase).
- Contradiction flags (within-run and against known structured facts, if available).
- Coverage: % of target evidence scanned; % excluded (and why).

### Evals (offline + CI)
- Maintain a small “golden set” of representative documents/threads with expected outputs and red-flag assertions.
- Regression tests on prompt/template changes (structure, schema validity, “must cite” compliance, and failure-mode checks).
- Periodic sampling review workflow: auditors can rate artifacts and feed scores back into routing/prompt improvements.

### Observability (production)
- End-to-end tracing (OpenTelemetry) across UI → API → orchestration → workers; propagate W3C trace context.
- Emit structured run events (phase start/end, shard start/end, throttles, retries, interventions, publish actions).
- Alerts: runaway cost, stuck phases, DLQ growth, OCR failure spikes, high unsupported-claim rate.
