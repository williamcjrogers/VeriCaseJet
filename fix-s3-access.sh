#!/bin/bash
# Fix S3 Access for App Runner

ROLE_NAME="VeriCaseAppRunnerInstanceRole"
REGION="eu-west-2"

echo "=== Adding S3 Permissions to App Runner Role ==="

# Create inline policy directly
aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name VeriCaseS3FullAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ],
        "Resource": [
          "arn:aws:s3:::vericase-data",
          "arn:aws:s3:::vericase-data/*"
        ]
      }
    ]
  }' \
  --region $REGION

if [ $? -eq 0 ]; then
    echo "✓ S3 policy successfully attached to $ROLE_NAME"
else
    echo "✗ Failed to attach S3 policy"
    exit 1
fi

echo ""
echo "=== Next: Add OpenSearch Access ==="
echo "Run this command to update OpenSearch access policy:"
echo ""
echo "aws opensearch update-domain-config \\"
echo "  --domain-name vericase-opensearch \\"
echo "  --access-policies '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"AWS\":\"arn:aws:iam::526015377510:role/VeriCaseAppRunnerInstanceRole\"},\"Action\":\"es:*\",\"Resource\":\"arn:aws:es:eu-west-2:526015377510:domain/vericase-opensearch/*\"}]}' \\"
echo "  --region eu-west-2"

echo ""
echo "=== Then Redeploy App Runner ==="
echo "aws apprunner start-deployment \\"
echo "  --service-arn arn:aws:apprunner:eu-west-2:526015377510:service/VeriCase-api/92edc88957f0476fab92a10457b9fe0f \\"
echo "  --region eu-west-2"
