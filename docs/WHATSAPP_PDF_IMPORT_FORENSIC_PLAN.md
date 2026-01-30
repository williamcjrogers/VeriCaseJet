# WhatsApp + PDF Email Import into Correspondence: Forensic Execution Plan

## Executive Summary
This document defines a forensic-grade, end-to-end execution plan to ingest WhatsApp chat exports (`.txt`/`.zip`) and email PDFs (`.pdf`) into the Correspondence system. Each WhatsApp message and each email extracted from a PDF becomes an **individual `EmailMessage` row** rendered in the Correspondence grid exactly like native emails. The plan **reuses the existing email import lifecycle** (synthetic PST container, per-message creation, attachment linking) to avoid new pipelines or schema changes. The design is structured for evidentiary defensibility, traceability, and controlled failure modes.  
  
In addition, the plan standardizes **evidence preservation**: store the original uploaded artifact bytes (content-addressed by SHA-256) and, where applicable, store **derived extraction artifacts** (e.g., Tika text, Textract JSON) so parsing can be reproduced later with the same parser version/config.

## Objectives
1. **Ingest WhatsApp and PDF-based email exports** through the existing Upload PST UI flow.  
2. **Normalize all parsed messages into `EmailMessage` rows** compatible with current Correspondence rendering and search.  
3. **Preserve forensic traceability** with deterministic message IDs, source metadata, and repeatable parsing.  
4. **Avoid schema changes** while enabling future filtering by source system.  
5. **Produce a batch-level import manifest** (counts, hashes, parser versions/config, errors) suitable for audit/chain-of-custody reporting.

## Non-Goals (Explicitly Out of Scope for v1)
- Deep reply threading or quoted-reply inference in WhatsApp chat logs.  
- PDF portfolio extraction (multi-file PDF containers).  
- LLM-based PDF parsing (stub only, no API wiring).  
- Manual correction UI for low-confidence PDF extraction.  
- Expanded localized header parsing beyond core English/French/German/Spanish patterns.  
- Automated acquisition of exports via browser automation (e.g., WhatsApp Web / webmail) using Playwright/Puppeteer/Brave.  

## v1 Decisions (Make Explicit)
These items should be decided up-front because they affect determinism, user expectations, and forensic defensibility:

- **Low-confidence PDF sections**: ingest with `meta.extraction.confidence` + UI warning (recommended) vs skip sections vs hard-fail the whole PDF.
- **WhatsApp system messages**: skip rows entirely (recommended) vs ingest as `EmailMessage` rows with `meta.whatsapp.is_system=true`.
- **Timezone policy**: default workspace timezone (recommended) vs user-specified override at upload-time; always store the assumption in `meta`.
- **Evidence retention & immutability**: retention duration for raw artifacts + derived OCR artifacts; optional S3 Object Lock/WORM where available.
- **HTML safety**: confirm `body_text_clean` is always sanitized for UI rendering (no script injection).

## Current Architecture Constraints (Anchors)
- Upload UI already routes `.eml/.msg` into `email_import` endpoints.  
- Correspondence grid relies on `EmailMessage` fields (`date_sent`, `sender_email`, `subject`, `body_text_clean`, `body_preview`, etc.).  
- `EmailMessage` supports threading metadata and a JSON metadata field for provenance.  
- Existing building blocks we should reuse:
  - `vericase/api/app/correspondence/email_import.py` (synthetic `PSTFile`, attachment linking, threading+dedupe finalize)  
  - `vericase/api/app/forensic_integrity.py` (SHA-256 + normalized text hashing helpers)  
  - `vericase/api/app/evidence_metadata.py` + Tika integration (file hashing, PDF metadata, text extraction fallbacks)  

## Definitions (Forensic Vocabulary)
- **Source artifact**: the exact uploaded bytes (`.txt`, `.zip`, `.pdf`). This is what we hash for chain-of-custody.
- **Import batch**: the synthetic `PSTFile` record created for one upload (or one user-selected batch of files).
- **Parsed record**: an internal `ParsedEmail`-like structure emitted by parsers and fed into the existing import lifecycle.
- **Derived artifact**: extraction outputs produced from the source artifact (e.g., Tika text, Textract JSON, rendered page images). These should be stored (or at least reproducibly regenerable) and linked in metadata.
- **Deterministic**: given identical source bytes and parser version/config, output `EmailMessage` rows (including IDs) are identical.

