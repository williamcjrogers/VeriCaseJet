# VeriCase Deployment Script (PowerShell)
# Usage: .\ops\deploy.ps1 [local|ec2|eks]

param(
    [Parameter(Position=0)]
    [ValidateSet("local", "ec2", "eks", "build", "status")]
    [string]$Command = "status",

    # Optional overrides (primarily for EKS)
    [string]$Namespace = "vericase",
    # Example: wcjrogers/vericase-api:latest OR wcjrogers/vericase-api@sha256:...
    [string]$Image = ""
)

$ErrorActionPreference = "Stop"

# Configuration
$AWS_ACCOUNT_ID = "526015377510"
$AWS_REGION = "eu-west-2"
$EC2_IP = "18.175.232.87"
$EKS_CLUSTER = "vericase-cluster"
$DOCKER_IMAGE = "wcjrogers/vericase-api:latest"
$SSH_KEY_PATH = "$env:USERPROFILE\.ssh\VeriCase-Safe.pem"

function Log-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Blue }
function Log-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Log-Warn { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Log-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Show-Usage {
    Write-Host ""
    Write-Host "VeriCase Deployment" -ForegroundColor Cyan
    Write-Host "==================="
    Write-Host ""
    Write-Host "Usage: .\ops\deploy.ps1 [command]"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  local     Deploy locally with docker-compose"
    Write-Host "  ec2       Deploy to EC2 instance ($EC2_IP)"
    Write-Host "  eks       Deploy to EKS cluster ($EKS_CLUSTER)"
    Write-Host "  build     Build and push Docker image"
    Write-Host "  status    Show deployment status"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Namespace   Kubernetes namespace (default: vericase)"
    Write-Host "  -Image       Override image for EKS deploy (tag or digest)"
    Write-Host ""
}

function Test-Prerequisites {
    Log-Info "Checking prerequisites..."

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Log-Error "Docker not found"
        exit 1
    }
    Log-Success "Docker installed"

    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
        Log-Warn "AWS CLI not found - EC2/EKS deploys will fail"
    } else {
        Log-Success "AWS CLI installed"
    }
}

function Test-EnvFile {
    if (-not (Test-Path ".env")) {
        Log-Error ".env file not found"
        Log-Info "Copy .env.example to .env and configure it"
        exit 1
    }
    Log-Success ".env file found"
}

