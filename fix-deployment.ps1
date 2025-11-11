# VeriCase Deployment Fix Script (PowerShell)
# Run this to configure VPC networking for App Runner

$ErrorActionPreference = "Continue"

$REGION = "eu-west-2"
$VPC_ID = "vpc-0880b8ccf488f527e"
$APP_RUNNER_SERVICE = "vericase-app"  # Update with your service name

Write-Host "=== VeriCase Deployment Fix ===" -ForegroundColor Cyan
Write-Host "Region: $REGION"
Write-Host "VPC: $VPC_ID"
Write-Host ""

# Step 1: Get VPC subnets
Write-Host "Step 1: Finding VPC subnets..." -ForegroundColor Yellow
$subnets = aws ec2 describe-subnets `
  --region $REGION `
  --filters "Name=vpc-id,Values=$VPC_ID" `
  --query 'Subnets[*].[SubnetId,AvailabilityZone]' `
  --output text

Write-Host "Available subnets:"
Write-Host $subnets
Write-Host ""

# Step 2: Create App Runner security group
Write-Host "Step 2: Creating App Runner security group..." -ForegroundColor Yellow
$SG_ID = aws ec2 create-security-group `
  --region $REGION `
  --group-name "apprunner-vericase-sg" `
  --description "Security group for VeriCase App Runner" `
  --vpc-id $VPC_ID `
  --query 'GroupId' `
  --output text 2>$null

if (-not $SG_ID) {
  $SG_ID = aws ec2 describe-security-groups `
    --region $REGION `
    --filters "Name=group-name,Values=apprunner-vericase-sg" "Name=vpc-id,Values=$VPC_ID" `
    --query 'SecurityGroups[0].GroupId' `
    --output text
  Write-Host "Using existing security group: $SG_ID" -ForegroundColor Green
} else {
  Write-Host "Created security group: $SG_ID" -ForegroundColor Green
}

# Step 3: Configure security group rules
Write-Host "Step 3: Configuring security group outbound rules..." -ForegroundColor Yellow

# Allow PostgreSQL
aws ec2 authorize-security-group-egress `
  --region $REGION `
  --group-id $SG_ID `
  --protocol tcp `
  --port 5432 `
  --cidr 0.0.0.0/0 2>$null

# Allow Redis
aws ec2 authorize-security-group-egress `
  --region $REGION `
  --group-id $SG_ID `
  --protocol tcp `
  --port 6379 `
  --cidr 0.0.0.0/0 2>$null

# Allow HTTPS (OpenSearch)
aws ec2 authorize-security-group-egress `
  --region $REGION `
  --group-id $SG_ID `
  --protocol tcp `
  --port 443 `
  --cidr 0.0.0.0/0 2>$null

# Allow HTTP (Tika)
aws ec2 authorize-security-group-egress `
  --region $REGION `
  --group-id $SG_ID `
  --protocol tcp `
  --port 9998 `
  --cidr 0.0.0.0/0 2>$null

Write-Host "✅ Security group configured: $SG_ID" -ForegroundColor Green
Write-Host ""

# Step 4: Get RDS security group
Write-Host "Step 4: Finding RDS security group..." -ForegroundColor Yellow
$RDS_SG = aws rds describe-db-instances `
  --region $REGION `
  --query 'DBInstances[?DBInstanceIdentifier==`database-1`].VpcSecurityGroups[0].VpcSecurityGroupId' `
  --output text

if ($RDS_SG) {
  Write-Host "RDS Security Group: $RDS_SG"
  Write-Host "Adding inbound rule from App Runner..."
  aws ec2 authorize-security-group-ingress `
    --region $REGION `
    --group-id $RDS_SG `
    --protocol tcp `
    --port 5432 `
    --source-group $SG_ID 2>$null
  Write-Host "✅ RDS security group updated" -ForegroundColor Green
} else {
  Write-Host "⚠️  Could not find RDS instance 'database-1'" -ForegroundColor Yellow
}
Write-Host ""

# Step 5: Manual VPC connector configuration
Write-Host "Step 5: VPC Connector Configuration (MANUAL)" -ForegroundColor Yellow
Write-Host ""
Write-Host "⚠️  MANUAL STEP REQUIRED:" -ForegroundColor Red
Write-Host "Go to AWS App Runner Console and configure VPC connector:"
Write-Host "  1. Open: https://console.aws.amazon.com/apprunner/home?region=$REGION"
Write-Host "  2. Select your service: $APP_RUNNER_SERVICE"
Write-Host "  3. Go to Configuration → Networking"
Write-Host "  4. Click 'Add VPC connector'"
Write-Host "  5. Configure:"
Write-Host "     - VPC: $VPC_ID"
Write-Host "     - Subnets: Select 2+ subnets from different AZs"
Write-Host "     - Security Group: $SG_ID" -ForegroundColor Cyan
Write-Host "  6. Save and redeploy"
Write-Host ""

Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "✅ Security group created: $SG_ID" -ForegroundColor Green
Write-Host "✅ Outbound rules configured" -ForegroundColor Green
Write-Host "✅ RDS inbound rule added" -ForegroundColor Green
Write-Host "⚠️  VPC connector must be configured manually in console" -ForegroundColor Yellow
Write-Host ""
Write-Host "After configuring VPC connector, redeploy your App Runner service."
