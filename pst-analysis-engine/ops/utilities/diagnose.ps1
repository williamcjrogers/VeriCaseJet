Write-Host "=== VeriCase Diagnostics ===" -ForegroundColor Cyan

Write-Host "`n1. Checking Docker containers..." -ForegroundColor Yellow
docker ps --format "table {{.Names}}\t{{.Status}}" | Select-String "pst-analysis"

Write-Host "`n2. Checking if UI directory exists locally..." -ForegroundColor Yellow
if (Test-Path ".\ui\wizard.html") {
    Write-Host "✓ UI files found locally" -ForegroundColor Green
    Get-ChildItem ".\ui" | Select-Object Name
} else {
    Write-Host "✗ UI files NOT found" -ForegroundColor Red
}

Write-Host "`n3. Checking UI inside API container..." -ForegroundColor Yellow
docker-compose exec -T api ls /code/ui 2>&1

Write-Host "`n4. Testing API endpoints..." -ForegroundColor Yellow
try {
    $root = Invoke-WebRequest -Uri "http://localhost:8010/" -UseBasicParsing -TimeoutSec 5
    Write-Host "✓ Root endpoint (/) - Status: $($root.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "✗ Root endpoint (/) - Error: $_" -ForegroundColor Red
}

try {
    $ui = Invoke-WebRequest -Uri "http://localhost:8010/ui/" -UseBasicParsing -TimeoutSec 5
    Write-Host "✓ UI endpoint (/ui/) - Status: $($ui.StatusCode)" -ForegroundColor Green
    Write-Host "  Content length: $($ui.Content.Length) bytes" -ForegroundColor White
} catch {
    Write-Host "✗ UI endpoint (/ui/) - Error: $_" -ForegroundColor Red
}

try {
    $wizard = Invoke-WebRequest -Uri "http://localhost:8010/ui/wizard.html" -UseBasicParsing -TimeoutSec 5
    Write-Host "✓ Wizard (/ui/wizard.html) - Status: $($wizard.StatusCode)" -ForegroundColor Green
    Write-Host "  Content length: $($wizard.Content.Length) bytes" -ForegroundColor White
} catch {
    Write-Host "✗ Wizard (/ui/wizard.html) - Error: $_" -ForegroundColor Red
}

Write-Host "`n5. Checking API logs for errors..." -ForegroundColor Yellow
docker-compose logs --tail=20 api

Write-Host "`n=== End Diagnostics ===" -ForegroundColor Cyan
