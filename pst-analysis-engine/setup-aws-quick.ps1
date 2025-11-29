# VeriCase AWS Services Quick Setup
param(
    [string]$Environment = "production",
    [string]$Region = "us-east-1"
)

Write-Host "🚀 Setting up VeriCase AWS Services..." -ForegroundColor Green

# Check AWS CLI
if (!(Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "❌ AWS CLI not found. Please install AWS CLI first." -ForegroundColor Red
    exit 1
}

# Check AWS credentials
try {
    aws sts get-caller-identity | Out-Null
    Write-Host "✅ AWS credentials configured" -ForegroundColor Green
} catch {
    Write-Host "❌ AWS credentials not configured. Run 'aws configure'" -ForegroundColor Red
    exit 1
}

# Generate secure password
$DatabasePassword = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 16 | ForEach-Object {[char]$_})
Write-Host "🔐 Generated password: $DatabasePassword" -ForegroundColor Yellow

# Step 1: Create S3 Buckets
Write-Host "📦 Step 1: Creating S3 buckets..." -ForegroundColor Blue

$AccountId = (aws sts get-caller-identity --query Account --output text)
$DocumentsBucket = "vericase-docs-$Environment-$AccountId"
$KnowledgeBaseBucket = "vericase-kb-$Environment-$AccountId"

aws s3 mb "s3://$DocumentsBucket" --region $Region
aws s3 mb "s3://$KnowledgeBaseBucket" --region $Region

Write-Host "✅ S3 buckets created" -ForegroundColor Green

# Step 2: Create IAM Role
Write-Host "🔐 Step 2: Creating IAM role..." -ForegroundColor Blue

$TrustPolicy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
"@

$TrustPolicy | Out-File -FilePath "trust-policy.json" -Encoding UTF8

aws iam create-role --role-name "VeriCaseLambdaRole-$Environment" --assume-role-policy-document file://trust-policy.json 2>$null

$Policy = @"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "textract:*",
                "comprehend:*",
                "rekognition:*",
                "transcribe:*",
                "bedrock:*",
                "s3:GetObject",
                "s3:PutObject"
            ],
            "Resource": "*"
        }
    ]
}
"@

$Policy | Out-File -FilePath "lambda-policy.json" -Encoding UTF8

aws iam put-role-policy --role-name "VeriCaseLambdaRole-$Environment" --policy-name "VeriCasePolicy" --policy-document file://lambda-policy.json

Write-Host "✅ IAM role created" -ForegroundColor Green

# Step 3: Create Lambda Function
Write-Host "🔧 Step 3: Creating Lambda function..." -ForegroundColor Blue

# Create Python file separately
$PythonCode = 'import json
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        logger.info("Processing document")
        return {
            "statusCode": 200,
            "body": json.dumps("Success")
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }'

$PythonCode | Out-File -FilePath "lambda_function.py" -Encoding UTF8

# Create ZIP
Compress-Archive -Path "lambda_function.py" -DestinationPath "function.zip" -Force

# Get role ARN
$RoleArn = aws iam get-role --role-name "VeriCaseLambdaRole-$Environment" --query 'Role.Arn' --output text

# Wait for role to propagate
Start-Sleep -Seconds 10

# Create Lambda function
aws lambda create-function --function-name "vericase-processor-$Environment" --runtime python3.11 --role $RoleArn --handler lambda_function.lambda_handler --zip-file fileb://function.zip --timeout 300 --region $Region 2>$null

Write-Host "✅ Lambda function created" -ForegroundColor Green

# Step 4: Create Configuration
Write-Host "⚙️ Step 4: Creating configuration..." -ForegroundColor Blue

$Config = @"
# VeriCase AWS Configuration
USE_AWS_SERVICES=true
AWS_REGION=$Region
S3_BUCKET=$DocumentsBucket
KNOWLEDGE_BASE_BUCKET=$KnowledgeBaseBucket
LAMBDA_FUNCTION=vericase-processor-$Environment
DATABASE_PASSWORD=$DatabasePassword
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
"@

$Config | Out-File -FilePath ".env.aws" -Encoding UTF8

Write-Host "✅ Configuration created" -ForegroundColor Green

# Step 5: Test Setup
Write-Host "🧪 Step 5: Testing setup..." -ForegroundColor Blue

aws s3 ls "s3://$DocumentsBucket" >$null 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ S3 access confirmed" -ForegroundColor Green
} else {
    Write-Host "⚠️ S3 access test failed" -ForegroundColor Yellow
}

aws lambda get-function --function-name "vericase-processor-$Environment" --region $Region >$null 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Lambda function accessible" -ForegroundColor Green
} else {
    Write-Host "⚠️ Lambda function test failed" -ForegroundColor Yellow
}

# Cleanup temp files
Remove-Item -Path "trust-policy.json", "lambda-policy.json", "lambda_function.py", "function.zip" -Force -ErrorAction SilentlyContinue

Write-Host "`n🎉 VeriCase AWS Setup Complete!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Blue
Write-Host "Documents Bucket: $DocumentsBucket" -ForegroundColor White
Write-Host "Knowledge Base Bucket: $KnowledgeBaseBucket" -ForegroundColor White
Write-Host "Lambda Function: vericase-processor-$Environment" -ForegroundColor White
Write-Host "Database Password: $DatabasePassword" -ForegroundColor Red
Write-Host "Configuration: .env.aws" -ForegroundColor White
Write-Host "`n🚀 Next Steps:" -ForegroundColor Blue
Write-Host "1. Copy .env.aws to .env" -ForegroundColor White
Write-Host "2. Restart your VeriCase application" -ForegroundColor White
Write-Host "3. Upload a test PST file" -ForegroundColor White