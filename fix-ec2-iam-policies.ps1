# VeriCase - Fix All IAM Policies for EC2 Deployment
# Run this script to attach all required policies to the EC2 instance role

$ErrorActionPreference = "Stop"
$Region = "eu-west-2"
$AccountId = "526015377510"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "VeriCase EC2 IAM Policy Fix Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if AWS CLI is available
try {
    aws --version | Out-Null
} catch {
    Write-Host "[ERROR] AWS CLI not found. Please install it first." -ForegroundColor Red
    exit 1
}

# Find the EC2 instance role
Write-Host "Finding EC2 instance role..." -ForegroundColor Yellow
$InstanceId = "i-0$(aws ec2 describe-instances --filters "Name=ip-address,Values=18.130.216.34" --query 'Reservations[0].Instances[0].InstanceId' --output text --region $Region 2>$null)"

# Try common role names
$PossibleRoles = @(
    "VeriCaseEC2Role",
    "VeriCaseInstanceRole", 
    "EC2-VeriCase-Role",
    "vericase-ec2-role"
)

$RoleName = $null
foreach ($role in $PossibleRoles) {
    try {
        aws iam get-role --role-name $role --region $Region 2>$null | Out-Null
        $RoleName = $role
        Write-Host "  Found role: $RoleName" -ForegroundColor Green
        break
    } catch {
        continue
    }
}

if (-not $RoleName) {
    Write-Host "  [WARN] Could not auto-detect EC2 role. Using 'VeriCaseEC2Role'" -ForegroundColor Yellow
    $RoleName = "VeriCaseEC2Role"
    
    # Create the role if it doesn't exist
    Write-Host "  Creating EC2 role..." -ForegroundColor Gray
    $TrustPolicy = @{
        Version = "2012-10-17"
        Statement = @(
            @{
                Effect = "Allow"
                Principal = @{ Service = "ec2.amazonaws.com" }
                Action = "sts:AssumeRole"
            }
        )
    } | ConvertTo-Json -Depth 10
    
    try {
        aws iam create-role --role-name $RoleName --assume-role-policy-document $TrustPolicy --region $Region 2>$null | Out-Null
        Write-Host "  [OK] Created role: $RoleName" -ForegroundColor Green
    } catch {
        Write-Host "  Role may already exist, continuing..." -ForegroundColor Gray
    }
}

Write-Host ""

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
Write-Host "  [OK] S3 policy attached to $RoleName" -ForegroundColor Green

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

# 4. Verify the secret exists
Write-Host "[4/4] Verifying Secrets Manager secret..." -ForegroundColor Yellow
$SecretName = "vericase/ai-api-keys"
try {
    $secretInfo = aws secretsmanager describe-secret --secret-id $SecretName --region $Region 2>$null | ConvertFrom-Json
    Write-Host "  [OK] Secret '$SecretName' exists" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] Secret '$SecretName' not found - create it in AWS Console" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "IAM policies attached to: $RoleName" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Ensure EC2 instance has this IAM role attached" -ForegroundColor White
Write-Host "2. Push code to GitHub to trigger rebuild" -ForegroundColor White
Write-Host "3. SSH to EC2 and restart Docker container:" -ForegroundColor White
Write-Host "   docker-compose down && docker-compose up -d" -ForegroundColor Gray
Write-Host ""
Write-Host "Or trigger GitHub Actions rebuild:" -ForegroundColor White
Write-Host "   git add . && git commit -m 'Fix f-strings and add Secrets Manager' && git push" -ForegroundColor Gray
