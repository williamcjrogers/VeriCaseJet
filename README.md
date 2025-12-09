# VeriCase

**Enterprise PST/email analysis platform for legal disputes.**

## Quick Start

```bash
cd vericase
docker-compose up -d
```

Open http://localhost:8010/ui/dashboard.html

## Repository Structure

```
vericase/
├── api/                 # FastAPI backend
│   ├── app/             # Application code
│   ├── migrations/      # Database migrations
│   └── Dockerfile
├── ui/                  # Production static UI (HTML/CSS/JS)
├── frontend/            # React dev UI (local development only)
├── worker_app/          # Celery background workers
├── ops/                 # Operations scripts
├── k8s/                 # Kubernetes deployment configs
├── docs/                # All documentation
├── docker-compose.yml   # Local development
└── docker-compose.prod.yml  # Production deployment
```

## Documentation

- [Deployment Guide](.github/DEPLOYMENT.md)
- [Local Development](vericase/docs/deployment/LOCAL_DEVELOPMENT.md)
- [AWS Setup](vericase/docs/aws/AWS_SETUP_GUIDE.md)
- [Project Brief](vericase/docs/PROJECT_VERICASE_BRIEF.md)

## Deployment

Automatic deployment via GitHub Actions on push to `main`.

### Manual Deployment

```bash
# Local
cd vericase && docker-compose up -d

# Production (EKS)
kubectl apply -f vericase/k8s/k8s-deployment.yaml -n vericase
```

## AWS Infrastructure

| Resource | Value |
|----------|-------|
| Region | eu-west-2 |
| EKS Cluster | vericase-cluster |
| EC2 (Backup) | 18.175.232.87 |
| S3 Bucket | vericase-docs |

## Status

- **Version:** 1.0.0
- **State:** Production
- **Last Updated:** December 2025
