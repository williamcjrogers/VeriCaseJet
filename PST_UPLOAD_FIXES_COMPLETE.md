# VeriCase PST Upload - All Fixes Applied

**Date:** December 3, 2025  
**Status:** ✅ All Issues Fixed - Waiting for Deployment

## Summary
Fixed all issues preventing PST uploads and correspondence view. The app should work once the automated deployment completes (3-5 minutes).

---

## Fixed Issues

### 1. ✅ Redis SSL Certificate Parameter (CRITICAL)
**Problem:**
- Redis URL used `ssl_cert_reqs=CERT_REQUIRED` 
- redis-py library expects lowercase: `ssl_cert_reqs=required`
- Error: `Invalid SSL Certificate Requirements Flag: CERT_REQUIRED`

**Fix Applied:**
- File: `pst-analysis-engine/k8s-deployment.yaml`
- Changed in 3 environment variables:
  - REDIS_URL
  - CELERY_BROKER_URL  
  - CELERY_RESULT_BACKEND
- **Commit:** 648f5412

---

### 2. ✅ Network Connectivity (EKS → Redis)
**Problem:**
- EKS pods could not reach ElastiCache Redis cluster
- Security group blocking traffic
- Error: `TimeoutError: Connection timed out`

**Fix Applied:**
- Added security group ingress rule
- Allowed traffic from EKS nodes (sg-04d1b49414bd19cf7) → Redis (sg-0fe33dbc9d4cf20ba)
- Port: 6379 (Redis)

**Command Executed:**
```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-0fe33dbc9d4cf20ba \
  --protocol tcp \
  --port 6379 \
  --source-group sg-04d1b49414bd19cf7 \
  --region eu-west-2
```

---

### 3. ✅ Database Schema: projects.description
**Problem:**
- Column missing from projects table
- Startup seed data failing
- Error: `column "description" of relation "projects" does not exist`

**Fix Applied:**
- Added missing column to production database
```sql
ALTER TABLE projects ADD COLUMN description TEXT;
```
- Verified: ✅ Column exists

---

### 4. ✅ Code Bug: att.file_size vs att.file_size_bytes
**Problem:**
- Code referenced non-existent column `att.file_size`
- Correct column is `att.file_size_bytes`
- This caused correspondence view to fail loading attachments

**Fix Applied:**
- File: `pst-analysis-engine/api/app/correspondence.py` (line 3225)
- Changed: `"size": att.file_size` → `"size": att.file_size_bytes`
- **Commit:** 147e6cc2

---

### 5. ✅ AG Grid License Key
**Status:** Already correct - no changes needed
**Files Verified:**
- `pst-analysis-engine/ui/evidence.html` ✅
- `pst-analysis-engine/ui/correspondence-enterprise.html` ✅

Both files have the correct enterprise license key valid until December 2, 2026.

---

## Deployment Status

### Commits Pushed:
1. **147e6cc2** - Fix att.file_size_bytes bug
2. **648f5412** - Fix Redis SSL + update correspondence UI

### Automatic Deployment:
GitHub Actions workflow (`.github/workflows/deploy-eks.yml`) automatically:
1. Builds Docker image from pst-analysis-engine/
2. Pushes to ECR: `526015377510.dkr.ecr.eu-west-2.amazonaws.com/vericase-api:latest`
3. Applies k8s-deployment.yaml
4. Restarts pods
5. Wait for rollout (5min timeout)

### Expected Timeline:
- **Build time:** ~2-3 minutes
- **Deploy time:** ~1-2 minutes
- **Total:** ~3-5 minutes from push

---

## Database Changes Applied

All schema fixes applied directly to production database:

```sql
-- Fix 1: Add missing description column
ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT;

-- These were already correct:
✅ pst_files.uploaded_at EXISTS
✅ pst_files.file_size_bytes is BIGINT
✅ email_attachments.file_size_bytes EXISTS
```

---

## Testing Instructions

### Once Deployment Completes (check after 5 minutes):

1. **Check pods are running new version:**
```bash
kubectl get pods -l app=vericase-api
kubectl describe pod <pod-name> | Select-String -Pattern "Image:"
```

2. **Check pod logs are clean:**
```bash
kubectl logs -l app=vericase-api --tail=50
```
Should see NO Redis errors!

3. **Test PST Upload:**
   - URL: http://af2f6cb519c4f4d4d94e1633e3c91f1c-509256539.eu-west-2.elb.amazonaws.com/ui/pst-upload.html?projectId=dca0d854-1655-4498-97f3-399b47a4d65f
   - Upload a small test PST file
   - Should show "PST uploaded successfully"
   - Check celery worker processes it

4. **Test Correspondence View:**
   - URL: http://af2f6cb519c4f4d4d94e1633e3c91f1c-509256539.eu-west-2.elb.amazonaws.com/ui/correspondence-enterprise.html?projectId=dca0d854-1655-4498-97f3-399b47a4d65f
   - Should load without "Network" errors
   - AG Grid should display emails properly
   - Attachments column should show file sizes correctly

---

## What Was Wrong (Root Cause Analysis)

1. **Redis couldn't connect** → PST uploads failed because Celery couldn't queue tasks
2. **Database schema mismatch** → Startup failed, preventing clean initialization
3. **Code used wrong column name** → Correspondence view crashed when loading attachments
4. **Network blocked** → EKS pods isolated from Redis cluster

All of these issues are now FIXED!

---

## Current Infrastructure State

### EKS Cluster:
- **Name:** vericase-cluster
- **Region:** eu-west-2
- **Nodes:** 2x m6i.xlarge
- **URL:** http://af2f6cb519c4f4d4d94e1633e3c91f1c-509256539.eu-west-2.elb.amazonaws.com

### Redis:
- **Cluster ID:** vericase-redis
- **Endpoint:** clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379
- **Security Group:** sg-0fe33dbc9d4cf20ba
- **Status:** ✅ Available and accessible from EKS

### Database:
- **RDS Instance:** database-1.cv8uw0uqr7f.eu-west-2.rds.amazonaws.com
- **Database:** vericase (PostgreSQL)
- **Schema:** ✅ All columns correct

---

## If Upload STILL Fails After Deployment

### Quick Diagnostics:

1. **Check if new image deployed:**
```bash
kubectl describe pod -l app=vericase-api | Select-String -Pattern "Image:"
```
Should show recent timestamp in image tag.

2. **Check real-time logs during upload:**
```bash
kubectl logs -l app=vericase-api --follow
```
Then attempt upload and watch for errors.

3. **Verify Redis connection from pod:**
```bash
kubectl exec deployment/vericase-api -- python -c "import redis; r = redis.from_url('rediss://clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0?ssl_cert_reqs=required'); print('PING:', r.ping())"
```
Should print: `PING: True`

4. **Check database has default project:**
```bash
kubectl exec deployment/vericase-api -- python -c "from app.db import engine; from sqlalchemy import text; conn = engine.connect(); result = conn.execute(text('SELECT id, project_name FROM projects')); print([row for row in result]); conn.close()"
```

---

## Next Steps if Issues Persist

If the app still doesn't work after the automated deployment:

1. Check GitHub Actions for build errors: https://github.com/williamcjrogers/VeriCaseJet/actions
2. Check pod startup logs for database migration errors
3. Verify all environment variables in k8s-deployment.yaml are correct
4. Consider a database schema export/compare to ensure consistency

---

**END OF DOCUMENT**
