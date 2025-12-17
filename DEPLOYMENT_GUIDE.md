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
| `AWS_ROLE_TO_ASSUME` | AWS IAM Role ARN for GitHub OIDC (recommended; avoids long-lived AWS keys) |

> Configure these in GitHub: **Settings → Secrets and variables → Actions**.
> `GITHUB_TOKEN` is provided automatically for GHCR access.

### AWS auth via GitHub OIDC (recommended)

This avoids storing long-lived AWS access keys in GitHub.

1. Create (or verify) the AWS IAM OIDC provider for GitHub Actions:
   - URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`
2. Create an IAM role trusted for your repo, attach the minimum permissions needed to deploy to EKS.
3. Set GitHub Secret `AWS_ROLE_TO_ASSUME` to the role ARN.
4. Remove any legacy `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` GitHub Secrets.

Example trust policy (replace placeholders):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:<OWNER>/<REPO>:ref:refs/heads/main"
        }
      }
    }
  ]
}
```

## Access Points (Local)

| Service | URL |
|---------|-----|
| API | http://localhost:8010 |
| API Docs | http://localhost:8010/docs |
| Frontend | http://localhost:5173 |

## Production (EKS)

- **Cluster:** `vericase-cluster` (eu-west-2)
- **Domains:** `veri-case.com`, `api.veri-case.com`
