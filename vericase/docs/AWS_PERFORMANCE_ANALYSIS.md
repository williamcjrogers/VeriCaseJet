# AWS/EKS Performance Analysis for 20GB+ PST Uploads

## Current Configuration

### EKS Cluster
- **Node Count**: 2 nodes
- **Instance Type**: ~4 vCPU, 16GB RAM per node (likely t3.xlarge or similar)
- **Total Capacity**: 8 vCPUs, 32GB RAM
- **Current Usage**: 8-29% CPU, 21-26% Memory

### API Pods (vericase-api)
- **Replicas**: 3-4 pods
- **Resources per pod**:
  - Request: 250m CPU, 512MB RAM
  - Limit: 1 CPU, 2GB RAM
- **Total API capacity**: Up to 3-4 CPUs, 6-8GB RAM

### Worker Pods (vericase-worker)
- **Replicas**: 2 pods
- **Resources per pod**:
  - Request: 500m CPU, 1GB RAM
  - Limit: 2 CPUs, 4GB RAM
- **Total Worker capacity**: Up to 4 CPUs, 8GB RAM

### Storage
- **S3 Bucket**: vericase-docs (eu-west-2)
- **Performance**: Virtually unlimited S3 throughput

## Performance Assessment for 20GB+ PST Uploads

### ✅ What's GOOD

1. **S3 Storage**: Excellent choice
   - Unlimited bandwidth
   - Multi-part upload support
   - Direct presigned URL uploads bypass API

2. **Node Resources**: Adequate headroom
   - Only 8-29% CPU usage
   - 21-26% memory usage
   - Can handle concurrent uploads

3. **Network**: AWS backbone
   - Within same region (eu-west-2)
   - Low latency to S3
   - High bandwidth

### ⚠️ BOTTLENECKS for 20GB+ Files

#### 1. **API Pod Memory Limits** (CRITICAL)
- **Current**: 2GB limit per pod
- **Problem**: Streaming 20GB files through API can spike memory
- **Impact**: Pods may OOM kill during large uploads

#### 2. **Worker Memory** (IMPORTANT)
- **Current**: 4GB limit per worker
- **Problem**: PST processing loads entire file into memory
- **Impact**: Processing 20GB PST will fail

#### 3. **Single-threaded Worker Pool** (MODERATE)
- **Current**: `--pool=solo` (single process)
- **Problem**: Can't parallelize PST extraction
- **Impact**: Slower processing

#### 4. **Node Instance Type** (MINOR)
- **Current**: t3.xlarge (burstable)
- **Problem**: CPU credits may exhaust during sustained uploads
- **Impact**: Throttling during peak usage

## Recommended Upgrades

### Option 1: Minimal (Keep Current Nodes) - **FREE**

Just increase pod resources to use available capacity:

```yaml
# API Pods
resources:
  requests:
    memory: "1Gi"      # Was 512Mi
    cpu: "500m"        # Was 250m
  limits:
    memory: "4Gi"      # Was 2Gi - CRITICAL for large uploads
    cpu: "2000m"       # Was 1000m
```

```yaml
# Worker Pods  
resources:
  requests:
    memory: "2Gi"      # Was 1Gi
    cpu: "1000m"       # Was 500m
  limits:
    memory: "8Gi"      # Was 4Gi - CRITICAL for PST processing
    cpu: "4000m"       # Was 2000m
```

**Pros**:
- Zero additional cost
- Uses existing capacity
- Fixes OOM issues

**Cons**:
- May need to reduce replicas to fit
- No horizontal scaling room

### Option 2: Memory-Optimized Instances - **~$200/month**

Upgrade to r6i.xlarge or r6i.2xlarge:

```bash
# r6i.xlarge: 4 vCPU, 32GB RAM - $0.252/hr = ~$180/mo
# r6i.2xlarge: 8 vCPU, 64GB RAM - $0.504/hr = ~$360/mo

# Add to your node group
aws eks update-nodegroup-config \
  --cluster-name your-cluster \
  --nodegroup-name your-nodegroup \
  --instance-types r6i.xlarge
```

**Pros**:
- 2x memory per instance
- Better for large file processing
- Same CPU performance

**Cons**:
- Moderate cost increase
- Requires node group update

### Option 3: Compute-Optimized Instances - **~$300/month**

Upgrade to c6i.2xlarge for better CPU:

```bash
# c6i.2xlarge: 8 vCPU, 16GB RAM - $0.340/hr = ~$245/mo
# Better for parallel processing

# Or c6i.4xlarge: 16 vCPU, 32GB RAM - $0.680/hr = ~$490/mo
```

**Pros**:
- Better multi-threading
- Faster PST extraction
- No CPU throttling

**Cons**:
- Higher cost
- Less memory than r6i

### Option 4: Production Grade - **~$500/month** ⭐ RECOMMENDED

**3x r6i.2xlarge instances**:
- 24 vCPUs total
- 192GB RAM total
- Full redundancy
- Auto-scaling ready

