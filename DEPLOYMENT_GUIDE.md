# VeriCase Deployment

## Quick Reference

| Environment | Command | Config |
|-------------|---------|--------|
| **Local Dev** | `cd vericase && docker-compose up -d` | `docker-compose.yml` |
| **Production** | `git push origin main` (auto-deploys) | EKS via `deploy-eks.yml` |

## Detailed Documentation

See **[vericase/docs/deployment/DEPLOYMENT.md](vericase/docs/deployment/DEPLOYMENT.md)** for:

- CI/CD pipeline details
- EKS cluster configuration
- AWS resources reference
- Local development setup
- Troubleshooting guides

## Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `DOCKER_PAT` | Docker Hub personal access token |
| `AWS_ACCESS_KEY_ID` | AWS IAM access key |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key |

## Access Points (Local)

| Service | URL |
|---------|-----|
| API | http://localhost:8010 |
| API Docs | http://localhost:8010/docs |
| Frontend | http://localhost:5173 |

## Production (EKS)

- **Cluster:** `vericase-cluster` (eu-west-2)
- **Domains:** `veri-case.com`, `api.veri-case.com`
