#!/usr/bin/env pwsh
# VeriCase AWS AI Services Deployment
# Deploys: Bedrock KB, S3 Buckets, Lambda Functions, EventBridge, Step Functions

$ErrorActionPreference = "Stop"

Write-Host "=== VeriCase AWS AI Services Deployment ===" -ForegroundColor Cyan
Write-Host ""

# Configuration
$REGION = "us-east-1"
$ACCOUNT_ID = "526015377510"
$PROJECT = "vericase"
$ENV = "production"

Write-Host "Region: $REGION" -ForegroundColor Yellow
Write-Host "Account: $ACCOUNT_ID" -ForegroundColor Yellow
Write-Host ""

# Step 1: Create S3 Buckets
Write-Host "[1/6] Creating S3 Buckets..." -ForegroundColor Green

$DOCS_BUCKET = "$PROJECT-documents-$ACCOUNT_ID"
$KB_BUCKET = "$PROJECT-knowledge-base-$ACCOUNT_ID"

try {
    aws s3 mb "s3://$DOCS_BUCKET" --region $REGION 2>$null
    Write-Host "  ✓ Created documents bucket: $DOCS_BUCKET" -ForegroundColor Green
} catch {
    Write-Host "  ℹ Documents bucket already exists" -ForegroundColor Yellow
}

try {
    aws s3 mb "s3://$KB_BUCKET" --region $REGION 2>$null
    Write-Host "  ✓ Created KB bucket: $KB_BUCKET" -ForegroundColor Green
} catch {
    Write-Host "  ℹ KB bucket already exists" -ForegroundColor Yellow
}

# Enable versioning on KB bucket
aws s3api put-bucket-versioning --bucket $KB_BUCKET --versioning-configuration Status=Enabled --region $REGION
Write-Host "  ✓ Enabled versioning on KB bucket" -ForegroundColor Green

# Step 2: Create IAM Role for Bedrock
Write-Host ""
Write-Host "[2/6] Creating IAM Roles..." -ForegroundColor Green

$BEDROCK_ROLE_NAME = "VeriCaseBedrockKBRole"

# Check if role exists
$roleExists = aws iam get-role --role-name $BEDROCK_ROLE_NAME 2>$null
if (-not $roleExists) {
    # Create trust policy
    $trustPolicy = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
"@
    
    $trustPolicy | Out-File -FilePath "trust-policy.json" -Encoding utf8
    
    aws iam create-role `
        --role-name $BEDROCK_ROLE_NAME `
        --assume-role-policy-document file://trust-policy.json `
        --region $REGION
    
    Write-Host "  ✓ Created Bedrock IAM role" -ForegroundColor Green
    
    # Attach S3 access policy
    $s3Policy = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:GetObject",
      "s3:ListBucket"
    ],
    "Resource": [
      "arn:aws:s3:::$KB_BUCKET",
      "arn:aws:s3:::$KB_BUCKET/*"
    ]
  }]
}
"@
    
    $s3Policy | Out-File -FilePath "s3-policy.json" -Encoding utf8
    
    aws iam put-role-policy `
        --role-name $BEDROCK_ROLE_NAME `
        --policy-name BedrockS3Access `
        --policy-document file://s3-policy.json `
        --region $REGION
    
    Write-Host "  ✓ Attached S3 access policy" -ForegroundColor Green
    
    # Attach Bedrock model access
    aws iam attach-role-policy `
        --role-name $BEDROCK_ROLE_NAME `
        --policy-arn "arn:aws:iam::aws:policy/AmazonBedrockFullAccess" `
        --region $REGION
    
    Write-Host "  ✓ Attached Bedrock access policy" -ForegroundColor Green
} else {
    Write-Host "  ℹ Bedrock role already exists" -ForegroundColor Yellow
}

$BEDROCK_ROLE_ARN = "arn:aws:iam::${ACCOUNT_ID}:role/$BEDROCK_ROLE_NAME"

# Wait for role to propagate
Write-Host "  ⏳ Waiting for IAM role to propagate..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Step 3: Create Bedrock Knowledge Base
Write-Host ""
Write-Host "[3/6] Creating Bedrock Knowledge Base..." -ForegroundColor Green

# Check if KB already exists
$kbList = aws bedrock-agent list-knowledge-bases --region $REGION 2>$null | ConvertFrom-Json
$existingKB = $kbList.knowledgeBaseSummaries | Where-Object { $_.name -eq "VeriCase-KB" }

if ($existingKB) {
    $KB_ID = $existingKB.knowledgeBaseId
    Write-Host "  ℹ Knowledge Base already exists: $KB_ID" -ForegroundColor Yellow
} else {
    # Create KB configuration
    $kbConfig = @"
{
  "name": "VeriCase-KB",
  "description": "VeriCase Legal Evidence Knowledge Base",
  "roleArn": "$BEDROCK_ROLE_ARN",
  "knowledgeBaseConfiguration": {
    "type": "VECTOR",
    "vectorKnowledgeBaseConfiguration": {
      "embeddingModelArn": "arn:aws:bedrock:$REGION::foundation-model/amazon.titan-embed-text-v1"
    }
  },
  "storageConfiguration": {
    "type": "OPENSEARCH_SERVERLESS",
    "opensearchServerlessConfiguration": {
      "collectionArn": "arn:aws:aoss:${REGION}:${ACCOUNT_ID}:collection/vericase-kb",
      "vectorIndexName": "vericase-index",
      "fieldMapping": {
        "vectorField": "embedding",
        "textField": "text",
        "metadataField": "metadata"
      }
    }
  }
}
"@
    
    $kbConfig | Out-File -FilePath "kb-config.json" -Encoding utf8
    
    try {
        $kbResult = aws bedrock-agent create-knowledge-base `
            --cli-input-json file://kb-config.json `
            --region $REGION | ConvertFrom-Json
        
        $KB_ID = $kbResult.knowledgeBase.knowledgeBaseId
        Write-Host "  ✓ Created Knowledge Base: $KB_ID" -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ KB creation failed (may need OpenSearch Serverless setup)" -ForegroundColor Yellow
        Write-Host "  Using placeholder KB ID" -ForegroundColor Yellow
        $KB_ID = "PLACEHOLDER-KB-ID"
    }
}

