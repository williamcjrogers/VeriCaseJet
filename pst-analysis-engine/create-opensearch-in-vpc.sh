#!/bin/bash
# Create OpenSearch domain in your existing EKS VPC

VPC_ID="vpc-0880b8ccf488f327e"
REGION="eu-west-2"

echo "Creating OpenSearch in VPC: $VPC_ID"
echo ""

# Step 1: Get private subnet IDs (need at least 2 for OpenSearch)
echo "Step 1: Getting private subnet IDs..."
SUBNET_1=$(aws ec2 describe-subnets \
  --region $REGION \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*PrivateEUWEST2A*" \
  --query 'Subnets[0].SubnetId' \
  --output text)

SUBNET_2=$(aws ec2 describe-subnets \
  --region $REGION \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*PrivateEUWEST2B*" \
  --query 'Subnets[0].SubnetId' \
  --output text)

echo "Using subnets: $SUBNET_1, $SUBNET_2"
echo ""

# Step 2: Create security group
echo "Step 2: Creating security group for OpenSearch..."
SG_ID=$(aws ec2 create-security-group \
  --region $REGION \
  --group-name vericase-opensearch-sg \
  --description "VeriCase OpenSearch security group" \
  --vpc-id $VPC_ID \
  --query 'GroupId' \
  --output text 2>/dev/null)

if [ -z "$SG_ID" ]; then
  echo "Security group already exists, getting ID..."
  SG_ID=$(aws ec2 describe-security-groups \
    --region $REGION \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=vericase-opensearch-sg" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)
fi

echo "Security group: $SG_ID"
echo ""

# Step 3: Allow HTTPS from VPC
echo "Step 3: Allowing HTTPS port 443 from VPC..."
aws ec2 authorize-security-group-ingress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol tcp \
  --port 443 \
  --cidr 192.168.0.0/16 2>/dev/null || echo "Rule already exists"
echo ""

# Step 4: Create OpenSearch domain
echo "Step 4: Creating OpenSearch domain (this takes 15-20 minutes)..."
aws opensearch create-domain \
  --region $REGION \
  --domain-name vericase-search \
  --engine-version "OpenSearch_2.11" \
  --cluster-config \
    InstanceType=t3.small.search,InstanceCount=1 \
  --ebs-options \
    EBSEnabled=true,VolumeType=gp3,VolumeSize=10 \
  --vpc-options \
    SubnetIds=$SUBNET_1,SecurityGroupIds=$SG_ID \
  --access-policies '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "*"},
      "Action": "es:*",
      "Resource": "arn:aws:es:'$REGION':*:domain/vericase-search/*"
    }]
  }' \
  --node-to-node-encryption-options Enabled=true \
  --encryption-at-rest-options Enabled=true \
  --domain-endpoint-options EnforceHTTPS=true

echo ""
echo "✅ OpenSearch domain creation started!"
echo ""
echo "Wait 15-20 minutes, then get the endpoint:"
echo ""
echo "aws opensearch describe-domain \\"
echo "  --region $REGION \\"
echo "  --domain-name vericase-search \\"
echo "  --query 'DomainStatus.Endpoint' \\"
echo "  --output text"
echo ""
echo "Then update .env.production with:"
echo "OPENSEARCH_HOST=https://[endpoint]"
echo ""
echo "Cost: ~$50/month (t3.small.search)"
