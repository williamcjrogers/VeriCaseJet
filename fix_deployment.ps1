$ErrorActionPreference = "Stop"

# Generate tag
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tag = "fix-deploy-$timestamp"
$image = "wcjrogers/vericase-api:$tag"

Write-Host "Building and pushing image: $image"

# Build and push
Set-Location vericase
docker buildx build --builder cloud-vericase-vericase --platform linux/amd64 -f api/Dockerfile -t $image --push .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed"
}

# Update deployments
$kc = "..\.kubeconfig-vericase"
Write-Host "Updating deployments in cluster..."

# Update API
kubectl --kubeconfig $kc -n vericase set image deployment/vericase-api vericase-api=$image
kubectl --kubeconfig $kc -n vericase rollout status deployment/vericase-api

# Update Worker
kubectl --kubeconfig $kc -n vericase set image deployment/vericase-worker vericase-worker=$image
kubectl --kubeconfig $kc -n vericase rollout status deployment/vericase-worker

Write-Host "Deployment updated successfully to $image"