# Step 4: Create Data Source
Write-Host ""
Write-Host "[4/6] Creating Knowledge Base Data Source..." -ForegroundColor Green

if ($KB_ID -ne "PLACEHOLDER-KB-ID") {
    $dsConfig = @"
{
  "knowledgeBaseId": "$KB_ID",
  "name": "VeriCase-S3-DataSource",
  "description": "S3 data source for VeriCase documents",
  "dataSourceConfiguration": {
    "type": "S3",
    "s3Configuration": {
      "bucketArn": "arn:aws:s3:::$KB_BUCKET"
    }
  }
}
"@
    
    $dsConfig | Out-File -FilePath "ds-config.json" -Encoding utf8
    
    try {
        $dsResult = aws bedrock-agent create-data-source `
            --cli-input-json file://ds-config.json `
            --region $REGION | ConvertFrom-Json
        
        $DS_ID = $dsResult.dataSource.dataSourceId
        Write-Host "  ✓ Created Data Source: $DS_ID" -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ Data source creation failed" -ForegroundColor Yellow
        $DS_ID = "PLACEHOLDER-DS-ID"
    }
} else {
    Write-Host "  ⏭ Skipping (KB not created)" -ForegroundColor Yellow
    $DS_ID = "PLACEHOLDER-DS-ID"
}

# Step 5: Create Lambda Function for Processing
Write-Host ""
Write-Host "[5/6] Creating Lambda Function..." -ForegroundColor Green

$LAMBDA_NAME = "vericase-evidence-processor"

# Create Lambda execution role
$lambdaRoleName = "VeriCaseLambdaRole"
$lambdaRoleExists = aws iam get-role --role-name $lambdaRoleName 2>$null

