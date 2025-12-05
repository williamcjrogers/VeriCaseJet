# VeriCase Development Helper Script
# Usage: .\scripts\dev.ps1 [command] [service]
# Examples:
#   .\scripts\dev.ps1 start
#   .\scripts\dev.ps1 logs api
#   .\scripts\dev.ps1 restart worker

param(
    [Parameter(Position=0)]
    [ValidateSet('start', 'stop', 'restart', 'logs', 'status', 'reset-db', 'health', 'pull', 'help')]
    [string]$Command = 'start',

    [Parameter(Position=1)]
    [string]$Service = '',

    [Parameter()]
    [switch]$Hub  # Use Docker Hub images instead of building locally
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $PSCommandPath
$ProjectRoot = Split-Path -Parent $ScriptDir

function Show-Help {
    Write-Host ""
    Write-Host "VeriCase Development Helper" -ForegroundColor Cyan
    Write-Host "===========================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "USAGE:" -ForegroundColor Yellow
    Write-Host "  .\scripts\dev.ps1 [command] [service] [-Hub]"
    Write-Host ""
    Write-Host "COMMANDS:" -ForegroundColor Yellow
    Write-Host "  start       - Start all services (default)" -ForegroundColor Green
    Write-Host "  stop        - Stop all services" -ForegroundColor Red
    Write-Host "  restart     - Restart all services or specific service" -ForegroundColor Yellow
    Write-Host "  logs        - View logs (all or specific service)" -ForegroundColor Cyan
    Write-Host "  status      - Show running services" -ForegroundColor Magenta
    Write-Host "  health      - Check service health" -ForegroundColor Blue
    Write-Host "  pull        - Pull latest images from Docker Hub" -ForegroundColor Magenta
    Write-Host "  reset-db    - Reset database (WARNING: deletes all data!)" -ForegroundColor Red
    Write-Host "  help        - Show this help" -ForegroundColor White
    Write-Host ""
    Write-Host "FLAGS:" -ForegroundColor Yellow
    Write-Host "  -Hub        - Use Docker Hub images (fast, no build)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "SERVICES:" -ForegroundColor Yellow
    Write-Host "  api, worker, postgres, redis, opensearch, minio, tika, frontend"
    Write-Host ""
    Write-Host "EXAMPLES:" -ForegroundColor Yellow
    Write-Host "  .\scripts\dev.ps1 start -Hub" -ForegroundColor Gray -NoNewline
    Write-Host "          # Pull from Docker Hub (fastest)" -ForegroundColor DarkGray
    Write-Host "  .\scripts\dev.ps1 pull" -ForegroundColor Gray -NoNewline
    Write-Host "               # Pull latest images" -ForegroundColor DarkGray
    Write-Host "  .\scripts\dev.ps1 start" -ForegroundColor Gray -NoNewline
    Write-Host "              # Build locally (for code changes)" -ForegroundColor DarkGray
    Write-Host "  .\scripts\dev.ps1 logs api" -ForegroundColor Gray -NoNewline
    Write-Host "           # View API logs" -ForegroundColor DarkGray
    Write-Host "  .\scripts\dev.ps1 restart worker" -ForegroundColor Gray -NoNewline
    Write-Host "     # Restart worker" -ForegroundColor DarkGray
    Write-Host "  .\scripts\dev.ps1 health" -ForegroundColor Gray -NoNewline
    Write-Host "             # Check all services" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "WORKFLOWS:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Quick Test (Docker Hub):" -ForegroundColor Cyan
    Write-Host "    .\scripts\dev.ps1 pull      # Pull latest" -ForegroundColor Gray
    Write-Host "    .\scripts\dev.ps1 start -Hub # Start" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Local Development (Hot Reload):" -ForegroundColor Cyan
    Write-Host "    .\scripts\dev.ps1 start      # Build & start" -ForegroundColor Gray
    Write-Host "    # Edit code, save, refresh!" -ForegroundColor DarkGray
    Write-Host ""
}

Push-Location $ProjectRoot

try {
    switch ($Command) {
        'help' {
            Show-Help
        }

        'pull' {
            Write-Host ""
            Write-Host "📥 Pulling latest images from Docker Hub..." -ForegroundColor Cyan
            Write-Host ""
            docker pull wcjrogers/vericase-api:latest
            Write-Host ""
            Write-Host "✅ Latest images pulled" -ForegroundColor Green
            Write-Host ""
            Write-Host "💡 Now run: " -ForegroundColor Yellow -NoNewline
            Write-Host ".\scripts\dev.ps1 start -Hub" -ForegroundColor White
            Write-Host ""
        }

        'start' {
            Write-Host ""
            if ($Hub) {
                Write-Host "🚀 Starting VeriCase with Docker Hub images..." -ForegroundColor Green
                Write-Host "   (Using pre-built images - no local build)" -ForegroundColor DarkGray
                Write-Host ""
                docker-compose -f docker-compose.hub.yml up -d
            } else {
                Write-Host "🚀 Starting VeriCase development environment..." -ForegroundColor Green
                Write-Host "   (Building locally with hot reload)" -ForegroundColor DarkGray
                Write-Host ""
                docker-compose up -d
            }
            Write-Host ""
            Write-Host "✅ Services starting. Waiting for health checks..." -ForegroundColor Green
            Start-Sleep -Seconds 5
            Write-Host ""
            Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
            Write-Host "  ACCESS POINTS" -ForegroundColor Cyan -NoNewline
            Write-Host ""
            Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "  📊 Dashboard:    " -ForegroundColor White -NoNewline
            Write-Host "http://localhost:8010/ui/dashboard.html" -ForegroundColor Cyan
            Write-Host "  📖 API Docs:     " -ForegroundColor White -NoNewline
            Write-Host "http://localhost:8010/docs" -ForegroundColor Cyan
            Write-Host "  🗄️  MinIO:        " -ForegroundColor White -NoNewline
            Write-Host "http://localhost:9003" -ForegroundColor Cyan -NoNewline
            Write-Host " (admin/changeme123)" -ForegroundColor DarkGray
            Write-Host "  🔍 OpenSearch:   " -ForegroundColor White -NoNewline
            Write-Host "http://localhost:9200" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
            Write-Host ""
            if ($Hub) {
                Write-Host "💡 TIPS:" -ForegroundColor Yellow
                Write-Host "  • You're running pre-built images from Docker Hub" -ForegroundColor Gray
                Write-Host "  • This is the latest deployed version" -ForegroundColor Gray
                Write-Host "  • To test local changes, use: " -ForegroundColor Gray -NoNewline
                Write-Host ".\scripts\dev.ps1 start" -ForegroundColor White -NoNewline
                Write-Host " (without -Hub)" -ForegroundColor Gray
            } else {
                Write-Host "💡 TIPS:" -ForegroundColor Yellow
                Write-Host "  • Edit code → Save → Refresh browser (changes auto-reload!)" -ForegroundColor Gray
                Write-Host "  • Watch logs: " -ForegroundColor Gray -NoNewline
                Write-Host '.\scripts\dev.ps1 logs api' -ForegroundColor White
                Write-Host "  • Check health: " -ForegroundColor Gray -NoNewline
                Write-Host '.\scripts\dev.ps1 health' -ForegroundColor White
            }
            Write-Host ""
        }

        'stop' {
            Write-Host ""
            Write-Host "⏹️  Stopping all services..." -ForegroundColor Yellow
            docker-compose down
            Write-Host ""
            Write-Host "✅ All services stopped" -ForegroundColor Green
            Write-Host ""
        }

        'restart' {
            Write-Host ""
            if ($Service) {
                Write-Host "🔄 Restarting $Service..." -ForegroundColor Yellow
                docker-compose restart $Service
                Write-Host ""
                Write-Host "✅ $Service restarted" -ForegroundColor Green
            } else {
                Write-Host "🔄 Restarting all services..." -ForegroundColor Yellow
                docker-compose restart
                Write-Host ""
                Write-Host "✅ All services restarted" -ForegroundColor Green
            }
            Write-Host ""
        }

        'logs' {
            Write-Host ""
            if ($Service) {
                Write-Host "📋 Showing logs for $Service (Ctrl+C to exit)..." -ForegroundColor Cyan
                Write-Host ""
                docker-compose logs -f $Service
            } else {
                Write-Host "📋 Showing logs for all services (Ctrl+C to exit)..." -ForegroundColor Cyan
                Write-Host ""
                docker-compose logs -f
            }
        }

        'status' {
            Write-Host ""
            Write-Host "📊 Service Status:" -ForegroundColor Cyan
            Write-Host ""
            docker-compose ps
            Write-Host ""
        }

        'reset-db' {
            Write-Host ""
            Write-Host "⚠️  WARNING: This will DELETE all local data!" -ForegroundColor Red
            Write-Host ""
            $confirm = Read-Host "Type 'yes' to continue"
            if ($confirm -eq 'yes') {
                Write-Host ""
                Write-Host "🗑️  Removing volumes..." -ForegroundColor Yellow
                docker-compose down -v
                Write-Host ""
                Write-Host "🚀 Starting fresh..." -ForegroundColor Yellow
                docker-compose up -d
                Write-Host ""
                Write-Host "✅ Database reset complete" -ForegroundColor Green
                Write-Host ""
            } else {
                Write-Host ""
                Write-Host "❌ Cancelled" -ForegroundColor Yellow
                Write-Host ""
            }
        }

        'health' {
            Write-Host ""
            Write-Host "🏥 Checking service health..." -ForegroundColor Cyan
            Write-Host ""

            # API Health
            try {
                $response = Invoke-WebRequest -Uri "http://localhost:8010/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) {
                    Write-Host "  ✅ API:         " -ForegroundColor Green -NoNewline
                    Write-Host "Healthy " -ForegroundColor Green -NoNewline
                    Write-Host "(http://localhost:8010)" -ForegroundColor DarkGray
                } else {
                    Write-Host "  ⚠️  API:         " -ForegroundColor Yellow -NoNewline
                    Write-Host "Running but unhealthy (Status: $($response.StatusCode))" -ForegroundColor Yellow
                }
            } catch {
                Write-Host "  ❌ API:         " -ForegroundColor Red -NoNewline
                Write-Host "Not responding" -ForegroundColor Red
            }

            # PostgreSQL
            $pgStatus = docker-compose ps postgres 2>$null | Select-String "Up"
            if ($pgStatus) {
                Write-Host "  ✅ PostgreSQL:  " -ForegroundColor Green -NoNewline
                Write-Host "Running " -ForegroundColor Green -NoNewline
                Write-Host "(localhost:54321)" -ForegroundColor DarkGray
            } else {
                Write-Host "  ❌ PostgreSQL:  " -ForegroundColor Red -NoNewline
                Write-Host "Not running" -ForegroundColor Red
            }

            # Redis
            $redisStatus = docker-compose ps redis 2>$null | Select-String "Up"
            if ($redisStatus) {
                Write-Host "  ✅ Redis:       " -ForegroundColor Green -NoNewline
                Write-Host "Running " -ForegroundColor Green -NoNewline
                Write-Host "(localhost:6379)" -ForegroundColor DarkGray
            } else {
                Write-Host "  ❌ Redis:       " -ForegroundColor Red -NoNewline
                Write-Host "Not running" -ForegroundColor Red
            }

            # OpenSearch
            try {
                $osResponse = Invoke-WebRequest -Uri "http://localhost:9200" -TimeoutSec 5 -ErrorAction SilentlyContinue
                if ($osResponse.StatusCode -eq 200) {
                    Write-Host "  ✅ OpenSearch:  " -ForegroundColor Green -NoNewline
                    Write-Host "Running " -ForegroundColor Green -NoNewline
                    Write-Host "(http://localhost:9200)" -ForegroundColor DarkGray
                }
            } catch {
                Write-Host "  ❌ OpenSearch:  " -ForegroundColor Red -NoNewline
                Write-Host "Not responding" -ForegroundColor Red
            }

            # MinIO
            try {
                $minioResponse = Invoke-WebRequest -Uri "http://localhost:9003" -TimeoutSec 5 -ErrorAction SilentlyContinue
                if ($minioResponse.StatusCode -eq 200 -or $minioResponse.StatusCode -eq 403) {
                    Write-Host "  ✅ MinIO:       " -ForegroundColor Green -NoNewline
                    Write-Host "Running " -ForegroundColor Green -NoNewline
                    Write-Host "(http://localhost:9003)" -ForegroundColor DarkGray
                }
            } catch {
                Write-Host "  ❌ MinIO:       " -ForegroundColor Red -NoNewline
                Write-Host "Not responding" -ForegroundColor Red
            }

            # Worker
            $workerStatus = docker-compose ps worker 2>$null | Select-String "Up"
            if ($workerStatus) {
                Write-Host "  ✅ Worker:      " -ForegroundColor Green -NoNewline
                Write-Host "Running" -ForegroundColor Green
            } else {
                Write-Host "  ❌ Worker:      " -ForegroundColor Red -NoNewline
                Write-Host "Not running" -ForegroundColor Red
            }

            Write-Host ""
            Write-Host "💡 Tip: Run " -ForegroundColor Yellow -NoNewline
            Write-Host ".\scripts\dev.ps1 logs api" -ForegroundColor White -NoNewline
            Write-Host " to view logs" -ForegroundColor Yellow
            Write-Host ""
        }

        default {
            Write-Host ""
            Write-Host "❌ Unknown command: $Command" -ForegroundColor Red
            Write-Host ""
            Show-Help
        }
    }
} catch {
    Write-Host ""
    Write-Host "❌ Error: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "💡 Make sure Docker Desktop is running and you're in the correct directory" -ForegroundColor Yellow
    Write-Host ""
} finally {
    Pop-Location
}
