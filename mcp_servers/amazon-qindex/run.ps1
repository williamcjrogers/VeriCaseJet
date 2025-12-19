# Amazon Q Index MCP Server Wrapper
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $scriptDir ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"

# Check if virtual environment exists
if (-not (Test-Path $pythonExe)) {
    Write-Host "Creating virtual environment..."
    python -m venv $venvDir
    
    Write-Host "Installing dependencies..."
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -r (Join-Path $scriptDir "requirements.txt")
}

# Run the server
& $pythonExe -m awslabs.amazon_qindex_mcp_server.server
