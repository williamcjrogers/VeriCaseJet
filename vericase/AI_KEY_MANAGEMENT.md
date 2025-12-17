# VeriCase AI Key Management Guide

## ðŸ”‘ Where Does VeriCase Load AI Keys From?

VeriCase supports **multiple AI providers** and loads API keys in the following priority order:

### Priority Order (Highest to Lowest)

1. **AWS Secrets Manager** (Production - Recommended)
2. **Environment Variables** (Local/Dev - Direct)
3. **Config Defaults** (Empty - No keys)

---

## ðŸ¤– Supported AI Providers

VeriCase supports **6 AI providers**:

| Provider | Environment Variable | AWS Secrets Manager Key | Notes |
|----------|---------------------|------------------------|-------|
| **Google Gemini** | `GEMINI_API_KEY` | `GEMINI_API_KEY` | Default model, best for general tasks |
| **Anthropic Claude** | `CLAUDE_API_KEY` | `CLAUDE_API_KEY` or `ANTHROPIC_API_KEY` | Best for complex reasoning |
| **OpenAI GPT** | `OPENAI_API_KEY` | `OPENAI_API_KEY` | GPT-4, GPT-3.5 support |
| **AWS Bedrock** | Uses IAM credentials | `BEDROCK_ENABLED`, `BEDROCK_REGION` | No API key needed, uses IAM roles |
| **Grok (X.AI)** | `GROK_API_KEY` | `GROK_API_KEY` | *(Future support - add to Secrets Manager)* |
| **Perplexity** | `PERPLEXITY_API_KEY` | `PERPLEXITY_API_KEY` | *(Future support - add to Secrets Manager)* |

---

## ðŸ“– Method 1: AWS Secrets Manager (Production - RECOMMENDED)

### How It Works

1. **VeriCase automatically checks** AWS Secrets Manager for AI keys when:
   - `AWS_EXECUTION_ENV` is set (running in AWS Lambda/ECS/App Runner)
   - `USE_AWS_SERVICES=true` is set
   - `AWS_SECRETS_MANAGER_AI_KEYS` is explicitly configured

2. **Secret Format**: Store keys in AWS Secrets Manager as JSON

### Setup Instructions

#### Step 1: Create the Secret in AWS Secrets Manager

```bash
# Using AWS CLI
aws secretsmanager create-secret \
  --name vericase/ai-api-keys \
  --description "VeriCase AI Provider API Keys" \
  --region eu-west-2 \
  --secret-string '{
    "GEMINI_API_KEY": "your-gemini-api-key-here",
    "CLAUDE_API_KEY": "your-claude-api-key-here",
    "ANTHROPIC_API_KEY": "your-claude-api-key-here",
    "OPENAI_API_KEY": "your-openai-api-key-here",
    "GROK_API_KEY": "your-grok-api-key-here",
    "PERPLEXITY_API_KEY": "your-perplexity-api-key-here",
    "BEDROCK_ENABLED": "true",
    "BEDROCK_REGION": "eu-west-2"
  }'
```

#### Step 2: Update the Secret (When Rotating Keys)

```bash
aws secretsmanager update-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2 \
  --secret-string '{
    "GEMINI_API_KEY": "your-NEW-gemini-key",
    "CLAUDE_API_KEY": "your-NEW-claude-key",
    "OPENAI_API_KEY": "your-NEW-openai-key"
  }'
```

#### Step 3: Grant IAM Permissions

Your ECS/App Runner/Lambda IAM role needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:eu-west-2:YOUR_ACCOUNT_ID:secret:vericase/ai-api-keys-*"
    }
  ]
}
```

#### Step 4: Configure Environment Variable

In your `.env.production`:

```bash
# Tell VeriCase where to find the secret
AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys
AWS_REGION=eu-west-2
USE_AWS_SERVICES=true
```

### Testing the Loading

Check application logs on startup:

```
[config_production] Should load AI keys from Secrets Manager: True
[config_production] Loading AI keys from Secrets Manager...
[config_production] âœ“ Loaded GEMINI_API_KEY from Secrets Manager
[config_production] âœ“ Loaded CLAUDE_API_KEY from Secrets Manager
[config_production] âœ“ Loaded OPENAI_API_KEY from Secrets Manager
Successfully loaded 3 AI API keys from Secrets Manager
```

---

## ðŸ“– Method 2: Environment Variables (Local Development)

### How It Works

Set API keys directly in your `.env.local`, `.env.aws`, or system environment variables.

### Setup Instructions

#### For Local Development

Edit `.env.local`:

```bash
# AI Model API Keys
GEMINI_API_KEY=<your-gemini-key>
CLAUDE_API_KEY=<your-api-key>
OPENAI_API_KEY=<your-api-key>
GROK_API_KEY=<your-grok-key>
PERPLEXITY_API_KEY=<your-perplexity-key>

