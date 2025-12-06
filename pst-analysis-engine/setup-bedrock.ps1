#!/usr/bin/env pwsh
# Amazon Bedrock Quick Setup Script for VeriCase

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Amazon Bedrock Setup for VeriCase" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if AWS CLI is installed
Write-Host "Checking AWS CLI..." -ForegroundColor Yellow
$awsInstalled = Get-Command aws -ErrorAction SilentlyContinue

if ($awsInstalled) {
    Write-Host "✓ AWS CLI found" -ForegroundColor Green
    
    # Check if credentials are configured
    try {
        $identity = aws sts get-caller-identity 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ AWS credentials configured" -ForegroundColor Green
            $identityJson = $identity | ConvertFrom-Json
            Write-Host "  Account: $($identityJson.Account)" -ForegroundColor Gray
            Write-Host "  User: $($identityJson.Arn)" -ForegroundColor Gray
        } else {
            Write-Host "✗ AWS credentials not configured" -ForegroundColor Red
            Write-Host ""
            Write-Host "Run: aws configure" -ForegroundColor Yellow
            Write-Host "Then enter your AWS credentials" -ForegroundColor Yellow
            exit 1
        }
    } catch {
        Write-Host "✗ Error checking AWS credentials" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "✗ AWS CLI not found" -ForegroundColor Red
    Write-Host ""
    Write-Host "Install AWS CLI:" -ForegroundColor Yellow
    Write-Host "  winget install Amazon.AWSCLI" -ForegroundColor Cyan
    Write-Host "  or download from: https://aws.amazon.com/cli/" -ForegroundColor Cyan
    exit 1
}

Write-Host ""

# Check boto3
Write-Host "Checking boto3 installation..." -ForegroundColor Yellow
$boto3Check = python -c "import boto3; print(boto3.__version__)" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ boto3 installed (version: $boto3Check)" -ForegroundColor Green
} else {
    Write-Host "✗ boto3 not installed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Installing boto3..." -ForegroundColor Yellow
    pip install boto3
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ Failed to install boto3" -ForegroundColor Red
        exit 1
    }
    Write-Host "✓ boto3 installed" -ForegroundColor Green
}

Write-Host ""

# Check .env file
Write-Host "Checking .env configuration..." -ForegroundColor Yellow
if (Test-Path ".env") {
    $envContent = Get-Content ".env" -Raw
    
    if ($envContent -match "BEDROCK_DEFAULT_MODEL") {
        Write-Host "✓ Bedrock configuration found in .env" -ForegroundColor Green
    } else {
        Write-Host "⚠ Bedrock configuration missing from .env" -ForegroundColor Yellow
        Write-Host "  The .env file has been updated with Bedrock settings" -ForegroundColor Gray
    }
    
    # Check if AI features are enabled
    if ($envContent -match "ENABLE_AI_AUTO_CLASSIFY=true") {
        Write-Host "✓ AI features enabled" -ForegroundColor Green
    } else {
        Write-Host "⚠ AI features disabled" -ForegroundColor Yellow
        Write-Host "  Update .env to enable AI features" -ForegroundColor Gray
    }
} else {
    Write-Host "✗ .env file not found" -ForegroundColor Red
    Write-Host "  Copy .env.example to .env and configure" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# Test Bedrock connection
Write-Host "Testing Bedrock connection..." -ForegroundColor Yellow
Write-Host ""

python test_bedrock_setup.py

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "✓ Bedrock Setup Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "1. Review BEDROCK_SETUP.md for detailed documentation" -ForegroundColor White
    Write-Host "2. Choose your preferred model in .env (BEDROCK_DEFAULT_MODEL)" -ForegroundColor White
    Write-Host "3. Start your application and use AI features!" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "✗ Bedrock Setup Failed" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "1. Check AWS credentials: aws sts get-caller-identity" -ForegroundColor White
    Write-Host "2. Verify IAM permissions for Bedrock" -ForegroundColor White
    Write-Host "3. Enable model access in Bedrock console" -ForegroundColor White
    Write-Host "4. Review BEDROCK_SETUP.md for detailed help" -ForegroundColor White
    Write-Host ""
    exit 1
}
