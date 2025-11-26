param(
    [switch]$SkipDocker
)

$ErrorActionPreference = 'Stop'

$scriptPath = $MyInvocation.MyCommand.Path
$setupDir = Split-Path -Parent $scriptPath
$repoRoot = Split-Path -Parent (Split-Path -Parent $setupDir)
if (-not $repoRoot) {
    Write-Error "Unable to determine repository root from script path."
    exit 1
}

Write-Host "Resetting VeriCase local state from $repoRoot" -ForegroundColor Cyan

$enginePath = $repoRoot
if (-not (Test-Path $enginePath)) {
    Write-Error "Could not find pst-analysis-engine directory at $enginePath"
    exit 1
}

if (-not $SkipDocker) {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        Write-Host "Stopping Docker stack and removing volumes..." -ForegroundColor Yellow
        Push-Location $enginePath
        try {
            docker-compose down -v
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Warning "docker-compose not found in PATH. Skipping container shutdown."
    }
}
else {
    Write-Warning "Skipping docker-compose down step (SkipDocker switch provided)."
}

$targets = @(
    Join-Path $enginePath "data",
    Join-Path $enginePath "uploads",
    Join-Path $enginePath "evidence",
    Join-Path $enginePath "vericase.db"
)

foreach ($fullPath in $targets) {
    if (Test-Path $fullPath) {
        $relative = $fullPath.Substring($repoRoot.Length).TrimStart('\\','/')
        Write-Host "Removing $relative" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $fullPath
    }
}

Write-Host "Local state reset complete. Next run will start with a clean environment." -ForegroundColor Green
