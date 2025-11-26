# AWS Asset Inventory (Legacy)

Date: 2025-11-21
Purpose: Catalogue AWS/App Runner specific files and scripts now considered legacy.

## Root-Level Assets

| Path | Notes |
|------|-------|
| `apprunner.yaml` | Former AWS App Runner service definition. |
| `check-iam-policies.sh` | Script for auditing IAM policies. |
| `configure-apprunner-s3-access.sh` | Configures S3 access for App Runner. |
| `fix-iam-role.sh` | Script to patch IAM roles. |
| `s3-policy.json` | Sample S3 bucket policy. |
| `PST_UPLOAD_FIX.md` | AWS-specific remediation notes (needs review). |

## `pst-analysis-engine/`

| Path | Notes |
|------|-------|
| `AWS_CONFIG_CHECKLIST.md` | AWS configuration checklist. |
| `AWS_SETUP_SECURE.md` | Secure setup guide for AWS. |
| `DEPLOY_AWS.md` | General AWS deployment instructions. |
| `VPC_NETWORKING_GUIDE.md` | VPC networking guide. |
| `env.aws.example` | Environment template for AWS deployment. |
| `setup_aws_s3.py` | Helper script for AWS S3 integration. |
| `api/run_apprunner.sh` | Shell script for running App Runner tasks. |
| `docs/aws-reference/*` | Five markdown files + `deploy-apprunner.sh` moved to docs tree during earlier cleanup. |

## Archived Previously (11-21)

- `pst-analysis-engine/docs/aws-reference/` (already relocated under `_archive/2025-11-21/...` during earlier documentation cleanup).
- `pst-analysis-engine/AWS_DEPLOYMENT_GUIDE.md` → `_archive/2025-11-21/docs/aws-reference/` (rename performed).

## Not in Scope
- `.venv/**` references (numerous third-party AWS modules) – part of virtual environment, to be ignored once `.venv/` is removed.

Next steps: move/retire the legacy AWS assets above and update onboarding documentation to reflect the current non-AWS hosting strategy.
