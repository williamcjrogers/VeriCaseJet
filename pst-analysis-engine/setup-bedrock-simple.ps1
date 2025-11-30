#!/usr/bin/env pwsh
# Simple Bedrock Setup - No OpenSearch Required
# Uses S3 + Direct Bedrock API calls instead of Knowledge Base

$ErrorActionPreference = "Stop"

Write-Host "=== VeriCase Simple Bedrock Setup ===" -ForegroundColor Cyan
Write-Host ""

$REGION = "us-east-1"
$ACCOUNT_ID = "526015377510"
$BUCKET = "vericase-knowledge-base-$ACCOUNT_ID"

Write-Host "[1/3] Checking S3 bucket..." -ForegroundColor Green
$bucketExists = aws s3 ls "s3://$BUCKET" 2>$null
if ($bucketExists) {
    Write-Host "  ✓ Bucket exists: $BUCKET" -ForegroundColor Green
} else {
    Write-Host "  ✗ Bucket not found - run deploy-aws-ai-services.ps1 first" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[2/3] Testing Bedrock access..." -ForegroundColor Green

# Test Bedrock model access
try {
    $models = aws bedrock list-foundation-models --region $REGION 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Bedrock API accessible" -ForegroundColor Green
        
        # Check for Claude
        $claudeAvailable = $models | Select-String "anthropic.claude"
        if ($claudeAvailable) {
            Write-Host "  ✓ Claude models available" -ForegroundColor Green
        }
        
        # Check for Titan
        $titanAvailable = $models | Select-String "amazon.titan"
        if ($titanAvailable) {
            Write-Host "  ✓ Titan models available" -ForegroundColor Green
        }
    } else {
        Write-Host "  ⚠ Bedrock access issue - may need model access request" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  ⚠ Could not test Bedrock: $_" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[3/3] Creating simple configuration..." -ForegroundColor Green

$simpleConfig = @"
# VeriCase Simple Bedrock Configuration
# No OpenSearch Serverless required - uses direct S3 + Bedrock API

USE_AWS_SERVICES=true
AWS_REGION=$REGION
AWS_ACCOUNT_ID=$ACCOUNT_ID

# S3 Storage
S3_BUCKET=vericase-documents-$ACCOUNT_ID
KNOWLEDGE_BASE_BUCKET=$BUCKET

# Bedrock Direct API (no Knowledge Base needed)
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v1

# Lambda
TEXTRACT_PROCESSOR_FUNCTION=arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:vericase-evidence-processor

# Features
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
USE_BEDROCK_DIRECT=true
"@

$simpleConfig | Out-File -FilePath ".env.bedrock-simple" -Encoding utf8
Write-Host "  ✓ Created .env.bedrock-simple" -ForegroundColor Green

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  • S3 Bucket: $BUCKET"
Write-Host "  • Bedrock Model: Claude 3 Sonnet"
Write-Host "  • Embedding Model: Titan Embed"
Write-Host "  • Mode: Direct API (no Knowledge Base)"
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Copy .env.bedrock-simple to .env"
Write-Host "  2. Add AWS credentials to .env"
Write-Host "  3. Restart VeriCase"
Write-Host ""
Write-Host "Cost: ~£5/month (Bedrock API calls only)" -ForegroundColor Green
Write-Host ""
Write-Host "Why no Knowledge Base?" -ForegroundColor Yellow
Write-Host "  • OpenSearch Serverless costs £200+/month"
Write-Host "  • Direct Bedrock API is simpler and cheaper"
Write-Host "  • Still get AI-powered search and insights"
Write-Host ""
