# MCP Server Diagnostic Script
# Checks why MCP servers might not persist between sessions
#
# Fixes:
# - Safe if .vscode/settings.json is missing
# - Safe if .vscode/settings.json is invalid JSON

Write-Host "MCP Server Diagnostic Tool" -ForegroundColor Cyan
Write-Host ("=" * 60)

# 1. Check workspace MCP config
Write-Host "`nChecking Workspace MCP Config..." -ForegroundColor Yellow
$workspaceMcp = Join-Path ".vscode" "mcp.json"
if (Test-Path $workspaceMcp) {
  $mcpContent = Get-Content $workspaceMcp -Raw | ConvertFrom-Json

  function Get-McpServersObject($obj) {
    if ($null -eq $obj) { return $null }
    if ($obj.servers) { return $obj.servers }
    if ($obj.mcp -and $obj.mcp.servers) { return $obj.mcp.servers }
    return $null
  }

  $serversObj = Get-McpServersObject $mcpContent
  if (-not $serversObj) {
    Write-Host ("  Found {0}" -f $workspaceMcp) -ForegroundColor Yellow
    Write-Host "  Could not find servers in mcp.json (expected 'servers' or 'mcp.servers')." -ForegroundColor Yellow
    $serverCount = 0
  } else {
    $serverCount = ($serversObj | Get-Member -MemberType NoteProperty).Count
  }
  Write-Host ("  Found {0}" -f $workspaceMcp) -ForegroundColor Green
  Write-Host ("  Server count: {0}" -f $serverCount) -ForegroundColor Green
  Write-Host ("  Last modified: {0}" -f (Get-Item $workspaceMcp).LastWriteTime) -ForegroundColor Gray
} else {
  Write-Host ("  NOT FOUND: {0}" -f $workspaceMcp) -ForegroundColor Red
}

# 2. Check global Cursor MCP config locations
Write-Host "`nChecking Global MCP Configs..." -ForegroundColor Yellow
$globalPaths = @(
  "$env:APPDATA\Cursor\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json",
  "$env:APPDATA\Cursor\User\globalStorage\saoudrizwan.claude-dev\settings\mcp_settings.json",
  "$env:APPDATA\Cursor\User\mcp.json",
  "$env:USERPROFILE\.cursor\mcp.json",
  "$env:LOCALAPPDATA\Cursor\mcp.json"
)
foreach ($path in $globalPaths) {
  if (Test-Path $path) {
    Write-Host ("  FOUND GLOBAL CONFIG: {0}" -f $path) -ForegroundColor Yellow
    Write-Host ("    Last modified: {0}" -f (Get-Item $path).LastWriteTime) -ForegroundColor Gray
  }
}

# 3. Check Claude Desktop config (can interfere)
Write-Host "`nChecking Claude Desktop Config..." -ForegroundColor Yellow
$claudeConfig = "$env:APPDATA\Claude\claude_desktop_config.json"
if (Test-Path $claudeConfig) {
  Write-Host ("  FOUND: {0}" -f $claudeConfig) -ForegroundColor Yellow
  try {
    $claudeContent = Get-Content $claudeConfig -Raw | ConvertFrom-Json
    if ($claudeContent.mcpServers) {
      $claudeServerCount = ($claudeContent.mcpServers | Get-Member -MemberType NoteProperty).Count
      Write-Host ("    Has {0} MCP servers configured" -f $claudeServerCount) -ForegroundColor Gray
    }
  } catch {
    Write-Host "    Could not parse Claude config JSON." -ForegroundColor Yellow
  }
}

# 4. Check if MCP executables exist
Write-Host "`nChecking MCP Executables..." -ForegroundColor Yellow
$expectedServers = @(
  "awslabs.core-mcp-server.exe",
  "awslabs.ec2-mcp-server.exe",
  "awslabs-s3-mcp-server.exe",
  "ecs-mcp-server.exe"
)
$missingCount = 0
foreach ($server in $expectedServers) {
  $path = Join-Path ".venv\Scripts" $server
  if (Test-Path $path) {
    Write-Host ("  OK: {0}" -f $server) -ForegroundColor Green
  } else {
    Write-Host ("  MISSING: {0}" -f $server) -ForegroundColor Red
    $missingCount++
  }
}

