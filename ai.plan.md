# VeriCase AI Refactoring & Hardening Plan

_Working document for AI-assisted changes. This is the high-level plan the AI should follow when making non-trivial edits._

---

## 1. Scope & Guardrails

- **Canonical backend:** `pst-analysis-engine/api/app` is the only authoritative API code.
- **Canonical worker:** `pst-analysis-engine/worker_app` is the only authoritative Celery worker code.
- **Canonical UI:** `pst-analysis-engine/ui` static files served under `/ui` from the FastAPI app.
- **Dead code:** The nested `pst-analysis-engine/pst-analysis-engine` tree and the Flask `main.py` have been removed; do not recreate alternative backends.
- **Single startup path:** Local/dev runs via `docker-compose.yml` in `pst-analysis-engine/`. Avoid adding new ad‑hoc `START_*.bat` / `.sh` entry points.

AI changes must:

- Keep FastAPI + Celery + Docker as the backbone.
- Avoid reintroducing parallel stacks (no Flask, no second FastAPI tree).
- Prefer incremental refactors over big‑bang rewrites.

---

## 2. Recent Structural & Data Changes (Baseline)

These are already in place and should be treated as **current truth**:

1. **Email canonicalisation & dedupe fields**
   - `EmailMessage` now has:
     - `body_text_clean`: top‑message canonical text.
     - `content_hash`: SHA‑256 over canonical body + normalised from/to/subject/date.
   - `EmailAttachment` now has:
     - `attachment_hash`: SHA‑256 of attachment bytes.
     - `is_inline`, `content_id`, `is_duplicate`.
   - Backed by `20251124_add_email_canonical_and_hashes.sql`.

2. **PST processor wiring**
   - `UltimatePSTProcessor` computes `body_text_clean` and `content_hash` and persists them.
   - Attachment hashes are computed and stored, with `is_duplicate` used for storage‑level dedupe only.

3. **Correspondence API wiring**
   - `/api/correspondence/emails` and `/api/correspondence/emails/{id}` expose:
     - `body_text_clean`, `content_hash` on emails.
     - `attachment_hash`, `is_inline`, `content_id`, `is_duplicate` on attachments.

4. **Search indexing wiring**
   - OpenSearch `emails` index now has:
     - `body_clean` (canonical body) and `content_hash`.
   - `ForensicPSTProcessor._index_email` passes these through.

All future work should **reuse** these fields instead of inventing parallel ones.

---

## 3. Near-Term AI Workstreams

### 3.1 Correspondence UI Enhancements

Goal: Make the email grid and detail views feel “forensic‑grade” and dedupe‑aware without backend breaking changes.

Tasks:

1. **Use `body_text_clean` in correspondence UI**
   - In `ui/correspondence-enterprise.html`, prefer `body_text_clean` when rendering snippets / previews.
   - Fall back to `body_text` if `body_text_clean` is null (for legacy rows).

2. **Duplicate email handling (client-side)**
   - Add a small toggle in the correspondence UI, e.g. “Hide duplicate emails”.
   - Client-side behaviour:
     - Group emails by `content_hash` (ignore null hashes).
     - Keep the earliest or most recent email per hash (configurable), hide others when the toggle is on.
     - Show a subtle “N duplicates hidden” badge or tooltip.

3. **Attachment display improvements**
   - Hide or visually de‑emphasize inline/logo attachments in the main attachment list when `is_inline=true` or `filename` matches obvious signature patterns.
   - Optionally add a second, collapsed “Inline content” section that lists them if needed.
   - Use `is_duplicate` and `attachment_hash` to annotate duplicate attachments (e.g. “shared across 5 emails”).

Constraints:

- Do **not** change API contracts; use already-exposed fields.
- No new build tooling; keep UI changes in existing static JS/HTML.

### 3.2 Correspondence API: Optional Server-Side Dedupe

Goal: Allow heavy users (AI, batch exports) to request deduped views without forcing the UI to do all work.

Tasks:

1. Add optional query parameters to `/api/correspondence/emails`:
   - `dedupe: bool = False` – when `true`, return at most one email per `content_hash` (hash-based grouping only for non-null).
   - `dedupe_strategy: Literal["newest", "oldest"]` – default `"newest"`.

2. Implementation:
   - Keep the default behaviour **identical** when `dedupe=false`.
   - When `dedupe=true`:
     - Use a window function or subquery to pick 1 row per `(case_id or project_id, content_hash)` according to `date_sent` (or `created_at` fallback).
     - Still respect existing filters and pagination semantics (document in code comments: dedupe applies before pagination).

3. Expose dedupe hints in responses:
   - In `EmailMessageSummary.meta`, include `dedupe_group_size` if `dedupe=true`, so UI/AI can show how many messages are collapsed per row.

Constraints:

- Must be implemented via SQLAlchemy in a DB‑portable way (or guarded behind a Postgres‑only path with safe fallback).
- Do not change response models; `meta` is the extensibility mechanism.

---

## 4. Medium-Term AI Workstreams

### 4.1 Search UX & Relevance

Goal: Use canonical bodies and hashes to improve search and avoid noisy duplicates.

Ideas:

- Enhance search endpoints (or add a dedicated `/api/search/emails`) that:
  - Searches primarily on `body_clean` and `subject` for text relevance.
  - Optionally groups results by `content_hash` and returns the best‑scoring email in each group.
  - Returns `content_hash` and `body_text_clean` in results for better UI display and dedupe controls.

### 4.2 AI Features on Top of Canonical Body

Goal: Feed clean, non-redundant content into AI pipelines.

Ideas:

- When generating summaries, chronologies, or semantic clusters:
  - Always use `body_text_clean` instead of raw `body_text`.
  - Use `content_hash` to:
    - Avoid sending multiple near-identical messages to the LLM.
    - Track and explain which messages are treated as duplicates in AI explanations (transparency).

---

## 5. Security & Compliance Follow-Ups

AI changes should opportunistically improve security where possible:

- **Do not** reintroduce hard-coded credentials, license keys, or hostnames in code or HTML.
- Prefer:
  - Environment variables (documented in `.env.example`) for secrets.
  - Backend injection (JSON config endpoints) instead of embedding secrets in static assets.
- Where dedupe / hashes are used, ensure:
  - Hashing remains one-way (no reversible encodings).
  - No user PII (e.g. full email addresses) is embedded into hashes beyond what’s already necessary for dedupe (current design is acceptable).

---

## 6. Operational Notes for Future AI Sessions

When this repo is opened again by an AI assistant:

1. **Read this file and `pst-analysis-engine/README.md` first.**
2. Confirm:
   - Canonical app paths (API, worker, UI) remain unchanged.
   - The latest migrations, especially `20251124_add_email_canonical_and_hashes.sql`, have been applied in target environments.
3. For any new feature touching PST processing, email models, or correspondence:
   - Extend `EmailMessage` / `EmailAttachment` models and the PST processors first.
   - Then surface fields through correspondence/search APIs.
   - Only then add UI changes.

This keeps the architecture coherent and prevents the “Russian doll” / “root rot” regressions that previously caused confusion.

