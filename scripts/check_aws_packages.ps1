$packages = @(
    'awslabs.lambda-mcp-server',
    'awslabs.ecs-mcp-server',
    'awslabs.eks-mcp-server',
    'awslabs-fargate-mcp-server',
    'awslabs-s3-mcp-server',
    'awslabs-rds-mcp-server',
    'awslabs.dynamodb-mcp-server',
    'awslabs.postgres-mcp-server',
    'awslabs.mysql-mcp-server',
    'awslabs.cloudwatch-mcp-server',
    'awslabs.cdk-mcp-server',
    'awslabs.terraform-mcp-server',
    'awslabs.iam-mcp-server',
    'awslabs.cost-explorer-mcp-server',
    'awslabs.bedrock-kb-retrieval-mcp-server',
    'awslabs.sagemaker-ai-mcp-server'
)

foreach ($pkg in $packages) {
    Write-Host "`n=== Checking $pkg ===" -ForegroundColor Cyan
    .\.venv\Scripts\python.exe -m pip index versions $pkg 2>&1 | Select-Object -First 3
}