## Input Acceptance & Guardrails (Fail Fast, Explain Clearly)
**File-type detection**
- Do not trust file extensions alone. Validate using MIME sniffing (magic bytes) + extension + basic structure checks.

**Accepted inputs**
- WhatsApp: `.txt` (export without media) or `.zip` (export with media containing at least one chat `.txt` and media files).
- PDF email: `.pdf` containing one-or-more printable email representations (headers + body).

**Hard rejects (HTTP 400)**
- Encrypted/password-protected PDFs (no deterministic extraction without keys).
- ZIPs with path traversal (`../`), extremely high file counts, or suspicious compression ratios (zip bombs).
- `.txt` that does not match WhatsApp export patterns within the first N lines (to avoid misclassification).

**Operational limits (configurable)**
- Max pages for OCR (Textract) per upload; require explicit user acknowledgement when exceeded.
- Max extracted text size per message/body to prevent DB bloat; store full bodies in S3 and keep DB preview.
- Store the original uploaded artifact in object storage (MinIO/S3) with a content-addressed key based on SHA-256.
- Compute the **source file SHA-256 before any transformation** (before unzip, before text normalization) and persist it in batch metadata.
- For WhatsApp `.txt`: support UTF-8 (with/without BOM) and fail clearly on unknown encodings; store detected encoding in batch metadata.
- For WhatsApp `.zip`: treat the ZIP as the source artifact; also hash extracted members (chat `.txt` + media) and store member-hash list in the batch manifest.

## Execution Plan (Phased)

### Phase 0 — Design Freeze & Threat Modeling
**Deliverables**
- Formal scope agreement (this plan).  
- Threat/risk model for parsing ambiguity, mistaken attribution, and duplicate ingestion.  
- Determinism spec: exact ID schemes, timezone assumptions, and what constitutes “same input”.  
- Audit spec: what we store in `EmailMessage.meta` and batch-level metadata for chain-of-custody.  
- Dependency review (Context7 or equivalent): confirm PDF/Email parsing libs and note any upgrades needed before implementation.  
- Evidence storage spec: object key layout, encryption (SSE-S3 / SSE-KMS), retention, and optional immutability (S3 Object Lock) where applicable.
- Observability spec: metrics and logs for parsing outcomes, OCR usage, and error reasons without leaking sensitive body content.

**Acceptance Criteria**
- Stakeholders acknowledge the parsing is best-effort for PDFs and deterministic for WhatsApp.  
- Error handling strategy defined for non-WhatsApp `.txt` and non-email `.pdf`.  
- Timezone policy is explicit (e.g., “assume workspace timezone; store assumption in meta”).  

---

### Phase 1 — WhatsApp Parser + Tests (Parallel Track A)
**Goal**: Parse WhatsApp exports into `ParsedEmail` objects with deterministic IDs.

**Artifacts**
- `whatsapp_parser.py` with:
  - Line parsing for Android UK/EU, Android US, and iOS formats.  
  - Format detection heuristics.  
  - System-message detection (skip or metadata-only).  
  - Deterministic `message_id` generation (stable across file renames).  
  - Optional ZIP media extraction + attachment matching.  
- `test_whatsapp_parser.py` with format, multiline, determinism, and media tests.  

**Key Rules**
- One chat line → one message; multiline continuation appended to previous message.  
- `subject = "WhatsApp: {chat_name}"` (stable, deterministic).  
- `sender_email` uses `@whatsapp.local` normalization.  
- All messages in a chat share `thread_group_id`; `thread_position` by sequence.  
- `message_id` should incorporate **source file hash** + **raw line number** (not the filtered index) to preserve determinism even if system-message filtering changes.  
- For WhatsApp timestamps (no timezone in export), store the assumed timezone in `meta` and normalize stored datetimes to a consistent tz-aware value.  
- Preserve a **raw locator** in metadata for later forensic review:
  - `meta.source.raw_line_no` (1-based) and `meta.source.raw_timestamp_text` (the exact timestamp prefix string)
  - `meta.source.raw_sender_text` (pre-normalization) where present
