# VeriCase PST Upload Failure - Forensic Root Cause Analysis

**Date:** December 3, 2025  
**Status:** ROOT CAUSE IDENTIFIED - FIX READY

---

## Executive Summary

The PST upload functionality has been failing because **production traffic is being routed to an outdated deployment that lacks critical environment variables**.

There are **TWO PARALLEL DEPLOYMENTS** in different Kubernetes namespaces:
- **`vericase` namespace (PRODUCTION)**: 43-day old deployment with ONLY 1-2 env vars
- **`default` namespace (UNUSED)**: 2-day old deployment with correct configuration (20 env vars)

Users access the `vericase` namespace through the production URL, but it lacks Redis/Celery configuration, causing workers to fail.

---

## Forensic Evidence

### 1. Dual LoadBalancer Discovery

| Namespace | LoadBalancer URL | Age | Ports | Status |
|-----------|------------------|-----|-------|--------|
| `vericase` | `af2f6cb519c4f4d4d94e1633e3c91f1c-509256539.eu-west-2.elb.amazonaws.com` | 43d | 80 | **PRODUCTION URL** |
| `default` | `a24d34bb36b0d4a14a343ce0691ae03b-896293173.eu-west-2.elb.amazonaws.com` | 2d9h | 80, 443 | Unused |

**The production URL used in PST_UPLOAD_FIXES_COMPLETE.md points to the `vericase` namespace!**

---

### 2. Environment Variable Comparison

#### `vericase` Namespace (BROKEN):
```
vericase-api: DATABASE_URL, PORT            (2 vars)
vericase-worker: DATABASE_URL               (1 var)
```

#### `default` Namespace (CORRECT):
```
vericase-api: USE_AWS_SERVICES, AWS_REGION, AWS_DEFAULT_REGION, AWS_S3_REGION_NAME,
              S3_BUCKET, S3_PST_BUCKET, S3_REGION, MINIO_BUCKET, MINIO_ENDPOINT,
              REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND,
              CELERY_BROKER_USE_SSL, CELERY_REDIS_BACKEND_USE_SSL,
              BEDROCK_KB_ID, BEDROCK_DS_ID, CORS_ORIGINS, AWS_SECRET_NAME,
              DATABASE_URL, JWT_SECRET                               (20 vars)
```

**Missing from `vericase` namespace:**
- ❌ REDIS_URL
- ❌ CELERY_BROKER_URL  
- ❌ CELERY_RESULT_BACKEND
- ❌ CELERY_BROKER_USE_SSL
- ❌ CELERY_REDIS_BACKEND_USE_SSL
- ❌ USE_AWS_SERVICES
- ❌ AWS_REGION
- ❌ S3_BUCKET, S3_PST_BUCKET
- ❌ BEDROCK_KB_ID, BEDROCK_DS_ID
- ...and more

---

### 3. Worker Failure Chain

```
Worker starts → No CELERY_BROKER_URL env var → Uses hardcoded default
                                              ↓
                              Defaults to: redis://clustercfg.vericase-redis...
                                              ↓
                              ElastiCache requires TLS (TransitEncryption: true)
                                              ↓
                              Connection timeout: "Cannot connect to redis://"
                                              ↓
                              Worker crashes → 29+ restarts
```

---

### 4. Why Previous Fixes Failed

The k8s-deployment.yaml file was correctly updated with:
- `rediss://` URLs (SSL)
- `ssl_cert_reqs=required` parameter
- Security group rule for EKS → Redis

**BUT** these updates deployed to `default` namespace, NOT `vericase` namespace!

The GitHub Actions workflow likely:
1. Applied k8s-deployment.yaml to `default` namespace (no namespace specified = default)
2. `vericase` namespace deployments remained untouched
3. Production traffic continued through `vericase` namespace → still broken

---

## The Fix

### Option A: Update `vericase` Namespace (RECOMMENDED)
Apply the correct configuration to the existing `vericase` namespace deployments.

**Pros:**
- Production URL remains unchanged
- No user disruption
- No DNS/URL changes needed

**Cons:**
- Need to maintain awareness of two namespaces

### Option B: Consolidate to `default` Namespace
Delete `vericase` namespace, update all URLs to point to `default` namespace.

**Pros:**
- Single deployment to maintain
- Cleaner architecture

**Cons:**
- URL change breaks existing links/bookmarks
- Requires communication with users

---

## Recommended Action

**Implement Option A:**

1. Apply the corrected Kubernetes manifest to `vericase` namespace:
   ```bash
   kubectl apply -f k8s-deployment-vericase-ns.yaml -n vericase
   ```

2. Verify pods restart with correct env vars:
   ```bash
   kubectl rollout status deployment/vericase-api -n vericase
   kubectl rollout status deployment/vericase-worker -n vericase
   ```

3. Test Redis connectivity from pod:
   ```bash
   kubectl exec -n vericase deployment/vericase-api -- python -c "import redis; r = redis.from_url('rediss://clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0?ssl_cert_reqs=required'); print('PING:', r.ping())"
   ```

4. Test PST upload end-to-end

---

## Rollback Plan

If the fix causes issues:

1. **Rollback deployment:**
   ```bash
   kubectl rollout undo deployment/vericase-api -n vericase
   kubectl rollout undo deployment/vericase-worker -n vericase
   ```

2. **Verify rollback:**
   ```bash
   kubectl rollout status deployment/vericase-api -n vericase
   ```

---

## Long-term Recommendations

1. **Consolidate namespaces**: Choose one namespace (`default` or `vericase`) and migrate everything there
2. **Update CI/CD**: Ensure GitHub Actions deploys to the correct namespace
3. **Add namespace to k8s-deployment.yaml**: Explicitly specify `namespace: vericase` or use a consistent deployment target
4. **Clean up unused resources**: Delete the redundant deployment in `default` namespace if consolidating to `vericase`

---

## Technical Details

### ElastiCache Configuration
- **Cluster ID:** vericase-redis
- **Endpoint:** clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379
- **TransitEncryption:** ENABLED (TLS required)
- **AtRestEncryption:** ENABLED

### Correct Redis URL Format
```
rediss://clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0?ssl_cert_reqs=required
```

Note:
- `rediss://` (with double 's') = SSL/TLS connection
- `ssl_cert_reqs=required` = validates server certificate

---

**END OF ANALYSIS**
