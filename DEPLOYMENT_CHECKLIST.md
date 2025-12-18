# Deployment Checklist - December 18, 2025

## ✅ Completed Steps

1. **Code Changes Committed**: Commit `76b6ee8` with comprehensive AI and claims module updates
2. **Pushed to GitHub**: Successfully pushed to `origin/main`
3. **Unit Tests Passing**: 7/7 AI-related tests passing
4. **Docker Build**: In progress (verification step)

## 🚀 Next Steps to Deploy

### 1. Wait for GitHub Actions Build

The push to main triggered the GitHub Actions workflow:
- Check status: https://github.com/williamcjrogers/VeriCaseJet/actions
- Workflow: `.github/workflows/deploy-eks.yml`
- This builds and pushes Docker images to Docker Hub and GHCR

### 2. Connect to EKS Cluster

```bash
# List clusters
aws eks list-clusters --region eu-west-2

# Update kubeconfig (replace YOUR_CLUSTER_NAME)
aws eks update-kubeconfig --region eu-west-2 --name YOUR_CLUSTER_NAME

# Verify connection
kubectl get nodes
kubectl get pods -n vericase
```

### 3. Update Kubernetes Deployment

```bash
# Apply the updated deployment configuration
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# Verify configmap and secrets are current
kubectl get configmap -n vericase
kubectl get secrets -n vericase
```

### 4. Restart Pods (CRITICAL!)

```bash
# Restart API pods to load new code
kubectl rollout restart deployment/vericase-api -n vericase

# Restart worker pods
kubectl rollout restart deployment/vericase-worker -n vericase

# Wait for rollout to complete
kubectl rollout status deployment/vericase-api -n vericase
kubectl rollout status deployment/vericase-worker -n vericase
```

### 5. Verify Deployment

```bash
# Check pod status
kubectl get pods -n vericase -w

# Check logs for new features
kubectl logs -n vericase -l app=vericase-api --tail=100 | grep -i "claims\|contentious"

# Verify environment variables
kubectl exec -n vericase deployment/vericase-api -- env | grep ENABLE

# Get application URL
kubectl get ingress -n vericase
```

### 6. Test New Features

1. **Access UI**: Navigate to ingress URL
2. **Test Claims Module**:
   - Open Contentious Matters page
   - Create a new matter
   - Add heads of claim
   - Verify no 500 errors
3. **Test AI Features**:
   - Run AI chat with evidence context
   - Verify model fallback works
   - Check AI routing logs

### 7. Monitor for Issues

```bash
# Watch logs in real-time
kubectl logs -n vericase -l app=vericase-api -f

# Check for errors
kubectl logs -n vericase -l app=vericase-api --tail=500 | grep -i error

# Monitor pod health
kubectl get pods -n vericase -w
```

## 📋 Key Changes Deployed

### Claims Module (`vericase/api/app/claims_module.py`)
- ✅ GET `/api/claims/matters` - List contentious matters
- ✅ GET `/api/claims/matters/{id}` - Get single matter
- ✅ POST `/api/claims/matters` - Create matter
- ✅ PUT `/api/claims/matters/{id}` - Update matter
- ✅ DELETE `/api/claims/matters/{id}` - Delete with cascades
- ✅ POST `/api/claims/heads-of-claim` - Create claim
- ✅ Fixed scalar queries preventing 500 errors

### AI System Enhancements
- ✅ Context capping for evidence emails
- ✅ Model fallback system
- ✅ Cost-optimized routing
- ✅ Enhanced configuration guide

### Email Processing
- ✅ IPM message detection and hiding
- ✅ OpenSearch reindexing script
- ✅ Improved metadata handling

## 🔍 Rollback Plan

If issues occur after deployment:

```bash
# Get previous revision
kubectl rollout history deployment/vericase-api -n vericase

# Rollback to previous version
kubectl rollout undo deployment/vericase-api -n vericase

# Or rollback to specific revision
kubectl rollout undo deployment/vericase-api -n vericase --to-revision=N
```

## 📞 Support

If you encounter issues:
1. Check pod logs: `kubectl logs -n vericase -l app=vericase-api --tail=200`
2. Check pod events: `kubectl describe pod -n vericase [POD_NAME]`
3. Verify secrets: `kubectl get secrets -n vericase`
4. Check AWS resources: Services (RDS, OpenSearch, ElastiCache, S3)

## 🎯 Success Criteria

- [ ] All pods in Running state
- [ ] No errors in logs
- [ ] Contentious matters page loads
- [ ] Can create/edit/delete matters
- [ ] Can create heads of claim
- [ ] AI chat works with evidence context
- [ ] No 500 errors on linked items
- [ ] Application responds at ingress URL
