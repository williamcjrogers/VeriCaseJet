#!/bin/bash
# Add missing policies to VeriCaseAppRunnerInstanceRole

ROLE_NAME="VeriCaseAppRunnerInstanceRole"
REGION="eu-west-2"
ACCOUNT_ID="526015377510"

echo "Adding policies to $ROLE_NAME..."

# Policy 1: S3 Access
cat > /tmp/s3-policy.json << 'EOF'
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
  --role-name "$ROLE_NAME" \
  --policy-name "VeriCaseS3Access" \
  --policy-document file:///tmp/s3-policy.json

echo "✓ S3 policy added"

# Policy 2: OpenSearch Access
cat > /tmp/opensearch-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "es:ESHttpGet",
        "es:ESHttpPost",
        "es:ESHttpPut",
        "es:ESHttpDelete",
        "es:ESHttpHead"
      ],
      "Resource": "arn:aws:es:${REGION}:${ACCOUNT_ID}:domain/vericase-opensearch/*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "VeriCaseOpenSearchAccess" \
  --policy-document file:///tmp/opensearch-policy.json

echo "✓ OpenSearch policy added"

# Policy 3: Secrets Manager Access
cat > /tmp/secrets-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": [
        "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:vericase/*",
        "arn:aws:secretsmanager:${REGION}:${ACCOUNT_ID}:secret:rds!*"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "VeriCaseSecretsAccess" \
  --policy-document file:///tmp/secrets-policy.json

echo "✓ Secrets Manager policy added"

echo ""
echo "=== All policies added successfully ==="
echo ""
echo "Now redeploy your App Runner service to apply changes:"
echo "1. Go to App Runner → VeriCase API"
echo "2. Click 'Deploy' button"
echo "3. Wait for deployment to complete"