- Treat common non-content lines deterministically:
  - “Messages and calls are end-to-end encrypted…” → system message (skip or tag per v1 decision)
  - “You deleted this message” / “This message was deleted” → ingest as message with `meta.whatsapp.is_deleted_placeholder=true` (recommended) to preserve chronology without inventing content
  - “<Media omitted>” / “‎<attached: filename>” → ingest a message and attach media if ZIP contains a matching filename; otherwise mark `meta.attachment_unmatched=true`
- Store parse provenance per message:
  - `meta.source.type = "whatsapp"`
  - `meta.source.file_sha256`, `meta.source.file_name`, `meta.source.raw_line_no`
  - `meta.source.chat_name`, `meta.source.export_format`, `meta.source.parser_version`
  - `meta.source.parser_config_sha256` (hash of parser config/patterns used)

**Acceptance Criteria**
- Given a sample export, message count equals expected lines (excluding system messages).  
- Repeated imports yield identical `message_id` values.  
- Message order preserved and consistent with timestamps.  
- Media attachments from `.zip` are linked to the correct messages when filenames are explicitly referenced in the chat text (otherwise attach to batch with `meta.attachment_unmatched=true`).  

---

### Phase 2 — PDF Email Parser + Tests (Parallel Track B)
**Goal**: Extract and parse email-like records from PDFs using deterministic rules.

**Artifacts**
- `pdf_email_parser.py` with:
  - Text extraction via existing Tika service first, then deterministic fallbacks.  
  - OCR fallback via AWS Textract (feature-flagged, with page/cost guardrails) when text layer is absent/insufficient.  
  - Deterministic local fallbacks (recommended):
    - `pypdf` for text-layer extraction and encrypted-PDF detection (reject encrypted PDFs).  
    - `PyMuPDF` for robust extraction and deterministic page rendering (PNG bytes) if a raster/OCR path is needed.  
  - Optional (future): render PDF pages via headless Brave/Chromium (Playwright/Puppeteer) before OCR for “visually readable but text-inaccessible” PDFs (only if PyMuPDF rendering is insufficient).  
  - Multi-email section splitting using header patterns.  
  - Regex header extraction for common formats (Outlook/Gmail/Apple Mail).  
  - Confidence scoring (overall + per-field).  
  - Deterministic `message_id` based on **source file hash** + section boundaries (stable across file renames).  
- `test_pdf_email_parser.py` using synthetic text outputs.  

**Key Rules**
- If confidence < threshold, skip or tag in metadata (v1 decision).  
- Body content begins after header block, preserved verbatim.  
- Reject encrypted/password-protected PDFs deterministically (e.g., `pypdf.PdfReader.is_encrypted == True`) unless a key is explicitly supplied (out-of-scope for v1).
- If Textract is used for PDFs, prefer asynchronous operations for multipage documents:
  - Start with `StartDocumentTextDetection` (S3 input) and store `JobId`, `ClientRequestToken`, and any `OutputConfig` used in `meta.extraction`.
  - Record the S3 object version (`DocumentLocation.S3Object.Version`) when available to make OCR replays unambiguous.
  - If used, persist `KMSKeyId` and `NotificationChannel` (SNS topic/role) in `meta.extraction` to fully document the OCR run configuration.
- Persist extraction provenance in `meta`:
  - `meta.source.type = "pdf_email"`
  - `meta.source.file_sha256`, `meta.source.file_name`, `meta.source.section_index`
  - `meta.extraction.method = "tika" | "textract"` (+ any local fallback), and `meta.extraction.warnings`
  - `meta.extraction.artifacts = { extracted_text_s3_key, textract_job_id, textract_output_s3_prefix }` (keys optional, omit when not applicable)

**Acceptance Criteria**
- Each known-format sample yields stable extraction of From/To/Date/Subject/Body.  
- Multi-section PDFs are split into multiple messages.  
- Missing headers handled safely without crashing.  
- OCR use is explicit (flag + metadata), and extraction artifacts are retained (Textract JSON / extracted text) for reproducibility.  

---

### Phase 3 — Email Import Service Extension
**Goal**: Route new file types through the existing `email_import.py` lifecycle.

