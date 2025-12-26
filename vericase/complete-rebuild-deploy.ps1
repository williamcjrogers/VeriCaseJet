# VeriCase Complete Rebuild & Deploy to EKS
# Runs entirely from VS Code - no GitHub required

param(
    [switch]$SkipDocker,
    [switch]$SkipECR,
    [switch]$SkipEKS,
    [switch]$CleanDB
)

$ErrorActionPreference = "Stop"

# Ensure script always runs from the vericase/ directory so relative paths (api/Dockerfile, worker_app/Dockerfile,
# docker-compose.yml) resolve correctly when invoked from repo root.
Push-Location $PSScriptRoot

$AWS_ACCOUNT_ID = "526015377510"
$AWS_REGION = "eu-west-2"
$ECR_REGISTRY = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
$IMAGE_NAME = "vericase-api"
$WORKER_IMAGE_NAME = "vericase-worker"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "VeriCase Complete Rebuild & Deploy" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Clean up local Docker
if (-not $SkipDocker) {
    Write-Host "[1/6] Cleaning Local Docker Environment" -ForegroundColor Cyan
    Write-Host "=======================================" -ForegroundColor Cyan
    
    Write-Host "`n  Stopping all VeriCase containers..." -ForegroundColor Yellow
    docker compose down --remove-orphans
    
    Write-Host "  Removing old images..." -ForegroundColor Yellow
    docker image rm vericase-api -f 2>$null
    docker image rm vericase-worker -f 2>$null
    docker image rm wcjrogers/vericase-api -f 2>$null
    docker image rm wcjrogers/vericase-worker -f 2>$null
    
    if ($CleanDB) {
        Write-Host "  Removing volumes (clean database)..." -ForegroundColor Red
        docker volume rm vericase_pg_data -f 2>$null
        docker volume rm vericase_minio_data -f 2>$null
        docker volume rm vericase_os_data -f 2>$null
    }
    
    Write-Host "  Pruning Docker system..." -ForegroundColor Yellow
    docker system prune -f
    
    Write-Host "`n✅ Docker cleanup complete`n" -ForegroundColor Green
} else {
    Write-Host "[1/6] Skipping Docker cleanup`n" -ForegroundColor Gray
}

# Step 2: Rebuild Docker images
if (-not $SkipDocker) {
    Write-Host "[2/6] Building Fresh Docker Images" -ForegroundColor Cyan
    Write-Host "===================================" -ForegroundColor Cyan
    
    Write-Host "`n  Building API image..." -ForegroundColor Yellow
    docker build -t vericase-api:latest -f api/Dockerfile .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ API build failed!" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "`n  Building Worker image..." -ForegroundColor Yellow
    docker build -t vericase-worker:latest -f worker_app/Dockerfile .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Worker build failed!" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "`n✅ Docker images built successfully`n" -ForegroundColor Green
    
    # Step 3: Start local containers for testing
    Write-Host "[3/6] Starting Local Test Environment" -ForegroundColor Cyan
    Write-Host "======================================" -ForegroundColor Cyan
    
    Write-Host "`n  Starting containers..." -ForegroundColor Yellow
    docker compose up -d --build
    
    Write-Host "`n  Waiting for API to be ready..." -ForegroundColor Yellow
    $maxAttempts = 30
    $attempt = 0
    $apiReady = $false
    
    while ($attempt -lt $maxAttempts -and -not $apiReady) {
        $attempt++
        Write-Host "    Attempt $attempt/$maxAttempts..." -NoNewline
        
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $apiReady = $true
                Write-Host " ✅ Ready!" -ForegroundColor Green
            }
        } catch {
            Write-Host " ⏳ Waiting..." -ForegroundColor Yellow
            Start-Sleep -Seconds 2
        }
    }
    
    if (-not $apiReady) {
        Write-Host "`n⚠️  API did not become ready in time. Check logs:" -ForegroundColor Yellow
        Write-Host "    docker logs vericase-api-1 --tail 50" -ForegroundColor Gray
        Write-Host "`nContinuing anyway...`n" -ForegroundColor Yellow
    } else {
        Write-Host "`n✅ Local environment running at http://localhost:8010`n" -ForegroundColor Green
    }
} else {
    Write-Host "[2/6] Skipping Docker build`n" -ForegroundColor Gray
    Write-Host "[3/6] Skipping local test`n" -ForegroundColor Gray
}

