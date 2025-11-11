#!/bin/bash
REGION="eu-west-2"
APPRUNNER_SG="sg-0fe33dbc9d4cf20ba"

# RDS
RDS_SG=$(aws rds describe-db-instances --db-instance-identifier database-1 --region $REGION --query 'DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $RDS_SG --protocol tcp --port 5432 --source-group $APPRUNNER_SG --region $REGION
echo "✓ RDS: $RDS_SG"

# Redis
REDIS_SG=$(aws elasticache describe-cache-clusters --region $REGION --query 'CacheClusters[?contains(CacheClusterId, `vericase`)].SecurityGroups[0].SecurityGroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $REDIS_SG --protocol tcp --port 6379 --source-group $APPRUNNER_SG --region $REGION
echo "✓ Redis: $REDIS_SG"

# OpenSearch
OPENSEARCH_SG=$(aws opensearch describe-domain --domain-name vericase-opensearch --region $REGION --query 'DomainStatus.VPCOptions.SecurityGroupIds[0]' --output text)
aws ec2 authorize-security-group-ingress --group-id $OPENSEARCH_SG --protocol tcp --port 443 --source-group $APPRUNNER_SG --region $REGION
echo "✓ OpenSearch: $OPENSEARCH_SG"
