# WhatsApp + PDF Email Import into Correspondence: Forensic Execution Plan

## Executive Summary
This document defines a forensic-grade, end-to-end execution plan to ingest WhatsApp chat exports (`.txt`/`.zip`) and email PDFs (`.pdf`) into the Correspondence system. Each WhatsApp message and each email extracted from a PDF becomes an **individual `EmailMessage` row** rendered in the Correspondence grid exactly like native emails. The plan **reuses the existing email import lifecycle** (synthetic PST container, per-message creation, attachment linking) to avoid new pipelines or schema changes. The design is structured for evidentiary defensibility, traceability, and controlled failure modes.  

## Objectives
1. **Ingest WhatsApp and PDF-based email exports** through the existing Upload PST UI flow.  
2. **Normalize all parsed messages into `EmailMessage` rows** compatible with current Correspondence rendering and search.  
3. **Preserve forensic traceability** with deterministic message IDs, source metadata, and repeatable parsing.  
4. **Avoid schema changes** while enabling future filtering by source system.  

## Non-Goals (Explicitly Out of Scope for v1)
- Deep reply threading or quoted-reply inference in WhatsApp chat logs.  
- PDF portfolio extraction (multi-file PDF containers).  
- LLM-based PDF parsing (stub only, no API wiring).  
- Manual correction UI for low-confidence PDF extraction.  
- Expanded localized header parsing beyond core English/French/German/Spanish patterns.  

## Current Architecture Constraints (Anchors)
- Upload UI already routes `.eml/.msg` into `email_import` endpoints.  
- Correspondence grid relies on `EmailMessage` fields (`email_date`, `email_from`, `email_subject`, `body_text_clean`, etc.).  
- `EmailMessage` supports threading metadata and a JSON metadata field for provenance.  

## Execution Plan (Phased)

### Phase 0 — Design Freeze & Threat Modeling
**Deliverables**
- Formal scope agreement (this plan).  
- Threat/risk model for parsing ambiguity, mistaken attribution, and duplicate ingestion.  

**Acceptance Criteria**
- Stakeholders acknowledge the parsing is best-effort for PDFs and deterministic for WhatsApp.  
- Error handling strategy defined for non-WhatsApp `.txt` and non-email `.pdf`.  

---

### Phase 1 — WhatsApp Parser + Tests (Parallel Track A)
**Goal**: Parse WhatsApp exports into `ParsedEmail` objects with deterministic IDs.

**Artifacts**
- `whatsapp_parser.py` with:
  - Line parsing for Android UK/EU, Android US, and iOS formats.  
  - Format detection heuristics.  
  - System-message detection (skip or metadata-only).  
  - Deterministic `message_id` generation.  
  - Optional ZIP media extraction + attachment matching.  
- `test_whatsapp_parser.py` with format, multiline, determinism, and media tests.  

**Key Rules**
- One chat line → one message; multiline continuation appended to previous message.  
- `subject = "WhatsApp: {chat_name}"` (stable, deterministic).  
- `sender_email` uses `@whatsapp.local` normalization.  
- All messages in a chat share `thread_group_id`; `thread_position` by sequence.  

**Acceptance Criteria**
- Given a sample export, message count equals expected lines (excluding system messages).  
- Repeated imports yield identical `message_id` values.  
- Message order preserved and consistent with timestamps.  

---

### Phase 2 — PDF Email Parser + Tests (Parallel Track B)
**Goal**: Extract and parse email-like records from PDFs using deterministic rules.

**Artifacts**
- `pdf_email_parser.py` with:
  - Text extraction via Tika, OCR fallback via Textract (if text layer absent).  
  - Multi-email section splitting using header patterns.  
  - Regex header extraction for common formats (Outlook/Gmail/Apple Mail).  
  - Confidence scoring (overall + per-field).  
  - Deterministic `message_id` based on section hash.  
- `test_pdf_email_parser.py` using synthetic text outputs.  

**Key Rules**
- If confidence < threshold, skip or tag in metadata (v1 decision).  
- Body content begins after header block, preserved verbatim.  

**Acceptance Criteria**
- Each known-format sample yields stable extraction of From/To/Date/Subject/Body.  
- Multi-section PDFs are split into multiple messages.  
- Missing headers handled safely without crashing.  

---

### Phase 3 — Email Import Service Extension
**Goal**: Route new file types through the existing `email_import.py` lifecycle.

