# PST Pipeline V2 – Terraform (Control Plane)

Creates the **SQS → EventBridge Pipe → Step Functions** control plane for PST ingestion V2.

This module intentionally **does not** create your compute (Batch/ECS) by default; instead you
provide ARNs for:
- Batch job queue
- Batch job definition(s)

That keeps this repo’s IaC safe to land without forcing an immediate infra change.

## Pipeline Modes (Safety)

- **`pipeline_mode = "single"` (default)**: Phase 1 “V2 now” — one Batch job that runs the existing forensic Python processor once.
- **`pipeline_mode = "multistage"`**: future Extract/Load/Thread/Dedupe/Index orchestration (requires separate job definitions).

## What You Get
- SQS queue + DLQ
- EventBridge Pipe that triggers Step Functions from SQS messages
- Step Functions state machine (Batch‑driven orchestration)
- IAM roles/policies for Pipe + Step Functions
- CloudWatch log group for state machine logs

## Expected SQS Message Body
The Pipe passes the SQS message body as Step Functions input. Minimum fields:

```json
{
  "pst_file_id": "uuid",
  "project_id": "uuid",
  "case_id": null,
  "source_bucket": "vericase-docs",
  "source_key": "project_<project_id>/pst/<pst_file_id>/<filename>.pst",
  "output_bucket": "vericase-docs",
  "output_prefix": "pst-v2/<pst_file_id>/"
}
```

## Usage
```bash
cd infra/pst-pipeline-v2/terraform

# 1) Configure remote state (recommended):
#    cp backend.hcl.example backend.hcl
#    terraform init -backend-config=backend.hcl

terraform init
terraform plan \
  -var aws_region=eu-west-2 \
  -var batch_job_queue_arn=arn:aws:batch:...:job-queue/... \
  -var pipeline_mode=single \
  -var process_job_definition_arn=arn:aws:batch:...:job-definition/vericase-pst-process-python:1
```

Apply when ready:
```bash
terraform apply
```

## Notes
- Autoscaling is provided by your Batch compute environment (EC2) or ECS capacity provider.
- For “local NVMe”, prefer instance types with instance store (e.g. `c7gd`, `i4i`) and mount to
  the extractor’s scratch dir.

