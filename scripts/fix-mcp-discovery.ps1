# Fix MCP Server Discovery Conflicts
# Disables multiple discovery sources that cause MCP servers to be "forgotten"

Write-Host "🔧 MCP Server Discovery Fix" -ForegroundColor Cyan
Write-Host "=" * 60

# Backup current settings
$settingsPath = ".vscode\settings.json"
$backupPath = ".vscode\settings.json.backup"

if (Test-Path $settingsPath) {
    Copy-Item $settingsPath $backupPath
    Write-Host "✅ Backed up settings to: $backupPath" -ForegroundColor Green
}

# Read current settings
$settings = Get-Content $settingsPath | ConvertFrom-Json

# Fix: Disable all MCP discovery sources except workspace
Write-Host "`n🎯 Fixing MCP Discovery Settings..." -ForegroundColor Yellow

$settings.'chat.mcp.discovery.enabled' = @{
    "claude-desktop" = $false
    "windsurf" = $false
    "cursor-global" = $false
    "cursor-workspace" = $true
}

Write-Host "  ✅ Disabled: claude-desktop" -ForegroundColor Green
Write-Host "  ✅ Disabled: windsurf" -ForegroundColor Green
Write-Host "  ✅ Disabled: cursor-global" -ForegroundColor Green
Write-Host "  ✅ Enabled: cursor-workspace (ONLY)" -ForegroundColor Green

# Save updated settings
$settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath

Write-Host "`n✅ Settings updated successfully!" -ForegroundColor Green

# Summary
Write-Host "`n" + "=" * 60
Write-Host "📊 WHAT WAS FIXED" -ForegroundColor Cyan
Write-Host "=" * 60

Write-Host "
✅ BEFORE: Multiple MCP discovery sources were enabled
   - This caused Cursor to look for MCP configs in multiple places
   - Configs could conflict or override each other
   - MCP servers appeared 'forgotten' after restart

✅ AFTER: Only workspace discovery is enabled
   - Cursor will ONLY use .vscode/mcp.json
   - No more conflicts from global/Claude Desktop configs
   - MCP servers will persist properly

" -ForegroundColor White

Write-Host "🎯 NEXT STEPS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. Reload Cursor to apply changes:" -ForegroundColor Cyan
Write-Host "   Press: Ctrl+Shift+P → 'Developer: Reload Window'" -ForegroundColor White
Write-Host ""
Write-Host "2. Verify MCP servers loaded:" -ForegroundColor Cyan
Write-Host "   Press: Ctrl+Shift+P → 'MCP: Show Servers'" -ForegroundColor White
Write-Host "   You should see all 37 servers" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Test a server:" -ForegroundColor Cyan
Write-Host "   Ask AI: 'List my AWS EC2 instances'" -ForegroundColor White
Write-Host ""

Write-Host "✨ If issues persist, run: ./scripts/diagnose-mcp.ps1" -ForegroundColor Green
