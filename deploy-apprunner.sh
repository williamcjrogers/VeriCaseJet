#!/bin/bash
# Deploy VeriCase to AWS App Runner with VPC configuration
# This script uses App Runner with apprunner.yaml configuration file

SERVICE_NAME="vericase-api"
REGION="eu-west-2"
VPC_ID="vpc-0880b8ccf488f527e"
REPO_URL="https://github.com/williamcjrogers/VeriCase-Analysis"
BRANCH="main"

echo "🚀 Deploying VeriCase to AWS App Runner..."
echo ""
echo "Repository: $REPO_URL"
echo "Branch: $BRANCH"
echo "Region: $REGION"
echo "VPC: $VPC_ID"
echo ""

# Note: VPC connector must be created through console first
echo "⚠️  PREREQUISITES:"
echo ""
echo "1. VPC Connector Configuration:"
echo "   - VPC: $VPC_ID"
echo "   - Subnets: 2+ subnets in different AZs"
echo "   - Security Group with outbound rules:"
echo "     • PostgreSQL (5432) → RDS"
echo "     • Redis (6379) → ElastiCache"
echo "     • HTTPS (443) → OpenSearch"
echo "     • All traffic → Internet (S3, AI APIs)"
echo ""
echo "2. RDS/Redis/OpenSearch Security Groups:"
echo "   - Must allow inbound from App Runner security group"
echo ""
echo "3. Configuration File:"
echo "   - apprunner.yaml at repository root"
echo "   - Contains all environment variables"
echo ""
echo "📖 See VPC_NETWORKING_GUIDE.md for detailed setup"
echo ""

read -p "Have you completed VPC setup and security group configuration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "❌ Please complete VPC setup first:"
    echo "   1. Review: VPC_NETWORKING_GUIDE.md"
    echo "   2. Create VPC connector in AWS Console"
    echo "   3. Configure security groups"
    echo "   4. Run this script again"
    exit 1
fi

read -p "Enter VPC Connector ARN: " VPC_CONNECTOR_ARN

if [ -z "$VPC_CONNECTOR_ARN" ]; then
    echo "❌ VPC Connector ARN is required"
    exit 1
fi

echo ""
echo "📦 Creating App Runner service with configuration file..."
echo ""

# Create service using apprunner.yaml configuration
aws apprunner create-service \
  --service-name "$SERVICE_NAME" \
  --region "$REGION" \
  --source-configuration "{
    \"CodeRepository\": {
      \"RepositoryUrl\": \"$REPO_URL\",
      \"SourceCodeVersion\": {
        \"Type\": \"BRANCH\",
        \"Value\": \"$BRANCH\"
      },
      \"CodeConfiguration\": {
        \"ConfigurationSource\": \"REPOSITORY\",
        \"CodeConfigurationValues\": {
          \"ConfigurationFile\": \"apprunner.yaml\"
        }
      }
    },
    \"AutoDeploymentsEnabled\": true
  }" \
  --instance-configuration '{
    "Cpu": "2048",
    "Memory": "4096"
  }' \
  --network-configuration "{
    \"EgressConfiguration\": {
      \"EgressType\": \"VPC\",
      \"VpcConnectorArn\": \"$VPC_CONNECTOR_ARN\"
    }
  }"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Deployment initiated successfully!"
    echo ""
    echo "📊 Monitor deployment:"
    echo "   https://$REGION.console.aws.amazon.com/apprunner/home?region=$REGION#/services"
    echo ""
    echo "⏱️  Deployment takes ~10-15 minutes for initial build"
    echo ""
    echo "📝 Next steps:"
    echo "   1. Wait for deployment to complete"
    echo "   2. Check logs for any connection errors"
    echo "   3. Test database, Redis, and OpenSearch connectivity"
    echo "   4. Access your app at the App Runner URL"
else
    echo ""
    echo "❌ Deployment failed!"
    echo ""
    echo "Common issues:"
    echo "   - Service name already exists (delete old service first)"
    echo "   - Invalid VPC Connector ARN"
    echo "   - AWS credentials not configured"
    echo "   - Insufficient IAM permissions"
fi
