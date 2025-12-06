# Amazon Bedrock Setup Guide

## Overview

Amazon Bedrock is now integrated into VeriCase Analysis, providing access to:
- **Amazon Nova** models (Micro, Lite, Pro, 2 Pro, 2 Lite)
- **Anthropic Claude** models (3.5 Sonnet, 4.5 Haiku, 4.5 Sonnet, 4.5 Opus)
- **Amazon Titan** models (Text Express, Embeddings v2)
- **Meta Llama** models (3.3 70B Instruct)
- **Mistral** models (Large 24.07)

## Quick Start

### 1. Configure AWS Credentials

Choose one of these methods:

#### Option A: AWS CLI (Recommended for Development)
```bash
aws configure
# Enter your AWS Access Key ID
# Enter your AWS Secret Access Key
# Enter your default region (e.g., eu-west-2)
```

#### Option B: Environment Variables
Add to your `.env` file:
```bash
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_REGION=eu-west-2
```

#### Option C: IAM Role (Recommended for Production)
- For EC2: Attach IAM role to instance
- For ECS/Fargate: Use task role
- For Lambda: Use execution role

### 2. Verify IAM Permissions

Your AWS user/role needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*"
      ]
    }
  ]
}
```

### 3. Enable Model Access

1. Go to AWS Console → Bedrock → Model access
2. Request access to models you want to use:
   - Amazon Nova (recommended - instant access)
   - Anthropic Claude (may require approval)
   - Amazon Titan
   - Meta Llama
   - Mistral

### 4. Test Your Setup

Run the test script:
```bash
cd pst-analysis-engine
python test_bedrock_setup.py
```

Expected output:
```
✓ AWS Region: eu-west-2
✓ Credentials: IAM Role/Default chain
✓ Bedrock provider imported successfully
✓ AWS credentials found
✓ Bedrock provider initialized
✓ Connection successful!
```

## Configuration

### Environment Variables

In your `.env` file:

```bash
# Enable AI features
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true

# AWS Configuration
AWS_REGION=eu-west-2
AWS_ACCESS_KEY_ID=          # Optional - leave empty to use IAM role
AWS_SECRET_ACCESS_KEY=      # Optional - leave empty to use IAM role

# Bedrock Configuration
BEDROCK_DEFAULT_MODEL=amazon.nova-micro-v1:0
BEDROCK_REGION=eu-west-2
```

### Model Selection

Choose based on your needs:

| Model | Use Case | Speed | Cost | Quality |
|-------|----------|-------|------|---------|
| `amazon.nova-micro-v1:0` | Simple tasks, high volume | ⚡⚡⚡ | 💰 | ⭐⭐⭐ |
| `amazon.nova-lite-v1:0` | Balanced performance | ⚡⚡ | 💰💰 | ⭐⭐⭐⭐ |
| `amazon.nova-pro-v1:0` | Complex analysis | ⚡ | 💰💰💰 | ⭐⭐⭐⭐⭐ |
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | Premium quality | ⚡ | 💰💰💰💰 | ⭐⭐⭐⭐⭐ |

## Usage Examples

### Basic Usage

```python
from api.app.ai_providers import BedrockProvider

# Initialize provider
provider = BedrockProvider(region="eu-west-2")

# Simple query
response = await provider.invoke(
    model_id="amazon.nova-micro-v1:0",
    prompt="Summarize this legal document...",
    max_tokens=1000,
    temperature=0.7
)

print(response)
```

### With System Prompt

```python
response = await provider.invoke(
    model_id="amazon.nova-pro-v1:0",
    prompt="Analyze this contract for key terms",
    system_prompt="You are a legal document analyst. Focus on obligations and deadlines.",
    max_tokens=2000,
    temperature=0.3
)
```

### Get Embeddings

```python
# For semantic search
embeddings = await provider.get_embeddings(
    text="Contract for software development services",
    model_id="amazon.titan-embed-text-v2:0"
)
```

## Integration with VeriCase

Bedrock is automatically used by:

1. **AI Orchestrator** (`/ai/orchestrator/*`)
   - Dataset analysis
   - Document insights
   - Timeline generation

2. **Document Classification** (when enabled)
   - Auto-categorize documents
   - Extract key entities
   - Identify document types

3. **Natural Language Search** (when enabled)
   - Query documents in plain English
   - Semantic search
   - Context-aware results

## Troubleshooting

### "No AWS credentials found"

**Solution:**
1. Run `aws configure` to set up credentials
2. Or add credentials to `.env` file
3. Or use IAM role (for AWS services)

### "Access denied" or "ValidationException"

**Solution:**
1. Check IAM permissions (see above)
2. Verify model access in Bedrock console
3. Ensure region supports Bedrock (eu-west-2 does)

### "Model not found"

**Solution:**
1. Go to Bedrock console → Model access
2. Request access to the model
3. Wait for approval (instant for Nova, may take time for Claude)

### "Rate limit exceeded"

**Solution:**
1. Reduce request frequency
2. Implement exponential backoff
3. Request quota increase in AWS console

## Cost Optimization

### Tips to Reduce Costs

1. **Use appropriate models:**
   - Nova Micro for simple tasks
   - Nova Pro only when needed

2. **Limit token usage:**
   - Set reasonable `max_tokens`
   - Use concise prompts

3. **Cache results:**
   - Store common queries
   - Reuse embeddings

4. **Monitor usage:**
   - Check AWS Cost Explorer
   - Set up billing alerts

### Estimated Costs (as of 2025)

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|-------|----------------------|------------------------|
| Nova Micro | $0.035 | $0.14 |
| Nova Lite | $0.06 | $0.24 |
| Nova Pro | $0.80 | $3.20 |
| Claude 3.5 Sonnet | $3.00 | $15.00 |

## Security Best Practices

1. **Never commit credentials:**
   - Use `.env` file (already in `.gitignore`)
   - Use AWS Secrets Manager for production

2. **Use IAM roles:**
   - Preferred over access keys
   - Automatic credential rotation

3. **Limit permissions:**
   - Only grant necessary Bedrock permissions
   - Use resource-based policies

4. **Monitor access:**
   - Enable CloudTrail logging
   - Set up CloudWatch alarms

## Next Steps

1. ✅ Configure AWS credentials
2. ✅ Test connection with `test_bedrock_setup.py`
3. ✅ Choose your default model
4. ✅ Enable AI features in `.env`
5. 🚀 Start using Bedrock in your application!

## Support

- **AWS Bedrock Docs:** https://docs.aws.amazon.com/bedrock/
- **Model Pricing:** https://aws.amazon.com/bedrock/pricing/
- **VeriCase Issues:** Check project documentation

---

**Status:** ✅ Bedrock integration complete and ready to use!
