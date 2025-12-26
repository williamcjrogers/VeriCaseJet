# VeriCase Production Setup Documentation

**Last Updated:** December 19, 2025  
**Environment:** Production  
**Region:** eu-west-2 (London)  
**AWS Account:** 526015377510

---

## 📋 Table of Contents
- [Infrastructure Overview](#infrastructure-overview)
- [Kubernetes Cluster](#kubernetes-cluster)
- [AWS Resources](#aws-resources)
- [Application Configuration](#application-configuration)
- [Secrets & ConfigMaps](#secrets--configmaps)
- [Access URLs](#access-urls)
- [Deployment Details](#deployment-details)
- [Monitoring & Operations](#monitoring--operations)

---

## 🏗️ Infrastructure Overview

### Kubernetes Cluster (EKS)
- **Namespace:** `vericase`
- **Cluster Age:** 60 days
- **Total Pods:** 8 running
- **Services:** 5 active
- **Deployments:** 3 (API, Worker, Tika)

### Current Status ✅
```
✅ vericase-api:    2/2 pods Running (7c5f8664db)
✅ vericase-worker: 2/2 pods Running (65cf9cc6b9)
✅ tika:            1/1 pods Running
✅ pg-tunnel:       1/1 pods Running
```

---

## ☸️ Kubernetes Cluster

### Deployments

#### 1. VeriCase API
```yaml
Name: vericase-api
Replicas: 2/2 (Auto-scales 2-4 based on CPU/Memory)
Image: docker.io/wcjrogers/vericase-api@sha256:68785e213c0c565a9803844a3fcda2bb0b8ce20dd5e0cff297f0b264c32febc8
Resources:
  Requests: 2Gi memory, 500m CPU
  Limits: 6Gi memory, 2000m CPU
Health Checks:
  - Liveness: /health (180s initial, 30s period)
  - Readiness: /health (60s initial, 10s period)
```

#### 2. VeriCase Worker (Celery)
```yaml
Name: vericase-worker
Replicas: 2/2 (Auto-scales 2-6 based on CPU)
Image: docker.io/wcjrogers/vericase-api@sha256:68785e213c0c565a9803844a3fcda2bb0b8ce20dd5e0cff297f0b264c32febc8
Resources:
  Requests: 4Gi memory, 1000m CPU
  Limits: 12Gi memory, 3000m CPU
Queues: celery, pst_processing
Concurrency: 2 workers
```

#### 3. Apache Tika
```yaml
Name: tika
Replicas: 1/1
Service: tika-service
Port: 9998
Purpose: Document text extraction
```

### Services

| Service Name | Type | Cluster IP | Port | Age |
|--------------|------|------------|------|-----|
| vericase-api | ClusterIP | 10.100.114.231 | 80 | 14d |
| tika-service | ClusterIP | 10.100.208.242 | 9998 | 7d12h |
| postgres | ClusterIP | 10.100.147.243 | 5432 | 18d |

### Ingress Configuration

| Ingress | Hosts | Load Balancer | Age |
|---------|-------|---------------|-----|
| vericase-ingress | veri-case.com<br>www.veri-case.com<br>api.veri-case.com | k8s-vericase-vericase-831b8104f3-1782642699.eu-west-2.elb.amazonaws.com | 14d |

### HorizontalPodAutoscaler (HPA)

```yaml
API HPA:
  Min Replicas: 2
  Max Replicas: 4
  Targets: CPU 70%, Memory 80%
  Current: CPU 0%, Memory 9%

Worker HPA:
  Min Replicas: 2
  Max Replicas: 6
  Targets: CPU 70%
  Current: CPU 0%
```

### Pod Disruption Budgets (PDB)

- **API:** Minimum 2 pods available during disruptions
- **Worker:** Minimum 1 pod available during disruptions

---

## ☁️ AWS Resources

### IAM & Service Account
```
Service Account: vericase-api-sa
IAM Role: arn:aws:iam::526015377510:role/vericase-eks-pod-role
Purpose: Pod-level AWS service access via IRSA
```

### S3 Storage
```
Bucket Name: vericase-docs
Region: eu-west-2
Purpose: Document storage, PST files, evidence attachments
Access: Via IAM role (IRSA)
```

### ElastiCache Redis (Cluster Mode)
```
Endpoint: clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379
Mode: Cluster Mode Enabled
SSL/TLS: Disabled (internal VPC communication)
Purpose: Celery broker, result backend, application cache
```

### OpenSearch (Vector Search)
```
Endpoint: vpc-vericase-opensearch-sl2a3zd5dnrbt64bssyocnrofu.eu-west-2.es.amazonaws.com
Purpose: Email search, vector embeddings, full-text search
Access: Via VPC endpoint
```

### AWS Bedrock (AI/ML)
```
Region: eu-west-2
Knowledge Base ID: ACKHIYIHPK
Data Source ID: D9BX79MBSG
Model: anthropic.claude-3-sonnet-20240229-v1:0
Embedding Model: amazon.titan-embed-text-v1
Purpose: AI-powered document analysis, classification, insights
```

### AWS Textract
```
Region: eu-west-2
Purpose: OCR and document text extraction
Status: Enabled
```

### AWS Comprehend
```
Region: eu-west-2
Purpose: Natural language processing, entity extraction
Status: Enabled
```

### AWS Secrets Manager
```
Active Secrets:
  - vericase/ai-api-keys (AI service API keys)
```

### RDS PostgreSQL
```
Access: Via pg-tunnel pod in vericase namespace
Service: postgres (ClusterIP: 10.100.147.243:5432)
Purpose: Primary application database
```

---

## ⚙️ Application Configuration

### Environment Variables (Key Settings)

#### AWS Configuration
```bash
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2
AWS_DEFAULT_REGION=eu-west-2
```

#### Storage
```bash
S3_BUCKET=vericase-docs
S3_PST_BUCKET=vericase-docs
S3_REGION=eu-west-2
```

#### Redis/Celery
```bash
REDIS_URL=redis://clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0
CELERY_BROKER_URL=redis://clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0
CELERY_RESULT_BACKEND=redis://clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0
CELERY_BROKER_USE_SSL=false
CELERY_REDIS_BACKEND_USE_SSL=false
```

#### AI Services (All Enabled)
```bash
# Bedrock
BEDROCK_ENABLED=true
BEDROCK_KB_ID=ACKHIYIHPK
BEDROCK_DS_ID=D9BX79MBSG
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v1
BEDROCK_REGION=eu-west-2

# Feature Flags
USE_TEXTRACT=true
USE_COMPREHEND=true
USE_KNOWLEDGE_BASE=true
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
MULTI_VECTOR_ENABLED=true

# AI Configuration
AI_DEFAULT_MODEL=gemini
AI_WEB_ACCESS_ENABLED=true
AI_TASK_COMPLEXITY_DEFAULT=advanced
EMBEDDING_PROVIDER=bedrock
```

#### Admin Account
```bash
ADMIN_EMAIL=admin@vericase.com
ADMIN_PASSWORD=<from vericase-secrets>
```

---

## 🔐 Secrets & ConfigMaps

### Kubernetes Secrets

#### vericase-secrets (4 keys)
```
Keys:
  - DATABASE_URL (PostgreSQL connection string)
  - JWT_SECRET (Application JWT signing key)
  - ADMIN_PASSWORD (Admin account password)
  - AG_GRID_LICENSE_KEY (AG Grid Enterprise license)
```

#### vericase-db (1 key)
```
Purpose: Database credentials
Age: 18 days
```

#### vericase-tls-2vdp7 (1 key)
```
Purpose: TLS certificates for HTTPS
Age: 14 days
```

### ConfigMaps

#### vericase-config (21 keys)
```yaml
Data includes:
  - REDIS_URL
  - OPENSEARCH_HOST
  - AWS service endpoints
  - Application configuration
Age: 60 days
```

---

## 🌐 Access URLs

### Primary Domain
```
Main Application: http://veri-case.com
WWW Redirect: http://www.veri-case.com
API Endpoint: http://api.veri-case.com
```

### Load Balancer
```
ELB URL: k8s-vericase-vericase-831b8104f3-1782642699.eu-west-2.elb.amazonaws.com
Region: eu-west-2
Type: Application Load Balancer
```

### Health Check
```bash
# API Health Endpoint
curl http://k8s-vericase-vericase-831b8104f3-1782642699.eu-west-2.elb.amazonaws.com/health

# Expected Response: 200 OK
```

---

## 🚀 Deployment Details

### Docker Images

#### Current Production Image (Stable)
```
Registry: docker.io/wcjrogers
Repository: vericase-api
Digest: sha256:68785e213c0c565a9803844a3fcda2bb0b8ce20dd5e0cff297f0b264c32febc8
Pull Policy: Always
Status: Stable ✅
Used By: API & Worker pods
```

#### Previous Image (Broken - Do Not Use)
```
Digest: sha256:f1f33728177a26295dd3b84579514831ab8b954eb825bc7f469420429728f5ce
Status: ❌ BROKEN - ModuleNotFoundError
Issue: Missing app.correspondence.routes module
Action: Rolled back to stable version
```

### Deployment History

| Date | Action | Image Digest | Status |
|------|--------|--------------|--------|
| Dec 19, 2025 | Updated manifest (Redis endpoints) | 68785e213c0c | ✅ Stable |
| Dec 19, 2025 | Rollback from broken image | 68785e213c0c | ✅ Success |
| Dec 19, 2025 | Failed deployment attempt | f1f33728177a | ❌ Failed |

### Kubernetes Manifest File
```
Location: vericase/k8s/k8s-deployment.yaml
Last Updated: Dec 19, 2025 (Commit: dd0a9d4)
Status: Synced with production cluster ✅
```

---

## 📊 Monitoring & Operations

### kubectl Quick Commands

```bash
# Check pod status
kubectl get pods -n vericase

# View API logs
kubectl logs -n vericase -l app=vericase-api --tail=100

# View Worker logs
kubectl logs -n vericase -l app=vericase-worker --tail=100

# Check HPA status
kubectl get hpa -n vericase

# Describe API deployment
kubectl describe deployment vericase-api -n vericase

# Port forward to API (for local testing)
kubectl port-forward -n vericase svc/vericase-api 8000:80

# Execute command in API pod
kubectl exec -it -n vericase deployment/vericase-api -- /bin/bash

# View recent events
kubectl get events -n vericase --sort-by='.lastTimestamp'
```

### Common Operational Tasks

#### 1. Update Deployment
```bash
# Apply updated manifest
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# Watch rollout status
kubectl rollout status deployment/vericase-api -n vericase
kubectl rollout status deployment/vericase-worker -n vericase
```

#### 2. Rollback Deployment
```bash
# Rollback API to previous version
kubectl rollout undo deployment/vericase-api -n vericase

# Rollback Worker to previous version
kubectl rollout undo deployment/vericase-worker -n vericase

# Check rollout history
kubectl rollout history deployment/vericase-api -n vericase
```

#### 3. Scale Deployments
```bash
# Manually scale API
kubectl scale deployment/vericase-api -n vericase --replicas=3

# Manually scale Workers
kubectl scale deployment/vericase-worker -n vericase --replicas=4

# Note: HPA will override manual scaling based on metrics
```

#### 4. Restart Pods
```bash
# Restart API pods
kubectl rollout restart deployment/vericase-api -n vericase

# Restart Worker pods
kubectl rollout restart deployment/vericase-worker -n vericase
```

### AWS CLI Commands

```bash
# Check Redis cluster
aws elasticache describe-cache-clusters --cache-cluster-id vericase-redis --region eu-west-2

# List S3 bucket contents
aws s3 ls s3://vericase-docs/ --region eu-west-2

# Check Bedrock knowledge base
aws bedrock-agent get-knowledge-base --knowledge-base-id ACKHIYIHPK --region eu-west-2

# View Secrets Manager secret (metadata only)
aws secretsmanager describe-secret --secret-id vericase/ai-api-keys --region eu-west-2

# Check OpenSearch domain
aws opensearch describe-domain --domain-name vericase-opensearch --region eu-west-2
```

---

## 🔧 Troubleshooting

### Common Issues & Solutions

#### 1. Pods in CrashLoopBackOff
```bash
# Check pod logs
kubectl logs -n vericase <pod-name> --previous

# Common causes:
# - Redis connection failure (check REDIS_URL)
# - Database connection issues (check DATABASE_URL secret)
# - Missing Python modules (check Docker image)
# - AWS permissions (check IAM role)
```

#### 2. Health Check Failures
```bash
# Test health endpoint directly
kubectl exec -it -n vericase deployment/vericase-api -- curl localhost:8000/health

# Check readiness/liveness probe configuration
kubectl describe pod -n vericase <pod-name>
```

#### 3. Worker Queue Processing Issues
```bash
# Check worker logs for Celery errors
kubectl logs -n vericase -l app=vericase-worker --tail=200

# Verify Redis connectivity
kubectl exec -it -n vericase deployment/vericase-worker -- python -c "import redis; r=redis.from_url('redis://clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0'); print(r.ping())"
```

#### 4. Image Pull Issues
```bash
# Check image pull status
kubectl describe pod -n vericase <pod-name> | grep -A 10 Events

# Verify image exists
docker manifest inspect docker.io/wcjrogers/vericase-api@sha256:68785e213c0c565a9803844a3fcda2bb0b8ce20dd5e0cff297f0b264c32febc8
```

---

## 📝 Important Notes

### Security Considerations
1. **IAM Role:** All AWS service access uses IRSA (no access keys in containers)
2. **Secrets:** Sensitive data stored in Kubernetes secrets, not in deployment YAML
3. **Network:** Redis and OpenSearch only accessible within VPC
4. **TLS:** Production uses TLS certificates managed by cert-manager

### Cost Optimization
- HPA configured to scale down to minimum replicas during low usage
- Pod Disruption Budgets ensure availability during node maintenance
- ElastiCache cluster mode provides better cost/performance ratio

### Backup & DR
- **S3:** Versioning enabled on vericase-docs bucket
- **Database:** Regular automated backups via RDS
- **Configuration:** All manifests version-controlled in GitHub

---

## 📚 Related Documentation

- [Kubernetes Deployment File](vericase/k8s/k8s-deployment.yaml)
- [GitHub Repository](https://github.com/williamcjrogers/VeriCaseJet.git)
- [AWS IAM Role](https://console.aws.amazon.com/iam/home?region=eu-west-2#/roles/vericase-eks-pod-role)
- [S3 Bucket Console](https://s3.console.aws.amazon.com/s3/buckets/vericase-docs?region=eu-west-2)
- [ElastiCache Console](https://console.aws.amazon.com/elasticache/home?region=eu-west-2)
- [OpenSearch Console](https://eu-west-2.console.aws.amazon.com/aos/home?region=eu-west-2)
- [Bedrock Console](https://eu-west-2.console.aws.amazon.com/bedrock/home?region=eu-west-2)

---

## 🔄 Change Log

| Date | Change | Author | Commit |
|------|--------|--------|--------|
| 2025-12-19 | Updated Redis endpoints to cluster mode | System | dd0a9d4 |
| 2025-12-19 | Removed non-existent AWS_SECRET_NAME | System | dd0a9d4 |
| 2025-12-19 | Rolled back to stable image digest | System | - |

---

**Document Status:** Current as of December 19, 2025, 8:30 AM UTC  
**Maintained By:** VeriCase DevOps Team  
**Review Schedule:** Monthly or after major infrastructure changes
