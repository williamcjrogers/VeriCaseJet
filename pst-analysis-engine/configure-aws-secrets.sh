#!/bin/bash
# One-click AWS Secrets Manager configuration for VeriCase

set -e

REGION="eu-west-2"
SECRET_NAME="vericase/api-keys"

echo "========================================="
echo "VeriCase AWS Secrets Manager Setup"
echo "========================================="
echo ""

# Prompt for API keys
echo "Enter your NEW API keys (get them from providers first!):"
echo ""
read -p "Gemini API Key: " GEMINI_KEY
read -p "Claude API Key: " CLAUDE_KEY
read -p "OpenAI API Key: " OPENAI_KEY
read -p "Grok API Key: " GROK_KEY
read -p "Perplexity API Key: " PERPLEXITY_KEY

echo ""
echo "Creating secret in AWS Secrets Manager..."

# Create or update the secret
aws secretsmanager create-secret \
  --region $REGION \
  --name $SECRET_NAME \
  --description "VeriCase AI API Keys" \
  --secret-string "{
    \"GEMINI_API_KEY\": \"$GEMINI_KEY\",
    \"CLAUDE_API_KEY\": \"$CLAUDE_KEY\",
    \"OPENAI_API_KEY\": \"$OPENAI_KEY\",
    \"GROK_API_KEY\": \"$GROK_KEY\",
    \"PERPLEXITY_API_KEY\": \"$PERPLEXITY_KEY\",
    \"SIGPARSER_API_KEY\": \"AuX7lTpPhZ+Ku70yTlKf0Y88X8LBilRoTdD8AQv0f5F0xXaU8837xOJNlGrGREg/z/mqzdKW8Z77CJelY0A21w==\"
  }" 2>/dev/null

if [ $? -ne 0 ]; then
  echo "Secret exists, updating..."
  aws secretsmanager update-secret \
    --region $REGION \
    --secret-id $SECRET_NAME \
    --secret-string "{
      \"GEMINI_API_KEY\": \"$GEMINI_KEY\",
      \"CLAUDE_API_KEY\": \"$CLAUDE_KEY\",
      \"OPENAI_API_KEY\": \"$OPENAI_KEY\",
      \"GROK_API_KEY\": \"$GROK_KEY\",
      \"PERPLEXITY_API_KEY\": \"$PERPLEXITY_KEY\",
      \"SIGPARSER_API_KEY\": \"AuX7lTpPhZ+Ku70yTlKf0Y88X8LBilRoTdD8AQv0f5F0xXaU8837xOJNlGrGREg/z/mqzdKW8Z77CJelY0A21w==\"
    }"
fi

echo ""
echo "✅ Secret created/updated successfully!"
echo ""

# Get secret ARN
SECRET_ARN=$(aws secretsmanager describe-secret \
  --region $REGION \
  --secret-id $SECRET_NAME \
  --query 'ARN' \
  --output text)

echo "Secret ARN: $SECRET_ARN"
echo ""

# Create IAM policy for accessing the secret
echo "Creating IAM policy for secret access..."

POLICY_NAME="VeriCaseSecretsAccess"
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)

aws iam create-policy \
  --policy-name $POLICY_NAME \
  --description "Allow VeriCase to read API keys from Secrets Manager" \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [{
      \"Effect\": \"Allow\",
      \"Action\": [
        \"secretsmanager:GetSecretValue\",
        \"secretsmanager:DescribeSecret\"
      ],
      \"Resource\": \"$SECRET_ARN\"
    }]
  }" 2>/dev/null

if [ $? -eq 0 ]; then
  echo "✅ IAM policy created!"
  POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
else
  echo "Policy already exists"
  POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
fi

echo ""
echo "Policy ARN: $POLICY_ARN"
echo ""

# Attach policy to EKS node role
echo "Attaching policy to EKS node role..."

NODE_ROLE=$(aws iam list-roles \
  --query "Roles[?contains(RoleName, 'eksctl-vericase-cluster-nodegroup')].RoleName" \
  --output text | head -1)

if [ -n "$NODE_ROLE" ]; then
  aws iam attach-role-policy \
    --role-name $NODE_ROLE \
    --policy-arn $POLICY_ARN 2>/dev/null
  
  if [ $? -eq 0 ]; then
    echo "✅ Policy attached to EKS node role: $NODE_ROLE"
  else
    echo "Policy already attached to: $NODE_ROLE"
  fi
else
  echo "⚠️  EKS node role not found. Attach policy manually."
fi

echo ""
echo "========================================="
echo "✅ Configuration Complete!"
echo "========================================="
echo ""
echo "Your API keys are now stored securely in AWS Secrets Manager."
echo ""
echo "Next steps:"
echo "1. Your .env.production is already configured"
echo "2. Deploy your application"
echo "3. Keys will be loaded automatically on startup"
echo ""
echo "To verify:"
echo "aws secretsmanager get-secret-value \\"
echo "  --secret-id $SECRET_NAME \\"
echo "  --region $REGION \\"
echo "  --query 'SecretString' --output text | jq"
echo ""
