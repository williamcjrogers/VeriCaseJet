#!/bin/bash
# Configure S3 access for App Runner service

# Variables
SERVICE_NAME="VeriCase-api"
REGION="eu-west-2"
S3_BUCKET="vericase-data"

echo "=== Configuring S3 Access for App Runner ==="

# Step 1: Get the App Runner service ARN
echo "Finding App Runner service ARN..."
SERVICE_ARN=$(aws apprunner list-services --region $REGION --query "ServiceSummaryList[?ServiceName=='$SERVICE_NAME'].ServiceArn" --output text)

if [ -z "$SERVICE_ARN" ]; then
    echo "Error: Could not find App Runner service $SERVICE_NAME"
    exit 1
fi
echo "Service ARN: $SERVICE_ARN"

# Step 2: Get the IAM role associated with the App Runner service
echo "Finding IAM role for App Runner service..."
ROLE_ARN=$(aws apprunner describe-service --service-arn $SERVICE_ARN --region $REGION --query "Service.InstanceConfiguration.InstanceRoleArn" --output text)

if [ -z "$ROLE_ARN" ] || [ "$ROLE_ARN" == "None" ]; then
    echo "Error: No IAM role associated with App Runner service"
    echo "App Runner might be using the default service role"
    
    # Get the default App Runner service role
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    ROLE_NAME="AppRunnerECRAccessRole"
    ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/service-role/$ROLE_NAME"
    echo "Attempting to use default role: $ROLE_ARN"
fi

# Extract role name from ARN
ROLE_NAME=$(echo $ROLE_ARN | cut -d'/' -f2-)
echo "IAM Role Name: $ROLE_NAME"

# Step 3: Create S3 access policy
POLICY_NAME="VeriCaseS3AccessPolicy"
POLICY_DOCUMENT='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket",
                "s3:GetBucketLocation",
                "s3:GetBucketVersioning"
            ],
            "Resource": [
                "arn:aws:s3:::'"$S3_BUCKET"'",
                "arn:aws:s3:::'"$S3_BUCKET"'/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets",
                "s3:GetBucketLocation"
            ],
            "Resource": "*"
        }
    ]
}'

echo "Creating IAM policy for S3 access..."
# Create the policy (this might fail if it already exists)
POLICY_ARN=$(aws iam create-policy \
    --policy-name $POLICY_NAME \
    --policy-document "$POLICY_DOCUMENT" \
    --description "S3 access policy for VeriCase App Runner" \
    --query "Policy.Arn" \
    --output text 2>/dev/null)

if [ $? -ne 0 ]; then
    echo "Policy might already exist, getting existing policy ARN..."
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    POLICY_ARN="arn:aws:iam::$ACCOUNT_ID:policy/$POLICY_NAME"
fi

echo "Policy ARN: $POLICY_ARN"

# Step 4: Attach the policy to the role
echo "Attaching policy to IAM role..."
aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn "$POLICY_ARN"

if [ $? -eq 0 ]; then
    echo "✅ Successfully attached S3 access policy to App Runner role"
else
    echo "❌ Failed to attach policy. You might need to:"
    echo "   1. Check if the role exists"
    echo "   2. Ensure you have IAM permissions"
    echo "   3. Manually create an instance role for App Runner"
fi

echo ""
echo "=== Next Steps ==="
echo "1. The App Runner service will automatically use the new permissions"
echo "2. No restart required - IAM changes take effect within seconds"
echo "3. Check App Runner logs to verify S3 access is working"
