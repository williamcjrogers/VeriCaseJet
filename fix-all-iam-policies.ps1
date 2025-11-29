# VeriCase - Fix All IAM Policies for App Runner
# Run this script to attach all required policies to the App Runner instance role

$ErrorActionPreference = "Stop"
$Region = "eu-west-2"
$RoleName = "VeriCaseAppRunnerInstanceRole"
$AccountId = "526015377510"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "VeriCase IAM Policy Fix Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if AWS CLI is available
try {
    aws --version | Out-Null
} catch {
    Write-Host "[ERROR] AWS CLI not found. Please install it first." -ForegroundColor Red
    exit 1
}

# 1. Create and attach S3 policy
Write-Host "[1/4] Creating S3 access policy..." -ForegroundColor Yellow
$S3PolicyName = "VeriCaseS3AccessPolicy"
$S3PolicyArn = "arn:aws:iam::${AccountId}:policy/${S3PolicyName}"

try {
    aws iam get-policy --policy-arn $S3PolicyArn --region $Region 2>$null | Out-Null
    Write-Host "  Policy exists, updating..." -ForegroundColor Gray
    $versions = aws iam list-policy-versions --policy-arn $S3PolicyArn --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text --region $Region
    foreach ($v in $versions -split '\s+') {
        if ($v) { aws iam delete-policy-version --policy-arn $S3PolicyArn --version-id $v --region $Region 2>$null }
    }
    aws iam create-policy-version --policy-arn $S3PolicyArn --policy-document file://pst-analysis-engine/iam-policies/apprunner-s3-policy.json --set-as-default --region $Region | Out-Null
} catch {
    aws iam create-policy --policy-name $S3PolicyName --policy-document file://pst-analysis-engine/iam-policies/apprunner-s3-policy.json --region $Region | Out-Null
}
aws iam attach-role-policy --role-name $RoleName --policy-arn $S3PolicyArn --region $Region 2>$null
Write-Host "  [OK] S3 policy attached" -ForegroundColor Green

# 2. Create and attach Secrets Manager policy
Write-Host "[2/4] Creating Secrets Manager access policy..." -ForegroundColor Yellow
$SecretsPolicy = "VeriCaseSecretsManagerPolicy"
$SecretsPolicyArn = "arn:aws:iam::${AccountId}:policy/${SecretsPolicy}"

try {
    aws iam get-policy --policy-arn $SecretsPolicyArn --region $Region 2>$null | Out-Null
    Write-Host "  Policy exists, updating..." -ForegroundColor Gray
    $versions = aws iam list-policy-versions --policy-arn $SecretsPolicyArn --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text --region $Region
    foreach ($v in $versions -split '\s+') {
        if ($v) { aws iam delete-policy-version --policy-arn $SecretsPolicyArn --version-id $v --region $Region 2>$null }
    }
    aws iam create-policy-version --policy-arn $SecretsPolicyArn --policy-document file://pst-analysis-engine/iam-policies/apprunner-secrets-policy.json --set-as-default --region $Region | Out-Null
} catch {
    aws iam create-policy --policy-name $SecretsPolicy --policy-document file://pst-analysis-engine/iam-policies/apprunner-secrets-policy.json --region $Region | Out-Null
}
aws iam attach-role-policy --role-name $RoleName --policy-arn $SecretsPolicyArn --region $Region 2>$null
Write-Host "  [OK] Secrets Manager policy attached" -ForegroundColor Green

# 3. Create and attach OpenSearch policy
Write-Host "[3/4] Creating OpenSearch access policy..." -ForegroundColor Yellow
$OSPolicyName = "VeriCaseOpenSearchPolicy"
$OSPolicyArn = "arn:aws:iam::${AccountId}:policy/${OSPolicyName}"

try {
    aws iam get-policy --policy-arn $OSPolicyArn --region $Region 2>$null | Out-Null
    Write-Host "  Policy exists, updating..." -ForegroundColor Gray
    $versions = aws iam list-policy-versions --policy-arn $OSPolicyArn --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text --region $Region
    foreach ($v in $versions -split '\s+') {
        if ($v) { aws iam delete-policy-version --policy-arn $OSPolicyArn --version-id $v --region $Region 2>$null }
    }
    aws iam create-policy-version --policy-arn $OSPolicyArn --policy-document file://pst-analysis-engine/iam-policies/apprunner-opensearch-policy.json --set-as-default --region $Region | Out-Null
} catch {
    aws iam create-policy --policy-name $OSPolicyName --policy-document file://pst-analysis-engine/iam-policies/apprunner-opensearch-policy.json --region $Region | Out-Null
}
aws iam attach-role-policy --role-name $RoleName --policy-arn $OSPolicyArn --region $Region 2>$null
Write-Host "  [OK] OpenSearch policy attached" -ForegroundColor Green

# 4. Create the AI API keys secret if it doesn't exist
Write-Host "[4/4] Checking Secrets Manager secret..." -ForegroundColor Yellow
$SecretName = "vericase/ai-api-keys"
try {
    aws secretsmanager describe-secret --secret-id $SecretName --region $Region 2>$null | Out-Null
    Write-Host "  Secret '$SecretName' already exists" -ForegroundColor Gray
} catch {
    Write-Host "  Creating secret '$SecretName'..." -ForegroundColor Gray
    $secretValue = @{
        OPENAI_API_KEY = ""
        ANTHROPIC_API_KEY = ""
        GEMINI_API_KEY = ""
        GROK_API_KEY = ""
        PERPLEXITY_API_KEY = ""
    } | ConvertTo-Json -Compress
    aws secretsmanager create-secret --name $SecretName --secret-string $secretValue --region $Region | Out-Null
    Write-Host "  [OK] Secret created (add your API keys via AWS Console)" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "All IAM policies attached successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Add your AI API keys to Secrets Manager:" -ForegroundColor White
Write-Host "   aws secretsmanager put-secret-value --secret-id vericase/ai-api-keys --secret-string '{""OPENAI_API_KEY"":""sk-..."",""ANTHROPIC_API_KEY"":""sk-ant-...""}' --region eu-west-2" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Update OpenSearch domain access policy (in AWS Console):" -ForegroundColor White
Write-Host "   - Go to OpenSearch Service > vericase-opensearch > Security" -ForegroundColor Gray
Write-Host "   - Add the App Runner role ARN to the access policy" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Restart App Runner service to apply changes:" -ForegroundColor White
Write-Host "   aws apprunner start-deployment --service-arn <your-service-arn> --region eu-west-2" -ForegroundColor Gray
