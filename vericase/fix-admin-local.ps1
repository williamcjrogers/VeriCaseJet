# Fix Admin Account - Local Docker
# Run this to diagnose and fix the admin@vericase.com account in local Docker

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 69) -ForegroundColor Cyan
Write-Host "VeriCase Admin Account Fix - Local Docker" -ForegroundColor Yellow
Write-Host ("=" * 70) -ForegroundColor Cyan

# Check if Docker is running
Write-Host "`nChecking Docker..." -ForegroundColor Cyan
$dockerRunning = docker ps 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Docker is not running!" -ForegroundColor Red
    Write-Host "   Start Docker Desktop and try again" -ForegroundColor Yellow
    exit 1
}

# Change to vericase directory
Set-Location -Path "$PSScriptRoot"
if (-not (Test-Path "docker-compose.yml")) {
    Write-Host "❌ Not in vericase directory!" -ForegroundColor Red
    exit 1
}

# Check if containers are running
Write-Host "Checking VeriCase containers..." -ForegroundColor Cyan
$apiContainer = docker ps --filter "name=vericase.*api" --format "{{.Names}}" | Select-Object -First 1

if (-not $apiContainer) {
    Write-Host "⚠️  VeriCase API container is not running!" -ForegroundColor Yellow
    Write-Host "   Starting containers..." -ForegroundColor Cyan
    docker compose up -d
    Start-Sleep -Seconds 5
    $apiContainer = docker ps --filter "name=vericase.*api" --format "{{.Names}}" | Select-Object -First 1
}

if (-not $apiContainer) {
    Write-Host "❌ Could not start VeriCase containers!" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Found API container: $apiContainer" -ForegroundColor Green

# Menu for action
Write-Host "`n📋 What would you like to do?" -ForegroundColor Yellow
Write-Host "   1. Fix existing admin@vericase.com account" -ForegroundColor White
Write-Host "   2. Create NEW admin@veri-case.com account (recommended)" -ForegroundColor White
Write-Host "   3. Both (fix old, create new)" -ForegroundColor White
Write-Host ""
$choice = Read-Host "Choice (1/2/3)"

Write-Host "`n" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan

switch ($choice) {
    "1" {
        Write-Host "Running fix on admin@vericase.com..." -ForegroundColor Cyan
        docker exec -it $apiContainer python /app/fix_admin_account.py
    }
    "2" {
        Write-Host "Creating NEW admin@veri-case.com account..." -ForegroundColor Cyan
        docker exec -it $apiContainer python /app/create_new_admin.py
    }
    "3" {
        Write-Host "Fixing admin@vericase.com..." -ForegroundColor Cyan
        docker exec -it $apiContainer python /app/fix_admin_account.py
        Write-Host "`nCreating NEW admin@veri-case.com..." -ForegroundColor Cyan
        docker exec -it $apiContainer python /app/create_new_admin.py
    }
    default {
        Write-Host "Invalid choice, running fix by default..." -ForegroundColor Yellow
        docker exec -it $apiContainer python /app/fix_admin_account.py
    }
}

Write-Host "`n" -ForegroundColor Cyan
Write-Host ("=" * 70) -ForegroundColor Cyan
Write-Host "Fix complete!" -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Cyan

Write-Host "`n📋 Next Steps:" -ForegroundColor Yellow
Write-Host "   1. Try logging in at http://localhost:8010/ui/login.html" -ForegroundColor White
Write-Host "   2. Use admin@vericase.com and the password from ADMIN_PASSWORD" -ForegroundColor White
Write-Host "   3. If login still fails, check the API logs:" -ForegroundColor White
Write-Host "      docker logs $apiContainer --tail 50" -ForegroundColor Gray
Write-Host ""