# AI Feature Flags (ENABLE ALL)
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_DEFAULT_MODEL=gemini
AI_WEB_ACCESS_ENABLED=true
AI_TASK_COMPLEXITY_DEFAULT=advanced
```

#### For AWS Testing

Edit `.env.aws`:

```bash
# Same as above, plus:
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2

# AWS Bedrock (uses IAM credentials, no API key)
BEDROCK_ENABLED=true
BEDROCK_REGION=eu-west-2
BEDROCK_KB_ID=YOUR_KB_ID
```

---

## ðŸŽ¯ All AI Features - Complete Configuration

### Required Environment Variables for Full AI Enablement

Add these to your `.env.local`, `.env.aws`, or `.env.production`:

```bash
# ============================================================
# AI PROVIDERS - Get keys from:
# ============================================================

# Google Gemini - https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your-key-here

# Anthropic Claude - https://console.anthropic.com/settings/keys
CLAUDE_API_KEY=your-key-here

# OpenAI - https://platform.openai.com/api-keys
OPENAI_API_KEY=your-key-here

# Grok (X.AI) - https://console.x.ai/
GROK_API_KEY=your-key-here

# Perplexity - https://www.perplexity.ai/settings/api
PERPLEXITY_API_KEY=your-key-here

# ============================================================
# AI FEATURE FLAGS - Enable Everything
# ============================================================

# Auto-classify documents by type (contract, email, evidence, etc.)
ENABLE_AI_AUTO_CLASSIFY=true

# Generate insights from datasets (summaries, trends, patterns)
ENABLE_AI_DATASET_INSIGHTS=true

# Natural language queries ("Show me all emails from John about delays")
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true

# Default AI model (options: gemini, claude, openai, grok)
AI_DEFAULT_MODEL=gemini

# Enable AI to access web for additional context
AI_WEB_ACCESS_ENABLED=true

# Default task complexity (options: basic, advanced, expert)
AI_TASK_COMPLEXITY_DEFAULT=advanced

# Multi-vector semantic search (4 vectors: content, participant, temporal, attachment)
MULTI_VECTOR_ENABLED=true

# ============================================================
# AWS BEDROCK CONFIGURATION
# ============================================================

# Enable AWS Bedrock for AI (uses IAM credentials, not API keys)
BEDROCK_ENABLED=true
BEDROCK_REGION=eu-west-2

# Bedrock Knowledge Base
USE_KNOWLEDGE_BASE=true
BEDROCK_KB_ID=YOUR_KNOWLEDGE_BASE_ID
BEDROCK_DS_ID=YOUR_DATA_SOURCE_ID

# Bedrock Models
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
BEDROCK_EMBEDDING_MODEL=cohere.embed-english-v3

# Embedding provider (bedrock or sentence-transformers)
EMBEDDING_PROVIDER=bedrock

# ============================================================
# AWS AI SERVICES CONFIGURATION
# ============================================================

# AWS Textract (OCR for PDFs/images)
USE_TEXTRACT=true
TEXTRACT_MAX_FILE_SIZE_MB=500
TEXTRACT_MAX_PAGE_SIZE_MB=10
TEXTRACT_MAX_PAGES=500
TEXTRACT_PAGE_THRESHOLD=100
AWS_REGION_FOR_TEXTRACT=eu-west-2

# AWS Comprehend (NLP - entity extraction, sentiment analysis)
USE_COMPREHEND=true

# AWS Macie (sensitive data scanning)
MACIE_ENABLED=true

# ============================================================
# AWS INFRASTRUCTURE
# ============================================================

# General AWS Settings
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2
AWS_DEFAULT_REGION=eu-west-2
AWS_ACCOUNT_ID=YOUR_ACCOUNT_ID

# S3 Buckets
S3_BUCKET=vericase-docs-YOUR_ACCOUNT_ID
MINIO_BUCKET=vericase-docs-YOUR_ACCOUNT_ID
S3_KNOWLEDGE_BASE_BUCKET=vericase-knowledge-base-YOUR_ACCOUNT_ID
S3_TRANSCRIBE_OUTPUT_BUCKET=vericase-transcribe-YOUR_ACCOUNT_ID

# AWS Lambda Functions
LAMBDA_TEXTRACT_PROCESSOR=vericase-textract-processor
LAMBDA_COMPREHEND_ANALYZER=vericase-comprehend-analyzer
LAMBDA_DOCUMENT_CLASSIFIER=vericase-document-classifier
LAMBDA_DATABASE_UPDATER=vericase-database-updater
LAMBDA_KB_INGESTER=vericase-kb-ingester

# AWS Step Functions
STEP_FUNCTION_ARN=arn:aws:states:REGION:ACCOUNT:stateMachine:vericase-processing

