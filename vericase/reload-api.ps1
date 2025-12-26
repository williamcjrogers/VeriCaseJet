# Reload VeriCase API container (fast) and optionally rebuild images
#
# Why this exists:
# - You were running: cd vericase ; docker compose down ; docker compose up -d --build
#   which is slow and also errors if you're already in vericase/ (it tries vericase\vericase).
#
# Default behavior: restart API only (best for UI/Python code changes because compose bind-mounts ./ui and ./api/app).
# Use -Rebuild when you changed Dockerfile/requirements or need a fresh image.

[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$IncludeWorker,
    [switch]$NoCache,
    [int]$HealthTimeoutSeconds = 60
)

$ErrorActionPreference = 'Stop'

function Resolve-ComposeInvoker {
    # Prefer docker compose (v2). Fall back to docker-compose (v1).
    $useV1 = $false
    try {
        & docker compose version *> $null
    } catch {
        $useV1 = $true
    }

    if ($useV1) {
        if (-not (Get-Command docker-compose -ErrorAction SilentlyContinue)) {
            throw "Neither 'docker compose' nor 'docker-compose' is available in PATH."
        }

        return {
            param([Parameter(Mandatory = $true)][string[]]$ComposeArgs)
            & docker-compose @ComposeArgs
        }
    }

    return {
        param([Parameter(Mandatory = $true)][string[]]$ComposeArgs)
        & docker compose @ComposeArgs
    }
}

$invokeCompose = Resolve-ComposeInvoker

# Always run from the vericase/ directory so docker-compose.yml resolves.
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path (Join-Path $PWD 'docker-compose.yml'))) {
        throw "docker-compose.yml not found in '$PWD'. Expected to run from the vericase/ folder."
    }

    $services = @('api')
    if ($IncludeWorker) {
        $services += 'worker'
    }

    if ($Rebuild) {
        Write-Host "Rebuilding: $($services -join ', ')" -ForegroundColor Cyan
        $buildArgs = @('build')
        if ($NoCache) { $buildArgs += '--no-cache' }
        $buildArgs += $services

        & $invokeCompose -ComposeArgs $buildArgs

        # Recreate containers from the new image without restarting dependencies.
        $upArgs = @('up', '-d', '--no-deps', '--force-recreate') + $services
        & $invokeCompose -ComposeArgs $upArgs
    } else {
        Write-Host "Restarting: $($services -join ', ')" -ForegroundColor Cyan
        & $invokeCompose -ComposeArgs (@('restart') + $services)
    }

    # Health check (api only)
    $deadline = (Get-Date).AddSeconds([Math]::Max(5, $HealthTimeoutSeconds))
    $healthy = $false

    while ((Get-Date) -lt $deadline -and -not $healthy) {
        try {
            $resp = Invoke-WebRequest -Uri 'http://localhost:8010/health' -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $healthy = $true; break }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    if ($healthy) {
        Write-Host "✅ API is healthy at http://localhost:8010" -ForegroundColor Green
    } else {
        Write-Host "⚠️  API didn't pass health check within ${HealthTimeoutSeconds}s" -ForegroundColor Yellow
        Write-Host "   Tip: check logs: docker logs vericase-api-1 --tail 100" -ForegroundColor Gray
    }
} finally {
    Pop-Location
}