# 5. Check Python packages
Write-Host "`nChecking Python MCP Packages..." -ForegroundColor Yellow
if (Test-Path ".venv\Scripts\pip.exe") {
  $mcpPackages = & .venv\Scripts\pip.exe list | Select-String "mcp"
  $packageCount = ($mcpPackages | Measure-Object).Count
  Write-Host ("  Found {0} MCP packages installed" -f $packageCount) -ForegroundColor Green
} else {
  Write-Host "  Virtual environment not found" -ForegroundColor Red
}

# 6. Check Cursor settings for MCP
Write-Host "`nChecking Cursor Settings..." -ForegroundColor Yellow
$cursorSettings = Join-Path ".vscode" "settings.json"
$settingsObj = $null
if (Test-Path $cursorSettings) {
  try {
    $settingsObj = Get-Content $cursorSettings -Raw | ConvertFrom-Json
  } catch {
    Write-Host ("  Could not parse {0} (invalid JSON). Skipping settings inspection." -f $cursorSettings) -ForegroundColor Yellow
  }

  if ($settingsObj -and $settingsObj.'chat.mcp.discovery.enabled') {
    Write-Host "  MCP Discovery Settings:" -ForegroundColor Gray
    $settingsObj.'chat.mcp.discovery.enabled' | Get-Member -MemberType NoteProperty | ForEach-Object {
      $name = $_.Name
      $value = $settingsObj.'chat.mcp.discovery.enabled'.$name
      if ($value) {
        Write-Host ("    {0} = {1} (ENABLED)" -f $name, $value) -ForegroundColor Yellow
      } else {
        Write-Host ("    {0} = {1} (disabled)" -f $name, $value) -ForegroundColor Green
      }
    }
  }
} else {
  Write-Host ("  No workspace settings file found at {0}" -f $cursorSettings) -ForegroundColor Gray
}

# 7. Summary & Recommendations
Write-Host "`n" + ("=" * 60)
Write-Host "DIAGNOSTIC SUMMARY" -ForegroundColor Cyan
Write-Host ("=" * 60)

Write-Host "`nIDENTIFIED ISSUES:" -ForegroundColor Yellow

# Issue 1: Multiple discovery sources
$enabledCount = 0
if ($settingsObj -and $settingsObj.'chat.mcp.discovery.enabled') {
  $discoveryEnabled = $settingsObj.'chat.mcp.discovery.enabled'
  $enabledCount = ($discoveryEnabled | Get-Member -MemberType NoteProperty | Where-Object {
    $discoveryEnabled.($_.Name) -eq $true
  }).Count
} elseif (Test-Path $cursorSettings) {
  # settings.json exists but was invalid JSON or didn't contain the setting
  Write-Host "  Issue 1: Could not read chat.mcp.discovery.enabled from settings.json" -ForegroundColor Yellow
} else {
  Write-Host "  Issue 1: settings.json not found (skip discovery-source count)" -ForegroundColor Gray
}

if ($enabledCount -gt 1) {
  Write-Host ("  Issue 1: Multiple MCP discovery sources enabled ({0})" -f $enabledCount) -ForegroundColor Red
  Write-Host "           This can cause config conflicts!" -ForegroundColor Red
}

# Issue 2: Missing executables
if ($missingCount -gt 0) {
  Write-Host ("  Issue 2: {0} MCP executables missing" -f $missingCount) -ForegroundColor Red
}

Write-Host "`nRECOMMENDATIONS:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1) Disable redundant MCP discovery sources"
Write-Host "   Only keep 'cursor-workspace' enabled in .vscode/settings.json"
Write-Host ""
Write-Host "2) Ensure .vscode/mcp.json is the ONLY config"
Write-Host "   Remove/disable global and Claude Desktop configs"
Write-Host ""
Write-Host "3) Reload Cursor after changes"
Write-Host "   Ctrl+Shift+P -> Developer: Reload Window"
Write-Host ""
Write-Host "4) Verify MCP servers load"
Write-Host "   Ctrl+Shift+P -> MCP: Show Servers"
Write-Host ""
Write-Host "Run: ./scripts/fix-mcp-discovery-fixed.ps1" -ForegroundColor Cyan

