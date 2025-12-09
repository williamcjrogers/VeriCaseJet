#!/bin/bash
# Extract complete AWS VeriCase setup details

OUTPUT_FILE="vericase-aws-setup-$(date +%Y%m%d-%H%M%S).txt"

echo "========================================" | tee $OUTPUT_FILE
echo "VERICASE AWS INFRASTRUCTURE DETAILS" | tee -a $OUTPUT_FILE
echo "Generated: $(date)" | tee -a $OUTPUT_FILE
echo "========================================" | tee -a $OUTPUT_FILE

# EC2 Instance
echo -e "\n=== EC2 INSTANCE ===" | tee -a $OUTPUT_FILE
aws ec2 describe-instances --instance-ids i-0ade6dff1811bdbcb --output json | tee -a $OUTPUT_FILE

# Security Groups
echo -e "\n=== SECURITY GROUPS ===" | tee -a $OUTPUT_FILE
SG_ID=$(aws ec2 describe-instances --instance-ids i-0ade6dff1811bdbcb --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text)
aws ec2 describe-security-groups --group-ids $SG_ID --output json | tee -a $OUTPUT_FILE

# Route 53
echo -e "\n=== ROUTE 53 DNS ===" | tee -a $OUTPUT_FILE
aws route53 list-hosted-zones --output json | tee -a $OUTPUT_FILE
aws route53 list-resource-record-sets --hosted-zone-id Z03217773PWCQOY354HX9 --output json | tee -a $OUTPUT_FILE

# S3 Buckets
echo -e "\n=== S3 BUCKETS ===" | tee -a $OUTPUT_FILE
aws s3 ls | tee -a $OUTPUT_FILE
aws s3api list-buckets --query 'Buckets[?contains(Name, `vericase`)]' --output json | tee -a $OUTPUT_FILE

# IAM Roles
echo -e "\n=== IAM ROLES ===" | tee -a $OUTPUT_FILE
aws iam list-roles --query 'Roles[?contains(RoleName, `vericase`) || contains(RoleName, `VeriCase`)]' --output json | tee -a $OUTPUT_FILE

# VPC
echo -e "\n=== VPC ===" | tee -a $OUTPUT_FILE
VPC_ID=$(aws ec2 describe-instances --instance-ids i-0ade6dff1811bdbcb --query 'Reservations[0].Instances[0].VpcId' --output text)
aws ec2 describe-vpcs --vpc-ids $VPC_ID --output json | tee -a $OUTPUT_FILE

# Subnets
echo -e "\n=== SUBNETS ===" | tee -a $OUTPUT_FILE
aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --output json | tee -a $OUTPUT_FILE

# Load Balancers
echo -e "\n=== LOAD BALANCERS ===" | tee -a $OUTPUT_FILE
aws elbv2 describe-load-balancers --output json | tee -a $OUTPUT_FILE

# EKS Clusters
echo -e "\n=== EKS CLUSTERS ===" | tee -a $OUTPUT_FILE
aws eks list-clusters --output json | tee -a $OUTPUT_FILE

# RDS Databases
echo -e "\n=== RDS DATABASES ===" | tee -a $OUTPUT_FILE
aws rds describe-db-instances --output json | tee -a $OUTPUT_FILE

# Secrets Manager
echo -e "\n=== SECRETS MANAGER ===" | tee -a $OUTPUT_FILE
aws secretsmanager list-secrets --output json | tee -a $OUTPUT_FILE

# CloudWatch Logs
echo -e "\n=== CLOUDWATCH LOG GROUPS ===" | tee -a $OUTPUT_FILE
aws logs describe-log-groups --log-group-name-prefix /aws/vericase --output json | tee -a $OUTPUT_FILE

# ACM Certificates
echo -e "\n=== ACM CERTIFICATES ===" | tee -a $OUTPUT_FILE
aws acm list-certificates --output json | tee -a $OUTPUT_FILE

# Lambda Functions
echo -e "\n=== LAMBDA FUNCTIONS ===" | tee -a $OUTPUT_FILE
aws lambda list-functions --query 'Functions[?contains(FunctionName, `vericase`)]' --output json | tee -a $OUTPUT_FILE

# OpenSearch
echo -e "\n=== OPENSEARCH DOMAINS ===" | tee -a $OUTPUT_FILE
aws opensearch list-domain-names --output json | tee -a $OUTPUT_FILE

# ElastiCache
echo -e "\n=== ELASTICACHE CLUSTERS ===" | tee -a $OUTPUT_FILE
aws elasticache describe-cache-clusters --output json | tee -a $OUTPUT_FILE

# App Runner
echo -e "\n=== APP RUNNER SERVICES ===" | tee -a $OUTPUT_FILE
aws apprunner list-services --output json | tee -a $OUTPUT_FILE

# Cost Explorer (Last 30 days)
echo -e "\n=== COST (LAST 30 DAYS) ===" | tee -a $OUTPUT_FILE
START_DATE=$(date -d '30 days ago' +%Y-%m-%d)
END_DATE=$(date +%Y-%m-%d)
aws ce get-cost-and-usage --time-period Start=$START_DATE,End=$END_DATE --granularity MONTHLY --metrics BlendedCost --output json | tee -a $OUTPUT_FILE

echo -e "\n========================================" | tee -a $OUTPUT_FILE
echo "Details saved to: $OUTPUT_FILE" | tee -a $OUTPUT_FILE
echo "========================================" | tee -a $OUTPUT_FILE
