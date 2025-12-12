# AI Advancement Roadmap: Agents, OCR & Bundling

This roadmap integrates recent proposals for Adaptive OCR, Intelligent Bundling, and AWS Bedrock AgentCore into the VeriCase platform strategy.

---

## 1. Adaptive OCR Feedback Loop

**Goal:** Improve data quality by capturing and reusing human corrections to OCR text.

### Status: Phase 1 Delivered (Safe Capture)

- **Schema:** `ocr_corrections` table created (`0003_ocr_corrections`).
- **API:** `POST /api/ocr/corrections` endpoint live.
- **Strategy:** "Capture & Overlay". We collect corrections without rewriting the forensic source of truth (search index/files).

### Next Steps (Phase 2 - Active)

- **Frontend:** Add "Correct Text" action to the document viewer context menu.
- **Overlay:** Fetch corrections when viewing a document and display them as a visual layer (like track changes).
- **Runtime Fixer:** Once we have >1,000 verified corrections, introduce `worker_app` logic to auto-apply high-confidence fixes to _new_ documents before indexing.

---

## 2. Intelligent Evidence Bundling

**Goal:** Automate tribunal-ready bundle generation with per-type pagination and headers.

### The Gap

Current exports are flat. We need structured streams:

- **Streams:** Emails (E), Drawings (D), Valuations (V), etc.
- **Pagination:** `E-1` to `E-500`, independent of other streams.
- **Stamping:** Vector headers with "Exhibit E-23 | Case Ref | Date".

### Implementation Plan

1.  **Taxonomy:** Define `EvidenceType` enum map (e.g., `EMAIL` -> `E`, `DRAWING` -> `D`).
2.  **Bundle Engine:** Create a new Celery task `generate_bundle(case_id)` that:
    - Sorts items by type + date.
    - Assigns running page numbers per stream.
    - Generates a `bundle_index.json` manifest.
3.  **PDF Stamping:** Use `pikepdf` or `reportlab` to overlay headers onto the original PDFs without rasterizing them (preserving text/search).

---

## 3. Agent Infrastructure (AgentCore vs Custom)

**Goal:** Adopt enterprise-grade controls (Memory, Policy, Evals) for AI agents.

### Analysis

VeriCase currently uses a custom multi-provider router (`AdaptiveModelRouter`). AWS Bedrock AgentCore (announced Dec 2025) offers managed state and guardrails.

### Recommendation

- **Adopt AgentCore for the "Supervisor":** Use Bedrock Agents for the high-level natural language interface (chatting with the case). It handles the "Episodic Memory" of user intent well.
- **Keep Custom Workers:** Continue using the existing `worker_app` (Celery) for heavy lifting (PST extraction, OCR). Expose these as **Agent Tools** via Lambda or API.
- **Policy Guardrails:** Implement Bedrock Guardrails to prevent the agent from hallucinating legal advice or leaking PII.

### Migration Path

1.  Define a Bedrock Agent schema that maps to our existing API tools (`search_evidence`, `get_timeline`).
2.  Replace the current `AI Chat` backend with a proxy to this Bedrock Agent.
3.  Enable "Episodic Memory" to let the agent remember context across sessions.
