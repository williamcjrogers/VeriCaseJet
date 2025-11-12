#!/bin/bash
# Add App Runner subnet to RDS security group

RDS_SG="sg-04d1b49414bd19cf7"  # Your RDS security group
APPRUNNER_SUBNET="192.168.98.0/24"  # App Runner subnet from logs

echo "Adding App Runner subnet to RDS security group..."
aws ec2 authorize-security-group-ingress \
    --group-id $RDS_SG \
    --protocol tcp \
    --port 5432 \
    --cidr $APPRUNNER_SUBNET \
    --group-owner 526015377510 \
    --region eu-west-2 \
    --tag-specifications "ResourceType=security-group-rule,Tags=[{Key=Name,Value='App Runner PostgreSQL access'}]"

echo "Done! App Runner subnet $APPRUNNER_SUBNET can now access RDS on port 5432"
