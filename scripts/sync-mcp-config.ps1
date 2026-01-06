param(
    # Path to the canonical MCP config (mcpServers schema). Defaults to VS Code user config.
    [string]$SourceMcpJson = (Join-Path $env:APPDATA 'Code\User\mcp.json'),

    # Write a repo-local canonical copy (gitignored) at .mcp/mcp.json
    [switch]$WriteCanonical = $true,

    # Generate/merge VS Code workspace config at .vscode/mcp.json (VS Code schema: top-level inputs/servers)
    [switch]$WriteVSCodeCline = $true,

    # Sync to KiloCode local config at .kilocode/mcp.local.json (gitignored)
    [switch]$WriteKiloLocal = $true,

    # Sync to Cursor global config at %USERPROFILE%\.cursor\mcp.json
    [switch]$WriteCursorGlobal = $false,

    # If set, overwrites existing destination files instead of merging.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Read-Json([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    return (Get-Content $Path -Raw -Encoding UTF8) | ConvertFrom-Json
}

function Write-Json([string]$Path, $Obj, [int]$Depth = 30) {
    Ensure-Dir (Split-Path $Path -Parent)
    $Obj | ConvertTo-Json -Depth $Depth | Set-Content -Path $Path -Encoding UTF8
}

function Normalize-VSCodeWorkspaceMcp($obj) {
    if (-not $obj) {
        return [pscustomobject]@{ inputs = @(); servers = [pscustomobject]@{} }
    }

    # Already new schema
    if ($obj.servers) {
        if (-not $obj.inputs) { $obj | Add-Member -MemberType NoteProperty -Name inputs -Value @() }
        return $obj
    }

    # Older nested schema: { mcp: { inputs: [...], servers: {...} } }
    if ($obj.mcp -and $obj.mcp.servers) {
        $inputs = @()
        if ($obj.mcp.inputs) { $inputs = $obj.mcp.inputs }
        return [pscustomobject]@{
            inputs  = $inputs
            servers = $obj.mcp.servers
        }
    }

    # Unknown shape; create a minimal shell.
    return [pscustomobject]@{ inputs = @(); servers = [pscustomobject]@{} }
}

function Normalize-McpServers($mcpServers) {
    if (-not $mcpServers) { return $mcpServers }

    foreach ($p in $mcpServers.PSObject.Properties) {
        $name = $p.Name
        $cfg = $p.Value

        # Ensure npx is non-interactive.
        if ($cfg.command -eq 'npx' -and $cfg.args) {
            $args = @($cfg.args)
            if (-not ($args -contains '-y')) {
                $cfg.args = @('-y') + $args
            }
        }

        # Fix Azure MCP: use dotnet dnx (dnx is a dotnet subcommand on Windows).
        if ($name -eq 'com.microsoft/azure' -and $cfg.command -eq 'dnx' -and $cfg.args) {
            $cfg.command = 'dotnet'
            $cfg.args = @('dnx') + @($cfg.args)
        }

        # Fix elasticsearch docker env passing: "-e ES_URL" not "-e $ES_URL"
        if ($name -eq 'elastic/mcp-server-elasticsearch' -and $cfg.command -eq 'docker') {
            $cfg.args = @('run', '-i', '--rm', '-e', 'ES_URL', '-e', 'ES_API_KEY', 'docker.elastic.co/mcp/elasticsearch', 'stdio')
        }
    }

    return $mcpServers
}

