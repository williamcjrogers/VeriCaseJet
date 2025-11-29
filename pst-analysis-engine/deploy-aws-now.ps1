# Deploy AWS Services for VeriCase
Write-Host "🚀 Deploying AWS Services..." -ForegroundColor Green

# Check AWS CLI
if (!(Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "❌ AWS CLI not found" -ForegroundColor Red
    exit 1
}

# Test AWS credentials
try {
    aws sts get-caller-identity | Out-Null
    Write-Host "✅ AWS credentials OK" -ForegroundColor Green
} catch {
    Write-Host "❌ AWS credentials failed" -ForegroundColor Red
    exit 1
}

# Get account ID
$AccountId = (aws sts get-caller-identity --query Account --output text)
Write-Host "Account ID: $AccountId" -ForegroundColor Yellow

# Create S3 buckets
$DocsBucket = "vericase-docs-$AccountId"
$KBBucket = "vericase-kb-$AccountId"

Write-Host "Creating S3 buckets..." -ForegroundColor Blue
aws s3 mb s3://$DocsBucket --region us-east-1 2>$null
aws s3 mb s3://$KBBucket --region us-east-1 2>$null

# Enable EventBridge on docs bucket
aws s3api put-bucket-notification-configuration --bucket $DocsBucket --notification-configuration '{"EventBridgeConfiguration":{}}'

Write-Host "✅ S3 buckets created" -ForegroundColor Green

# Create .env.aws config
$Config = @"
USE_AWS_SERVICES=true
AWS_REGION=us-east-1
S3_BUCKET=$DocsBucket
KNOWLEDGE_BASE_BUCKET=$KBBucket
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
"@

$Config | Out-File -FilePath ".env.aws" -Encoding UTF8
Write-Host "✅ Configuration created: .env.aws" -ForegroundColor Green

# Copy to .env
Copy-Item ".env.aws" ".env" -Force
Write-Host "✅ Configuration activated" -ForegroundColor Green

Write-Host "`n🎉 AWS Services Deployed!" -ForegroundColor Green
Write-Host "Buckets: $DocsBucket, $KBBucket" -ForegroundColor White
Write-Host "Restart VeriCase to use AWS services" -ForegroundColor Yellow