**Work Items**
- Extend file-type dispatch: `.txt`/`.zip` → WhatsApp parser; `.pdf` → PDF parser (prefer MIME sniffing + extension).  
- Wrap current single-message flow into a list loop (EML/MSG become a length-1 list).  
- Aggregate results (`email_ids`, `messages_imported`) without altering existing behavior.  
- Decide and implement transaction policy: fail-fast vs best-effort per message, with a structured error summary returned to the UI either way.  
- Emit a batch-level **import manifest** (JSON) that summarizes:
  - source artifact hashes, extracted member hashes (ZIP), parser versions/config hashes
  - message counts, skipped counts (system/low-confidence), OCR pages processed
  - per-message errors (without full bodies) and per-file warnings

**Acceptance Criteria**
- Existing EML/MSG tests pass unchanged.  
- WhatsApp/PDF imports create *multiple* `EmailMessage` rows per upload.  
- Deduplication and attachment handling still function.  
- Each created `EmailMessage.meta` includes `source.file_sha256` and parser versioning fields, enabling chain-of-custody export.  

---

### Phase 4 — Upload UI Enhancements
**Goal**: Route WhatsApp/PDF candidate files into email import and surface classification.

**Work Items**
- Extend file routing in `pst-upload.html` to include `txt`, `zip`, `pdf`.  
- Add a lightweight WhatsApp badge for recognized filenames.  
- Improve batch name label for WhatsApp/PDF imports.  
- Show an import summary: detected type, messages found, attachments matched/unmatched, and (for PDFs) OCR usage and confidence warnings.  
- Add explicit UI language for PDFs: “Best-effort extraction from a PDF representation; headers may be incomplete; see per-message provenance.”

**Acceptance Criteria**
- WhatsApp `.txt` and `.zip` files are sent to email import endpoints.  
- `.pdf` files route to the same import endpoints.  
- Non-matching `.txt` files receive a clear error from the backend.  
- The UI surfaces “best-effort PDF parse” warnings without implying complete or authoritative extraction.  

---

### Phase 5 — Verification & Forensic Validation
**Goal**: Validate parsing integrity and reproducibility.

**Verification Types**
- Unit tests for parsers.  
- Manual workflow tests through Upload PST UI.  
- Deduplication check on re-uploads.  
- Message ordering + thread grouping check.  
- Chain-of-custody check: the stored `meta.source.file_sha256` matches the uploaded artifact bytes.  

**Acceptance Criteria**
- Identical input yields identical output IDs and counts.  
- No schema changes required.  
- Correspondence grid displays rows as expected.  
- Exported audit metadata is sufficient to reproduce parsing decisions (format detected, timezone assumption, confidence, extraction method).  

## Forensic Principles (Evidence Reliability)
1. **Determinism**: Each input byte sequence yields a predictable output.  
2. **Traceability**: `EmailMessage.meta` stores source system, filenames, and parsing method.  
3. **Non-Destructive**: Raw extracts remain accessible; no destructive normalization.  
4. **Repeatability**: Re-processing yields identical message IDs and metadata.  
5. **Chain-of-custody**: Store source file hash + import context (uploader, timestamp, parser version/config) in a queryable form.  
6. **Immutability (where possible)**: Store source and derived artifacts with write-once semantics and explicit retention controls (e.g., S3 Object Lock) when the deployment supports it.

## Data Mapping (WhatsApp → EmailMessage)
| WhatsApp Concept | EmailMessage Field | Notes |
|---|---|---|
| Chat name | `subject` | `WhatsApp: {chat_name}` |
| Sender display | `sender_name` | Raw display name |
| Sender phone | `sender_email` | `+447...@whatsapp.local` |
| Timestamp | `date_sent` | Parsed from prefix |
| Message body | `body_text` + `body_text_clean` | Message text |
| Chat group | `thread_group_id` | Stable chat hash |
| Order | `thread_position` | Message sequence index within chat (excluding skipped system messages) |
| Provenance | `meta` | source, format, index |

## Data Mapping (PDF → EmailMessage)
| Extracted Field | EmailMessage Field | Notes |
|---|---|---|
| From | `sender_email`/`sender_name` | Normalize email addresses |
| To/CC | `recipients_to`/`recipients_cc` | Arrays |
| Date/Sent | `date_sent` | Parsed with locale heuristics |
| Subject | `subject` | Extracted |
| Body | `body_text` | Everything after header block |
| Provenance | `meta` | extraction method, confidence |

