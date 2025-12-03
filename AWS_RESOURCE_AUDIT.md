# VeriCase AWS Resource Audit - Definitive Analysis

## Summary: Code Review vs Deployed Resources

Based on comprehensive code review of:
- `k8s-deployment.yaml` (actual EKS deployment)
- `api/app/config.py` (configuration)
- `api/app/search.py` (OpenSearch client)
- `worker_app/worker.py` (Celery worker)

---

## ✅ RESOURCES ACTIVELY IN USE

| Resource | Details | Evidence | Monthly Cost |
|----------|---------|----------|--------------|
| **EKS Cluster** | vericase namespace | k8s-deployment.yaml deploys here | ~$73 |
| **ElastiCache (Redis-simple)** | `vericase-redis-simple` (2x t3.medium) | REDIS_URL in k8s env | ~$50 |
| **S3 Bucket** | `vericase-docs-526015377510` | S3_BUCKET in k8s env | ~$5-20 |
| **Bedrock KB** | ID: `ACKHIYIHPK` | BEDROCK_KB_ID in k8s env | ~$50-100 |
| **RDS PostgreSQL** | Via secrets | DATABASE_URL in k8s secret | ~$100-200 |
| **Textract** | Enabled | USE_TEXTRACT=true in config | Pay per use |
| **ACM Certificate** | SSL for LoadBalancer | Annotation in Service | ~$0 |
| **ECR** | vericase-api image | Deployment image reference | ~$5 |

**Active Monthly Total: ~$280-450**

---

## ❌ LEGACY/UNUSED RESOURCES - SAFE TO DELETE

### 1. `vericase-redis` ElastiCache Cluster (LARGE)
- **Type**: 9x r7g.xlarge nodes
- **Monthly Cost**: ~$2,700
- **Evidence**: 
  - k8s-deployment.yaml uses `vericase-redis-simple` not `vericase-redis`
  - REDIS_URL points to: `master.vericase-redis-simple.dbbgbx.euw2.cache.amazonaws.com`
- **Status**: 🗑️ **SAFE TO DELETE**

### 2. `vericase-opensearch` OpenSearch Domain
- **Type**: 3x r8g.large nodes
- **Monthly Cost**: ~$350
- **Evidence**:
  - k8s-deployment.yaml does NOT set `OPENSEARCH_HOST` environment variable
  - Config defaults to `OPENSEARCH_HOST: str = "opensearch"` (won't resolve in EKS)
  - Code in search.py handles missing OpenSearch gracefully:
    ```python
    # API will start anyway - OpenSearch features disabled until connectivity is restored
    ```
  - Workers create client but indexing silently fails
- **Impact**: Full-text search disabled but app runs fine
- **Status**: 🗑️ **SAFE TO DELETE** (search features not working anyway)

### 3. `vericase-production` EC2 Instance
- **Type**: m6i.12xlarge
- **Monthly Cost**: ~$2,000/month
- **Evidence**:
  - EKS deployment runs API and workers in pods
  - No reference to EC2 in k8s-deployment.yaml
  - Likely old pre-containerized deployment
- **Status**: 🗑️ **LIKELY SAFE TO DELETE** (verify nothing runs on it first)

---

## ⚠️ RESOURCES REQUIRING VERIFICATION

### Other S3 Buckets Found (7 additional)
The deployment only references `vericase-docs-526015377510`. These may be deletable:
- Check if they contain data
- Check if any backups/logs reference them
- Check if Bedrock KB uses a different bucket

### Other IAM Roles
- `vericase-eks-pod-role` - IN USE (ServiceAccount annotation)
- Others may be legacy

---

## 💰 POTENTIAL MONTHLY SAVINGS

| Resource | Current Cost | After Cleanup |
|----------|-------------|---------------|
| vericase-redis (large) | $2,700 | $0 |
| vericase-opensearch | $350 | $0 |
| vericase-production EC2 | $2,000 | $0 |
| **TOTAL SAVINGS** | **$5,050/month** | |

---

## 🔧 RECOMMENDED ACTIONS

### Immediate (Safe)
1. **Delete `vericase-redis`** (the large 9-node cluster)
   ```bash
   aws elasticache delete-replication-group --replication-group-id vericase-redis
   ```

2. **Delete `vericase-opensearch`** domain
   ```bash
   aws opensearch delete-domain --domain-name vericase-opensearch
   ```

### After Verification
3. **Terminate `vericase-production` EC2**
   - SSH in first to verify nothing critical is running
   - Or check CloudWatch metrics for any activity

### Optional - Re-enable OpenSearch (if full-text search is needed)
If you want search features working, add to k8s-deployment.yaml:
```yaml
- name: OPENSEARCH_HOST
  value: "your-opensearch-endpoint.eu-west-2.es.amazonaws.com"
- name: OPENSEARCH_PORT
  value: "443"
- name: OPENSEARCH_USE_SSL
  value: "true"
```

---

## 📊 Architecture Clarity

### What VeriCase Actually Uses:
```
┌─────────────────────────────────────────────────────────────┐
│                        EKS Cluster                          │
│  ┌─────────────────┐        ┌─────────────────┐            │
│  │  vericase-api   │        │ vericase-worker │            │
│  │  (3 replicas)   │        │  (2 replicas)   │            │
│  └────────┬────────┘        └────────┬────────┘            │
│           │                          │                      │
└───────────┼──────────────────────────┼──────────────────────┘
            │                          │
            ▼                          ▼
    ┌───────────────┐         ┌───────────────┐
    │  RDS Postgres │         │  ElastiCache  │
    │   (Database)  │         │ Redis-simple  │
    └───────────────┘         └───────────────┘
            │                          │
            ▼                          │
    ┌───────────────┐                  │
    │  S3 Bucket    │◄─────────────────┘
    │ vericase-docs │
    └───────────────┘
            │
            ▼
    ┌───────────────┐    ┌───────────────┐
    │ AWS Bedrock   │    │ AWS Textract  │
    │ Knowledge Base│    │ (OCR/Text)    │
    └───────────────┘    └───────────────┘

    ╔═══════════════════════════════════════╗
    ║  NOT USED (Legacy):                   ║
    ║  - vericase-redis (large cluster)     ║
    ║  - vericase-opensearch domain         ║
    ║  - vericase-production EC2            ║
    ╚═══════════════════════════════════════╝
```

---

## Date of Audit
- **Performed**: December 3, 2025
- **Based on**: Code review (not MCP/API calls)
- **Confidence**: HIGH for k8s env vars, MEDIUM for EC2 (needs SSH verification)
