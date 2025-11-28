#!/bin/bash
# Deploy all AWS services for VeriCase in one go

echo "========================================="
echo "VeriCase AWS Services Deployment"
echo "========================================="
echo ""
echo "This will create:"
echo "  1. ElastiCache Redis (~$13/month) - REQUIRED"
echo "  2. OpenSearch (~$50/month) - OPTIONAL"
echo "  3. Tika on ECS (~$30/month) - OPTIONAL"
echo ""
echo "Total cost: $13-93/month depending on what you deploy"
echo ""
read -p "Deploy Redis only (R), All services (A), or Cancel (C)? " choice

case $choice in
  [Rr]* )
    echo ""
    echo "Deploying Redis only..."
    ./create-redis-in-vpc.sh
    ;;
  [Aa]* )
    echo ""
    echo "Deploying all services..."
    echo ""
    echo "1/3: Creating Redis..."
    ./create-redis-in-vpc.sh
    echo ""
    echo "2/3: Creating OpenSearch..."
    ./create-opensearch-in-vpc.sh
    echo ""
    echo "3/3: Creating Tika..."
    ./create-tika-in-vpc.sh
    ;;
  * )
    echo "Cancelled"
    exit 0
    ;;
esac

echo ""
echo "========================================="
echo "Deployment Started!"
echo "========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Wait for services to be ready:"
echo "   - Redis: 5-10 minutes"
echo "   - OpenSearch: 15-20 minutes"
echo "   - Tika: 5 minutes"
echo ""
echo "2. Get endpoints:"
echo ""
echo "   # Redis endpoint"
echo "   aws elasticache describe-cache-clusters \\"
echo "     --region eu-west-2 \\"
echo "     --cache-cluster-id vericase-redis \\"
echo "     --show-cache-node-info \\"
echo "     --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' \\"
echo "     --output text"
echo ""
echo "   # OpenSearch endpoint"
echo "   aws opensearch describe-domain \\"
echo "     --region eu-west-2 \\"
echo "     --domain-name vericase-search \\"
echo "     --query 'DomainStatus.Endpoint' \\"
echo "     --output text"
echo ""
echo "3. Update .env.production with the endpoints"
echo ""
echo "4. Deploy your application"
echo ""
