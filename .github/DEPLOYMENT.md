# VeriCase Deployment Guide

## Automated Deployments

VeriCase uses GitHub Actions for automated builds and deployments.

### Docker Image Registries

Images are automatically published to **two registries** for redundancy:

1. **Docker Hub**: `wcjrogers/vericase-api:latest`
2. **GitHub Container Registry**: `ghcr.io/williamcjrogers/vericase-api:latest`

### Workflows

#### 1. Multi-Registry Docker Build
**File**: `.github/workflows/docker-publish-multi.yml`

- **Trigger**: Push to `main` branch or manual dispatch
- **What it does**: Builds and pushes to both Docker Hub and GHCR
- **When to use**: For creating versioned releases

#### 2. Deploy to EKS
**File**: `.github/workflows/deploy-eks.yml`

- **Trigger**: Push to `main` affecting `vericase/` files
- **What it does**: Builds image -> Pushes to Docker Hub -> Deploys to AWS EKS
- **Deployments**: Automatically updates `vericase-cluster` in `eu-west-2`

## Required GitHub Secrets

Set these in your repository settings (`Settings` -> `Secrets and variables` -> `Actions`):

### Docker Hub
- `DOCKERHUB_USERNAME` - Your Docker Hub username
- `DOCKERHUB_TOKEN` - Docker Hub access token ([create here](https://hub.docker.com/settings/security))

### AWS (for EKS deployment)
- `AWS_ACCESS_KEY_ID` - AWS IAM access key
- `AWS_SECRET_ACCESS_KEY` - AWS IAM secret key

### GitHub Container Registry
- `GITHUB_TOKEN` - Automatically provided by GitHub Actions (no setup needed)

## Manual Deployment

### Building Locally

```bash
# Build the Docker image
cd vericase
docker build -f api/Dockerfile -t vericase-api:local .

# Test locally
docker-compose up -d
```

### Pushing to Docker Hub Manually

```bash
# Login
docker login

# Tag the image
docker tag vericase-api:local wcjrogers/vericase-api:latest

# Push
docker push wcjrogers/vericase-api:latest
```

## Deployment Environments

### Local Development
```bash
cd vericase
docker-compose up -d
```

### Production (AWS EKS)
Automatic via GitHub Actions on push to `main`

Or manually:
```bash
kubectl apply -f vericase/k8s/k8s-deployment.yaml -n vericase
kubectl apply -f vericase/k8s/k8s-ingress.yaml -n vericase
```

## Updating Running Containers

### Pull Latest Images

```bash
# From Docker Hub
docker pull wcjrogers/vericase-api:latest

# From GHCR
docker pull ghcr.io/williamcjrogers/vericase-api:latest
```

### Restart with New Images

```bash
cd vericase
docker-compose up -d --force-recreate api worker
```

### On EKS

```bash
kubectl rollout restart deployment/vericase-api -n vericase
kubectl rollout restart deployment/vericase-worker -n vericase
```

## Monitoring Deployments

- **GitHub Actions**: Check workflow status in the `Actions` tab
- **Docker Hub**: https://hub.docker.com/r/wcjrogers/vericase-api
- **GHCR**: https://github.com/williamcjrogers?tab=packages

## Troubleshooting

### Images Not Pulling

1. Check if image exists: `docker pull wcjrogers/vericase-api:latest`
2. Verify GitHub Actions succeeded
3. Try GHCR as fallback: `docker pull ghcr.io/williamcjrogers/vericase-api:latest`

### EKS Deployment Failing

```bash
# Check pod status
kubectl get pods -n vericase

# Check logs
kubectl logs -n vericase deployment/vericase-api

# Describe for events
kubectl describe pod -n vericase <pod-name>
```

### SSL/TLS Issues

Use the diagnostic script:
```powershell
cd vericase
.\ops\diagnose-ssl.ps1
```

## Image Tags

Images are tagged with:
- `latest` - Most recent main branch build
- `{sha}-{commit}` - Specific commit (e.g., `abc123-fix-bug`)
- `YYYYMMDD-HHmmss` - Build timestamp

Example:
```bash
docker pull wcjrogers/vericase-api:20241205-143022
```
