# VeriCase — Legal Counsel Feature & Control Summary

This document summarizes **existing** capabilities in VeriCase that are relevant to legal counsel, eDiscovery teams, and expert evidence workflows. It focuses on **defensibility**, **auditability**, **chain-of-custody**, and **AI governance/guardrails**.

> Scope: what the application already implements in code/config.  
> This is not legal advice, and should be complemented with your engagement terms, disclosure protocol, and environment-level security policies (e.g., KMS, bucket policies, IAM least privilege).

---

## 1) What VeriCase is for (in one paragraph)

VeriCase is designed to ingest large evidence sources (notably PST email archives and associated attachments), normalize and index them for fast search and review, and provide “counsel-ready” workflows such as chronology building, evidence linking, disclosure bundle generation, and AI-assisted analysis—while preserving verifiable integrity references (hashes and deterministic excerpt pointers) and an audit trail of actions.

---

## 2) Evidence integrity & “unique stamping” (forensic-grade controls)

### 2.1 File-level integrity (SHA-256)

Evidence items carry a **SHA-256 content hash** (stored as `file_hash`) to support:
- **Deduplication** (identical artifacts can be detected deterministically)
- **Integrity verification** (a produced file can be re-hashed and compared)
- **Stable evidence referencing** across analysis and export steps

**Why this matters for counsel:** supports defensible statements such as “Exhibit X is byte-for-byte identical to the file originally ingested,” and reduces the risk of duplicate documents contaminating review sets.

### 2.2 Deterministic Evidence Pointers (DEP URIs) — excerpt stamping

VeriCase implements **Deterministic Evidence Pointers (DEP URIs)** to uniquely “stamp” a specific excerpt of a source text by:
- **Source identity** (email message or evidence item)
- **Exact character offsets** (start/end)
- **A cryptographic hash of the normalized excerpt**

This yields a stable pointer of the form:

`dep://{case_id}/{source_type}/{source_id}/chars_{start}-{end}#{hash_prefix}`

**Verification is supported:** the system can later re-compute hashes from the current stored text and confirm whether the excerpt still matches the recorded DEP span.

**Why this matters for counsel:** enables citation-grade excerpt references that are reproducible and testable (helpful for pleadings, expert reports, and structured chronologies).

### 2.3 Bundle manifests (export integrity)

VeriCase can generate a **deterministic bundle manifest** and an accompanying **hashes file**:
- Deterministic JSON manifest (stable ordering/serialization)
- `hashes.txt` including the manifest hash and hashes for referenced items/spans

**Why this matters for counsel:** supports disclosure packs where receiving parties can verify package integrity and counsel can show consistent provenance across productions.

---

## 3) Chain-of-custody and provenance (practical)

VeriCase tracks:
- **Where evidence is stored** (object storage bucket + key)
- **Ingestion provenance** (e.g., derived from a PST/email attachment vs direct upload)
- **Linking between evidence objects and correspondence** (evidence ⇄ email linkage)

**Why this matters for counsel:** helps answer “where did this come from?”, “how did it arrive in the dataset?”, and “what is the relationship between Exhibit Y and Email Z?”

---

## 4) Auditability and investigation readiness

### 4.1 Evidence activity logging

An evidence activity log model exists to record actions against evidence/collections, including:
- Action name + structured details
- Actor (user)
- IP address / user agent (where captured)
- Timestamp

**Why this matters for counsel:** supports internal defensibility, and helps investigate disputes around access, edits, deletions, and review progress.

### 4.2 Request correlation (chain IDs)

The API emits correlation identifiers (“chain IDs”) per request so activity can be tied together across systems/logs.

**Why this matters for counsel:** improves traceability during incident response and helps reconstruct timelines of system activity.

---

## 5) Access control and administrative governance

### 5.1 Role-based access model

The application defines user roles (e.g., ADMIN and standard user roles) and uses role checks on administrative workflows.

### 5.2 Admin approval gating (controlled onboarding)

User registration flow supports **pending approval** (accounts start inactive until approved by an administrator).

**Why this matters for counsel:** supports controlled access to sensitive matter data and reduces accidental/unvetted access to the evidence corpus.

---

## 6) eDiscovery / review workflows already present

### 6.1 Evidence repository (documents, text, metadata)

Evidence items support:
- Structured metadata fields (title, author, dates, file type, mime type, size)
- Extracted text storage for review/search
- Manual tags + auto tags
- Document category classification field (useful for triage)
- Review/privilege/confidentiality flags

### 6.2 Collections and grouping

Evidence can be organized into collections (manual/smart-like grouping) to support:
- Review sets
- Production/disclosure sets
- Thematic clusters (e.g., “Payment”, “Delay”, “Variations”, “Termination”)