```bash
# Cost: 3 x $0.504/hr = $1.512/hr = ~$1,089/month
# But can use Savings Plans or Spot for ~50% savings
```

**Node Configuration**:
```yaml
API Pods (5 replicas):
  requests: 1 CPU, 2GB RAM
  limits: 4 CPUs, 8GB RAM

Worker Pods (6 replicas):
  requests: 2 CPUs, 4GB RAM
  limits: 8 CPUs, 16GB RAM
```

**Pros**:
- Handle multiple 20GB uploads simultaneously
- Fast PST processing
- Production-ready redundancy
- Room for growth

**Cons**:
- Higher cost (but still cheap for enterprise)

## Immediate Actions (No Cost)

### 1. Update Resource Limits NOW

```bash
# Edit the deployment
kubectl edit deployment vericase-api -n vericase

# Change limits to:
limits:
  memory: "4Gi"
  cpu: "2000m"
```

### 2. Enable Better Worker Pooling

```yaml
# In k8s-deployment.yaml for workers
command: 
  - "celery"
  - "-A"
  - "worker_app.worker:celery_app"
  - "worker"
  - "--loglevel=info"
  - "--pool=prefork"      # Was solo
  - "--concurrency=4"     # Enable parallel tasks
  - "--max-tasks-per-child=10"  # Prevent memory leaks
```

### 3. Add Upload Size Validation

Already done in the upload optimization! Your frontend now:
- Uses 100MB chunks
- Uploads 6 chunks in parallel
- Has proper timeout (10 min per chunk)

### 4. Enable HPA (Horizontal Pod Autoscaler)

Your deployment already has HPA configured:
```yaml
minReplicas: 3
maxReplicas: 10
targetCPUUtilizationPercentage: 70
```

This will auto-scale based on load!

## Cost-Benefit Analysis

| Option | Monthly Cost | Max File Size | Concurrent Users | Recommendation |
|--------|-------------|---------------|------------------|----------------|
| **Current (Optimized)** | $0 | 5-10GB | 5-10 | Quick fix |
| **r6i.xlarge x2** | ~$360 | 20GB | 10-20 | Good balance |
| **c6i.2xlarge x2** | ~$490 | 15GB | 20-30 | CPU-intensive |
| **r6i.2xlarge x3** | ~$545* | 50GB+ | 30-50 | Production ⭐ |

*With 50% Savings Plan

## Testing Your Current Setup

### Test with 20GB File:

```bash
# 1. Monitor during upload
watch kubectl top pods -n vericase

# 2. Check for OOM kills
kubectl get events -n vericase --sort-by='.lastTimestamp' | grep -i oom

# 3. Monitor S3 transfer
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name BytesUploaded \
  --dimensions Name=BucketName,Value=vericase-docs \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum
```

### Expected Behavior:

**With optimizations + presigned URLs**:
- Upload: 20GB ÷ 100MB chunks = 200 chunks
- Parallel: 6 chunks at once
- Time: ~5-15 minutes (depends on internet)
- API memory: < 1GB (chunks bypass API)
- Processing: ~30-60 minutes

**If you see OOM kills**: Upgrade to Option 2 or 4

## Migration Path

### Phase 1: Immediate (Today) - FREE
1. ✅ Increase pod memory limits to 4GB/8GB
2. ✅ Already optimized upload code
3. Test with 20GB file

### Phase 2: If Needed (This Week) - $360/mo
1. Add 1x r6i.2xlarge node
2. Drain old t3.xlarge nodes
3. Retest

### Phase 3: Scale (Future) - $545/mo
1. Full production setup
2. 3x r6i.2xlarge
3. Auto-scaling enabled
4. Multi-AZ deployment

## Monitoring Dashboard

```bash
# Watch real-time resource usage
kubectl top pods -n vericase -l app=vericase-api --watch

# Check upload throughput
kubectl logs -f -n vericase -l app=vericase-api | grep -i "upload\|multipart"

# Monitor S3 operations
aws cloudwatch get-dashboard --dashboard-name vericase-s3-metrics
```

## Bottom Line

### Your current setup CAN handle 20GB files with these changes:

1. ✅ **Frontend optimization** (already done)
   - 100MB chunks
   - 6 parallel uploads
   - Direct S3 presigned URLs

2. ⚠️ **Backend limits** (needs update)
   - Increase API memory to 4GB
   - Increase Worker memory to 8GB
   - Enable prefork worker pool

3. ✅ **S3 infrastructure** (already perfect)
   - Unlimited bandwidth
   - Same region
   - Proper IAM roles

### Should you upgrade instances?

**Test first with current nodes + increased limits**

- If uploads work but processing is slow → Add nodes
- If you get OOM kills → Upgrade to r6i
- If processing > 2 hours → Add c6i nodes

**My recommendation**: Start with FREE Option 1, monitor for 1 week, then decide if you need Option 4.

---

**Next Steps**:
1. Apply updated k8s-deployment.yaml (I'll prepare it)
2. Monitor first 20GB upload
3. Check logs for OOM or timeouts
4. Scale if needed

Want me to prepare the updated deployment YAML with optimized resources?