# AWS EventBridge
EVENT_BUS_NAME=vericase-events

# AWS OpenSearch Serverless
OPENSEARCH_COLLECTION_ARN=arn:aws:aoss:REGION:ACCOUNT:collection/ID
OPENSEARCH_COLLECTION_ENDPOINT=https://xxx.eu-west-2.aoss.amazonaws.com
OPENSEARCH_VECTOR_INDEX=vericase-evidence-index

# AWS QuickSight (Analytics Dashboards)
QUICKSIGHT_DASHBOARD_ID=your-dashboard-id
QUICKSIGHT_DATASET_ID=your-dataset-id
```

---

## ðŸš€ Quick Start: Enable All Features Now

### For Local Development

```bash
# 1. Copy the template
cp vericase/.env.local.example vericase/.env.local

# 2. Edit .env.local and add your API keys
code vericase/.env.local

# 3. Set these to enable all AI features:
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_WEB_ACCESS_ENABLED=true
AI_TASK_COMPLEXITY_DEFAULT=advanced
MULTI_VECTOR_ENABLED=true

# Add your keys:
GEMINI_API_KEY=your-key
CLAUDE_API_KEY=your-key
OPENAI_API_KEY=your-key

# 4. Start the application
docker-compose up -d
```

### For AWS Production

```bash
# 1. Create AWS Secrets Manager secret (see above)
aws secretsmanager create-secret ...

# 2. Copy the template
cp vericase/.env.production.example vericase/.env.production

# 3. Configure in .env.production:
AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2

# Enable all features
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
USE_TEXTRACT=true
USE_COMPREHEND=true
BEDROCK_ENABLED=true
USE_KNOWLEDGE_BASE=true
MACIE_ENABLED=true

# 4. Deploy to AWS
```

---

## ðŸ”’ Security Best Practices

### âœ… DO

- **Use AWS Secrets Manager in production**
- **Rotate API keys every 90-180 days**
- **Use IAM roles (IRSA) for AWS services**
- **Set different keys for dev/staging/prod**
- **Monitor API usage and costs**
- **Enable CloudTrail for audit logs**

### âŒ DON'T

- **Never commit API keys to Git**
- **Never share API keys in Slack/email**
- **Never use production keys in development**
- **Never log API keys (VeriCase has log sanitization)**
- **Don't use root AWS credentials**

---

## ðŸ” Troubleshooting

### "No AI providers configured"

**Solution**: Add at least one API key to environment or Secrets Manager

```bash
# Check what's loaded
docker-compose exec api python -c "from app.config import settings; print(f'Gemini: {bool(settings.GEMINI_API_KEY)}, Claude: {bool(settings.CLAUDE_API_KEY)}, OpenAI: {bool(settings.OPENAI_API_KEY)}')"
```

### "Secrets Manager access denied"

**Solution**: Check IAM role has permissions

```bash
# Test from AWS environment
aws secretsmanager describe-secret --secret-id vericase/ai-api-keys --region eu-west-2
```

### "AI features not working"

**Solution**: Check feature flags are enabled

```bash
# In .env.local or .env.production
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
```

### "Bedrock not working"

**Solution**: Bedrock uses IAM credentials, not API keys

```bash
# Bedrock requirements:
# 1. BEDROCK_ENABLED=true
# 2. BEDROCK_REGION set correctly
# 3. IAM role has Bedrock permissions
# 4. Model access enabled in Bedrock console
```

---

## ðŸ“Š Cost Optimization Tips

1. **Use Gemini as default** - Most cost-effective for general tasks
2. **Reserve Claude for complex reasoning** - More expensive but better quality
3. **Cache embeddings** - Don't re-embed same content
4. **Set token limits** - Prevent runaway costs
5. **Monitor usage** - Set up CloudWatch alarms for API costs
6. **Use Bedrock for high volume** - Often cheaper than direct API calls

---

## ðŸŽ“ Getting Your API Keys

### Google Gemini
1. Visit: https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy key to `GEMINI_API_KEY`

### Anthropic Claude
1. Visit: https://console.anthropic.com/settings/keys
2. Create API key
3. Copy to `CLAUDE_API_KEY`

### OpenAI
1. Visit: https://platform.openai.com/api-keys
2. Create new secret key
3. Copy to `OPENAI_API_KEY`

### AWS Bedrock
1. **No API key needed!**
2. Enable models in AWS Bedrock console
3. Add IAM permissions to your role
4. Set `BEDROCK_ENABLED=true`

---

## ðŸ“ Summary

**Where VeriCase loads AI keys from:**

1. **Production**: AWS Secrets Manager (`vericase/ai-api-keys`)
2. **Development**: `.env.local`, `.env.aws`, or system environment variables
3. **Fallback**: Empty (AI features disabled)

**To enable all features**: Set all environment variables listed in the "All AI Features" section above!

