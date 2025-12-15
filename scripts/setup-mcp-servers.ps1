param(
    [switch]$WriteVSCodeConfig = $true,
    [switch]$Force
)

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

if ($WriteVSCodeConfig) {
    $vscodeDir = Join-Path $repoRoot '.vscode'
    $mcpConfigPath = Join-Path $vscodeDir 'mcp.json'

    if (-not (Test-Path $vscodeDir)) {
        New-Item -ItemType Directory -Path $vscodeDir | Out-Null
    }

    if ((-not (Test-Path $mcpConfigPath)) -or $Force) {
        $mcpConfig = @{
            mcp = @{
                inputs  = @(
                    @{
                        type        = 'promptString'
                        id          = 'sqlite_db_path'
                        description = 'SQLite Database Path'
                        default     = '${workspaceFolder}/db.sqlite'
                    },
                    @{
                        type        = 'promptString'
                        id          = 'aws_profile'
                        description = 'AWS profile (for AWS MCP servers)'
                        default     = 'default'
                    },
                    @{
                        type        = 'promptString'
                        id          = 'aws_region'
                        description = 'AWS region (for AWS MCP servers)'
                        default     = 'eu-west-2'
                    },
                    @{
                        type        = 'promptString'
                        id          = 'ssh_host'
                        description = 'SSH host (hostname or IP)'
                        default     = '18.175.232.87'
                    },
                    @{
                        type        = 'promptString'
                        id          = 'ssh_user'
                        description = 'SSH username'
                        default     = 'ec2-user'
                    },
                    @{
                        type        = 'promptString'
                        id          = 'ssh_port'
                        description = 'SSH port'
                        default     = '22'
                    },
                    @{
                        type        = 'promptString'
                        id          = 'ssh_key_path'
                        description = 'SSH private key path'
                        default     = '${env:USERPROFILE}/.ssh/VeriCase-Safe.pem'
                    },
                    @{
                        type        = 'promptString'
                        id          = 'ssh_known_hosts_path'
                        description = 'SSH known_hosts path (used when strict host key checking is enabled)'
                        default     = '${env:USERPROFILE}/.ssh/known_hosts'
                    }
                )
                servers = @{
                    fetch  = @{
                        command = '${workspaceFolder}/.venv/Scripts/python.exe'
                        args    = @('-m', 'mcp_server_fetch')
                    }
                    time   = @{
                        command = '${workspaceFolder}/.venv/Scripts/python.exe'
                        args    = @('-m', 'mcp_server_time')
                    }
                    git    = @{
                        command = '${workspaceFolder}/.venv/Scripts/python.exe'
                        args    = @('-m', 'mcp_server_git', '--repository', '${workspaceFolder}')
                    }
                    sqlite = @{
                        command = '${workspaceFolder}/.venv/Scripts/python.exe'
                        args    = @('-m', 'mcp_server_sqlite.server', '--db-path', '${input:sqlite_db_path}')
                    }
                    'awslabs.core-mcp-server' = @{
                        command = '${workspaceFolder}/.venv/Scripts/awslabs.core-mcp-server.exe'
                        args    = @()
                        env     = @{
                            AWS_PROFILE      = '${input:aws_profile}'
                            AWS_REGION       = '${input:aws_region}'
                            FASTMCP_LOG_LEVEL = 'ERROR'
                        }
                    }
                    'awslabs.ccapi-mcp-server' = @{
                        command = '${workspaceFolder}/.venv/Scripts/awslabs.ccapi-mcp-server.exe'
                        args    = @('--readonly')
                        env     = @{
                            AWS_PROFILE      = '${input:aws_profile}'
                            AWS_REGION       = '${input:aws_region}'
                            FASTMCP_LOG_LEVEL = 'ERROR'
                        }
                    }
                    ssh = @{
                        command = '${workspaceFolder}/.venv/Scripts/python.exe'
                        args    = @('-m', 'mcp_ssh_server', '--transport', 'stdio')
                        env     = @{
                            SSH_HOST                    = '${input:ssh_host}'
                            SSH_USER                    = '${input:ssh_user}'
                            SSH_PORT                    = '${input:ssh_port}'
                            SSH_PRIVATE_KEY_PATH        = '${input:ssh_key_path}'
                            SSH_STRICT_HOST_KEY_CHECKING = 'true'
                            SSH_KNOWN_HOSTS_PATH         = '${input:ssh_known_hosts_path}'
                        }
                    }
                }
            }
        }

        $mcpConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $mcpConfigPath -Encoding UTF8
        Write-Host "Wrote VS Code MCP config: $mcpConfigPath"
    } else {
        Write-Host "VS Code MCP config already exists: $mcpConfigPath (use -Force to overwrite)"
    }
}

Write-Host "MCP server venv ready at: $venvPython"
Write-Host 'Next: VS Code Command Palette -> MCP: List Servers -> Start/Restart servers (or reload window).'
