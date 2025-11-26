#!/bin/bash
# Fix IAM role trust policy for App Runner
# Run this with AWS CLI configured for VeriCaseDocs account

ROLE_NAME="VeriCaseAppRunnerInstanceRole"

echo "Updating trust policy for $ROLE_NAME..."

# Create trust policy
cat > /tmp/trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "tasks.apprunner.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Update the role's trust policy
aws iam update-assume-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-document file:///tmp/trust-policy.json

echo "✓ Trust policy updated"
echo ""
echo "Now you can assign this role in App Runner console:"
echo "1. Go to App Runner → VeriCase API → Configuration"
echo "2. Security → Instance role → Select VeriCaseAppRunnerInstanceRole"
echo "3. Save and Deploy"
