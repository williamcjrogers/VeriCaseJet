# Fix Docker Alignment - Stop old worktrees, start canonical project

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 69) -ForegroundColor Cyan
Write-Host "VeriCase Docker Alignment Fix" -ForegroundColor Yellow
Write-Host ("=" * 70) -ForegroundColor Cyan

# 1. Stop old worktree containers
Write-Host "`n📍 Step 1: Stopping old worktree containers..." -ForegroundColor Cyan
$oldContainers = @("main-api-1", "main-db-1", "main-redis-1", "main-worker-1")
foreach ($container in $oldContainers) {
    $exists = docker ps -a --format "{{.Names}}" | Select-String -Pattern "^$container$"
    if ($exists) {
        Write-Host "   Stopping $container..." -ForegroundColor Yellow
        docker stop $container 2>&1 | Out-Null
        docker rm $container 2>&1 | Out-Null
    }
}
Write-Host "   ✅ Old containers cleaned up" -ForegroundColor Green

# 2. Navigate to canonical project
Write-Host "`n📍 Step 2: Starting canonical VeriCase project..." -ForegroundColor Cyan
Set-Location -Path "C:\Users\William\Documents\Projects\VeriCaseJet_canonical\vericase"

# 3. Stop any existing vericase containers (clean slate)
Write-Host "   Cleaning up any existing vericase containers..." -ForegroundColor Yellow
docker compose down -v 2>&1 | Out-Null

# 4. Start fresh
Write-Host "   Building and starting containers..." -ForegroundColor Yellow
docker compose up -d --build

# 5. Wait for health
Write-Host "`n📍 Step 3: Waiting for services to be healthy..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

$maxAttempts = 30
$attempt = 0
$healthy = $false

while ($attempt -lt $maxAttempts -and -not $healthy) {
    $attempt++
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8010/health" -TimeoutSec 2 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            Write-Host "   ✅ API is healthy!" -ForegroundColor Green
        }
    } catch {
        Write-Host "   ⏳ Waiting... (attempt $attempt/$maxAttempts)" -ForegroundColor Gray
        Start-Sleep -Seconds 2
    }
}

if (-not $healthy) {
    Write-Host "   ⚠️  API didn't respond within timeout" -ForegroundColor Yellow
    Write-Host "   Check logs with: docker logs vericase-api-1" -ForegroundColor Gray
}

# 6. Check containers
Write-Host "`n📍 Step 4: Current VeriCase containers:" -ForegroundColor Cyan
docker ps --filter "name=vericase" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

Write-Host "`n" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "Docker Alignment Complete!" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Cyan

Write-Host "`n📋 Next Steps:" -ForegroundColor Yellow
Write-Host "   1. Verify admin login at http://localhost:8010/ui/login.html" -ForegroundColor White
Write-Host "   2. Check debug endpoint: http://localhost:8010/debug/auth" -ForegroundColor White
Write-Host "   3. Once verified, run: .\deploy-to-eks.ps1" -ForegroundColor White
Write-Host ""
