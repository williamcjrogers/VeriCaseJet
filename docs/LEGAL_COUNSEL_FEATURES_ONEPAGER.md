# VeriCase — Counsel One‑Pager (Defensibility & Guardrails)

## What it is
VeriCase is an evidence processing and review platform built for high‑volume email and document corpora (e.g., PST archives). It supports search, review, chronology building, controlled sharing, and AI‑assisted analysis—while preserving verifiable integrity references (hashes and deterministic excerpt pointers) and activity/audit trails.

## What makes it defensible (the “legal-grade” features)

### Integrity & “unique stamping”
- **SHA‑256 file hashing**: evidence items store a SHA‑256 hash (`file_hash`) to support deduplication and later integrity verification.
- **Deterministic Evidence Pointers (DEP URIs)**: counsel can “stamp” a precise excerpt (character offsets) with a cryptographic hash and later **verify** that the excerpt still matches (tamper evidence / integrity validation).
- **Bundle manifest + hashes export**: deterministic bundle manifests and `hashes.txt` support integrity-checked disclosure/export packages.

### Chain of custody & provenance
- Evidence records carry storage location (bucket/key), provenance fields (source relationships), and evidence⇄correspondence linkage patterns to support “where did this come from?” questions.

### Auditability
- **Evidence activity logging model** exists (action + details + actor + timestamp; IP/user-agent fields available), supporting defensible internal audit trails.
- **Request correlation IDs** (chain IDs) support forensic investigation and timeline reconstruction.

### Access governance & controlled onboarding
- **Role-based access model** and **admin approval gating** (registrations can be held pending approval), supporting controlled access to sensitive matter data.

### Review workflow support
- Evidence repository supports metadata + extracted text, tags and categorization, plus **privilege/confidentiality/review flags** for legal review workflows.
- Collections/grouping support disclosure/review sets.

### Search & retrieval
- Full‑text search (OpenSearch in production) supports fast relevance review and retrieval of corroborating communications.

## AI assistance (AWS Bedrock + guardrails)
- **Evidence-constrained prompting**: AI assistant prompts are structured to answer based **only** on provided evidence, cite sources, and say when evidence is insufficient (anti‑hallucination posture).
- **AWS Bedrock integration**: enterprise option using AWS IAM controls.
- **Bedrock Guardrails support (wired)**: Bedrock calls can be executed with guardrails when configured (guardrail ID + version).
- **Knowledge Base / RAG capability** exists to support “answer with sources” style workflows.

## AWS-native extraction that matters in disputes
- **Textract** for OCR/structured extraction (tables/forms/queries/signatures).
- **Comprehend** capability for entities and PII detection workflows.
- **Transcribe** supports PII redaction configuration for audio/video evidence workflows (where used).

## Deliverables counsel can rely on
- Integrity-verifiable evidence objects (SHA‑256)
- Integrity-verifiable excerpt citations (DEP URIs + verification)
- Integrity-verifiable disclosure bundles (manifest + hashes)
- Audit trails and correlation IDs for investigation and governance

## Reference
For the full counsel feature summary and technical pointers, see `docs/LEGAL_COUNSEL_FEATURES.md`.

