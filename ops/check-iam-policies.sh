#!/bin/bash
# Check current policies on VeriCaseAppRunnerInstanceRole

ROLE_NAME="VeriCaseAppRunnerInstanceRole"

echo "=== Checking IAM Role: $ROLE_NAME ==="
echo ""

echo "Attached Managed Policies:"
aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[*].[PolicyName,PolicyArn]' --output table

echo ""
echo "Inline Policies:"
aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames' --output table

echo ""
echo "=== Policy Details ==="
for policy in $(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames[]' --output text); do
    echo ""
    echo "Policy: $policy"
    aws iam get-role-policy --role-name "$ROLE_NAME" --policy-name "$policy" --query 'PolicyDocument' --output json
done
