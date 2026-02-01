# VeriCase — Legal Counsel Controls Narrative (Defensibility, Audit, AI Guardrails)

This document describes the **controls and features already present** in VeriCase that support legal defensibility, review governance, and integrity‑checked disclosure. It is written in a controls‑narrative style suitable for counsel review and (where appropriate) compliance programs (e.g., ISO 27001 / SOC 2).

> Note: This is not legal advice. “Defensible” here refers to technical properties that enable verification, traceability, and controlled access when deployed with appropriate operational policies (IAM least privilege, KMS/bucket policies, secure logging retention, etc.).

---

## 1) Integrity controls (hashing, stamping, verification)

### Control objective
Ensure that evidence artifacts and excerpt references can be **verified** and that integrity can be demonstrated to third parties.

### Implemented controls
- **Artifact hashing (SHA‑256)**: evidence items store a SHA‑256 hash, supporting deterministic deduplication and integrity comparison.
- **Deterministic Evidence Pointer (DEP) stamping**: excerpt pointers include:
  - Source identity (email_message or evidence_item)
  - Character offsets (start/end)
  - Hash of normalized excerpt text
  - A stable `dep://...` URI format
- **Integrity verification**: verification recomputes excerpt and source hashes and returns match/mismatch.
- **Integrity‑checked exports**: bundle manifests are deterministically serialized and written with accompanying hashes.

### Evidence / auditability benefits
- Enables reproducible citations to specific text spans (useful for chronologies, pleadings, and expert reports).
- Enables detection of content drift or tampering (mismatch on verification).
- Enables disclosure bundles that are independently verifiable (manifest hash + referenced hashes).

---

## 2) Provenance & chain-of-custody support

### Control objective
Maintain a clear provenance trail for where artifacts originated and how they relate to communications.

### Implemented controls
- Evidence items store object storage location (bucket/key) and provenance fields (source relationships).
- Evidence-to-correspondence linkage supports demonstrating “this exhibit came from this email/attachment context.”

### Counsel benefit
Supports foundational questions in disputes:
- “Where did this document come from?”
- “Is this attachment the one actually sent on date X?”
- “Which communications support this event?”

---

## 3) Audit logging & investigation readiness

### Control objective
Provide a defensible record of significant actions and enable investigation and reconstruction of operational timelines.

### Implemented controls
- **Evidence activity log model** exists capturing action + details + actor + timestamp, with optional IP and user agent fields.
- **Request correlation IDs (chain IDs)** are emitted per request and can be used to correlate activity across logs and subsystems.
- **AI event logging** records metrics and hashes (rather than storing raw prompts everywhere), supporting audit while reducing duplication of sensitive evidence in logs.

### Counsel benefit
Supports internal defensibility, dispute resolution around access/edits, and incident response.

---

## 4) Access governance (RBAC + controlled onboarding)

### Control objective
Limit access to evidence and administrative functionality to authorized users and roles, and control onboarding to sensitive datasets.

### Implemented controls
- **Role-based access model** exists (admin and standard user roles).
- **Admin approval gating** exists for new registrations (accounts can be held pending approval).

### Counsel benefit
Supports controlled access to evidence corpora and reduces unintended access by unapproved users.

---

## 5) Review workflow controls (privilege, confidentiality, and review state)

### Control objective
Support legal review workflows that include privilege marking, confidentiality designation, and review state tracking.

### Implemented controls
Evidence items include:
- **Privilege flags** (`is_privileged`)
- **Confidentiality flags** (`is_confidential`)
- **Review flags** (`is_reviewed`, plus reviewer fields)
- Tags, categorization fields, extracted text and metadata to support triage and review.

### Counsel benefit
Provides structure for privilege review workflows and disciplined review tracking.

---

## 6) Search and retrieval (relevance review at scale)

### Control objective
Enable fast location and retrieval of relevant material across large corpora.

### Implemented controls
- Full‑text indexing/search (OpenSearch in production) to support relevance review and fast retrieval.
- Visibility/noise reduction mechanisms exist to exclude hidden/spam‑flagged material from certain flows.

### Counsel benefit
Reduces time-to-relevance and improves ability to triangulate corroboration quickly.

---

## 7) AI assistance governance (Bedrock, guardrails, evidence-only posture)

### Control objective
Enable AI-assisted analysis while reducing hallucination risk and supporting policy enforcement.

### Implemented controls
- **Evidence-only prompting posture**: AI assistant prompts are structured to answer based only on provided evidence and to disclose when evidence is insufficient.
- **AWS Bedrock integration**: enterprise-oriented provider option leveraging IAM.
- **Bedrock Guardrails integration is wired**: Bedrock calls can be issued with guardrails when a guardrail ID and version are configured.
- **Knowledge Base (KB) / RAG capability** exists to support “answer with sources” style assistance.

### Counsel benefit
Supports positioning AI as an analysis aid that is constrained by the evidence corpus and subject to policy controls (guardrails), rather than an unbounded “general advice” tool.

---

## 8) AWS-native evidence processing features (extract/identify/govern)

### Control objective
Use scalable managed services for extraction and governance‑adjacent detection tasks.

### Implemented controls/capabilities (when enabled)
- **Textract**: OCR + structured extraction (tables/forms/queries/signatures).
- **Comprehend**: entity extraction and PII detection capability (useful for privacy review workflows).
- **Transcribe**: transcription with PII redaction configuration for audio/video evidence workflows (where used).

### Counsel benefit
Improves scalability and consistency of extraction for large volumes of heterogeneous evidence.

---

## Appendix — Deployment posture notes (for context)

In production, the platform is designed to run on AWS infrastructure, with:
- Kubernetes/EKS deployment
- Pod IAM roles (IRSA)
- TLS termination via ALB/ACM
- Managed services (S3, RDS, OpenSearch, ElastiCache) as configured

Operational controls (IAM least privilege, encryption policies, log retention, key management) remain essential to fully realize the compliance posture.

