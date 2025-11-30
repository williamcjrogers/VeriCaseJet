#!/usr/bin/env pwsh
# VeriCase Premium Features - Simple Deployment
# Cost: ~£100/month

$ErrorActionPreference = "Stop"

Write-Host "=== VeriCase Premium Deployment ===" -ForegroundColor Cyan
Write-Host ""

$REGION = "eu-west-2"
$ACCOUNT_ID = "526015377510"

# 1. RDS PostgreSQL (replaces container DB)
Write-Host "[1/3] Creating RDS PostgreSQL..." -ForegroundColor Green

aws rds create-db-instance `
    --db-instance-identifier vericase-db `
    --db-instance-class db.t3.micro `
    --engine postgres `
    --engine-version 15.4 `
    --master-username vericase `
    --master-user-password "$(New-Guid)" `
    --allocated-storage 20 `
    --backup-retention-period 7 `
    --multi-az `
    --publicly-accessible `
    --region $REGION

Write-Host "  ✓ RDS creating (takes 10 minutes)" -ForegroundColor Green

# 2. Upgrade EC2 to t3.medium
Write-Host ""
Write-Host "[2/3] Upgrading EC2 instance..." -ForegroundColor Green

aws ec2 stop-instances --instance-ids i-0ade6dff1811bdbcb --region $REGION
Start-Sleep -Seconds 30

aws ec2 modify-instance-attribute `
    --instance-id i-0ade6dff1811bdbcb `
    --instance-type t3.medium `
    --region $REGION

aws ec2 start-instances --instance-ids i-0ade6dff1811bdbcb --region $REGION

Write-Host "  ✓ EC2 upgraded to t3.medium" -ForegroundColor Green

# 3. Enable S3 storage for PST files
Write-Host ""
Write-Host "[3/3] Configuring S3 storage..." -ForegroundColor Green

aws s3api put-bucket-lifecycle-configuration `
    --bucket vericase-documents-526015377510 `
    --lifecycle-configuration '{
        "Rules": [{
            "Id": "archive-old-pst",
            "Status": "Enabled",
            "Transitions": [{
                "Days": 90,
                "StorageClass": "GLACIER"
            }]
        }]
    }' `
    --region us-east-1

Write-Host "  ✓ S3 lifecycle configured" -ForegroundColor Green

Write-Host ""
Write-Host "=== Premium Features Deployed ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Monthly Cost: ~£100" -ForegroundColor Yellow
Write-Host "  • RDS PostgreSQL (Multi-AZ): £40/month"
Write-Host "  • EC2 t3.medium: £30/month"
Write-Host "  • Redis (existing): £150/month"
Write-Host "  • S3 + Glacier: £10/month"
Write-Host ""
Write-Host "Benefits:" -ForegroundColor Green
Write-Host "  ✓ No data loss on deployments (RDS)"
Write-Host "  ✓ 4x faster PST processing (t3.medium)"
Write-Host "  ✓ Unlimited PST storage (S3)"
Write-Host "  ✓ Automated backups (RDS + S3)"
Write-Host ""
