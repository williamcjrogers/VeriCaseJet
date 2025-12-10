# VeriCase Deployment Guide

This document provides a comprehensive overview of the VeriCase deployment architecture, configuration files, and workflows for developers joining the project.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Deployment Platforms](#deployment-platforms)
4. [Key Files Reference](#key-files-reference)
5. [CI/CD Pipeline](#cicd-pipeline)
6. [Environment Configuration](#environment-configuration)
7. [Local Development](#local-development)
8. [Production Deployment](#production-deployment)
9. [Kubernetes (EKS)](#kubernetes-eks)
10. [External Services & AWS Resources](#external-services--aws-resources)
11. [Health Checks](#health-checks)
12. [Troubleshooting](#troubleshooting)

---

## Overview

VeriCase is deployed using a **multi-platform approach** supporting:
- **Local Docker Compose** – for development
- **AWS EC2** – single instance deployment
- **AWS EKS** – Kubernetes cluster for production

The system uses automated **GitHub Actions CI/CD pipelines** that build and push Docker images to multiple registries.

---

## Architecture

### Services

| Service | Purpose | Port |
|---------|---------|------|
| **api** | FastAPI backend (Python 3.11) | 8010 |
| **worker** | Celery background task processor | - |
| **beat** | Celery scheduler (production) | - |
| **flower** | Celery monitoring UI | 5555 |
| **frontend** | React + Vite application | 3000 |
| **postgres** | PostgreSQL 15 database | 5432 |
| **redis** | Cache and message broker | 6379 |
| **opensearch** | Full-text search engine | 9200 |
| **tika** | Apache Tika document processor | 9998 |
| **minio** | S3-compatible storage (dev only) | 9000/9001 |
| **nginx** | Reverse proxy with SSL (production) | 80/443 |

### Docker Image Registries

Images are published to two registries for redundancy:
- **Docker Hub**: `wcjrogers/vericase-api:latest`
- **GitHub Container Registry**: `ghcr.io/williamcjrogers/vericase-api:latest`

Image tags follow this pattern:
- `latest` – most recent build
- `{sha}-{commit}` – commit-specific
- `YYYYMMDD-HHmmss` – timestamp-based

---

## Deployment Platforms

| Platform | Use Case | Location |
|----------|----------|----------|
| Local Docker | Development | Your machine |
| AWS EC2 | Staging/simple prod | `18.175.232.87` (eu-west-2) |
| AWS EKS | Production | Cluster: `vericase-cluster` |

---

## Key Files Reference

### CI/CD & Workflows

| File | Purpose |
|------|---------|
| `.github/workflows/docker-publish-multi.yml` | Builds & publishes Docker images to Docker Hub + GHCR |
| `.github/workflows/deploy-eks.yml` | Builds, pushes, and deploys to EKS cluster |
| `.github/DEPLOYMENT.md` | GitHub secrets setup and manual deployment steps |

### Docker Configuration

| File | Purpose |
|------|---------|
| `vericase/docker-compose.yml` | Local development environment (7 services) |
| `vericase/docker-compose.prod.yml` | Production environment (9 services with replicas) |
| `vericase/api/Dockerfile` | API container image definition |
| `vericase/api/start.sh` | Container startup script (migrations + uvicorn) |

### Kubernetes

| File | Purpose |
|------|---------|
| `vericase/k8s/k8s-deployment.yaml` | Main deployment manifest (API + Worker) |
| `vericase/k8s/k8s-ingress.yaml` | ALB ingress with SSL/TLS configuration |
| `vericase/k8s/tika-deployment.yaml` | Apache Tika service deployment |

### Nginx & SSL

| File | Purpose |
|------|---------|
| `vericase/nginx/conf.d/default.conf` | HTTPS reverse proxy configuration |

### Operations Scripts

| File | Purpose |
|------|---------|
| `vericase/ops/deploy.sh` | Multi-environment deployment (local/ec2/eks) |
| `vericase/ops/deploy.ps1` | Windows deployment script |
| `vericase/ops/diagnose.sh` | Health and status diagnostics |
| `vericase/ops/setup-aws.sh` | AWS infrastructure provisioning |
| `vericase/ops/ec2-bootstrap.sh` | EC2 instance initialization |
| `vericase/ops/reset-db.sh` | Database reset utility |

### Configuration

| File | Purpose |
|------|---------|
| `vericase/.env.example` | Environment variables template |
| `vericase/api/app/config.py` | Application configuration |
| `vericase/api/app/config_production.py` | Production-specific settings |
| `vericase/frontend/vite.config.ts` | Frontend build configuration |

---

## CI/CD Pipeline

### Automatic Deployment Flow

```
Push to main branch
        │
        ▼
┌───────────────────────────────┐
│  docker-publish-multi.yml     │
│  - Build Docker image         │
│  - Push to Docker Hub         │
│  - Push to GHCR               │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│  deploy-eks.yml               │
│  - Configure AWS credentials  │
│  - Update kubeconfig          │
│  - Apply k8s manifests        │
│  - Restart deployments        │
│  - Verify rollout             │
└───────────────────────────────┘
```

### Required GitHub Secrets

Configure these in your repository settings:

| Secret | Description |
|--------|-------------|
| `DOCKERHUB_USERNAME` | Docker Hub account username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |
| `AWS_ACCESS_KEY_ID` | AWS IAM credentials for EKS |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM credentials for EKS |

---

## Environment Configuration

### Local Development (.env)

Copy from the template and modify as needed:

```bash
cp vericase/.env.example vericase/.env
```

Key variables for local development:

```env
USE_AWS_SERVICES=false
MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=changeme123
DATABASE_URL=postgresql+psycopg2://vericase:vericase@postgres:5432/vericase
REDIS_URL=redis://localhost:6379/0
OPENSEARCH_HOST=opensearch
TIKA_URL=http://tika:9998
JWT_SECRET=your-dev-secret
CORS_ORIGINS=http://localhost:8010,http://localhost:3000
```

### Production Environment (EKS)

```env
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2
S3_BUCKET=vericase-docs
REDIS_URL=rediss://master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com:6379/0
BEDROCK_KB_ID=ACKHIYIHPK
BEDROCK_DS_ID=D9BX79MBSG
USE_TEXTRACT=true
ADMIN_EMAIL=admin@vericase.com
# Secrets from AWS Secrets Manager or k8s secrets
DATABASE_URL=<from-secrets>
JWT_SECRET=<from-secrets>
AG_GRID_LICENSE_KEY=<from-secrets>
```

---

## Local Development

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for frontend development outside container)
- Python 3.11+ (for API development outside container)

### Starting the Stack

```bash
cd vericase

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop services
docker-compose down
```

### Access Points

| Service | URL |
|---------|-----|
| API | http://localhost:8010 |
| API Docs | http://localhost:8010/docs |
| Frontend | http://localhost:3000 |
| MinIO Console | http://localhost:9001 |
| OpenSearch | http://localhost:9200 |
| Flower (Celery UI) | http://localhost:5555 |

### Frontend Development

```bash
cd vericase/frontend
npm install
npm run dev
```

### API Development

```bash
cd vericase/api
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```

---

## Production Deployment

### EC2 Deployment

```bash
# SSH into EC2
ssh -i "VeriCase-Safe.pem" ec2-user@18.175.232.87

# Pull latest images and restart
cd vericase
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d

# Check status
docker-compose -f docker-compose.prod.yml ps
docker-compose -f docker-compose.prod.yml logs -f api
```

### Using the Deploy Script

```bash
# Local deployment
./vericase/ops/deploy.sh local

# EC2 deployment
./vericase/ops/deploy.sh ec2

# EKS deployment
./vericase/ops/deploy.sh eks
```

---

## Kubernetes (EKS)

### Cluster Information

- **Cluster Name**: `vericase-cluster`
- **Region**: `eu-west-2`
- **Namespace**: `vericase`

### Deployments

| Deployment | Replicas | Scaling |
|------------|----------|---------|
| vericase-api | 3 | HPA: 3-10 pods |
| vericase-worker | 2 | HPA: 2-6 pods |
| tika | 1 | Fixed |

### Common Commands

```bash
# Configure kubectl
aws eks update-kubeconfig --name vericase-cluster --region eu-west-2

# View deployments
kubectl get deployments -n vericase

# View pods
kubectl get pods -n vericase

# View logs
kubectl logs -f deployment/vericase-api -n vericase

# Apply changes
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# Restart deployment
kubectl rollout restart deployment/vericase-api -n vericase

# Check rollout status
kubectl rollout status deployment/vericase-api -n vericase

# Scale deployment
kubectl scale deployment/vericase-api --replicas=5 -n vericase
```

### Ingress & Domains

The ALB Ingress serves these domains:
- `veri-case.com`
- `www.veri-case.com`
- `api.veri-case.com`

SSL certificate is managed via AWS ACM.

---

## External Services & AWS Resources

### AWS Resources Summary

| Resource | Identifier | Region |
|----------|------------|--------|
| **Account ID** | 526015377510 | - |
| **EC2 Instance** | 18.175.232.87 | eu-west-2 |
| **EKS Cluster** | vericase-cluster | eu-west-2 |
| **S3 Bucket** | vericase-docs | eu-west-2 |
| **RDS Database** | database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com | eu-west-2 |
| **ElastiCache** | master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com | eu-west-2 |
| **ACM Certificate** | fa1c323e-4062-4480-9234-b0c7476a23d0 | eu-west-2 |
| **IAM Role (IRSA)** | vericase-eks-pod-role | - |

### External Service Dependencies

| Service | Purpose | Local Alternative |
|---------|---------|-------------------|
| AWS S3 | File storage | MinIO |
| AWS ElastiCache | Redis cache/broker | Local Redis |
| AWS RDS | PostgreSQL database | Local PostgreSQL |
| AWS Bedrock | AI Knowledge Base | - |
| AWS Textract | Document text extraction | Apache Tika |
| AWS Secrets Manager | Credential storage | .env file |

---

## Health Checks

### Container Health Endpoints

| Service | Endpoint | Interval |
|---------|----------|----------|
| API | `GET /health` | 30s |
| PostgreSQL | `pg_isready` | 10s |
| Redis | `redis-cli ping` | 10s |
| OpenSearch | `GET /_cluster/health` | 30s |
| MinIO | `GET /minio/health/live` | 30s |
| Tika | `GET /tika` | 10s |

### Kubernetes Probes

Both liveness and readiness probes are configured in `k8s-deployment.yaml`:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8010
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /health
    port: 8010
  initialDelaySeconds: 5
  periodSeconds: 5
```

---

## Troubleshooting

### Running Diagnostics

```bash
# Linux/Mac
./vericase/ops/diagnose.sh

# Windows
./vericase/ops/diagnose.ps1

# SSL diagnostics
./vericase/ops/diagnose-ssl.ps1
```

### Common Issues

**API won't start:**
```bash
# Check logs
docker-compose logs api

# Verify database connection
docker-compose exec api python -c "from app.db import engine; engine.connect()"
```

**Database migrations failed:**
```bash
# Run migrations manually
docker-compose exec api alembic upgrade head

# Reset database (caution: destroys data)
./vericase/ops/reset-db.sh
```

**Worker not processing tasks:**
```bash
# Check worker logs
docker-compose logs worker

# Check Redis connectivity
docker-compose exec worker redis-cli -h redis ping

# Check Flower for task status
# Open http://localhost:5555
```

**EKS deployment issues:**
```bash
# Check pod status
kubectl get pods -n vericase

# Describe failing pod
kubectl describe pod <pod-name> -n vericase

# Check events
kubectl get events -n vericase --sort-by='.lastTimestamp'
```

### Useful Debug Commands

```bash
# Enter API container
docker-compose exec api bash

# Enter worker container
docker-compose exec worker bash

# Check database
docker-compose exec postgres psql -U vericase -d vericase

# Check Redis
docker-compose exec redis redis-cli

# View MinIO buckets
docker-compose exec minio mc ls local
```

---

## Quick Reference

### Start Local Environment
```bash
cd vericase && docker-compose up -d
```

### Deploy to EKS
```bash
git push origin main  # Triggers automatic deployment
```

### Manual EKS Deploy
```bash
kubectl apply -f vericase/k8s/ && kubectl rollout restart deployment/vericase-api -n vericase
```

### Check Production Status
```bash
kubectl get pods -n vericase
kubectl logs -f deployment/vericase-api -n vericase
```

---

## Additional Documentation

- `.github/DEPLOYMENT.md` – GitHub secrets and CI/CD setup
- `vericase/ops/README.md` – Operations scripts documentation
- `vericase/docs/deployment/DEPLOYMENT.md` – Detailed deployment guide

---

*Last updated: December 2024*
