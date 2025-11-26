# VeriCase Brand Color Update
# Replace purple (#667eea, #764ba2) with VeriCase teal/professional colors

$wizardPath = "ui\wizard.html"
$content = Get-Content $wizardPath -Raw

# VeriCase brand colors
# Primary: #1a2332 (dark navy)
# Accent: #00bcd4 (teal/cyan)
# Secondary: #0097a7 (darker teal)

$content = $content -replace '#667eea', '#00bcd4'
$content = $content -replace '#764ba2', '#0097a7'

$content | Out-File -FilePath $wizardPath -Encoding utf8 -NoNewline

Write-Host "Updated wizard.html with VeriCase brand colors"
Write-Host "Purple #667eea -> Teal #00bcd4"
Write-Host "Purple #764ba2 -> Dark Teal #0097a7"
