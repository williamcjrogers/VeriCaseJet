#!/bin/bash
# Create ElastiCache Redis in your existing EKS VPC

VPC_ID="vpc-0880b8ccf488f327e"
REGION="eu-west-2"

echo "Creating Redis in VPC: $VPC_ID"
echo ""

# Step 1: Get private subnet IDs from your VPC
echo "Step 1: Getting private subnet IDs..."
PRIVATE_SUBNETS=$(aws ec2 describe-subnets \
  --region $REGION \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*Private*" \
  --query 'Subnets[*].SubnetId' \
  --output text)

echo "Found private subnets: $PRIVATE_SUBNETS"
echo ""

# Step 2: Create subnet group for Redis
echo "Step 2: Creating Redis subnet group..."
aws elasticache create-cache-subnet-group \
  --region $REGION \
  --cache-subnet-group-name vericase-redis-subnet-group \
  --cache-subnet-group-description "VeriCase Redis subnet group" \
  --subnet-ids $PRIVATE_SUBNETS 2>/dev/null || echo "Subnet group already exists"
echo ""

# Step 3: Get or create security group
echo "Step 3: Creating security group for Redis..."
SG_ID=$(aws ec2 create-security-group \
  --region $REGION \
  --group-name vericase-redis-sg \
  --description "VeriCase Redis security group" \
  --vpc-id $VPC_ID \
  --query 'GroupId' \
  --output text 2>/dev/null)

if [ -z "$SG_ID" ]; then
  echo "Security group already exists, getting ID..."
  SG_ID=$(aws ec2 describe-security-groups \
    --region $REGION \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=vericase-redis-sg" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)
fi

echo "Security group: $SG_ID"
echo ""

# Step 4: Allow Redis port from VPC CIDR
echo "Step 4: Allowing Redis port 6379 from VPC..."
aws ec2 authorize-security-group-ingress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol tcp \
  --port 6379 \
  --cidr 192.168.0.0/16 2>/dev/null || echo "Rule already exists"
echo ""

# Step 5: Create Redis cluster
echo "Step 5: Creating Redis cluster (this takes 5-10 minutes)..."
aws elasticache create-cache-cluster \
  --region $REGION \
  --cache-cluster-id vericase-redis \
  --cache-node-type cache.t3.micro \
  --engine redis \
  --num-cache-nodes 1 \
  --cache-subnet-group-name vericase-redis-subnet-group \
  --security-group-ids $SG_ID \
  --tags Key=Name,Value=vericase-redis

echo ""
echo "✅ Redis cluster creation started!"
echo ""
echo "Wait 5-10 minutes, then get the endpoint:"
echo ""
echo "aws elasticache describe-cache-clusters \\"
echo "  --region $REGION \\"
echo "  --cache-cluster-id vericase-redis \\"
echo "  --show-cache-node-info \\"
echo "  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' \\"
echo "  --output text"
echo ""
echo "Then update .env.production with:"
echo "REDIS_URL=redis://[endpoint]:6379/0"