**Work Items**
- Extend file-type dispatch: `.txt`/`.zip` → WhatsApp parser; `.pdf` → PDF parser.  
- Wrap current single-message flow into a list loop (EML/MSG become a length-1 list).  
- Aggregate results (`email_ids`, `messages_imported`) without altering existing behavior.  

**Acceptance Criteria**
- Existing EML/MSG tests pass unchanged.  
- WhatsApp/PDF imports create *multiple* `EmailMessage` rows per upload.  
- Deduplication and attachment handling still function.  

---

### Phase 4 — Upload UI Enhancements
**Goal**: Route WhatsApp/PDF candidate files into email import and surface classification.

**Work Items**
- Extend file routing in `pst-upload.html` to include `txt`, `zip`, `pdf`.  
- Add a lightweight WhatsApp badge for recognized filenames.  
- Improve batch name label for WhatsApp/PDF imports.  

**Acceptance Criteria**
- WhatsApp `.txt` and `.zip` files are sent to email import endpoints.  
- `.pdf` files route to the same import endpoints.  
- Non-matching `.txt` files receive a clear error from the backend.  

---

### Phase 5 — Verification & Forensic Validation
**Goal**: Validate parsing integrity and reproducibility.

**Verification Types**
- Unit tests for parsers.  
- Manual workflow tests through Upload PST UI.  
- Deduplication check on re-uploads.  
- Message ordering + thread grouping check.  

**Acceptance Criteria**
- Identical input yields identical output IDs and counts.  
- No schema changes required.  
- Correspondence grid displays rows as expected.  

## Forensic Principles (Evidence Reliability)
1. **Determinism**: Each input byte sequence yields a predictable output.  
2. **Traceability**: `EmailMessage.meta` stores source system, filenames, and parsing method.  
3. **Non-Destructive**: Raw extracts remain accessible; no destructive normalization.  
4. **Repeatability**: Re-processing yields identical message IDs and metadata.  

## Data Mapping (WhatsApp → EmailMessage)
| WhatsApp Concept | EmailMessage Field | Notes |
|---|---|---|
| Chat name | `subject` | `WhatsApp: {chat_name}` |
| Sender display | `sender_name` | Raw display name |
| Sender phone | `sender_email` | `+447...@whatsapp.local` |
| Timestamp | `date_sent` | Parsed from prefix |
| Message body | `body_text` + `body_text_clean` | Message text |
| Chat group | `thread_group_id` | Stable chat hash |
| Order | `thread_position` | Line index |
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
| Empty export | Return empty list, user notified |
| Confidence below threshold | Skip or mark in metadata (v1 decision) |

## Security & Privacy Considerations
- Strip executable content from parsed text.  
- Validate media files extracted from ZIPs against allowlist.  
- Store phone numbers only where necessary for sender identification.  
- Ensure logs do not dump full message bodies.  

## Rollout Strategy
1. **Internal beta**: limited to test cases with controlled exports.  
2. **Pilot**: one production workspace with explicit user instruction.  
3. **General release**: after pass/fail thresholds and regression checks.  

## Risk Register (Top 5)
| Risk | Mitigation |
|---|---|
| Parsing ambiguity in PDF headers | Confidence scoring + deterministic regex |
| WhatsApp export format variants | Expand regex patterns based on field testing |
| Duplicate ingestion | Deterministic IDs + existing dedupe helpers |
| Large exports memory use | Cap messages + partial processing |
| Misclassification of `.txt` files | Detect format and return clear errors |

## Testing Plan (Required)
**Unit Tests**
- `test_whatsapp_parser.py`  
- `test_pdf_email_parser.py`  
- Existing email import tests (EML/MSG).  

**Manual Tests**
- Upload WhatsApp `.txt` (no media).  
- Upload WhatsApp `.zip` (media).  
- Upload PDF email.  
- Re-upload same file (dedupe check).  
- Upload invalid `.txt` (expect 400 error).  

## Deliverables Checklist
✅ WhatsApp parser + tests  
✅ PDF email parser + tests  
✅ Email import dispatch + list handling  
✅ Upload UI routing + WhatsApp badge  
✅ Regression tests pass  
✅ Manual verification performed  

## Appendix: Deterministic ID Schemes
- **WhatsApp**: `whatsapp-{hash(chat_name|timestamp|sender|index)}@whatsapp.local`  
- **PDF**: `pdf-{sha256(filename|section_index|from|date|subject)[:16]}@pdf-import.local`  

