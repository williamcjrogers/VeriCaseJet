#!/bin/bash
# Store API keys in AWS Secrets Manager

REGION="eu-west-2"
SECRET_NAME="vericase/api-keys"

echo "Creating AWS Secrets Manager secret for API keys..."

# Create the secret with all API keys
aws secretsmanager create-secret \
  --region $REGION \
  --name $SECRET_NAME \
  --description "VeriCase AI API Keys" \
  --secret-string '{
    "GEMINI_API_KEY": "YOUR_NEW_GEMINI_KEY",
    "CLAUDE_API_KEY": "YOUR_NEW_CLAUDE_KEY",
    "OPENAI_API_KEY": "YOUR_NEW_OPENAI_KEY",
    "GROK_API_KEY": "YOUR_NEW_GROK_KEY",
    "PERPLEXITY_API_KEY": "YOUR_NEW_PERPLEXITY_KEY",
    "SIGPARSER_API_KEY": "AuX7lTpPhZ+Ku70yTlKf0Y88X8LBilRoTdD8AQv0f5F0xXaU8837xOJNlGrGREg/z/mqzdKW8Z77CJelY0A21w=="
  }' 2>/dev/null

if [ $? -eq 0 ]; then
  echo "✅ Secret created successfully!"
else
  echo "Secret already exists, updating..."
  aws secretsmanager update-secret \
    --region $REGION \
    --secret-id $SECRET_NAME \
    --secret-string '{
      "GEMINI_API_KEY": "YOUR_NEW_GEMINI_KEY",
      "CLAUDE_API_KEY": "YOUR_NEW_CLAUDE_KEY",
      "OPENAI_API_KEY": "YOUR_NEW_OPENAI_KEY",
      "GROK_API_KEY": "YOUR_NEW_GROK_KEY",
      "PERPLEXITY_API_KEY": "YOUR_NEW_PERPLEXITY_KEY",
      "SIGPARSER_API_KEY": "AuX7lTpPhZ+Ku70yTlKf0Y88X8LBilRoTdD8AQv0f5F0xXaU8837xOJNlGrGREg/z/mqzdKW8Z77CJelY0A21w=="
    }'
  echo "✅ Secret updated successfully!"
fi

echo ""
echo "Secret ARN:"
aws secretsmanager describe-secret \
  --region $REGION \
  --secret-id $SECRET_NAME \
  --query 'ARN' \
  --output text

echo ""
echo "Next: Update .env.production to reference this secret"
