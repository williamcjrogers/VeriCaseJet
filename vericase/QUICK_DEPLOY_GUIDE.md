# 🚀 QUICK DEPLOY GUIDE - Push Everything Now!

## ✅ YES! You Can Deploy Everything Now

With SSH configured, you have **3 deployment options**:

1. **Build & Push Docker Image** (Updates everywhere)
2. **Deploy to EKS** (Production Kubernetes)
3. **Deploy to EC2** (Legacy single server)

---

## 🎯 OPTION 1: Build & Push New Docker Image (RECOMMENDED)

This builds your latest code and makes it available everywhere.

### Step 1: Build the Image Locally

```bash
cd c:\Users\William\Documents\Projects\main\vericase

# Build the Docker image with your latest code
docker build -t wcjrogers/vericase-api:latest -f api/Dockerfile .
```

### Step 2: Push to Docker Hub

```bash
# Login to Docker Hub (if not already logged in)
docker login

# Push the image
docker push wcjrogers/vericase-api:latest
```

### Step 3: Deploy to Production

```bash
# EKS will automatically pull the new image on restart
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase
```

**✅ DONE!** Your new code is now live in production.

---

## 🎯 OPTION 2: Deploy to EKS (Kubernetes Production)

This updates your EKS cluster with latest configuration.

### Quick Deploy (3 Commands)

```bash
# 1. Connect to EKS
aws eks update-kubeconfig --region eu-west-2 --name vericase-cluster

# 2. Apply your latest Kubernetes config
kubectl apply -f vericase/k8s/k8s-deployment.yaml

# 3. Restart pods to use new config
kubectl rollout restart deployment/vericase-api -n vericase && \
kubectl rollout restart deployment/vericase-worker -n vericase && \
kubectl rollout status deployment/vericase-api -n vericase
```

### Verify Deployment

```bash
# Check pods are running
kubectl get pods -n vericase

# Check environment variables are set
kubectl exec -n vericase deployment/vericase-api -- env | grep -E "ENABLE_AI|BEDROCK"

# Get your application URL
kubectl get ingress -n vericase -o wide

# Check logs
kubectl logs -n vericase -l app=vericase-api --tail=50
```

---

## 🎯 OPTION 3: Deploy to EC2 via SSH

This updates your EC2 instance directly via SSH.

### Using the Deploy Script

```bash
cd c:\Users\William\Documents\Projects\main\vericase

# Deploy to EC2 (pulls latest Docker image)
./ops/deploy.sh ec2
```

### Manual SSH Deploy

```bash
# SSH to EC2
ssh -i ~/.ssh/VeriCase-Safe.pem ec2-user@18.175.232.87

# On the EC2 instance:
cd ~/vericase
sudo docker-compose pull  # Pull latest images
sudo docker-compose down  # Stop services
sudo docker-compose up -d # Start with new images

# Check status
sudo docker-compose ps
sudo docker-compose logs -f api
```

### Access EC2 Application

```
http://18.175.232.87:8010
```

---

## 🔄 COMPLETE WORKFLOW: From Code Change to Production

### Full Stack Update (All Changes)

```bash
# 1. BUILD: Create new Docker image with your latest code
cd c:\Users\William\Documents\Projects\main\vericase
docker build -t wcjrogers/vericase-api:latest -f api/Dockerfile .

# 2. PUSH: Upload to Docker Hub
docker push wcjrogers/vericase-api:latest

# 3. DEPLOY TO EKS: Update production Kubernetes
aws eks update-kubeconfig --region eu-west-2 --name vericase-cluster
kubectl apply -f k8s/k8s-deployment.yaml
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase

# 4. DEPLOY TO EC2: Update legacy server (optional)
./ops/deploy.sh ec2

# 5. VERIFY: Check everything is running
kubectl get pods -n vericase
kubectl logs -n vericase -l app=vericase-api --tail=20
```

**Time: ~5-10 minutes from code to live!**

---

## 🚀 ONE-COMMAND DEPLOYMENT

Save this as a script for rapid deployment:

### Windows PowerShell: `deploy-all.ps1`

```powershell
# VeriCase Full Deployment Script
param(
    [switch]$SkipBuild,
    [switch]$EKSOnly,
    [switch]$EC2Only
)

Write-Host "🚀 VeriCase Deployment Starting..." -ForegroundColor Green

# Build and push Docker image
if (-not $SkipBuild) {
    Write-Host "📦 Building Docker image..." -ForegroundColor Cyan
    docker build -t wcjrogers/vericase-api:latest -f vericase/api/Dockerfile vericase/
    
    Write-Host "⬆️  Pushing to Docker Hub..." -ForegroundColor Cyan
    docker push wcjrogers/vericase-api:latest
}

# Deploy to EKS
if (-not $EC2Only) {
    Write-Host "☸️  Deploying to EKS..." -ForegroundColor Cyan
    aws eks update-kubeconfig --region eu-west-2 --name vericase-cluster
    kubectl apply -f vericase/k8s/k8s-deployment.yaml
    kubectl rollout restart deployment/vericase-api -n vericase
    kubectl rollout restart deployment/vericase-worker -n vericase
    kubectl rollout status deployment/vericase-api -n vericase --timeout=300s
}

# Deploy to EC2
if (-not $EKSOnly) {
    Write-Host "🖥️  Deploying to EC2..." -ForegroundColor Cyan
    & vericase/ops/deploy.sh ec2
}

Write-Host "✅ Deployment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Access your application:"
kubectl get ingress -n vericase -o wide
```

### Usage

