# Setup IRSA (IAM Roles for Service Accounts) for VeriCase EKS

$CLUSTER_NAME = "vericase-cluster"
$REGION = "eu-west-2"
$ACCOUNT_ID = "526015377510"
$ROLE_NAME = "vericase-eks-pod-role"

# Create IAM policy for VeriCase
$POLICY_DOC = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:*",
        "textract:*",
        "comprehend:*",
        "bedrock:*",
        "rekognition:*",
        "transcribe:*"
      ],
      "Resource": "*"
    }
  ]
}
"@

Write-Host "Creating IAM policy..."
$POLICY_DOC | Out-File -FilePath policy.json -Encoding utf8
aws iam create-policy --policy-name VeriCaseEKSPolicy --policy-document file://policy.json --region $REGION

# Create IAM role with trust policy for EKS
$TRUST_POLICY = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/$(aws eks describe-cluster --name $CLUSTER_NAME --region $REGION --query 'cluster.identity.oidc.issuer' --output text | Split-Path -Leaf)"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.${REGION}.amazonaws.com/id/$(aws eks describe-cluster --name $CLUSTER_NAME --region $REGION --query 'cluster.identity.oidc.issuer' --output text | Split-Path -Leaf):sub": "system:serviceaccount:default:vericase-api-sa"
        }
      }
    }
  ]
}
"@

Write-Host "Creating IAM role..."
$TRUST_POLICY | Out-File -FilePath trust-policy.json -Encoding utf8
aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document file://trust-policy.json --region $REGION

Write-Host "Attaching policy to role..."
aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/VeriCaseEKSPolicy" --region $REGION

Write-Host "Done! Role ARN: arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
