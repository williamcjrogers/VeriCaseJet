# Script to add all AWS MCP servers to .vscode/mcp.json configuration

$mcpConfigPath = ".vscode\mcp.json"

Write-Host "Adding AWS MCP servers to $mcpConfigPath..." -ForegroundColor Cyan

# Define all AWS MCP servers to add
$awsServers = @{
    "awslabs.ec2-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.ec2-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.lambda-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.lambda-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.ecs-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.ecs-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.eks-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.eks-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs-fargate-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs-fargate-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs-s3-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs-s3-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs-rds-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs-rds-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.dynamodb-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.dynamodb-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.postgres-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.postgres-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.mysql-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.mysql-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.cloudwatch-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.cloudwatch-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.cdk-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.cdk-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.terraform-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.terraform-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.iam-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.iam-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.cost-explorer-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.cost-explorer-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.bedrock-kb-retrieval-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.bedrock-kb-retrieval-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
    "awslabs.sagemaker-ai-mcp-server" = @{
        "command" = "`${workspaceFolder}/.venv/Scripts/awslabs.sagemaker-ai-mcp-server.exe"
        "args" = @()
        "env" = @{
            "AWS_PROFILE" = "`${input:aws_profile}"
            "AWS_REGION" = "`${input:aws_region}"
            "FASTMCP_LOG_LEVEL" = "ERROR"
        }
    }
}

# Read existing config
$config = Get-Content $mcpConfigPath -Raw | ConvertFrom-Json

# Add new servers (skip if already exists)
$addedCount = 0
foreach ($serverName in $awsServers.Keys) {
    if (-not $config.mcp.servers.PSObject.Properties[$serverName]) {
        Write-Host "Adding $serverName..." -ForegroundColor Green
        $config.mcp.servers | Add-Member -MemberType NoteProperty -Name $serverName -Value $awsServers[$serverName]
        $addedCount++
    } else {
        Write-Host "Skipping $serverName (already exists)" -ForegroundColor Yellow
    }
}

# Save updated config
$config | ConvertTo-Json -Depth 10 | Set-Content $mcpConfigPath

Write-Host "`nConfiguration updated!" -ForegroundColor Green
Write-Host "Added $addedCount new AWS MCP servers to $mcpConfigPath" -ForegroundColor Cyan
Write-Host "`nPlease reload VS Code to activate the new MCP servers." -ForegroundColor Yellow
