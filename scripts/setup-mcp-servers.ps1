$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            py -3.11 -m venv .venv
        } catch {
            py -3 -m venv .venv
        }
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv .venv
    } else {
        throw 'Python not found (expected py.exe or python.exe on PATH).'
    }
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $repoRoot 'scripts\mcp-servers-requirements.txt')

Write-Host "MCP server venv ready at: $venvPython"
Write-Host 'Next: VS Code Command Palette -> MCP: List Servers -> Start/Restart servers (or reload window).'