# Step 4: Tag and push to ECR
if (-not $SkipECR) {
    Write-Host "[4/6] Pushing Images to AWS ECR" -ForegroundColor Cyan
    Write-Host "================================" -ForegroundColor Cyan
    
    Write-Host "`n  Logging into ECR..." -ForegroundColor Yellow
    aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ ECR login failed!" -ForegroundColor Red
        exit 1
    }
    
    # Ensure ECR repositories exist
    Write-Host "`n  Checking ECR repositories..." -ForegroundColor Yellow
    
    $apiRepoExists = aws ecr describe-repositories --repository-names $IMAGE_NAME --region $AWS_REGION 2>$null
    if (-not $apiRepoExists) {
        Write-Host "    Creating API repository..." -ForegroundColor Yellow
        aws ecr create-repository --repository-name $IMAGE_NAME --region $AWS_REGION | Out-Null
    }
    
    $workerRepoExists = aws ecr describe-repositories --repository-names $WORKER_IMAGE_NAME --region $AWS_REGION 2>$null
    if (-not $workerRepoExists) {
        Write-Host "    Creating Worker repository..." -ForegroundColor Yellow
        aws ecr create-repository --repository-name $WORKER_IMAGE_NAME --region $AWS_REGION | Out-Null
    }
    
    # Tag images
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    
    Write-Host "`n  Tagging API image..." -ForegroundColor Yellow
    docker tag vericase-api:latest "$ECR_REGISTRY/${IMAGE_NAME}:latest"
    docker tag vericase-api:latest "$ECR_REGISTRY/${IMAGE_NAME}:$timestamp"
    
    Write-Host "  Tagging Worker image..." -ForegroundColor Yellow
    docker tag vericase-worker:latest "$ECR_REGISTRY/${WORKER_IMAGE_NAME}:latest"
    docker tag vericase-worker:latest "$ECR_REGISTRY/${WORKER_IMAGE_NAME}:$timestamp"
    
    # Push images
    Write-Host "`n  Pushing API image..." -ForegroundColor Yellow
    docker push "$ECR_REGISTRY/${IMAGE_NAME}:latest"
    docker push "$ECR_REGISTRY/${IMAGE_NAME}:$timestamp"
    
    Write-Host "`n  Pushing Worker image..." -ForegroundColor Yellow
    docker push "$ECR_REGISTRY/${WORKER_IMAGE_NAME}:latest"
    docker push "$ECR_REGISTRY/${WORKER_IMAGE_NAME}:$timestamp"
    
    Write-Host "`n✅ Images pushed to ECR`n" -ForegroundColor Green
    Write-Host "  API: $ECR_REGISTRY/${IMAGE_NAME}:latest" -ForegroundColor Gray
    Write-Host "  API: $ECR_REGISTRY/${IMAGE_NAME}:$timestamp" -ForegroundColor Gray
    Write-Host "  Worker: $ECR_REGISTRY/${WORKER_IMAGE_NAME}:latest" -ForegroundColor Gray
    Write-Host "  Worker: $ECR_REGISTRY/${WORKER_IMAGE_NAME}:$timestamp`n" -ForegroundColor Gray
} else {
    Write-Host "[4/6] Skipping ECR push`n" -ForegroundColor Gray
}

