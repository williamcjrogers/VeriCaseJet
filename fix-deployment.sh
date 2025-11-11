#!/bin/bash
# VeriCase Deployment Fix Script
# Run this to configure VPC networking for App Runner

set -e

REGION="eu-west-2"
VPC_ID="vpc-0880b8ccf488f527e"
APP_RUNNER_SERVICE="vericase-app"  # Update with your service name

echo "=== VeriCase Deployment Fix ==="
echo "Region: $REGION"
echo "VPC: $VPC_ID"
echo ""

# Step 1: Get VPC subnets
echo "Step 1: Finding VPC subnets..."
SUBNETS=$(aws ec2 describe-subnets \
  --region $REGION \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].[SubnetId,AvailabilityZone]' \
  --output text)

echo "Available subnets:"
echo "$SUBNETS"
echo ""

# Step 2: Create App Runner security group
echo "Step 2: Creating App Runner security group..."
SG_ID=$(aws ec2 create-security-group \
  --region $REGION \
  --group-name "apprunner-vericase-sg" \
  --description "Security group for VeriCase App Runner" \
  --vpc-id $VPC_ID \
  --query 'GroupId' \
  --output text 2>/dev/null || echo "exists")

if [ "$SG_ID" = "exists" ]; then
  SG_ID=$(aws ec2 describe-security-groups \
    --region $REGION \
    --filters "Name=group-name,Values=apprunner-vericase-sg" "Name=vpc-id,Values=$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)
  echo "Using existing security group: $SG_ID"
else
  echo "Created security group: $SG_ID"
fi

# Step 3: Configure security group rules
echo "Step 3: Configuring security group outbound rules..."

# Allow PostgreSQL
aws ec2 authorize-security-group-egress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol tcp \
  --port 5432 \
  --cidr 0.0.0.0/0 2>/dev/null || echo "PostgreSQL rule exists"

# Allow Redis
aws ec2 authorize-security-group-egress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol tcp \
  --port 6379 \
  --cidr 0.0.0.0/0 2>/dev/null || echo "Redis rule exists"

# Allow HTTPS (OpenSearch)
aws ec2 authorize-security-group-egress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol tcp \
  --port 443 \
  --cidr 0.0.0.0/0 2>/dev/null || echo "HTTPS rule exists"

# Allow HTTP (Tika)
aws ec2 authorize-security-group-egress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol tcp \
  --port 9998 \
  --cidr 0.0.0.0/0 2>/dev/null || echo "HTTP rule exists"

# Allow all outbound (for internet)
aws ec2 authorize-security-group-egress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol -1 \
  --cidr 0.0.0.0/0 2>/dev/null || echo "All traffic rule exists"

echo "✅ Security group configured: $SG_ID"
echo ""

# Step 4: Get RDS security group
echo "Step 4: Finding RDS security group..."
RDS_SG=$(aws rds describe-db-instances \
  --region $REGION \
  --query 'DBInstances[?DBInstanceIdentifier==`database-1`].VpcSecurityGroups[0].VpcSecurityGroupId' \
  --output text)

if [ -n "$RDS_SG" ]; then
  echo "RDS Security Group: $RDS_SG"
  echo "Adding inbound rule from App Runner..."
  aws ec2 authorize-security-group-ingress \
    --region $REGION \
    --group-id $RDS_SG \
    --protocol tcp \
    --port 5432 \
    --source-group $SG_ID 2>/dev/null || echo "Rule already exists"
  echo "✅ RDS security group updated"
else
  echo "⚠️  Could not find RDS instance 'database-1'"
fi
echo ""

# Step 5: Create VPC connector
echo "Step 5: Creating VPC connector..."
echo ""
echo "⚠️  MANUAL STEP REQUIRED:"
echo "Go to AWS App Runner Console and configure VPC connector:"
echo "  1. Open: https://console.aws.amazon.com/apprunner/home?region=$REGION"
echo "  2. Select your service: $APP_RUNNER_SERVICE"
echo "  3. Go to Configuration → Networking"
echo "  4. Click 'Add VPC connector'"
echo "  5. Configure:"
echo "     - VPC: $VPC_ID"
echo "     - Subnets: Select 2+ subnets from different AZs"
echo "     - Security Group: $SG_ID"
echo "  6. Save and redeploy"
echo ""

echo "=== Summary ==="
echo "✅ Security group created: $SG_ID"
echo "✅ Outbound rules configured"
echo "✅ RDS inbound rule added"
echo "⚠️  VPC connector must be configured manually in console"
echo ""
echo "After configuring VPC connector, redeploy your App Runner service."
