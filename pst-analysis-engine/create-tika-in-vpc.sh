#!/bin/bash
# Deploy Apache Tika to ECS Fargate in your existing EKS VPC

VPC_ID="vpc-0880b8ccf488f327e"
REGION="eu-west-2"
CLUSTER_NAME="vericase-cluster"

echo "Deploying Tika to ECS in VPC: $VPC_ID"
echo ""

# Step 1: Get private subnet IDs
echo "Step 1: Getting private subnet IDs..."
PRIVATE_SUBNETS=$(aws ec2 describe-subnets \
  --region $REGION \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Name,Values=*Private*" \
  --query 'Subnets[*].SubnetId' \
  --output text | tr '\t' ',')

echo "Using subnets: $PRIVATE_SUBNETS"
echo ""

# Step 2: Create security group
echo "Step 2: Creating security group for Tika..."
SG_ID=$(aws ec2 create-security-group \
  --region $REGION \
  --group-name vericase-tika-sg \
  --description "VeriCase Tika security group" \
  --vpc-id $VPC_ID \
  --query 'GroupId' \
  --output text 2>/dev/null)

if [ -z "$SG_ID" ]; then
  echo "Security group already exists, getting ID..."
  SG_ID=$(aws ec2 describe-security-groups \
    --region $REGION \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=vericase-tika-sg" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)
fi

echo "Security group: $SG_ID"
echo ""

# Step 3: Allow Tika port from VPC
echo "Step 3: Allowing Tika port 9998 from VPC..."
aws ec2 authorize-security-group-ingress \
  --region $REGION \
  --group-id $SG_ID \
  --protocol tcp \
  --port 9998 \
  --cidr 192.168.0.0/16 2>/dev/null || echo "Rule already exists"
echo ""

# Step 4: Create ECS cluster (if not exists)
echo "Step 4: Creating ECS cluster..."
aws ecs create-cluster \
  --region $REGION \
  --cluster-name $CLUSTER_NAME \
  --capacity-providers FARGATE \
  --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1 2>/dev/null || echo "Cluster already exists"
echo ""

# Step 5: Create task execution role (if not exists)
echo "Step 5: Creating ECS task execution role..."
ROLE_ARN=$(aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }' \
  --query 'Role.Arn' \
  --output text 2>/dev/null)

if [ -z "$ROLE_ARN" ]; then
  ROLE_ARN=$(aws iam get-role --role-name ecsTaskExecutionRole --query 'Role.Arn' --output text)
fi

aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy 2>/dev/null || echo "Policy already attached"

echo "Task execution role: $ROLE_ARN"
echo ""

# Step 6: Register task definition
echo "Step 6: Registering Tika task definition..."
aws ecs register-task-definition \
  --region $REGION \
  --family vericase-tika \
  --network-mode awsvpc \
  --requires-compatibilities FARGATE \
  --cpu 1024 \
  --memory 2048 \
  --execution-role-arn $ROLE_ARN \
  --container-definitions '[{
    "name": "tika",
    "image": "apache/tika:latest-full",
    "cpu": 1024,
    "memory": 2048,
    "essential": true,
    "portMappings": [{
      "containerPort": 9998,
      "protocol": "tcp"
    }],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {
        "awslogs-group": "/ecs/vericase-tika",
        "awslogs-region": "'$REGION'",
        "awslogs-stream-prefix": "tika",
        "awslogs-create-group": "true"
      }
    }
  }]'

echo ""

# Step 7: Create service
echo "Step 7: Creating ECS service..."
aws ecs create-service \
  --region $REGION \
  --cluster $CLUSTER_NAME \
  --service-name vericase-tika \
  --task-definition vericase-tika \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[$PRIVATE_SUBNETS],
    securityGroups=[$SG_ID],
    assignPublicIp=DISABLED
  }"

echo ""
echo "✅ Tika service creation started!"
echo ""
echo "Wait 5 minutes, then get the private IP:"
echo ""
echo "aws ecs list-tasks \\"
echo "  --region $REGION \\"
echo "  --cluster $CLUSTER_NAME \\"
echo "  --service-name vericase-tika"
echo ""
echo "Then get task details to find the private IP"
echo ""
echo "Update .env.production with:"
echo "TIKA_URL=http://[private-ip]:9998"
echo ""
echo "Cost: ~$30/month (Fargate 1vCPU/2GB)"
echo ""
echo "NOTE: For production, create an internal ALB for better reliability"