function Merge-Inputs($dstInputs, $srcInputs) {
    if (-not $dstInputs) { $dstInputs = @() }
    if (-not $srcInputs) { return $dstInputs }

    $seen = @{}
    foreach ($i in $dstInputs) {
        if ($i -and $i.id) { $seen[$i.id] = $true }
    }

    foreach ($i in $srcInputs) {
        if ($i -and $i.id -and -not $seen.ContainsKey($i.id)) {
            $dstInputs += $i
            $seen[$i.id] = $true
        }
    }
    return $dstInputs
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $repoRoot

if (-not (Test-Path $SourceMcpJson)) {
    throw "Source MCP config not found: $SourceMcpJson"
}

$src = Read-Json $SourceMcpJson
if (-not $src) { throw "Failed to parse JSON: $SourceMcpJson" }

# Support both schemas:
# - Cursor/KiloCode schema: { mcpServers: { ... }, inputs?: [...] }
# - VS Code schema:        { servers: { ... }, inputs?: [...] }
$srcMcpServers = $null
$srcInputs = $null

if ($src.mcpServers) {
    $srcMcpServers = $src.mcpServers
    $srcInputs = $src.inputs
} elseif ($src.servers) {
    $srcMcpServers = $src.servers
    $srcInputs = $src.inputs
} else {
    throw "Source config does not contain 'mcpServers' or 'servers': $SourceMcpJson"
}

$srcMcpServers = Normalize-McpServers $srcMcpServers

if ($WriteCanonical) {
    $canonicalPath = Join-Path $repoRoot '.mcp\mcp.json'
    $canonSrc = [pscustomobject]@{ mcpServers = $srcMcpServers }
    if ($srcInputs) { $canonSrc | Add-Member -MemberType NoteProperty -Name inputs -Value $srcInputs }
    if ((Test-Path $canonicalPath) -and (-not $Force)) {
        # Merge (keep existing but refresh servers/inputs from source)
        $canon = Read-Json $canonicalPath
        if (-not $canon) { $canon = [pscustomobject]@{} }
        $canon.mcpServers = $canonSrc.mcpServers
        if ($canonSrc.inputs) { $canon.inputs = $canonSrc.inputs }
        Write-Json $canonicalPath $canon
    } else {
        Write-Json $canonicalPath $canonSrc
    }
    Write-Host "Wrote canonical MCP config: $canonicalPath"
}

if ($WriteVSCodeCline) {
    $dstPath = Join-Path $repoRoot '.vscode\mcp.json'
    $dst = Read-Json $dstPath

    if ($Force -or (-not $dst)) {
        $dst = [pscustomobject]@{ inputs = @(); servers = [pscustomobject]@{} }
    } else {
        $dst = Normalize-VSCodeWorkspaceMcp $dst
    }

    # Merge inputs from user config into workspace config (dedupe by id).
    $dst.inputs = Merge-Inputs $dst.inputs $srcInputs

    # Merge servers: bring all user servers into workspace config.
    foreach ($p in $srcMcpServers.PSObject.Properties) {
        $name = $p.Name
        $cfg = $p.Value
        if (-not $dst.servers.PSObject.Properties[$name]) {
            $dst.servers | Add-Member -MemberType NoteProperty -Name $name -Value $cfg
        } else {
            $dst.servers.$name = $cfg
        }
    }

    Write-Json $dstPath $dst
    Write-Host "Wrote VS Code/Cline workspace MCP config: $dstPath"
}

if ($WriteKiloLocal) {
    $kiloLocal = Join-Path $repoRoot '.kilocode\mcp.local.json'
    # Prefer canonical if present
    $canonicalPath = Join-Path $repoRoot '.mcp\mcp.json'
    $fallback = [pscustomobject]@{ mcpServers = $srcMcpServers }
    if ($srcInputs) { $fallback | Add-Member -MemberType NoteProperty -Name inputs -Value $srcInputs }
    $srcForKilo = if (Test-Path $canonicalPath) { Read-Json $canonicalPath } else { $fallback }
    Write-Json $kiloLocal $srcForKilo
    Write-Host "Wrote KiloCode local MCP config: $kiloLocal"
}

if ($WriteCursorGlobal) {
    $cursorPath = Join-Path $env:USERPROFILE '.cursor\mcp.json'
    $canonicalPath = Join-Path $repoRoot '.mcp\mcp.json'
    $fallback = [pscustomobject]@{ mcpServers = $srcMcpServers }
    if ($srcInputs) { $fallback | Add-Member -MemberType NoteProperty -Name inputs -Value $srcInputs }
    $srcForCursor = if (Test-Path $canonicalPath) { Read-Json $canonicalPath } else { $fallback }
    Write-Json $cursorPath $srcForCursor
    Write-Host "Wrote Cursor global MCP config: $cursorPath"
}

Write-Host "Done. Next: reload VS Code and run 'MCP: Restart Servers'."




