param(
    # Path to the canonical MCP config (mcpServers schema). Defaults to VS Code user config.
    [string]$SourceMcpJson = (Join-Path $env:APPDATA 'Code\User\mcp.json'),

    # Write a repo-local canonical copy (gitignored) at .mcp/mcp.json
    [switch]$WriteCanonical = $true,

    # Generate/merge VS Code/Cline workspace config at .vscode/mcp.json (mcp.servers schema)
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

if (-not $src.mcpServers) {
    throw "Source config does not contain 'mcpServers': $SourceMcpJson"
}

$src.mcpServers = Normalize-McpServers $src.mcpServers

if ($WriteCanonical) {
    $canonicalPath = Join-Path $repoRoot '.mcp\mcp.json'
    if ((Test-Path $canonicalPath) -and (-not $Force)) {
        # Merge (keep existing but refresh servers/inputs from source)
        $canon = Read-Json $canonicalPath
        if (-not $canon) { $canon = [pscustomobject]@{} }
        $canon.mcpServers = $src.mcpServers
        if ($src.inputs) { $canon.inputs = $src.inputs }
        Write-Json $canonicalPath $canon
    } else {
        Write-Json $canonicalPath $src
    }
    Write-Host "Wrote canonical MCP config: $canonicalPath"
}

if ($WriteVSCodeCline) {
    $dstPath = Join-Path $repoRoot '.vscode\mcp.json'
    $dst = Read-Json $dstPath

    if ($Force -or (-not $dst)) {
        $dst = [pscustomobject]@{ mcp = [pscustomobject]@{ inputs = @(); servers = [pscustomobject]@{} } }
    } elseif (-not $dst.mcp) {
        $dst | Add-Member -MemberType NoteProperty -Name mcp -Value ([pscustomobject]@{ inputs=@(); servers=[pscustomobject]@{} })
    }

    if (-not $dst.mcp.inputs) { $dst.mcp | Add-Member -MemberType NoteProperty -Name inputs -Value @() }
    if (-not $dst.mcp.servers) { $dst.mcp | Add-Member -MemberType NoteProperty -Name servers -Value ([pscustomobject]@{}) }

    # Merge inputs from user config into workspace config (dedupe by id).
    $dst.mcp.inputs = Merge-Inputs $dst.mcp.inputs $src.inputs

    # Merge servers: bring all user servers into workspace config.
    foreach ($p in $src.mcpServers.PSObject.Properties) {
        $name = $p.Name
        $cfg = $p.Value
        if (-not $dst.mcp.servers.PSObject.Properties[$name]) {
            $dst.mcp.servers | Add-Member -MemberType NoteProperty -Name $name -Value $cfg
        } else {
            $dst.mcp.servers.$name = $cfg
        }
    }

    Write-Json $dstPath $dst
    Write-Host "Wrote VS Code/Cline workspace MCP config: $dstPath"
}

if ($WriteKiloLocal) {
    $kiloLocal = Join-Path $repoRoot '.kilocode\mcp.local.json'
    # Prefer canonical if present
    $canonicalPath = Join-Path $repoRoot '.mcp\mcp.json'
    $srcForKilo = if (Test-Path $canonicalPath) { Read-Json $canonicalPath } else { $src }
    Write-Json $kiloLocal $srcForKilo
    Write-Host "Wrote KiloCode local MCP config: $kiloLocal"
}

if ($WriteCursorGlobal) {
    $cursorPath = Join-Path $env:USERPROFILE '.cursor\mcp.json'
    $canonicalPath = Join-Path $repoRoot '.mcp\mcp.json'
    $srcForCursor = if (Test-Path $canonicalPath) { Read-Json $canonicalPath } else { $src }
    Write-Json $cursorPath $srcForCursor
    Write-Host "Wrote Cursor global MCP config: $cursorPath"
}

Write-Host "Done. Next: reload VS Code and run 'MCP: Restart Servers'."




