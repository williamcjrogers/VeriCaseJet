<#
Patches awslabs.ec2-mcp-server to work with newer MCP SDKs.

Problem:
  awslabs.ec2_mcp_server/server.py (v0.1.2) passes `version=...` into FastMCP(...).
  Newer `mcp` releases removed that constructor argument, causing:
    TypeError: FastMCP.__init__() got an unexpected keyword argument 'version'

This script removes that argument in-place inside the local .venv.
It is safe to run multiple times.

Usage:
  pwsh -File scripts/patch-awslabs-ec2-mcp-server.ps1
#>

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target = Join-Path $repoRoot '.venv\Lib\site-packages\awslabs\ec2_mcp_server\server.py'

if (-not (Test-Path $target)) {
    Write-Host "Not found: $target" -ForegroundColor Yellow
    Write-Host "Is the venv created and is awslabs.ec2-mcp-server installed?" -ForegroundColor Yellow
    exit 2
}

$content = Get-Content -LiteralPath $target -Raw

# Remove the FastMCP(version=...) line (handles arbitrary whitespace)
$patched = $content -replace "(?m)^\s*version\s*=\s*['\"][^'\"]+['\"]\s*,\s*$", ""

if ($patched -eq $content) {
    Write-Host "No change needed (version=... not present)." -ForegroundColor Green
    exit 0
}

$backup = "$target.bak"
Copy-Item -LiteralPath $target -Destination $backup -Force

Set-Content -LiteralPath $target -Value $patched -Encoding UTF8

Write-Host "Patched: $target" -ForegroundColor Green
Write-Host "Backup:  $backup" -ForegroundColor DarkGray
