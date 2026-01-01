# PST Pipeline V2 (Best‑In‑Class, Compiled Extractor)

## Goal
Move PST ingestion from “Python + pypff + per‑row ORM writes” to a **staged, observable, autoscaling pipeline**:

1. **Ingest trigger**: API enqueues a job to **SQS** (with **DLQ**).
2. **Orchestrate**: **EventBridge Pipes → Step Functions** (no Lambda glue).
3. **Extract (compiled)**: Run a **compiled extractor** on **EC2** (via AWS Batch/ECS on EC2) with local NVMe/EBS.
4. **Write once**: Emit **NDJSON + CSV** (optionally Parquet later) to S3 under a deterministic prefix.
5. **Load fast**: Bulk **COPY** into Postgres/Aurora (staging + upsert).
6. **Post‑process**: Threading, dedupe, indexing as separate, retryable stages.

This separates failure domains, makes processing idempotent, and gives clear per‑stage metrics.

## Data Flow
**S3 PST** → SQS `pst_ingest` → EventBridge Pipe → Step Functions `pst_ingest_v2`

Step Functions stages (recommended):
1. `extract`: Batch job `pst-extractor` (EC2, instance store/NVMe if available)
2. `load`: Batch job `pst-loader` (COPY into DB)
3. `thread`: Batch job (runs `build_email_threads`)
4. `dedupe`: Batch job (runs `dedupe_emails`)
5. `index`: Batch job (OpenSearch indexing / semantic indexing)

All stages:
- Write stage outputs to S3 (`manifest.json`, logs, metrics)
- Use Step Functions retries with exponential backoff
- Route terminal failures to DLQ and mark PST as failed

## Extractor Output (S3)
For input:
`s3://<docs-bucket>/project_<project_id>/pst/<pst_file_id>/<filename>.pst`

Write outputs:
`s3://<pipeline-bucket>/pst-v2/<pst_file_id>/`
- `emails.ndjson.gz` (audit / reprocess)
- `emails.csv.gz` (DB bulk load)
- `manifest.json` (counts, timings, checksums, version)

## Loader Strategy (Postgres/Aurora)
Recommended:
1. `COPY` into a staging table (fast, forgiving).
2. Validate counts + basic invariants.
3. Upsert into `email_messages`/attachments tables in SQL.

Why staging: avoids partial writes and makes rollback easy.

## Why EC2 (not Fargate) for Extract
PST parsing + attachment extraction is CPU + IO heavy and benefits from:
- High vCPU instance types (Batch on EC2)
- Local NVMe (instance store) for scratch
- Larger ephemeral storage than Fargate defaults

## Repo Locations
- Terraform skeleton: `infra/pst-pipeline-v2/terraform`
- Rust extractor skeleton: `services/pst-extractor`
- Loader skeleton: `services/pst-loader`

## Rollout Plan
1. Deploy V2 alongside existing pipeline (no cut‑over).
2. Shadow‑run: process a PST in V2 and compare counts/hashes to existing pipeline.
3. Cut over per project (feature flag / queue routing).
4. Decommission legacy pypff pipeline after confidence.

