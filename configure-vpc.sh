#!/bin/bash
# VeriCase App Runner VPC Configuration Script

VPC_ID="vpc-0880b8ccf488f527e"
REGION="eu-west-2"
APP_RUNNER_SERVICE="vericase-apprunner"

# Get subnet IDs (replace with your actual subnet IDs)
SUBNET_1="subnet-xxxxxxxxx"  # Replace with your subnet ID
SUBNET_2="subnet-yyyyyyyyy"  # Replace with your subnet ID

# Create VPC connector security group
SG_ID=$(aws ec2 create-security-group \
  --group-name apprunner-vpc-connector-sg \
  --description "App Runner VPC Connector Security Group" \
  --vpc-id $VPC_ID \
  --region $REGION \
  --query 'GroupId' \
  --output text)

echo "Created Security Group: $SG_ID"

# Add outbound rules
aws ec2 authorize-security-group-egress \
  --group-id $SG_ID \
  --ip-permissions \
    IpProtocol=tcp,FromPort=5432,ToPort=5432,IpRanges='[{CidrIp=0.0.0.0/0}]' \
    IpProtocol=tcp,FromPort=6379,ToPort=6379,IpRanges='[{CidrIp=0.0.0.0/0}]' \
    IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges='[{CidrIp=0.0.0.0/0}]' \
  --region $REGION

# Create VPC connector
aws apprunner create-vpc-connector \
  --vpc-connector-name vericase-vpc-connector \
  --subnets $SUBNET_1 $SUBNET_2 \
  --security-groups $SG_ID \
  --region $REGION

echo "VPC Connector created. Now update your App Runner service in the console."
