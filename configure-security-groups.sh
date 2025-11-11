#!/bin/bash
# Configure Security Groups for VeriCase App Runner

# Security Group IDs
RDS_SG="sg-04d1b49414bd19cf7"  # EKS cluster security group (confirmed - this is your RDS security group)
# Note: Currently using VPC CIDR 192.168.0.0/16 as source instead of specific App Runner security group

echo "Configuring security groups..."

# Add inbound rule to RDS security group to allow App Runner
echo "Adding inbound rule to RDS security group..."
aws ec2 authorize-security-group-ingress \
    --group-id $RDS_SG \
    --protocol tcp \
    --port 5432 \
    --source-group $APPRUNNER_SG \
    --group-owner 526015377510 \
    --region eu-west-2

# Add outbound rule to App Runner security group
echo "Adding outbound rule to App Runner security group..."
aws ec2 authorize-security-group-egress \
    --group-id $APPRUNNER_SG \
    --protocol tcp \
    --port 5432 \
    --destination-group $RDS_SG \
    --group-owner 526015377510 \
    --region eu-west-2

# Additional outbound rules for App Runner
echo "Adding Redis outbound rule..."
aws ec2 authorize-security-group-egress \
    --group-id $APPRUNNER_SG \
    --protocol tcp \
    --port 6379 \
    --cidr 0.0.0.0/0 \
    --region eu-west-2

echo "Adding HTTPS outbound rule..."
aws ec2 authorize-security-group-egress \
    --group-id $APPRUNNER_SG \
    --protocol tcp \
    --port 443 \
    --cidr 0.0.0.0/0 \
    --region eu-west-2

echo "Security groups configured!"
echo "RDS SG: $RDS_SG can now receive connections from App Runner SG: $APPRUNNER_SG on port 5432"
