# NUCLEAR OPTION - Force Complete MCP Reset
# Use this when normal reload doesn't work

Write-Host "💣 NUCLEAR MCP FIX - Complete Reset" -ForegroundColor Red
Write-Host "=" * 70
Write-Host ""

# Step 1: Close Cursor processes
Write-Host "🔴 Step 1: Attempting to close Cursor..." -ForegroundColor Yellow
try {
    $cursorProcesses = Get-Process -Name "Cursor" -ErrorAction SilentlyContinue
    if ($cursorProcesses) {
        Write-Host "   Found $($cursorProcesses.Count) Cursor process(es)" -ForegroundColor Gray
        Write-Host "   ⚠️  Please CLOSE CURSOR MANUALLY now!" -ForegroundColor Red
        Write-Host "   Click File → Exit (or Alt+F4)" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "   Press ANY KEY after Cursor is closed..." -ForegroundColor Cyan
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    } else {
        Write-Host "   ✅ Cursor not running" -ForegroundColor Green
    }
} catch {
    Write-Host "   ⚠️  Please make sure Cursor is closed" -ForegroundColor Yellow
}

# Step 2: Validate config
Write-Host "`n📋 Step 2: Validating Configuration..." -ForegroundColor Yellow

$mcpConfig = ".vscode\mcp.json"
if (!(Test-Path $mcpConfig)) {
    Write-Host "   ❌ ERROR: mcp.json not found!" -ForegroundColor Red
    exit 1
}

$mcp = Get-Content $mcpConfig -Raw | ConvertFrom-Json
$serverCount = ($mcp.mcp.servers | Get-Member -MemberType NoteProperty).Count
Write-Host "   ✅ Config valid: $serverCount servers" -ForegroundColor Green

# Step 3: Force timestamp update
Write-Host "`n🔄 Step 3: Force Updating Config Timestamp..." -ForegroundColor Yellow
$configFile = Get-Item $mcpConfig
$configFile.LastWriteTime = Get-Date
$configFile.LastAccessTime = Get-Date
$configFile.CreationTime = Get-Date
Write-Host "   ✅ Timestamps updated" -ForegroundColor Green

# Step 4: Check for workspace cache and clear it
Write-Host "`n🗑️  Step 4: Clearing Workspace Cache..." -ForegroundColor Yellow
$workspaceCachePaths = @(
    "$env:APPDATA\Cursor\User\workspaceStorage",
    "$env:APPDATA\Cursor\User\globalStorage",
    "$env:APPDATA\Cursor\Cache",
    "$env:LOCALAPPDATA\Cursor\Cache"
)

foreach ($path in $workspaceCachePaths) {
    if (Test-Path $path) {
        Write-Host "   Found cache: $path" -ForegroundColor Gray
        try {
            # Don't delete everything, just rename to backup
            $backup = "$path.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            if (!(Test-Path $backup)) {
                Write-Host "   ⚠️  Cache found but leaving it (can cause issues to delete)" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "   ⚠️  Could not process cache" -ForegroundColor Yellow
        }
    }
}

# Step 5: Create a marker file
Write-Host "`n📝 Step 5: Creating Reload Marker..." -ForegroundColor Yellow
$markerPath = ".vscode\mcp-reload-marker.txt"
@"
MCP RELOAD TRIGGERED
Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Server Count: $serverCount
Action: Nuclear reset

If you're seeing this, the nuclear reset was triggered.
This file helps Cursor detect changes.
"@ | Set-Content $markerPath
Write-Host "   ✅ Marker created" -ForegroundColor Green

# Step 6: Wait and instructions
Write-Host "`n" + "=" * 70
Write-Host "✅ PREPARATION COMPLETE" -ForegroundColor Green
Write-Host "=" * 70
Write-Host ""

Write-Host "🎯 NOW DO THIS:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. ⚠️  MAKE SURE CURSOR IS COMPLETELY CLOSED" -ForegroundColor Red
Write-Host "   (Check Task Manager if unsure)" -ForegroundColor Gray
Write-Host ""
Write-Host "2. ⏰ WAIT 10 SECONDS" -ForegroundColor Yellow
Write-Host "   Let Windows fully release resources" -ForegroundColor Gray
Write-Host ""
Write-Host "3. 🚀 START CURSOR" -ForegroundColor Green
Write-Host "   Open from Start Menu or Desktop" -ForegroundColor Gray
Write-Host ""
Write-Host "4. ⏰ WAIT 30 SECONDS" -ForegroundColor Yellow
Write-Host "   Let Cursor fully initialize and load MCP servers" -ForegroundColor Gray
Write-Host ""
Write-Host "5. ✅ CHECK FOR SERVERS" -ForegroundColor Cyan
Write-Host "   Open this chat and ask:" -ForegroundColor Gray
Write-Host '   "List all available MCP servers"' -ForegroundColor White
Write-Host ""

Write-Host "💡 IMPORTANT:" -ForegroundColor Cyan
Write-Host "   - Don't rush - give Cursor time to start" -ForegroundColor Gray
Write-Host "   - Wait for the window to fully load" -ForegroundColor Gray
Write-Host "   - MCP servers take 20-30 seconds to initialize" -ForegroundColor Gray
Write-Host ""

Write-Host "🔍 TO VERIFY:" -ForegroundColor Cyan
Write-Host "   After 30 seconds, press Ctrl+Shift+P" -ForegroundColor White
Write-Host "   Type 'MCP' and see if MCP commands appear" -ForegroundColor White
Write-Host ""

Write-Host "❌ IF STILL NO SERVERS:" -ForegroundColor Red
Write-Host "   1. Check Cursor logs: Help → Toggle Developer Tools → Console" -ForegroundColor White
Write-Host "   2. Look for 'MCP' or 'server' errors" -ForegroundColor White
Write-Host "   3. Try disabling/re-enabling MCP extension" -ForegroundColor White
Write-Host "   4. Consider reinstalling Cursor (last resort)" -ForegroundColor White
Write-Host ""

Write-Host "📊 Current Status:" -ForegroundColor Cyan
Write-Host "   Servers configured: $serverCount" -ForegroundColor White
Write-Host "   Config file: $mcpConfig" -ForegroundColor White
Write-Host "   Marker file: $markerPath" -ForegroundColor White
Write-Host ""

Write-Host "🎯 Press ANY KEY to open Cursor automatically..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')

# Try to start Cursor
Write-Host "`n🚀 Attempting to start Cursor..." -ForegroundColor Yellow
try {
    $cursorPath = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Cursor" -Filter "Cursor.exe" -Recurse -ErrorAction Stop | Select-Object -First 1
    if ($cursorPath) {
        Start-Process $cursorPath.FullName -WorkingDirectory (Get-Location)
        Write-Host "   ✅ Cursor starting..." -ForegroundColor Green
        Write-Host ""
        Write-Host "⏰ NOW WAIT 30 SECONDS for initialization!" -ForegroundColor Yellow
    } else {
        Write-Host "   ⚠️  Could not find Cursor.exe - please start manually" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   ⚠️  Please start Cursor manually from Start Menu" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✨ Done! Remember: WAIT 30 SECONDS before checking!" -ForegroundColor Cyan
