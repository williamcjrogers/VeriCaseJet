# Agents & Visual Builder Track (Plan)

Goal: deliver a visual, auditable workflow builder on top of VeriCase tools, MCP, and (optionally) AWS Bedrock AgentCore.

## Positioning

- **Canvas-first UX**: curated nodes representing VeriCase skills (PST ingest, OCR, Thread Emails, Classify, Summarise, Bundle, Export, Egnyte/SharePoint push).
- **Execution engine**: Celery tasks + existing REST/MCP tools; AgentCore provides reasoning, memory, and policy guardrails.
- **Auditability**: every node logs inputs/outputs, model, prompt, hashes; workflows saved as JSON specs and versioned.

## MVP Scope (2–3 weeks)

1. **Node palette (curated)**

   - Ingest (PST/IMAP/upload)
   - OCR (existing pipeline)
   - Thread Emails (new threading metadata already added)
   - Classify (relevance/heads of claim)
   - Summarise (LLM windowed summaries)
   - Bundle Builder (spec stub)
   - Export (CSV/ZIP/PDF index)

2. **Workflow spec**

   - JSON DAG with nodes: `{id, type, params, inputs[]}`
   - Stored per project/case; versioned; executable via API.

3. **Runner**

   - REST endpoint: `POST /api/workflows/run` with spec ID -> enqueues Celery chain; streams status.
   - Uses existing tools/routers; AgentCore optional flag (when available) to supervise steps.

4. **UI prototype**

   - Use Langflow/Node-RED or lightweight React canvas (e.g., React Flow) internally.
   - Templates: "Delay Claim Pack", "S278 Discovery", "NCR Review".

5. **Policy/guardrails (if Bedrock AgentCore enabled)**
   - Guardrail rules: no PII leakage, no legal advice; only allowed tool list; rate limits.
   - Episodic memory: store recent runs per project; recall previous summaries/decisions.

## Future (nice-to-haves)

- Human-in-the-loop approval nodes.
- A/B model selection per node; cost tracking per run.
- Visual diffing of workflow versions; promotion to templates.
- Scheduling/cron and webhooks.

## Dependencies

- MCP server already present; ensure key tools exposed (evidence list/get/download, search, bundle stub, OCR trigger).
- AgentCore: when available, map MCP tools to AgentCore tool schema and register guardrails.

## Rollout Steps

1. Implement workflow spec + storage + run endpoint.
2. Ship internal canvas (React Flow or Langflow) wired to spec CRUD/run endpoints.
3. Add templates and logging/telemetry for nodes.
4. Integrate AgentCore guardrails + memory when AWS access is ready.
