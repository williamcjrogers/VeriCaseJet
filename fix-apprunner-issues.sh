#!/bin/bash
# Fix App Runner deployment issues

REGION="eu-west-2"
SERVICE_NAME="VeriCase-api"

echo "=== Fixing App Runner Issues ==="

# 1. Fix Database Password in Secrets Manager
echo "1. Update DATABASE_URL with correct password..."
echo "   Current: VericaseDocsAdmin:Sunnyday8?!"
echo "   Action: Verify RDS password matches environment variable"

# 2. Fix S3 Access - Update Instance Role
echo ""
echo "2. Fix S3 Access - Add S3 permissions to instance role..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_NAME="VeriCaseAppRunnerInstanceRole"

cat > /tmp/s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::vericase-data",
        "arn:aws:s3:::vericase-data/*"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name VeriCaseS3Access \
  --policy-document file:///tmp/s3-policy.json \
  --region $REGION

echo "✓ S3 policy attached to $ROLE_NAME"

# 3. Fix OpenSearch Access
echo ""
echo "3. Fix OpenSearch Access..."
OPENSEARCH_DOMAIN="vericase-opensearch"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

echo "   Add this to OpenSearch access policy:"
echo "   {\"Effect\":\"Allow\",\"Principal\":{\"AWS\":\"$ROLE_ARN\"},\"Action\":\"es:*\",\"Resource\":\"arn:aws:es:${REGION}:${ACCOUNT_ID}:domain/${OPENSEARCH_DOMAIN}/*\"}"

# 4. Fix UI 404 - Check static files mount
echo ""
echo "4. UI 404 Fix - Verify static files..."
echo "   UI is mounted at: /app/pst-analysis-engine/ui"
echo "   Accessing via: /ui/"
echo "   Issue: StaticFiles may need html=True parameter"

echo ""
echo "=== Next Steps ==="
echo "1. Verify RDS password in AWS Console"
echo "2. Redeploy App Runner service to apply changes"
echo "3. Check logs after deployment"

# Trigger redeployment
SERVICE_ARN=$(aws apprunner list-services --region $REGION --query "ServiceSummaryList[?ServiceName=='$SERVICE_NAME'].ServiceArn" --output text)
echo ""
echo "Trigger deployment:"
echo "aws apprunner start-deployment --service-arn $SERVICE_ARN --region $REGION"