```powershell
# Full deployment (build + EKS + EC2)
.\deploy-all.ps1

# Just EKS (skip build)
.\deploy-all.ps1 -SkipBuild -EKSOnly

# Just EC2 (skip build)
.\deploy-all.ps1 -SkipBuild -EC2Only
```

---

## 🛠️ QUICK OPERATIONS

### Update Environment Variables Only

```bash
# Edit the K8s deployment file
code vericase/k8s/k8s-deployment.yaml

# Apply changes
kubectl apply -f vericase/k8s/k8s-deployment.yaml
kubectl rollout restart deployment/vericase-api -n vericase
```

### Hot Reload Without Rebuilding

```bash
# Just restart with existing image
kubectl rollout restart deployment/vericase-api -n vericase
```

### Check What's Running

```bash
# EKS status
kubectl get all -n vericase

# EC2 status
ssh -i ~/.ssh/VeriCase-Safe.pem ec2-user@18.175.232.87 \
  "sudo docker-compose -f ~/vericase/docker-compose.prod.yml ps"
```

### View Logs

```bash
# EKS logs (live tail)
kubectl logs -n vericase -l app=vericase-api -f

# EC2 logs (via SSH)
ssh -i ~/.ssh/VeriCase-Safe.pem ec2-user@18.175.232.87 \
  "sudo docker-compose -f ~/vericase/docker-compose.prod.yml logs -f api"
```

---

## 🔍 TROUBLESHOOTING

### "Cannot connect to Docker daemon"

```bash
# Windows: Ensure Docker Desktop is running
# Or restart Docker service
```

### "kubectl: command not found"

```bash
# Install kubectl
az aks install-cli
# or
choco install kubernetes-cli
```

### "Access Denied" on AWS

```bash
# Check AWS credentials
aws sts get-caller-identity

# Should show: Account 526015377510
```

### "Image pull failed" in EKS

```bash
# Make sure you pushed the image
docker push wcjrogers/vericase-api:latest

# Make Docker Hub repo public or add imagePullSecrets
```

### "Old code still running"

```bash
# Force recreation of pods
kubectl delete pod -n vericase -l app=vericase-api
kubectl get pods -n vericase --watch
```

---

## 📋 DEPLOYMENT CHECKLIST

### Before Deploying

- [ ] Code changes committed to Git
- [ ] Tests passing locally
- [ ] Environment variables updated in k8s-deployment.yaml
- [ ] Docker Hub credentials configured
- [ ] AWS credentials configured
- [ ] kubectl connected to cluster

### During Deployment

- [ ] Build Docker image
- [ ] Push to Docker Hub
- [ ] Apply K8s manifests
- [ ] Restart deployments
- [ ] Wait for rollout completion
- [ ] Check pod status

### After Deployment

- [ ] Test application URL
- [ ] Check logs for errors
- [ ] Verify environment variables
- [ ] Test key features
- [ ] Monitor for 5-10 minutes

---

## 🎯 RECOMMENDED WORKFLOW

### For Small Changes (Config, Environment Variables)

```bash
# Just update K8s and restart
kubectl apply -f vericase/k8s/k8s-deployment.yaml
kubectl rollout restart deployment/vericase-api -n vericase
```

**Time: 1 minute**

### For Code Changes (New Features, Bug Fixes)

```bash
# Build, push, deploy
docker build -t wcjrogers/vericase-api:latest -f vericase/api/Dockerfile vericase/
docker push wcjrogers/vericase-api:latest
kubectl rollout restart deployment/vericase-api -n vericase
```

**Time: 5-10 minutes**

### For Major Updates (Breaking Changes, Migrations)

```bash
# Full deployment with database migrations
docker build -t wcjrogers/vericase-api:latest -f vericase/api/Dockerfile vericase/
docker push wcjrogers/vericase-api:latest

# Scale down to prevent conflicts
kubectl scale deployment/vericase-api -n vericase --replicas=0

# Run migrations
kubectl apply -f vericase/k8s/migration-job.yaml

# Scale back up
kubectl apply -f vericase/k8s/k8s-deployment.yaml
kubectl rollout status deployment/vericase-api -n vericase
```

**Time: 10-15 minutes**

---

## 📊 MONITORING YOUR DEPLOYMENT

### Real-time Status Dashboard

```bash
# Watch pods restart
kubectl get pods -n vericase --watch

# Watch deployment progress
kubectl rollout status deployment/vericase-api -n vericase

# Live log stream
kubectl logs -n vericase -l app=vericase-api -f --tail=100
```

### Health Checks

```bash
# Get application URL
APP_URL=$(kubectl get ingress -n vericase -o jsonpath='{.items[0].spec.rules[0].host}')

# Check health endpoint
curl https://$APP_URL/health

# Check API status
curl https://$APP_URL/api/health
```

---

## 🎉 YOU'RE READY TO DEPLOY!

With SSH configured and Docker available, you can now:

✅ **Build** - Create Docker images with your latest code
✅ **Push** - Upload images to Docker Hub
✅ **Deploy** - Update EKS and EC2 with one command
✅ **Monitor** - Watch logs and status in real-time
✅ **Rollback** - Quickly revert if needed

### Next Steps

1. **Test locally first**: `docker-compose up`
2. **Build and push**: `docker build` + `docker push`
3. **Deploy to EKS**: `kubectl apply` + `kubectl rollout restart`
4. **Verify**: Check logs and test the application
5. **Monitor**: Keep an eye on logs for 10 minutes

### Need Help?

- 📖 See `DEPLOY_NOW.md` for detailed EKS instructions
- 📖 See `ops/deploy.sh` for automated deployment scripts
- 📖 See `k8s/k8s-deployment.yaml` for Kubernetes configuration
- 📞 AWS Support: Check AWS Console for issues

---

**Happy Deploying! 🚀**
