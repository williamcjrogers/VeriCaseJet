# VeriCase Production Deployment Script for Windows
# Run with: .\deploy.ps1

Write-Host "🚀 VeriCase Production Deployment" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

# Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-Host "❌ Error: .env file not found!" -ForegroundColor Red
    Write-Host "   Please copy .env.example to .env and configure it" -ForegroundColor Yellow
    exit 1
}

# Function to check if service is healthy
function Check-ServiceHealth {
    param($ServiceName)
    
    $maxAttempts = 30
    $attempt = 1
    
    Write-Host -NoNewline "   Waiting for $ServiceName to be healthy"
    while ($attempt -le $maxAttempts) {
        $health = docker-compose -f docker-compose.prod.yml ps | Select-String "$ServiceName.*healthy"
        if ($health) {
            Write-Host " ✅" -ForegroundColor Green
            return $true
        }
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 2
        $attempt++
    }
    Write-Host " ❌" -ForegroundColor Red
    return $false
}

# Build images
Write-Host "`n📦 Building Docker images..." -ForegroundColor Cyan
docker-compose -f docker-compose.prod.yml build --no-cache

# Tag images for registry (if using)
if ($env:DOCKER_REGISTRY) {
    Write-Host "🏷️  Tagging images for registry: $env:DOCKER_REGISTRY" -ForegroundColor Cyan
    docker tag vericase/api:latest "$env:DOCKER_REGISTRY/vericase/api:latest"
    docker tag vericase/worker:latest "$env:DOCKER_REGISTRY/vericase/worker:latest"
}

# Start infrastructure services first
Write-Host "`n🏗️  Starting infrastructure services..." -ForegroundColor Cyan
docker-compose -f docker-compose.prod.yml up -d postgres redis minio opensearch tika

# Wait for services to be healthy
Write-Host "`n⏳ Waiting for services to be ready..." -ForegroundColor Yellow
Check-ServiceHealth "postgres"
Check-ServiceHealth "redis"
Check-ServiceHealth "minio"
Check-ServiceHealth "opensearch"
Check-ServiceHealth "tika"

# Load environment variables
$envContent = Get-Content .env
foreach ($line in $envContent) {
    if ($line -match '^([^#][^=]+)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        Set-Variable -Name $name -Value $value -Scope Script
    }
}

# Create MinIO bucket if it doesn't exist
Write-Host "`n📤 Setting up MinIO bucket..." -ForegroundColor Cyan
docker-compose -f docker-compose.prod.yml exec -T minio mc alias set local http://localhost:9000 $MINIO_ACCESS_KEY $MINIO_SECRET_KEY 2>$null
docker-compose -f docker-compose.prod.yml exec -T minio mc mb "local/$MINIO_BUCKET" --ignore-existing 2>$null

# Run database migrations
Write-Host "`n🗄️  Running database migrations..." -ForegroundColor Cyan
docker-compose -f docker-compose.prod.yml run --rm api python -m app.apply_migrations

# Start application services
Write-Host "`n🚀 Starting application services..." -ForegroundColor Cyan
docker-compose -f docker-compose.prod.yml up -d api worker beat flower

# Wait for API to be healthy
Check-ServiceHealth "api"

# Show status
Write-Host "`n✨ Deployment complete!" -ForegroundColor Green
Write-Host "`n📍 Service URLs:" -ForegroundColor Cyan
Write-Host "   - API:        http://localhost:8010"
Write-Host "   - MinIO:      http://localhost:9001 (user: $MINIO_ACCESS_KEY)"
Write-Host "   - Flower:     http://localhost:5555"
Write-Host "   - OpenSearch: http://localhost:9200"
Write-Host "`n📊 Check status with: docker-compose -f docker-compose.prod.yml ps" -ForegroundColor Yellow
Write-Host "📋 View logs with:    docker-compose -f docker-compose.prod.yml logs -f [service]" -ForegroundColor Yellow
Write-Host "🛑 Stop with:        docker-compose -f docker-compose.prod.yml down" -ForegroundColor Yellow
