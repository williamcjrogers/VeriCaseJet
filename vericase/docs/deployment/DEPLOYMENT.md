# VeriCase Deployment Guide

## Overview

VeriCase uses a streamlined deployment model:

| Environment    | Target         | Config                        |
| -------------- | -------------- | ----------------------------- |
| **Local Dev**  | Docker Compose | `vericase/docker-compose.yml` |
| **Production** | AWS EKS        | `vericase/k8s/` manifests     |

## Quick Start

### Local Development

```bash
cd vericase
docker-compose up -d
```

Access points:

- API: http://localhost:8010
- API Docs: http://localhost:8010/docs
- MinIO Console: http://localhost:9003

### Production (EKS)

Push to `main` branch triggers automatic deployment:

```
git push origin main  →  Build image  →  Push to registries  →  Deploy to EKS
```

---

## CI/CD Pipeline

### Single Workflow: `deploy-eks.yml`

**Trigger:** Push to `main` affecting `vericase/**` files, or manual dispatch

**Steps:**

1. Build Docker image
2. Push to Docker Hub (`wcjrogers/vericase-api`)
3. Push to GHCR (`ghcr.io/williamcjrogers/vericase-api`)
4. Deploy to EKS cluster

**Image tags:**

- `latest` - most recent build
- `{commit-sha}` - for rollback/pinning
- `YYYYMMDD-HHmmss` - timestamp

### Required GitHub Secrets

| Secret                  | Description                      |
| ----------------------- | -------------------------------- |
| `DOCKER_PAT`            | Docker Hub personal access token |
| `AWS_ACCESS_KEY_ID`     | AWS IAM access key               |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key               |

---

## EKS Production Environment

### Cluster Details

- **Cluster:** `vericase-cluster`
- **Region:** `eu-west-2`
- **Namespace:** `vericase`

### Deployments

| Deployment      | Replicas      | Purpose             |
| --------------- | ------------- | ------------------- |
| vericase-api    | 3 (HPA: 3-10) | FastAPI backend     |
| vericase-worker | 2 (HPA: 2-6)  | Celery workers      |
| tika            | 1             | Document processing |

### Common Commands

```bash
# Configure kubectl
aws eks update-kubeconfig --name vericase-cluster --region eu-west-2

# View status
kubectl get pods -n vericase
kubectl get deployments -n vericase

# View logs
kubectl logs -f deployment/vericase-api -n vericase

# Manual rollout restart
kubectl rollout restart deployment/vericase-api -n vericase

# Check rollout status
kubectl rollout status deployment/vericase-api -n vericase
```

### Ingress & Domains

Served via AWS ALB Ingress:

- `veri-case.com`
- `www.veri-case.com`
- `api.veri-case.com`

SSL managed by AWS ACM.

---

## AWS Resources

| Resource    | Identifier                                                     |
| ----------- | -------------------------------------------------------------- |
| EKS Cluster | `vericase-cluster`                                             |
| S3 Bucket   | `vericase-docs`                                                |
| RDS         | `database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com`          |
| ElastiCache | `master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com` |
| Region      | `eu-west-2`                                                    |

### Production Environment Variables

```env
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2
S3_BUCKET=vericase-docs
USE_TEXTRACT=true
BEDROCK_KB_ID=ACKHIYIHPK
BEDROCK_DS_ID=D9BX79MBSG
```

Secrets (DATABASE_URL, JWT_SECRET, etc.) are managed via Kubernetes secrets.

---

## Local Development Details

### Services

| Service    | Purpose               | Port      |
| ---------- | --------------------- | --------- |
| api        | FastAPI backend       | 8010      |
| worker     | Celery task processor | -         |
| postgres   | PostgreSQL 15         | 54321     |
| redis      | Cache/broker          | 6379      |
| opensearch | Search engine         | 9200      |
| tika       | Document processor    | 9998      |
| minio      | S3-compatible storage | 9002/9003 |

### Environment Setup

```bash
cp vericase/.env.example vericase/.env
# Edit .env as needed
```

Key local variables:

```env
USE_AWS_SERVICES=false
DATABASE_URL=postgresql+psycopg2://vericase:vericase@postgres:5432/vericase
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=http://minio:9000
```

---

## Troubleshooting

### Local

```bash
# Check logs
docker-compose logs -f api

# Restart a service
docker-compose restart api

# Reset database
docker-compose down -v
docker-compose up -d
```

### EKS

```bash
# Check pod status
kubectl get pods -n vericase

# Describe failing pod
kubectl describe pod <pod-name> -n vericase

# View recent events
kubectl get events -n vericase --sort-by='.lastTimestamp'

# Check image being used
kubectl get deployment vericase-api -n vericase -o jsonpath='{.spec.template.spec.containers[0].image}'
```

---

## Legacy: EC2 Deployment

For single-server deployments (not recommended for production), see `docker-compose.prod.yml`. This is maintained for reference but EKS is the canonical production target.
