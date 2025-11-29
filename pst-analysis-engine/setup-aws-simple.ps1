# VeriCase AWS Quick Setup - Minimal Version
# This script sets up just the essential services to get you started

Write-Host "🚀 VeriCase AWS Quick Setup" -ForegroundColor Green

# Check AWS CLI
if (!(Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Please install AWS CLI first: https://aws.amazon.com/cli/" -ForegroundColor Red
    exit 1
}

# Check credentials
try {
    $Account = aws sts get-caller-identity --query Account --output text
    Write-Host "✅ AWS Account: $Account" -ForegroundColor Green
} catch {
    Write-Host "❌ Run 'aws configure' to set up credentials" -ForegroundColor Red
    exit 1
}

# Create S3 bucket for documents
$BucketName = "vericase-docs-$(Get-Random)"
Write-Host "📦 Creating S3 bucket: $BucketName" -ForegroundColor Blue

aws s3 mb s3://$BucketName --region us-east-1

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ S3 bucket created" -ForegroundColor Green
} else {
    Write-Host "❌ S3 bucket creation failed" -ForegroundColor Red
    exit 1
}

# Enable S3 event notifications
aws s3api put-bucket-notification-configuration `
    --bucket $BucketName `
    --notification-configuration '{
        "EventBridgeConfiguration": {}
    }'

# Create basic configuration
$Config = @"
# VeriCase AWS Configuration
USE_AWS_SERVICES=true
AWS_REGION=us-east-1
S3_BUCKET=$BucketName

# Enable AI features
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
AI_DEFAULT_MODEL=textract
"@

$Config | Out-File -FilePath ".env.aws" -Encoding UTF8

Write-Host "✅ Configuration saved to .env.aws" -ForegroundColor Green

# Test S3 access
Write-Host "🧪 Testing S3 access..." -ForegroundColor Blue
$TestFile = "test-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
"VeriCase AWS Test" | Out-File -FilePath $TestFile -Encoding UTF8

aws s3 cp $TestFile s3://$BucketName/test/

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ S3 upload test successful" -ForegroundColor Green
    aws s3 rm s3://$BucketName/test/$TestFile
    Remove-Item $TestFile
} else {
    Write-Host "⚠️  S3 upload test failed" -ForegroundColor Yellow
}

Write-Host "`n🎉 Quick Setup Complete!" -ForegroundColor Green
Write-Host "S3 Bucket: $BucketName" -ForegroundColor White
Write-Host "Config File: .env.aws" -ForegroundColor White
Write-Host "`nNext: Copy .env.aws to .env and restart your app" -ForegroundColor Yellow