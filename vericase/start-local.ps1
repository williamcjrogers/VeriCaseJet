# Start VeriCase from Canonical Project
# Uses your locally built images (not old Docker Hub images)

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 69) -ForegroundColor Cyan
Write-Host "Starting VeriCase Canonical Containers" -ForegroundColor Yellow
Write-Host ("=" * 70) -ForegroundColor Cyan

Set-Location -Path "C:\Users\William\Documents\Projects\VeriCaseJet_canonical\vericase"

Write-Host "`n📍 Starting containers with docker compose..." -ForegroundColor Cyan
docker compose up -d

Write-Host "`n📍 Waiting for health check..." -ForegroundColor Cyan
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

Write-Host "`n📍 Current containers:" -ForegroundColor Cyan
docker ps --filter "name=vericase" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

Write-Host "`n📍 Testing debug endpoint..." -ForegroundColor Cyan
try {
    $debug = Invoke-RestMethod -Uri "http://localhost:8010/debug/auth" -ErrorAction Stop
    Write-Host "   Admin exists: $($debug.admin_exists)" -ForegroundColor White
    Write-Host "   Admin email: $($debug.admin_email)" -ForegroundColor White
    Write-Host "   Total users: $($debug.total_users)" -ForegroundColor White
} catch {
    Write-Host "   ⚠️  Could not reach debug endpoint" -ForegroundColor Yellow
}

Write-Host "`n" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "✅ Containers Started!" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Cyan

Write-Host "`n📋 Access Points:" -ForegroundColor Yellow
Write-Host "   Login: http://localhost:8010/ui/login.html" -ForegroundColor White
Write-Host "   Dashboard: http://localhost:8010/ui/dashboard.html" -ForegroundColor White
Write-Host "   API Docs: http://localhost:8010/docs" -ForegroundColor White
Write-Host "   Debug: http://localhost:8010/debug/auth" -ForegroundColor White
Write-Host ""