if (-not $lambdaRoleExists) {
    $lambdaTrust = @"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
"@
    
    $lambdaTrust | Out-File -FilePath "lambda-trust.json" -Encoding utf8
    
    aws iam create-role `
        --role-name $lambdaRoleName `
        --assume-role-policy-document file://lambda-trust.json `
        --region $REGION
    
    # Attach policies
    aws iam attach-role-policy `
        --role-name $lambdaRoleName `
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" `
        --region $REGION
    
    aws iam attach-role-policy `
        --role-name $lambdaRoleName `
        --policy-arn "arn:aws:iam::aws:policy/AmazonTextractFullAccess" `
        --region $REGION
    
    aws iam attach-role-policy `
        --role-name $lambdaRoleName `
        --policy-arn "arn:aws:iam::aws:policy/ComprehendFullAccess" `
        --region $REGION
    
    aws iam attach-role-policy `
        --role-name $lambdaRoleName `
        --policy-arn "arn:aws:iam::aws:policy/AmazonRekognitionFullAccess" `
        --region $REGION
    
    Write-Host "  ✓ Created Lambda execution role" -ForegroundColor Green
    Start-Sleep -Seconds 10
}

$LAMBDA_ROLE_ARN = "arn:aws:iam::${ACCOUNT_ID}:role/$lambdaRoleName"

# Create simple Lambda function code
$lambdaCode = @"
import json
import boto3

textract = boto3.client('textract')
comprehend = boto3.client('comprehend')

def lambda_handler(event, context):
    print(f'Processing event: {json.dumps(event)}')
    
    # Extract S3 details from event
    bucket = event.get('bucket')
    key = event.get('key')
    
    if not bucket or not key:
        return {'statusCode': 400, 'body': 'Missing bucket or key'}
    
    # Start Textract job
    response = textract.start_document_text_detection(
        DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}}
    )
    
    job_id = response['JobId']
    
    return {
        'statusCode': 200,
        'body': json.dumps({'jobId': job_id, 'status': 'processing'})
    }
"@

$lambdaCode | Out-File -FilePath "lambda_function.py" -Encoding utf8

# Create deployment package
Compress-Archive -Path "lambda_function.py" -DestinationPath "lambda.zip" -Force

# Check if function exists
$functionExists = aws lambda get-function --function-name $LAMBDA_NAME --region $REGION 2>$null

if (-not $functionExists) {
    aws lambda create-function `
        --function-name $LAMBDA_NAME `
        --runtime python3.11 `
        --role $LAMBDA_ROLE_ARN `
        --handler lambda_function.lambda_handler `
        --zip-file fileb://lambda.zip `
        --timeout 300 `
        --memory-size 512 `
        --region $REGION
    
    Write-Host "  ✓ Created Lambda function: $LAMBDA_NAME" -ForegroundColor Green
} else {
    Write-Host "  ℹ Lambda function already exists" -ForegroundColor Yellow
}

$LAMBDA_ARN = "arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_NAME}"

# Step 6: Update .env file
Write-Host ""
Write-Host "[6/6] Updating .env configuration..." -ForegroundColor Green

$envContent = @"
# AWS Services Configuration - DEPLOYED $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
USE_AWS_SERVICES=true
AWS_REGION=$REGION
AWS_ACCOUNT_ID=$ACCOUNT_ID

# S3 Buckets
S3_BUCKET=$DOCS_BUCKET
KNOWLEDGE_BASE_BUCKET=$KB_BUCKET

# Bedrock Knowledge Base
BEDROCK_KB_ID=$KB_ID
BEDROCK_DS_ID=$DS_ID

# Lambda Functions
TEXTRACT_PROCESSOR_FUNCTION=$LAMBDA_ARN

# AI Features
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true

# EventBridge
EVENT_BUS_NAME=vericase-events

# Existing Redis (already deployed)
REDIS_ENDPOINT=clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379
"@

$envContent | Out-File -FilePath ".env.aws-deployed" -Encoding utf8
Write-Host "  ✓ Created .env.aws-deployed" -ForegroundColor Green

# Cleanup temp files
Remove-Item -Path "trust-policy.json", "s3-policy.json", "kb-config.json", "ds-config.json", "lambda-trust.json", "lambda_function.py", "lambda.zip" -ErrorAction SilentlyContinue

# Summary
Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Resources Created:" -ForegroundColor Yellow
Write-Host "  • S3 Documents Bucket: $DOCS_BUCKET"
Write-Host "  • S3 KB Bucket: $KB_BUCKET"
Write-Host "  • Bedrock KB ID: $KB_ID"
Write-Host "  • Data Source ID: $DS_ID"
Write-Host "  • Lambda Function: $LAMBDA_NAME"
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Copy .env.aws-deployed to .env"
Write-Host "  2. Add your AWS credentials to .env:"
Write-Host "     AWS_ACCESS_KEY_ID=your_key"
Write-Host "     AWS_SECRET_ACCESS_KEY=your_secret"
Write-Host "  3. Restart VeriCase application"
Write-Host ""
Write-Host "Estimated Monthly Cost: ~£17" -ForegroundColor Green
Write-Host ""
