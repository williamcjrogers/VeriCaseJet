# VeriCase CI/CD

## Workflow

**File:** `.github/workflows/deploy-eks.yml`

**Trigger:** Push to `main` affecting `vericase/**` files (or manual **Run workflow**)

**Pipeline:**
```
Push to main  →  Build  →  Push to Docker Hub + GHCR  →  Deploy to EKS (by image digest)
```

## Required Secrets

Configure in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `DOCKER_PAT` | Docker Hub personal access token |
| `AWS_ROLE_TO_ASSUME` | IAM role ARN trusted for GitHub OIDC (used by `aws-actions/configure-aws-credentials`) |

> Note: CI/CD uses GitHub OIDC via `AWS_ROLE_TO_ASSUME` and does **not** require long-lived `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` secrets.

`GITHUB_TOKEN` is automatically provided for GHCR access.

## Image Registries

- **Docker Hub:** `wcjrogers/vericase-api`
- **GHCR:** `ghcr.io/williamcjrogers/vericase-api`

## Full Documentation

See **[vericase/docs/deployment/DEPLOYMENT.md](../vericase/docs/deployment/DEPLOYMENT.md)** for complete deployment guide including:

- EKS cluster details
- kubectl commands
- AWS resources
- Troubleshooting
