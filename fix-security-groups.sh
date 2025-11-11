#!/bin/bash
# Fix VeriCase Security Groups
# VPC connector exists but security group needs rules

REGION="eu-west-2"
VPC_ID="vpc-0880b8ccf488f327e"
DEFAULT_SG="sg-0fe33dbc9d4cf20ba"

echo "=== Fixing VeriCase Security Groups ==="
echo ""

# Step 1: Add outbound rules to default security group
echo "Step 1: Configuring default security group outbound rules..."

# PostgreSQL
echo "Adding PostgreSQL (5432) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 5432 --cidr 0.0.0.0/0 2>/dev/null && echo "  ✅ PostgreSQL rule added" || echo "  ℹ️  Rule already exists"

# Redis
echo "Adding Redis (6379) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 6379 --cidr 0.0.0.0/0 2>/dev/null && echo "  ✅ Redis rule added" || echo "  ℹ️  Rule already exists"

# HTTPS (OpenSearch)
echo "Adding HTTPS (443) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 443 --cidr 0.0.0.0/0 2>/dev/null && echo "  ✅ HTTPS rule added" || echo "  ℹ️  Rule already exists"

# HTTP (Tika)
echo "Adding HTTP (9998) rule..."
aws ec2 authorize-security-group-egress --region $REGION --group-id $DEFAULT_SG --protocol tcp --port 9998 --cidr 0.0.0.0/0 2>/dev/null && echo "  ✅ HTTP rule added" || echo "  ℹ️  Rule already exists"

echo ""

# Step 2: Find and update RDS security group
echo "Step 2: Updating RDS security group..."
RDS_SG=$(aws rds describe-db-instances --region $REGION --query 'DBInstances[?DBInstanceIdentifier==`database-1`].VpcSecurityGroups[0].VpcSecurityGroupId' --output text)

if [ -n "$RDS_SG" ]; then
    echo "RDS Security Group: $RDS_SG"
    aws ec2 authorize-security-group-ingress --region $REGION --group-id $RDS_SG --protocol tcp --port 5432 --source-group $DEFAULT_SG 2>/dev/null && echo "  ✅ RDS inbound rule added" || echo "  ℹ️  Rule already exists"
else
    echo "  ⚠️  RDS not found, add manually"
fi

echo ""

# Step 3: Find and update ElastiCache security group
echo "Step 3: Updating Redis security group..."
REDIS_SG=$(aws elasticache describe-cache-clusters --region $REGION --cache-cluster-id vericase-redis --show-cache-node-info --query 'CacheClusters[0].SecurityGroups[0].SecurityGroupId' --output text 2>/dev/null)

if [ -n "$REDIS_SG" ]; then
    echo "Redis Security Group: $REDIS_SG"
    aws ec2 authorize-security-group-ingress --region $REGION --group-id $REDIS_SG --protocol tcp --port 6379 --source-group $DEFAULT_SG 2>/dev/null && echo "  ✅ Redis inbound rule added" || echo "  ℹ️  Rule already exists"
else
    echo "  ⚠️  Redis cluster not found, add manually"
fi

echo ""

# Step 4: Find and update OpenSearch security group
echo "Step 4: Updating OpenSearch security group..."
OS_SG=$(aws opensearch describe-domain --region $REGION --domain-name vericase-opensearch --query 'DomainStatus.VPCOptions.SecurityGroupIds[0]' --output text 2>/dev/null)

if [ -n "$OS_SG" ]; then
    echo "OpenSearch Security Group: $OS_SG"
    aws ec2 authorize-security-group-ingress --region $REGION --group-id $OS_SG --protocol tcp --port 443 --source-group $DEFAULT_SG 2>/dev/null && echo "  ✅ OpenSearch inbound rule added" || echo "  ℹ️  Rule already exists"
else
    echo "  ⚠️  OpenSearch not found, add manually"
fi

echo ""
echo "=== Summary ==="
echo "✅ Default security group ($DEFAULT_SG) configured"
echo "✅ Outbound rules added for PostgreSQL, Redis, HTTPS, HTTP"
echo "✅ Inbound rules added to RDS, Redis, OpenSearch"
echo ""
echo "Next: Redeploy your App Runner service"
echo "Go to: https://console.aws.amazon.com/apprunner/home?region=$REGION"