function Wait-ServiceHealthy {
    param($ServiceName)

    $maxAttempts = 30
    $attempt = 1

    Write-Host -NoNewline "  Waiting for $ServiceName"
    while ($attempt -le $maxAttempts) {
        $status = docker-compose -f docker-compose.prod.yml ps 2>$null | Select-String "$ServiceName.*healthy"
        if ($status) {
            Write-Host " OK" -ForegroundColor Green
            return $true
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
        $attempt++
    }
    Write-Host " FAILED" -ForegroundColor Red
    return $false
}

function Deploy-Local {
    Log-Info "Deploying locally with docker-compose..."
    Test-EnvFile

    Log-Info "Building images..."
    docker-compose -f docker-compose.prod.yml build

    Log-Info "Starting infrastructure..."
    docker-compose -f docker-compose.prod.yml up -d postgres redis minio opensearch tika

    Log-Info "Waiting for services..."
    Wait-ServiceHealthy "postgres"
    Wait-ServiceHealthy "redis"

    Log-Info "Running migrations (Alembic)..."
    docker-compose -f docker-compose.prod.yml run --rm api alembic upgrade head

    Log-Info "Starting application..."
    docker-compose -f docker-compose.prod.yml up -d api worker

    Wait-ServiceHealthy "api"

    Log-Success "Local deployment complete!"
    Write-Host ""
    Write-Host "  API:        http://localhost:8010" -ForegroundColor White
    Write-Host "  MinIO:      http://localhost:9001" -ForegroundColor White
    Write-Host "  OpenSearch: http://localhost:9200" -ForegroundColor White
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  Logs:   docker-compose -f docker-compose.prod.yml logs -f api"
    Write-Host "  Stop:   docker-compose -f docker-compose.prod.yml down"
}

function Deploy-EC2 {
    Log-Info "Deploying to EC2 ($EC2_IP)..."

    # Check for SSH key
    $keyPath = if ($env:SSH_KEY_PATH) { $env:SSH_KEY_PATH } else { $SSH_KEY_PATH }

    if (-not (Test-Path $keyPath)) {
        Log-Error "SSH key not found: $keyPath"
        Log-Info "Set SSH_KEY_PATH environment variable or place key at default location"
        exit 1
    }

    Log-Info "Connecting to EC2..."

    $commands = @"
cd ~/vericase || exit 1
echo "Pulling latest images..."
sudo docker-compose pull
echo "Restarting services..."
sudo docker-compose down
sudo docker-compose up -d
echo "Checking status..."
sudo docker-compose ps
"@

    $knownHosts = "$env:USERPROFILE\.ssh\known_hosts"
    if (-not (Test-Path $knownHosts)) {
        Log-Warn "known_hosts not found: $knownHosts"
        Log-Info "Run: powershell -ExecutionPolicy Bypass -File .\\vericase\\ops\\setup-ssh.ps1"
        Log-Info "Then retry this deploy."
        exit 1
    }

    ssh -i "$keyPath" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$knownHosts" ec2-user@$EC2_IP $commands
    if ($LASTEXITCODE -ne 0) {
        Log-Error "SSH command failed (exit code $LASTEXITCODE)."
        Log-Info "If this is the first connection or the instance was rebuilt, prime known_hosts:"
        Log-Info "  powershell -ExecutionPolicy Bypass -File .\\vericase\\ops\\setup-ssh.ps1"
        exit $LASTEXITCODE
    }

    Log-Success "EC2 deployment complete!"
    Write-Host ""
    Write-Host "  API: http://$EC2_IP`:8010" -ForegroundColor White
    Write-Host "  Health: curl http://$EC2_IP`:8010/health" -ForegroundColor White
}

function Deploy-EKS {
    Log-Info "Deploying to EKS ($EKS_CLUSTER)..."

    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        Log-Error "kubectl not found"
        exit 1
    }

    Log-Info "Updating kubeconfig..."
    aws eks update-kubeconfig --region $AWS_REGION --name $EKS_CLUSTER

    Log-Info "Applying Kubernetes manifests..."
    kubectl apply -f k8s\k8s-deployment.yaml
    kubectl apply -f k8s\k8s-ingress.yaml

    if ($Image) {
        Log-Info "Setting deployment images to $Image in namespace '$Namespace'..."
        kubectl set image deployment/vericase-api vericase-api=$Image -n $Namespace
        kubectl set image deployment/vericase-worker vericase-worker=$Image -n $Namespace
    }

    Log-Info "Restarting deployment..."
    kubectl rollout restart deployment/vericase-api -n $Namespace
    kubectl rollout restart deployment/vericase-worker -n $Namespace

    Log-Info "Waiting for rollout..."
    kubectl rollout status deployment/vericase-api -n $Namespace --timeout=300s
    kubectl rollout status deployment/vericase-worker -n $Namespace --timeout=300s

    Log-Success "EKS deployment complete!"
    kubectl get pods -n $Namespace -l app=vericase-api
    kubectl get pods -n $Namespace -l app=vericase-worker
}

function Build-Push {
    Log-Info "Building and pushing Docker image..."

    docker build -t $DOCKER_IMAGE -f api/Dockerfile .
    docker push $DOCKER_IMAGE

    # Helpful for digest-pinned Kubernetes deployments
    try {
        $repoDigest = docker inspect --format='{{index .RepoDigests 0}}' $DOCKER_IMAGE 2>$null
        if ($repoDigest) {
            Log-Info "Image repo digest: $repoDigest"
            Log-Info "Tip: deploy with: .\\ops\\deploy.ps1 eks -Namespace $Namespace -Image $repoDigest"
        }
    } catch {
        # Best-effort only; ignore digest lookup failures.
    }

    Log-Success "Image pushed: $DOCKER_IMAGE"
}

function Show-Status {
    Write-Host ""
    Write-Host "=== VeriCase Deployment Status ===" -ForegroundColor Cyan
    Write-Host ""

    Write-Host "Local Docker:" -ForegroundColor Yellow
    try {
        docker-compose -f docker-compose.prod.yml ps 2>$null
    } catch {
        Write-Host "  Not running" -ForegroundColor Gray
    }
    Write-Host ""

    Write-Host "EC2 ($EC2_IP):" -ForegroundColor Yellow
    try {
        $health = Invoke-RestMethod -Uri "http://$EC2_IP`:8010/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Host "  Status: $($health.status)" -ForegroundColor Green
    } catch {
        Write-Host "  Not reachable" -ForegroundColor Gray
    }
    Write-Host ""

    Write-Host "EKS ($EKS_CLUSTER):" -ForegroundColor Yellow
    try {
        kubectl get pods -n $Namespace -l app=vericase-api 2>$null
    } catch {
        Write-Host "  Not configured" -ForegroundColor Gray
    }
    Write-Host ""
}

# Main
Push-Location "$PSScriptRoot\.."

try {
    Test-Prerequisites

    switch ($Command) {
        "local" { Deploy-Local }
        "ec2" { Deploy-EC2 }
        "eks" { Deploy-EKS }
        "build" { Build-Push }
        "status" { Show-Status }
        default { Show-Usage }
    }
} finally {
    Pop-Location
}
