# VeriCase CI/CD

## Workflow

**File:** `.github/workflows/deploy-eks.yml`

**Trigger:** Push to `main` affecting `vericase/**` files

**Pipeline:**
```
Push to main  →  Build  →  Push to Docker Hub + GHCR  →  Deploy to EKS
```

## Required Secrets

Configure in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `DOCKER_PAT` | Docker Hub personal access token |
| `AWS_ACCESS_KEY_ID` | AWS IAM access key |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key |

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
