#!/bin/bash
# VeriCase AWS Infrastructure Overview Script
# Run this in AWS CloudShell to get complete infrastructure status

set -e

echo "========================================"
echo "VeriCase AWS Infrastructure Overview"
echo "========================================"
echo ""

# Account Info
echo "=== AWS Account ==="
aws sts get-caller-identity
echo ""

# EC2 Instances
echo "=== EC2 Instances ==="
aws ec2 describe-instances --region eu-west-2 --query 'Reservations[*].Instances[*].{InstanceId:InstanceId,Type:InstanceType,State:State.Name,PublicIP:PublicIpAddress,PrivateIP:PrivateIpAddress,Name:Tags[?Key==`Name`].Value|[0]}' --output table
echo ""

# VPC & Networking
echo "=== VPC & Subnets ==="
aws ec2 describe-vpcs --region eu-west-2 --query 'Vpcs[*].{VpcId:VpcId,CidrBlock:CidrBlock,State:State,Name:Tags[?Key==`Name`].Value|[0]}' --output table
echo ""
aws ec2 describe-subnets --region eu-west-2 --query 'Subnets[*].{SubnetId:SubnetId,VpcId:VpcId,CidrBlock:CidrBlock,AZ:AvailabilityZone,Public:MapPublicIpOnLaunch}' --output table
echo ""

# Security Groups
echo "=== Security Groups ==="
aws ec2 describe-security-groups --region eu-west-2 --query 'SecurityGroups[*].{GroupId:GroupId,GroupName:GroupName,VpcId:VpcId,Description:Description}' --output table
echo ""

# EKS Clusters
echo "=== EKS Clusters ==="
aws eks list-clusters --region eu-west-2 --output table
echo ""
aws eks describe-cluster --name vericase-cluster --region eu-west-2 --query 'cluster.{Name:name,Status:status,Version:version,Endpoint:endpoint,CreatedAt:createdAt}' --output table
echo ""

# EKS Node Groups
echo "=== EKS Node Groups ==="
aws eks list-nodegroups --cluster-name vericase-cluster --region eu-west-2 --output table
echo ""

# EKS Access Entries
echo "=== EKS Access Entries ==="
aws eks list-access-entries --cluster-name vericase-cluster --region eu-west-2 --output table
echo ""

# RDS/Aurora
echo "=== RDS Instances ==="
aws rds describe-db-instances --region eu-west-2 --query 'DBInstances[*].{DBInstanceIdentifier:DBInstanceIdentifier,Engine:Engine,Class:DBInstanceClass,Status:DBInstanceStatus,Endpoint:Endpoint.Address,Port:Endpoint.Port}' --output table
echo ""

echo "=== RDS Clusters ==="
aws rds describe-db-clusters --region eu-west-2 --query 'DBClusters[*].{DBClusterIdentifier:DBClusterIdentifier,Engine:Engine,Status:Status,Endpoint:Endpoint,ReaderEndpoint:ReaderEndpoint}' --output table
echo ""

# S3 Buckets
echo "=== S3 Buckets ==="
aws s3api list-buckets --query 'Buckets[*].{Name:Name,CreationDate:CreationDate}' --output table
echo ""

# IAM Roles (filtered to VeriCase related)
echo "=== IAM Roles (VeriCase Related) ==="
aws iam list-roles --query 'Roles[?contains(RoleName, `vericase`) || contains(RoleName, `VeriCase`) || contains(RoleName, `GitHub`)].{RoleName:RoleName,CreateDate:CreateDate}' --output table
echo ""

# IAM Users
echo "=== IAM Users ==="
aws iam list-users --query 'Users[*].{UserName:UserName,CreateDate:CreateDate,PasswordLastUsed:PasswordLastUsed}' --output table
echo ""

# Lambda Functions
echo "=== Lambda Functions ==="
aws lambda list-functions --region eu-west-2 --query 'Functions[*].{FunctionName:FunctionName,Runtime:Runtime,LastModified:LastModified}' --output table
echo ""

# ElastiCache
echo "=== ElastiCache Clusters ==="
aws elasticache describe-cache-clusters --region eu-west-2 --query 'CacheClusters[*].{CacheClusterId:CacheClusterId,Engine:Engine,NodeType:CacheNodeType,Status:CacheClusterStatus}' --output table
echo ""

# OpenSearch
echo "=== OpenSearch Domains ==="
aws opensearch list-domain-names --region eu-west-2 --query 'DomainNames[*].{DomainName:DomainName}' --output table
echo ""

# Secrets Manager
echo "=== Secrets Manager ==="
aws secretsmanager list-secrets --region eu-west-2 --query 'SecretList[*].{Name:Name,Description:Description,LastChangedDate:LastChangedDate}' --output table
echo ""

# Load Balancers
echo "=== Application Load Balancers ==="
aws elbv2 describe-load-balancers --region eu-west-2 --query 'LoadBalancers[*].{LoadBalancerName:LoadBalancerName,Type:Type,State:State.Code,DNSName:DNSName}' --output table
echo ""

# Auto Scaling Groups
echo "=== Auto Scaling Groups ==="
aws autoscaling describe-auto-scaling-groups --region eu-west-2 --query 'AutoScalingGroups[*].{AutoScalingGroupName:AutoScalingGroupName,MinSize:MinSize,MaxSize:MaxSize,DesiredCapacity:DesiredCapacity}' --output table
echo ""

# CloudFormation Stacks
echo "=== CloudFormation Stacks ==="
aws cloudformation list-stacks --region eu-west-2 --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query 'StackSummaries[*].{StackName:StackName,StackStatus:StackStatus,CreationTime:CreationTime}' --output table
echo ""

# Route53 Hosted Zones
echo "=== Route53 Hosted Zones ==="
aws route53 list-hosted-zones --query 'HostedZones[*].{Name:Name,Id:Id,RecordSetCount:ResourceRecordSetCount}' --output table
echo ""

# Kubernetes Resources (if EKS access works)
echo "=== Kubernetes Resources ==="
if aws eks update-kubeconfig --name vericase-cluster --region eu-west-2 >/dev/null 2>&1; then
    echo "Deployments:"
    kubectl get deployments -n vericase -o wide 2>/dev/null || echo "No deployments found or access denied"
    echo ""
    echo "Pods:"
    kubectl get pods -n vericase -o wide 2>/dev/null || echo "No pods found or access denied"
    echo ""
    echo "Services:"
    kubectl get services -n vericase 2>/dev/null || echo "No services found or access denied"
    echo ""
    echo "Ingress:"
    kubectl get ingress -n vericase 2>/dev/null || echo "No ingress found or access denied"
else
    echo "Cannot access EKS cluster - check permissions"
fi
echo ""

echo "========================================"
echo "Infrastructure Overview Complete"
echo "========================================"