# Step 5: Update Kubernetes deployment
if (-not $SkipEKS) {
    Write-Host "[5/6] Updating Kubernetes Deployment" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
    
    # Check kubectl connection
    Write-Host "`n  Checking EKS connection..." -ForegroundColor Yellow
    $eksCheck = kubectl get nodes 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Cannot connect to EKS cluster!" -ForegroundColor Red
        Write-Host "   Run: aws eks update-kubeconfig --name vericase-cluster --region $AWS_REGION" -ForegroundColor Yellow
        exit 1
    }
    
    # Get new image digest
    Write-Host "`n  Getting new image digest..." -ForegroundColor Yellow
    $imageDetails = aws ecr describe-images --repository-name $IMAGE_NAME --region $AWS_REGION --query 'sort_by(imageDetails,& imagePushedAt)[-1].imageDigest' --output text
    $apiImageUri = "$ECR_REGISTRY/${IMAGE_NAME}@$imageDetails"
    
    $workerImageDetails = aws ecr describe-images --repository-name $WORKER_IMAGE_NAME --region $AWS_REGION --query 'sort_by(imageDetails,& imagePushedAt)[-1].imageDigest' --output text
    $workerImageUri = "$ECR_REGISTRY/${WORKER_IMAGE_NAME}@$workerImageDetails"
    
    Write-Host "  API Image: $apiImageUri" -ForegroundColor Gray
    Write-Host "  Worker Image: $workerImageUri" -ForegroundColor Gray
    
    # Update deployment
    Write-Host "`n  Updating API deployment..." -ForegroundColor Yellow
    kubectl set image deployment/vericase-api vericase-api=$apiImageUri -n vericase
    
    Write-Host "  Updating Worker deployment..." -ForegroundColor Yellow
    kubectl set image deployment/vericase-worker vericase-worker=$workerImageUri -n vericase
    
    # Wait for rollout
    Write-Host "`n  Waiting for API rollout..." -ForegroundColor Yellow
    kubectl rollout status deployment/vericase-api -n vericase --timeout=300s
    
    Write-Host "`n  Waiting for Worker rollout..." -ForegroundColor Yellow
    kubectl rollout status deployment/vericase-worker -n vericase --timeout=300s
    
    Write-Host "`n✅ Kubernetes deployment updated`n" -ForegroundColor Green
} else {
    Write-Host "[5/6] Skipping EKS deployment`n" -ForegroundColor Gray
}

# Step 6: Verify deployment
if (-not $SkipEKS) {
    Write-Host "[6/6] Verifying Deployment" -ForegroundColor Cyan
    Write-Host "===========================" -ForegroundColor Cyan
    
    Write-Host "`n  Checking pod status..." -ForegroundColor Yellow
    kubectl get pods -n vericase -l app=vericase-api
    
    Write-Host "`n  Checking worker status..." -ForegroundColor Yellow
    kubectl get pods -n vericase -l app=vericase-worker
    
    Write-Host "`n  Getting service endpoint..." -ForegroundColor Yellow
    $ingress = kubectl get ingress -n vericase -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}'
    
    if ($ingress) {
        Write-Host "`n✅ Deployment complete!`n" -ForegroundColor Green
        Write-Host "  URL: https://$ingress" -ForegroundColor Gray
        Write-Host "`n  Testing health endpoint..." -ForegroundColor Yellow
        
        try {
            $health = Invoke-WebRequest -Uri "http://$ingress/health" -UseBasicParsing -TimeoutSec 10
            Write-Host "  ✅ Health check passed!" -ForegroundColor Green
        } catch {
            Write-Host "  ⚠️  Health check failed (may need a moment to start)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "`n✅ Deployment updated, but ingress not found" -ForegroundColor Yellow
    }
} else {
    Write-Host "[6/6] Skipping verification`n" -ForegroundColor Gray
}

# Summary
Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "Deployment Summary" -ForegroundColor Yellow
Write-Host "================================================================" -ForegroundColor Cyan

if (-not $SkipDocker) {
    Write-Host "✅ Local Docker: Rebuilt and running at http://localhost:8010" -ForegroundColor Green
}

if (-not $SkipECR) {
    Write-Host "✅ ECR Images: Pushed with timestamp $timestamp" -ForegroundColor Green
}

if (-not $SkipEKS) {
    Write-Host "✅ EKS Deployment: Updated and rolled out" -ForegroundColor Green
    Write-Host "`nNext steps:" -ForegroundColor Yellow
    Write-Host "  1. Test login at your production URL" -ForegroundColor White
    Write-Host "  2. Create/fix admin account: kubectl exec -it -n vericase deployment/vericase-api -- python /code/create_new_admin.py" -ForegroundColor White
    Write-Host "  3. Check logs: kubectl logs -n vericase -l app=vericase-api --tail=50" -ForegroundColor White
}

Write-Host "`n================================================================`n" -ForegroundColor Cyan

Pop-Location
