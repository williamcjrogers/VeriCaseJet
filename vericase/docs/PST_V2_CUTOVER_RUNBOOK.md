## PST V2 Cutover Runbook (Ruthless Parity Gates)

This runbook turns the V2 cutover criteria into repeatable, testable steps.

**Goal**: prove that **V2 orchestration (SQS/Pipe/SFN/Batch)** produces **forensically identical outputs** to V1 for a representative PST set, before routing production traffic.

---

## What you’ll run (artifacts)

- **Trigger a V2 ingest via SQS**: `scripts/pst_v2_trigger_sqs.ps1`
- **Run parity gates**: `scripts/pst_v2_parity_check.py`

---

## Preconditions

- **AWS CLI** configured with credentials that can `sqs:SendMessage` in `eu-west-2`.
- **Database access** to the same Postgres the API/worker uses.
  - Set `DATABASE_URL` in your environment (do not paste it into tickets/chat).
- **Two PST ingests** for the *same underlying PST content*:
  - **Baseline**: processed via V1 (Celery / EKS).
  - **Candidate**: processed via V2 (SQS → Pipe → SFN → Batch).

> Important: The parity tool compares two `pst_files.id` values. It does **not** attempt to “re-run” the same `pst_file_id` twice (the API prevents that once completed).

---

## Step 1 — Choose the 5 PST shadow-run set

Minimum recommended set (matches your success criteria):

- **Small**: <100MB
- **Medium**: ~500MB
- **Large**: 2–5GB
- **Unicode / non-English**
- **Deep folder hierarchy / lots of inline images**

---

## Step 2 — Produce a baseline (V1) ingest

You need a completed `pst_file_id` processed via V1.

Options:

- **From the UI**: upload + process normally (current default path uses Celery).
- **From API** (if you already have a `pst_file_id`):
  - `POST /pst/{pst_file_id}/process`
  - Poll: `GET /pst/{pst_file_id}/status`

Record:

- **Baseline `pst_file_id`**
- **S3 source** (`pst_files.s3_bucket`, `pst_files.s3_key`)

---

## Step 3 — Produce a candidate (V2) ingest

Create a second PST ingest record for the *same file content* (new `pst_file_id`) and trigger V2.

Practical way (no DB surgery):

- **Upload the same PST again** (creates a new `pst_file_id`), then do **not** press the “process” button (to avoid Celery).
- Trigger V2 via SQS using the new `pst_file_id` + the new record’s `project_id`/`case_id` + its `s3_bucket`/`s3_key`.

Run:

```powershell
pwsh -File scripts/pst_v2_trigger_sqs.ps1 `
  -PstFileId "<candidate-pst-file-uuid>" `
  -ProjectId "<project-uuid>" `
  -CaseId "<case-uuid-or-empty>" `
  -FileName "<original pst filename>" `
  -SourceBucket "vericase-docs"
```

Then wait until candidate is done:

- `GET /pst/{candidate_pst_file_id}/status` shows `completed`, OR
- `SELECT processing_status, error_message FROM pst_files WHERE id = '<candidate>'`

---

## Step 4 — Run the ruthless parity gates

Set DB connection:

```powershell
$env:DATABASE_URL = "<your database url>"
```

Run parity:

```powershell
python scripts/pst_v2_parity_check.py `
  --baseline-pst-file-id "<baseline-pst-file-uuid>" `
  --candidate-pst-file-id "<candidate-pst-file-uuid>" `
  --json-out "pst-parity-report.json"
```

If you also want to verify **every attachment object exists in S3** (slower; requires AWS creds):

```powershell
python scripts/pst_v2_parity_check.py `
  --baseline-pst-file-id "<baseline-pst-file-uuid>" `
  --candidate-pst-file-id "<candidate-pst-file-uuid>" `
  --s3-head `
  --json-out "pst-parity-report.json"
```

### Interpreting results

- **All `BLOCKER` gates must PASS** for cutover.
- `WARNING` gates can be tolerated only within your stated thresholds (threading <= 1% delta, OCR >= 95% baseline).

---

## Go/No-Go gates (what the tool enforces)

- **PST status**: both baseline and candidate are `processing_status='completed'` and `error_message IS NULL` (**BLOCKER**)
- **Counts**: emails, attachments, distinct `message_id`, emails with body_text (**BLOCKER**)
- **Message-ID identity**: `message_id` multiset exact (**BLOCKER**)
- **Forensic presence**:
  - `conversation_index` pct
  - `in_reply_to` pct
  - `email_references` pct
  - `pst_message_path` pct
  - **Transport headers presence** via `email_messages.metadata->>'transport_headers_present'`
  - Candidate must be **>= baseline (within -1pp tolerance)** (**BLOCKER**)
- **Content integrity**: **content_hash multiset exact** (**BLOCKER**)
- **Attachment integrity**:
  - `attachment_hash` multiset exact (**BLOCKER**)
  - attachments-per-email distribution exact (grouped by parent email `content_hash`) (**BLOCKER**)
- **Threading**:
  - <= 1% deltas are **WARNING**
  - > 5% delta is a **BLOCKER**
- **OCR coverage**:
  - Attachment `documents` created count exact (**BLOCKER**)
  - text present ratio within baseline tolerances (**WARNING / BLOCKER thresholds**)

---

## After the 5 PST shadow runs

**Cutover plan**:

- **10%** of new PSTs to V2 (feature flag) → monitor 4 hours
- **50%** → monitor 24 hours
- **100%** → keep V1 runnable for 7 days as rollback

---

## Cost-safety (Batch)

If you temporarily scaled Batch capacity to unblock a test run:

- **Preferred**: ensure the compute environment has **`minvCpus=0`** so Batch can scale down to zero when idle.
- **Note**: AWS Batch may reject “manual scale-down” updates to `desiredvCpus`. If you must force scale-down immediately, you generally need to **disconnect job queues** / **disable the compute environment**, which will stop scheduling new jobs.

---

## Known schema notes (why some queries differ from earlier drafts)

- **Transport headers**: not stored as `transport_headers_text`; presence is tracked in `email_messages.metadata` (`transport_headers_present`, `transport_headers_sha256`).
- **OCR completion**: attachment OCR updates `documents.status` to `READY` and stores text in `documents.text_excerpt`.
- **Attachment hash column**: `email_attachments.attachment_hash` (not `file_hash`).


