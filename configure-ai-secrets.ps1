# PowerShell script to configure AI API keys in AWS Secrets Manager

$ErrorActionPreference = "Stop"

Write-Host "=== Configuring AI API Keys in AWS Secrets Manager ===" -ForegroundColor Green

# Get AWS account info
$accountId = aws sts get-caller-identity --query Account --output text
Write-Host "AWS Account: $accountId"

# Secret name
$secretName = "vericase/ai-api-keys"
$region = "eu-west-2"

# Create the secret with AI API keys
$secretValue = @{
    OPENAI_API_KEY = "sk-your-openai-api-key-here"
    ANTHROPIC_API_KEY = "sk-ant-your-anthropic-key-here"
    GEMINI_API_KEY = "AIza-your-gemini-key-here"
    GROK_API_KEY = "xai-your-grok-key-here"
    PERPLEXITY_API_KEY = "pplx-your-perplexity-key-here"
} | ConvertTo-Json

Write-Host "`nCreating/updating secret: $secretName"

# Try to create the secret
try {
    aws secretsmanager create-secret `
        --name $secretName `
        --description "AI API keys for VeriCase application" `
        --secret-string $secretValue `
        --region $region
    Write-Host "✓ Secret created successfully" -ForegroundColor Green
} catch {
    # If secret exists, update it
    Write-Host "Secret already exists, updating..."
    aws secretsmanager update-secret `
        --secret-id $secretName `
        --secret-string $secretValue `
        --region $region
    Write-Host "✓ Secret updated successfully" -ForegroundColor Green
}

# Get the App Runner instance role
Write-Host "`nFinding App Runner instance role..."
$serviceName = "VeriCase"
$serviceArn = aws apprunner list-services --query "ServiceSummaryList[?ServiceName=='$serviceName'].ServiceArn | [0]" --output text

if ($serviceArn -eq "None") {
    Write-Host "Error: App Runner service 'VeriCase' not found" -ForegroundColor Red
    exit 1
}

$service = aws apprunner describe-service --service-arn $serviceArn --output json | ConvertFrom-Json
$instanceRoleArn = $service.Service.InstanceConfiguration.InstanceRoleArn

if (!$instanceRoleArn) {
    Write-Host "Error: No instance role found for App Runner service" -ForegroundColor Red
    Write-Host "Please assign the VeriCaseAppRunnerInstanceRole to your service first" -ForegroundColor Yellow
    exit 1
}

$roleName = $instanceRoleArn.Split("/")[-1]
Write-Host "Found role: $roleName"

# Create policy for Secrets Manager access
$policyName = "VeriCaseSecretsAccess"
$policyDocument = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Effect = "Allow"
            Action = @(
                "secretsmanager:GetSecretValue",
                "secretsmanager:DescribeSecret"
            )
            Resource = "arn:aws:secretsmanager:${region}:${accountId}:secret:vericase/*"
        }
    )
} | ConvertTo-Json -Depth 5

Write-Host "`nCreating IAM policy for Secrets Manager access..."
$policyFile = "secrets-policy.json"
$policyDocument | Out-File -FilePath $policyFile -Encoding UTF8

try {
    # Create policy
    $policyArn = aws iam create-policy `
        --policy-name $policyName `
        --policy-document file://$policyFile `
        --description "Allows VeriCase App Runner to access secrets" `
        --query Policy.Arn --output text
    Write-Host "✓ Policy created: $policyArn" -ForegroundColor Green
} catch {
    # Policy might already exist
    $policyArn = "arn:aws:iam::${accountId}:policy/$policyName"
    Write-Host "Policy already exists: $policyArn"
}

# Attach policy to role
Write-Host "`nAttaching policy to role..."
aws iam attach-role-policy --role-name $roleName --policy-arn $policyArn
Write-Host "✓ Policy attached successfully" -ForegroundColor Green

# Clean up
Remove-Item $policyFile -ErrorAction SilentlyContinue

Write-Host "`n=== Next Steps ===" -ForegroundColor Yellow
Write-Host "1. Update your actual API keys in AWS Secrets Manager:"
Write-Host "   - Go to AWS Secrets Manager console"
Write-Host "   - Find secret: $secretName"
Write-Host "   - Click 'Retrieve secret value'"
Write-Host "   - Click 'Edit'"
Write-Host "   - Replace placeholder values with your actual API keys"
Write-Host ""
Write-Host "2. Update apprunner.yaml to use Secrets Manager (see next file)"
Write-Host ""
Write-Host "3. Redeploy your App Runner service"
