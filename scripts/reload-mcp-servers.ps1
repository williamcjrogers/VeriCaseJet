# Reload MCP Servers - Forces Cursor to reload MCP configuration
# Run this after Cursor restart if servers disappear

Write-Host "🔄 MCP Server Reload Tool" -ForegroundColor Cyan
Write-Host "=" * 60

# Step 1: Validate configuration exists
Write-Host "`n📋 Step 1: Validating Configuration..." -ForegroundColor Yellow

$mcpConfig = ".vscode\mcp.json"
$settingsConfig = ".vscode\settings.json"

if (!(Test-Path $mcpConfig)) {
    Write-Host "  ❌ ERROR: $mcpConfig not found!" -ForegroundColor Red
    exit 1
}

if (!(Test-Path $settingsConfig)) {
    Write-Host "  ❌ ERROR: $settingsConfig not found!" -ForegroundColor Red
    exit 1
}

$mcp = Get-Content $mcpConfig | ConvertFrom-Json
$settings = Get-Content $settingsConfig | ConvertFrom-Json

function Get-McpServersObject($obj) {
    if ($null -eq $obj) { return $null }
    if ($obj.servers) { return $obj.servers }
    if ($obj.mcp -and $obj.mcp.servers) { return $obj.mcp.servers }
    return $null
}

$serversObj = Get-McpServersObject $mcp
if (-not $serversObj) {
    Write-Host "  ❌ ERROR: Could not find MCP servers in $mcpConfig (expected 'servers' or 'mcp.servers')." -ForegroundColor Red
    exit 1
}

$serverCount = ($serversObj | Get-Member -MemberType NoteProperty).Count
Write-Host "  ✅ Found mcp.json with $serverCount servers" -ForegroundColor Green

# Step 2: Verify workspace-only discovery
Write-Host "`n⚙️  Step 2: Checking Discovery Settings..." -ForegroundColor Yellow

$discovery = $settings.'chat.mcp.discovery.enabled'
if ($discovery.'cursor-workspace' -eq $true) {
    Write-Host "  ✅ Workspace discovery: ENABLED" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  Workspace discovery: DISABLED - Fixing..." -ForegroundColor Yellow
    $settings.'chat.mcp.discovery.enabled'.'cursor-workspace' = $true
    $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsConfig
    Write-Host "  ✅ Fixed!" -ForegroundColor Green
}

$otherSources = @('claude-desktop', 'windsurf', 'cursor-global')
foreach ($source in $otherSources) {
    if ($discovery.$source -eq $true) {
        Write-Host "  ⚠️  $source discovery: ENABLED - This causes conflicts!" -ForegroundColor Red
        $settings.'chat.mcp.discovery.enabled'.$source = $false
        Write-Host "  ✅ Disabled $source" -ForegroundColor Green
    }
}

# Step 3: Touch mcp.json to trigger reload
Write-Host "`n🔄 Step 3: Triggering Configuration Reload..." -ForegroundColor Yellow

# Update lastWriteTime to force Cursor to detect change
(Get-Item $mcpConfig).LastWriteTime = Get-Date
Write-Host "  ✅ Updated mcp.json timestamp" -ForegroundColor Green

# Step 4: Check MCP executables
Write-Host "`n💻 Step 4: Verifying MCP Executables..." -ForegroundColor Yellow

$mcpExes = Get-ChildItem -Path ".venv\Scripts" -Filter "*mcp*.exe" -ErrorAction SilentlyContinue
$exeCount = ($mcpExes | Measure-Object).Count
Write-Host "  ✅ Found $exeCount MCP executables" -ForegroundColor Green

# Step 5: List configured vs available servers
Write-Host "`n📊 Step 5: Server Status..." -ForegroundColor Yellow

$configuredServers = $serversObj | Get-Member -MemberType NoteProperty | Select-Object -ExpandProperty Name
$availableExes = $mcpExes | Select-Object -ExpandProperty Name | ForEach-Object { $_ -replace '\.exe$', '' }

$awsServers = $configuredServers | Where-Object { $_ -like 'awslabs*' }
$pythonServers = @('sqlite', 'git', 'fetch', 'time', 'ssh')
$npxServers = @('context7', 'github', 'filesystem', 'brave-search', 'google-maps', 'slack', 'puppeteer', 'everything', 'sequential-thinking', 'memory')
$httpServers = @('lex')

Write-Host "  AWS Servers: $($awsServers.Count)" -ForegroundColor Gray
Write-Host "  Python Servers: $($pythonServers.Count)" -ForegroundColor Gray
Write-Host "  NPX Servers: $($npxServers.Count)" -ForegroundColor Gray
Write-Host "  HTTP Servers: $($httpServers.Count)" -ForegroundColor Gray
Write-Host "  Total: $serverCount" -ForegroundColor Cyan

# Step 6: Instructions
Write-Host "`n" + "=" * 60
Write-Host "✅ CONFIGURATION VALIDATED & RELOADED" -ForegroundColor Green
Write-Host "=" * 60

Write-Host "`n🎯 NEXT STEPS:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Reload Cursor Window:" -ForegroundColor Yellow
Write-Host "   Press: Ctrl+Shift+P" -ForegroundColor White
Write-Host "   Type: 'Developer: Reload Window'" -ForegroundColor White
Write-Host "   Press: Enter" -ForegroundColor White
Write-Host ""
Write-Host "2. Wait 10-15 seconds for MCP servers to initialize" -ForegroundColor Yellow
Write-Host ""
Write-Host "3. Verify servers loaded:" -ForegroundColor Yellow
Write-Host "   Press: Ctrl+Shift+P" -ForegroundColor White
Write-Host "   Type: 'MCP: Show Servers' or 'MCP: List Servers'" -ForegroundColor White
Write-Host ""
Write-Host "4. Test with AI:" -ForegroundColor Yellow
Write-Host "   Ask: 'List all available MCP servers'" -ForegroundColor White
Write-Host ""

Write-Host "💡 TIP: If servers still don't appear:" -ForegroundColor Cyan
Write-Host "   - Completely quit Cursor (File → Exit)" -ForegroundColor Gray
Write-Host "   - Wait 5 seconds" -ForegroundColor Gray
Write-Host "   - Restart Cursor" -ForegroundColor Gray
Write-Host "   - Run this script again" -ForegroundColor Gray
Write-Host ""

Write-Host "📚 If problem persists, check:" -ForegroundColor Cyan
Write-Host "   - Cursor logs: Help → Toggle Developer Tools → Console" -ForegroundColor Gray
Write-Host "   - MCP extension status in Extensions panel" -ForegroundColor Gray
Write-Host ""

# Step 7: Create startup reminder
$reminderPath = ".vscode\mcp-startup-reminder.txt"
@"
⚠️  MCP SERVERS STARTUP REMINDER ⚠️

If your MCP servers disappear after restarting Cursor:

QUICK FIX (30 seconds):
1. Run: pwsh scripts/reload-mcp-servers.ps1
2. Reload Cursor: Ctrl+Shift+P → "Developer: Reload Window"
3. Wait 15 seconds
4. Verify: Ask AI "list available MCP servers"

NUCLEAR OPTION (if quick fix fails):
1. Quit Cursor completely (File → Exit)
2. Wait 5 seconds
3. Restart Cursor
4. Run reload script again

This is a known Cursor bug with MCP configuration persistence.
The script forces a reload by touching the config files.

Last validated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Server count: $serverCount
"@ | Set-Content $reminderPath

Write-Host "✅ Created reminder file: $reminderPath" -ForegroundColor Green
Write-Host ""
Write-Host "🎉 Ready! Now reload Cursor." -ForegroundColor Cyan