### 6.3 Chronology building

Chronology features exist to structure events and link those events to evidence references (including DEP URIs where used).

**Why this matters for counsel:** aligns to real-world dispute workflows—turning large email corpora into structured, citeable chronologies.

---

## 7) Search and retrieval (relevance review)

### 7.1 Full-text search

The system uses a search backend (OpenSearch in production) to support:
- Full-text search
- Highlighting
- Email-specific search flows

**Why this matters for counsel:** accelerates relevance review, issue spotting, and rapid retrieval of corroborating communications.

### 7.2 Visibility controls (noise reduction)

The application includes mechanisms to exclude hidden/spam-flagged content from certain flows, reducing noise in review and analysis.

---

## 8) AI legal assistance (with governance hooks)

### 8.1 Evidence-constrained prompting (anti-hallucination posture)

AI prompts used by the evidence assistant are explicitly framed to:
- Answer based **only on provided evidence**
- Cite specific emails
- Say when evidence does not support an answer

**Why this matters for counsel:** supports defensible use of AI as an “analysis aid,” not an evidence source.

### 8.2 Multi-provider architecture (enterprise optionality)

VeriCase supports multiple AI providers, including AWS-native Bedrock and non-AWS providers (configurable).

**Counsel note:** whether you permit external providers is a matter of policy, contract (DPA), and data transfer analysis. Bedrock typically offers a more enterprise-aligned posture.

### 8.3 AWS Bedrock Guardrails support

Bedrock calls can be executed **with Bedrock Guardrails** when configured (guardrail identifier + version).

**Why this matters for counsel:** provides a mechanism to enforce content policies and reduce unsafe generations in AI outputs (e.g., disallowed content, certain data types, etc.), subject to your configured guardrail policy.

### 8.4 Knowledge Base (KB) / RAG capability

The system supports a “retrieve” and “retrieve-and-generate” style pattern against a Bedrock Knowledge Base.

**Why this matters for counsel:** enables “answer with sources” style assistance—useful for locating supporting material and building narratives with traceability.

### 8.5 AI event logging (audit without storing raw prompts)

AI runtime logging is designed to store:
- Metrics (latency, provider/model, success/failure)
- Hashes of prompts/responses (rather than full sensitive content)
- Chain/context metadata for correlation

**Why this matters for counsel:** supports oversight and troubleshooting while minimizing duplication of sensitive content in logs.

---

## 9) AWS-native evidence extraction and governance features (when enabled)

The application integrates with AWS services that are commonly relevant in legal evidence processing:
- **Textract**: OCR + structured extraction (tables/forms/queries/signatures)
- **Comprehend**: entity extraction and PII detection capability
- **Transcribe**: transcription workflows with PII redaction configuration (where used)
- **OpenSearch**: enterprise search/indexing

**Why this matters for counsel:** supports defensible extraction pipelines and scalable review for large evidence volumes.

---

## 10) Secure sharing / controlled access

The application includes share-link patterns (including password-protected share links) for controlled external access to a subset of evidence.

**Why this matters for counsel:** supports limited disclosure to counterparties or experts without full system onboarding, subject to your policy.

---

## 11) Recent security hardening relevant to counsel (implemented)

To protect defensibility and audit integrity:
- Evidence repository endpoints are now **authenticated** (prevents unauthenticated upload/list/access of evidence).
- The unsafe “auto-create a default admin user with a hardcoded password” behavior was removed (protects the integrity of “who did what” and prevents unauthorized admin access).
- Debug endpoints were gated behind authentication/admin and are disabled in production unless explicitly enabled.

These changes protect the core legal value proposition: **defensible access control + trustworthy audit trails + integrity references.**

---

## Appendix A — Where these features live (technical pointers)

This appendix is for technical validation and audit support.

- **Evidence file hashing and storage**: `vericase/api/app/models.py` (evidence models), `vericase/api/app/evidence/utils.py` (hash helper)
- **DEP stamping + verification**: `vericase/api/app/forensic_integrity.py`, `vericase/api/app/forensics.py`
- **Bundle manifest + hashes export**: `vericase/api/app/bundle_manifest.py`
- **Evidence repository API**: `vericase/api/app/evidence/routes.py`, `vericase/api/app/evidence/services.py`
- **Auth and approvals**: `vericase/api/app/security.py`, `vericase/api/app/main.py`, `vericase/api/app/admin_approval.py`
- **AI runtime + Bedrock guardrails hook**: `vericase/api/app/ai_runtime.py`, `vericase/api/app/ai_providers/bedrock.py`
- **AWS service integrations**: `vericase/api/app/aws_services.py`

