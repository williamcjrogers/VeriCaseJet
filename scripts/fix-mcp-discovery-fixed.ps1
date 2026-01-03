# Fix MCP Server Discovery Conflicts
# Disables multiple discovery sources that can cause MCP servers to be "forgotten".
#
# Fixes:
# - Safe if .vscode/settings.json is missing (creates it)
# - Safe if .vscode/settings.json is invalid JSON (backs up, then starts fresh)

Write-Host "MCP Server Discovery Fix" -ForegroundColor Cyan
Write-Host ("=" * 60)

$settingsPath = Join-Path ".vscode" "settings.json"
$backupPath = Join-Path ".vscode" "settings.json.backup"
$vscodeDir = Split-Path -Parent $settingsPath

if (-not (Test-Path $vscodeDir)) {
  New-Item -ItemType Directory -Path $vscodeDir -Force | Out-Null
  Write-Host "Created .vscode directory." -ForegroundColor Gray
}

if (Test-Path $settingsPath) {
  Copy-Item $settingsPath $backupPath -Force
  Write-Host ("Backed up settings to: {0}" -f $backupPath) -ForegroundColor Green
}

# Read current settings (or initialize)
$settings = @{}
if (Test-Path $settingsPath) {
  try {
    $raw = Get-Content $settingsPath -Raw -ErrorAction Stop
    if ($raw -and $raw.Trim().Length -gt 0) {
      try {
        # PowerShell 6+ supports -AsHashtable
        $settings = $raw | ConvertFrom-Json -AsHashtable
      } catch {
        # Fallback for older PowerShell: shallow conversion
        $settingsObj = $raw | ConvertFrom-Json
        foreach ($p in $settingsObj.PSObject.Properties) {
          $settings[$p.Name] = $p.Value
        }
      }
    }
  } catch {
    Write-Host ("Warning: Failed to parse {0}. Starting with empty settings." -f $settingsPath) -ForegroundColor Yellow
    $settings = @{}
  }
} else {
  Write-Host ("Info: {0} not found; creating it." -f $settingsPath) -ForegroundColor Yellow
}

Write-Host "`nUpdating MCP discovery settings..." -ForegroundColor Yellow

$settings["chat.mcp.discovery.enabled"] = @{
  "claude-desktop"   = $false
  "windsurf"         = $false
  "cursor-global"    = $false
  "cursor-workspace" = $true
}

$settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Encoding utf8

Write-Host "`nSettings updated successfully." -ForegroundColor Green
Write-Host ""
Write-Host "Next:" -ForegroundColor Yellow
Write-Host "  1) Reload Cursor: Ctrl+Shift+P -> Developer: Reload Window"
Write-Host "  2) Verify MCP servers: Ctrl+Shift+P -> MCP: Show Servers"

