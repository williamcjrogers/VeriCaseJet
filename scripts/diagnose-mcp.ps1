# MCP Server Diagnostic Script
# Checks why MCP servers might not persist between sessions

Write-Host "🔍 MCP Server Diagnostic Tool" -ForegroundColor Cyan
Write-Host "=" * 60

# 1. Check workspace MCP config
Write-Host "`n📁 Checking Workspace MCP Config..." -ForegroundColor Yellow
$workspaceMcp = ".vscode\mcp.json"
if (Test-Path $workspaceMcp) {
    $mcpContent = Get-Content $workspaceMcp | ConvertFrom-Json
    $serverCount = ($mcpContent.mcp.servers | Get-Member -MemberType NoteProperty).Count
    Write-Host "  ✅ Found $workspaceMcp" -ForegroundColor Green
    Write-Host "  ✅ Server count: $serverCount" -ForegroundColor Green
    Write-Host "  Last modified: $((Get-Item $workspaceMcp).LastWriteTime)" -ForegroundColor Gray
} else {
    Write-Host "  ❌ NOT FOUND: $workspaceMcp" -ForegroundColor Red
}

# 2. Check global Cursor MCP config locations
Write-Host "`n🌍 Checking Global MCP Configs..." -ForegroundColor Yellow

$globalPaths = @(
    "$env:APPDATA\Cursor\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json",
    "$env:APPDATA\Cursor\User\globalStorage\saoudrizwan.claude-dev\settings\mcp_settings.json",
    "$env:APPDATA\Cursor\User\mcp.json",
    "$env:USERPROFILE\.cursor\mcp.json",
    "$env:LOCALAPPDATA\Cursor\mcp.json"
)

foreach ($path in $globalPaths) {
    if (Test-Path $path) {
        Write-Host "  ⚠️  FOUND GLOBAL CONFIG: $path" -ForegroundColor Yellow
        Write-Host "     Last modified: $((Get-Item $path).LastWriteTime)" -ForegroundColor Gray
    }
}

# 3. Check Claude Desktop config (can interfere)
Write-Host "`n🤖 Checking Claude Desktop Config..." -ForegroundColor Yellow
$claudeConfig = "$env:APPDATA\Claude\claude_desktop_config.json"
if (Test-Path $claudeConfig) {
    Write-Host "  ⚠️  FOUND: $claudeConfig" -ForegroundColor Yellow
    $claudeContent = Get-Content $claudeConfig | ConvertFrom-Json
    if ($claudeContent.mcpServers) {
        $claudeServerCount = ($claudeContent.mcpServers | Get-Member -MemberType NoteProperty).Count
        Write-Host "     Has $claudeServerCount MCP servers configured" -ForegroundColor Gray
    }
}

# 4. Check if MCP executables exist
Write-Host "`n💻 Checking MCP Executables..." -ForegroundColor Yellow
$expectedServers = @(
    "awslabs.core-mcp-server.exe",
    "awslabs.ec2-mcp-server.exe",
    "awslabs.s3-mcp-server.exe",
    "ecs-mcp-server.exe"
)

$missingCount = 0
foreach ($server in $expectedServers) {
    $path = ".venv\Scripts\$server"
    if (Test-Path $path) {
        Write-Host "  ✅ $server" -ForegroundColor Green
    } else {
        Write-Host "  ❌ MISSING: $server" -ForegroundColor Red
        $missingCount++
    }
}

# 5. Check Python packages
Write-Host "`n🐍 Checking Python MCP Packages..." -ForegroundColor Yellow
if (Test-Path ".venv\Scripts\pip.exe") {
    $mcpPackages = & .venv\Scripts\pip.exe list | Select-String "mcp"
    $packageCount = ($mcpPackages | Measure-Object).Count
    Write-Host "  ✅ Found $packageCount MCP packages installed" -ForegroundColor Green
} else {
    Write-Host "  ❌ Virtual environment not found" -ForegroundColor Red
}

# 6. Check Cursor settings for MCP
Write-Host "`n⚙️  Checking Cursor Settings..." -ForegroundColor Yellow
$cursorSettings = ".vscode\settings.json"
if (Test-Path $cursorSettings) {
    $settings = Get-Content $cursorSettings | ConvertFrom-Json
    
    Write-Host "  MCP Discovery Settings:" -ForegroundColor Gray
    if ($settings.'chat.mcp.discovery.enabled') {
        $settings.'chat.mcp.discovery.enabled' | Get-Member -MemberType NoteProperty | ForEach-Object {
            $name = $_.Name
            $value = $settings.'chat.mcp.discovery.enabled'.$name
            if ($value) {
                Write-Host "    ⚠️  $name = $value (ENABLED)" -ForegroundColor Yellow
            } else {
                Write-Host "    ✅ $name = $value (disabled)" -ForegroundColor Green
            }
        }
    }
}

# 7. Summary & Recommendations
Write-Host "`n" + "=" * 60
Write-Host "📊 DIAGNOSTIC SUMMARY" -ForegroundColor Cyan
Write-Host "=" * 60

Write-Host "`n🎯 IDENTIFIED ISSUES:" -ForegroundColor Yellow

# Issue 1: Multiple discovery sources
$settings = Get-Content ".vscode\settings.json" | ConvertFrom-Json
$discoveryEnabled = $settings.'chat.mcp.discovery.enabled'
$enabledCount = ($discoveryEnabled | Get-Member -MemberType NoteProperty | Where-Object { 
    $discoveryEnabled.($_.Name) -eq $true 
}).Count

if ($enabledCount -gt 1) {
    Write-Host "  ⚠️  Issue 1: Multiple MCP discovery sources enabled ($enabledCount)" -ForegroundColor Red
    Write-Host "     This can cause config conflicts!" -ForegroundColor Red
}

# Issue 2: Missing executables
if ($missingCount -gt 0) {
    Write-Host "  ⚠️  Issue 2: $missingCount MCP executables missing" -ForegroundColor Red
}

Write-Host "`n💡 RECOMMENDATIONS:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1️⃣  Disable redundant MCP discovery sources" -ForegroundColor Green
Write-Host "   Only keep 'cursor-workspace' enabled in .vscode/settings.json"
Write-Host ""
Write-Host "2️⃣  Ensure .vscode/mcp.json is the ONLY config" -ForegroundColor Green
Write-Host "   Remove/disable global and Claude Desktop configs"
Write-Host ""
Write-Host "3️⃣  Reload Cursor after changes" -ForegroundColor Green
Write-Host "   Press: Ctrl+Shift+P → 'Developer: Reload Window'"
Write-Host ""
Write-Host "4️⃣  Verify MCP servers load" -ForegroundColor Green
Write-Host "   Open: Ctrl+Shift+P → 'MCP: Show Servers'"
Write-Host ""

Write-Host "`n✨ Run 'fix-mcp-discovery.ps1' to auto-fix these issues" -ForegroundColor Cyan
