# deploy-fixes.ps1
Write-Host "=== VeriCase Deployment Fixer ===" -ForegroundColor Cyan

# 1. Check for Kubernetes Secret
Write-Host "`n[1/3] Checking for 'vericase-secrets'..."
$secretCheck = kubectl get secret vericase-secrets --ignore-not-found
if (-not $secretCheck) {
    Write-Host "Secret 'vericase-secrets' not found!" -ForegroundColor Yellow
    Write-Host "You must create it with your database credentials."
    Write-Host "Run the following command (replace placeholders):" -ForegroundColor White
    Write-Host "kubectl create secret generic vericase-secrets --from-literal=DATABASE_URL='postgresql+psycopg2://postgres:YOUR_PASSWORD@database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com:5432/postgres' --from-literal=JWT_SECRET='$(New-Guid)'" -ForegroundColor Green
    exit 1
}
else {
    Write-Host "Secret 'vericase-secrets' exists. ✅" -ForegroundColor Green
}

# 2. Apply Deployment
Write-Host "`n[2/3] Applying updated deployment configuration..."
kubectl apply -f k8s-deployment.yaml
if ($LASTEXITCODE -eq 0) {
    Write-Host "Deployment configuration applied. ✅" -ForegroundColor Green
}
else {
    Write-Host "Failed to apply deployment!" -ForegroundColor Red
    exit 1
}

# 3. Restart Deployment
Write-Host "`n[3/3] Restarting pods to pick up new code and secrets..."
kubectl rollout restart deployment/vericase-api
if ($LASTEXITCODE -eq 0) {
    Write-Host "Rollout restart triggered. ✅" -ForegroundColor Green
    Write-Host "`nMonitor the rollout with: kubectl rollout status deployment/vericase-api"
}
else {
    Write-Host "Failed to restart deployment!" -ForegroundColor Red
    exit 1
}
