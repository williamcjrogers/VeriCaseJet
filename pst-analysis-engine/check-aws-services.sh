#!/bin/bash
# Check what AWS services are already deployed

echo "Checking AWS Services in eu-west-2..."
echo ""

# Check ElastiCache Redis
echo "=== ElastiCache Redis Clusters ==="
aws elasticache describe-cache-clusters --region eu-west-2 --query 'CacheClusters[*].[CacheClusterId,CacheNodeType,CacheClusterStatus,ConfigurationEndpoint.Address,ConfigurationEndpoint.Port]' --output table 2>/dev/null || echo "No Redis clusters found or AWS CLI not configured"
echo ""

# Check OpenSearch domains
echo "=== OpenSearch Domains ==="
aws opensearch list-domain-names --region eu-west-2 --query 'DomainNames[*].DomainName' --output table 2>/dev/null || echo "No OpenSearch domains found or AWS CLI not configured"
echo ""

# Check ECS clusters (for Tika)
echo "=== ECS Clusters ==="
aws ecs list-clusters --region eu-west-2 --query 'clusterArns' --output table 2>/dev/null || echo "No ECS clusters found or AWS CLI not configured"
echo ""

# Check RDS instances
echo "=== RDS Instances ==="
aws rds describe-db-instances --region eu-west-2 --query 'DBInstances[*].[DBInstanceIdentifier,DBInstanceClass,DBInstanceStatus,Endpoint.Address]' --output table 2>/dev/null || echo "No RDS instances found or AWS CLI not configured"
echo ""

# Check S3 buckets
echo "=== S3 Buckets ==="
aws s3 ls 2>/dev/null | grep vericase || echo "No vericase buckets found or AWS CLI not configured"
echo ""

echo "Done! If you see 'AWS CLI not configured', run: aws configure"