## Error Handling Policy
| Scenario | Handling |
|---|---|
| Non-WhatsApp `.txt` | 400 error with clear message |
| Non-email `.pdf` | 400 error with clear message |
| Encrypted `.pdf` | 400 error with clear message (“password-protected PDF not supported”) |
| Empty export | Return empty list, user notified |
| ZIP traversal / zip bomb indicators | 400 error; log event without extracting |
| Confidence below threshold | Skip or mark in metadata (v1 decision) |

## Security & Privacy Considerations
- Strip executable content from parsed text.  
- Ensure **UI-safe sanitization** for any rendered HTML (e.g., sanitize `body_text_clean` to prevent XSS from malicious PDFs/ZIP contents).  
- Validate media files extracted from ZIPs against allowlist.  
- Enforce ZIP safety: path traversal protection, max file count, max uncompressed bytes, and timeouts.  
- Enforce PDF safety: max pages, timeouts for extraction/OCR, reject encrypted PDFs.  
- Store phone numbers only where necessary for sender identification.  
- Ensure logs do not dump full message bodies.  
- Treat OCR as a cost+privacy boundary: require explicit flags, redact logs, and encrypt artifacts at rest (S3/MinIO SSE / AWS KMS where applicable).  

## Recommended Evidence Storage Layout (S3/MinIO)
- **Raw artifacts**: `evidence/raw/{sha256}/{original_filename}` (+ content-type, size, upload actor, upload timestamp)
- **Derived artifacts** (optional but recommended):
  - `evidence/derived/{source_sha256}/tika/text.txt`
  - `evidence/derived/{source_sha256}/textract/{job_id}/output.jsonl|output.json`
  - `evidence/derived/{source_sha256}/rendered/{page_no}.png` (if page rendering is used)
- Store a batch manifest: `evidence/manifests/{batch_id}.json`

## Rollout Strategy
1. **Internal beta**: limited to test cases with controlled exports.  
2. **Pilot**: one production workspace with explicit user instruction.  
3. **General release**: after pass/fail thresholds and regression checks.  

## Risk Register (Top 5)
| Risk | Mitigation |
|---|---|
| Parsing ambiguity in PDF headers / OCR drift | Confidence scoring + deterministic regex; store extraction method + artifacts in `meta` |
| WhatsApp export format variants / timezone ambiguity | Expand regex patterns based on field testing; make timezone assumption explicit in `meta` |
| Duplicate ingestion | Deterministic IDs + existing dedupe helpers |
| Large imports (size/cost/timeouts) | Cap messages/pages; enforce limits; background processing for large OCR jobs |
| Malicious content in PDFs/ZIP (XSS / attachment abuse) | Sanitize rendered fields, validate + allowlist attachments, enforce strict ZIP/PDF guardrails |

## Testing Plan (Required)
**Unit Tests**
- `test_whatsapp_parser.py`  
- `test_pdf_email_parser.py`  
- Existing email import tests (EML/MSG).  
- ZIP safety tests (path traversal, zip bomb heuristics, file count/size caps).  
- Encrypted PDF rejection test (deterministic).  

**Manual Tests**
- Upload WhatsApp `.txt` (no media).  
- Upload WhatsApp `.zip` (media).  
- Upload PDF email.  
- Re-upload same file (dedupe check).  
- Upload invalid `.txt` (expect 400 error).  

## Deliverables Checklist
- [ ] WhatsApp parser + tests  
- [ ] PDF email parser + tests  
- [ ] Email import dispatch + list handling  
- [ ] Upload UI routing + WhatsApp badge  
- [ ] Regression tests pass  
- [ ] Manual verification performed  

## Appendix: Deterministic ID Schemes
- **WhatsApp**: `whatsapp-{sha256(source_file_sha256|chat_name|raw_line_no|timestamp|sender|body_hash)[:16]}@whatsapp.local`  
- **PDF**: `pdf-{sha256(source_file_sha256|section_index|header_hash|body_hash)[:16]}@pdf-import.local`  

