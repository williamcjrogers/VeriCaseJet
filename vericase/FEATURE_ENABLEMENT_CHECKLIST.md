# VeriCase Feature Enablement Checklist

## ✅ Quick Status Check

Use this checklist to ensure all AI and AWS features are properly enabled in your environment.

---

## 🤖 AI Features Status

### Core AI Features

- [ ] **AI Auto-Classification** - `ENABLE_AI_AUTO_CLASSIFY=true`
  - Automatically classifies documents by type (contract, email, evidence, etc.)
  - Requires: At least one AI provider key

- [ ] **AI Dataset Insights** - `ENABLE_AI_DATASET_INSIGHTS=true`
  - Generates summaries, trends, and patterns from datasets
  - Requires: At least one AI provider key

- [ ] **Natural Language Queries** - `ENABLE_AI_NATURAL_LANGUAGE_QUERY=true`
  - "Show me all emails from John about delays"
  - Requires: At least one AI provider key

- [ ] **AI Web Access** - `AI_WEB_ACCESS_ENABLED=true`
  - Allows AI to search the web for additional context
  - Optional: Enhances AI responses

- [ ] **Advanced Task Complexity** - `AI_TASK_COMPLEXITY_DEFAULT=advanced`
  - Options: basic, advanced, expert
  - Higher complexity = better results but slower/more expensive

- [ ] **Multi-Vector Semantic Search** - `MULTI_VECTOR_ENABLED=true`
  - Uses 4 vectors: content, participant, temporal, attachment
  - Significantly improves search accuracy

### AI Provider Configuration

At least ONE of these must be configured:

- [ ] **Google Gemini** - `GEMINI_API_KEY=your-key`
  - ✅ Recommended: Best balance of speed, cost, and quality
  - Get key: https://aistudio.google.com/app/apikey
  - Cost: ~$0.25 per 1M input tokens

- [ ] **Anthropic Claude** - `CLAUDE_API_KEY=your-key`
  - ✅ Best for: Complex reasoning, long documents
  - Get key: https://console.anthropic.com/settings/keys
  - Cost: ~$3 per 1M input tokens

- [ ] **OpenAI GPT** - `OPENAI_API_KEY=your-key`
  - ✅ Best for: Structured data, JSON outputs
  - Get key: https://platform.openai.com/api-keys
  - Cost: ~$5 per 1M input tokens (GPT-4)

- [ ] **AWS Bedrock** - `BEDROCK_ENABLED=true` + IAM permissions
  - ✅ Best for: High volume, enterprise deployments
  - No API key needed (uses IAM)
  - Cost: Varies by model

- [ ] **Grok** - `GROK_API_KEY=your-key` *(Future support)*
  - Get key: https://console.x.ai/
  
- [ ] **Perplexity** - `PERPLEXITY_API_KEY=your-key` *(Future support)*
  - Get key: https://www.perplexity.ai/settings/api

### AI Configuration

- [ ] **Default Model Set** - `AI_DEFAULT_MODEL=gemini`
  - Options: gemini, claude, openai, bedrock
  - Choose based on your use case

- [ ] **Embedding Provider** - `EMBEDDING_PROVIDER=bedrock`
  - Options: bedrock (recommended), sentence-transformers
  - Bedrock requires AWS setup

### AI Key Loading Method

Choose ONE method:

- [ ] **Method 1: AWS Secrets Manager** (Production - Recommended)
  - `AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys`
  - Secret created in AWS Secrets Manager
  - IAM role has GetSecretValue permission
  - All keys stored as JSON in secret

- [ ] **Method 2: Environment Variables** (Local/Dev)
  - Keys set directly in `.env.local` or `.env.aws`
  - SECURITY: Never commit files with real keys!

---

## ☁️ AWS Features Status

### Core AWS Services

- [ ] **AWS Mode Enabled** - `USE_AWS_SERVICES=true`
  - Required for all AWS features
  - Set to `false` for local development with MinIO

- [ ] **AWS Region Configured** - `AWS_REGION=eu-west-2`
  - Choose region closest to users
  - Affects latency and compliance

- [ ] **S3 Configured** - Bucket name set
  - `S3_BUCKET=vericase-docs-YOUR_ACCOUNT_ID`
  - `MINIO_BUCKET=vericase-docs-YOUR_ACCOUNT_ID` (alias)
  - Bucket must exist and have proper IAM permissions

### AWS AI Services

- [ ] **AWS Textract** - `USE_TEXTRACT=true`
  - **Purpose**: OCR for PDF and image documents
  - **Cost**: ~$1.50 per 1000 pages
  - **Limits**: 500 pages, 10MB per page
  - Set `TEXTRACT_PAGE_THRESHOLD=100` to use Tika for large PDFs

- [ ] **AWS Comprehend** - `USE_COMPREHEND=true`
  - **Purpose**: Entity extraction, sentiment analysis, NLP
  - **Cost**: ~$0.0001 per unit (100 chars)
  - **Use cases**: Extract names, dates, locations from documents

- [ ] **AWS Bedrock Knowledge Base** - `USE_KNOWLEDGE_BASE=true`
  - **Purpose**: RAG (Retrieval Augmented Generation)
  - Set `BEDROCK_KB_ID=YOUR_KB_ID`
  - Set `BEDROCK_DS_ID=YOUR_DS_ID`
  - Requires: S3 bucket for documents
  - Cost: ~$0.10 per 1M tokens + storage

- [ ] **AWS Macie** - `MACIE_ENABLED=true`
  - **Purpose**: Sensitive data scanning (PII, credentials)
  - **Cost**: ~$5 per GB scanned
  - **Use cases**: Compliance, data protection
  - Optional: High cost, only enable if needed

### AWS Infrastructure Services

- [ ] **AWS Lambda Functions** - Configure function names
  - `LAMBDA_TEXTRACT_PROCESSOR=vericase-textract-processor`
  - `LAMBDA_COMPREHEND_ANALYZER=vericase-comprehend-analyzer`
  - `LAMBDA_DOCUMENT_CLASSIFIER=vericase-document-classifier`
  - `LAMBDA_DATABASE_UPDATER=vericase-database-updater`
  - `LAMBDA_KB_INGESTER=vericase-kb-ingester`
  - Optional: Only needed if using Step Functions workflow

- [ ] **AWS Step Functions** - `STEP_FUNCTION_ARN=arn:...`
  - **Purpose**: Orchestrate document processing pipeline
  - Optional: For complex workflows

- [ ] **AWS EventBridge** - `EVENT_BUS_NAME=vericase-events`
  - **Purpose**: Event-driven architecture
  - Optional: For real-time processing

- [ ] **AWS ElastiCache Redis** - `REDIS_URL=redis://...`
  - Required: For caching and Celery task queue
  - Production: Use ElastiCache
  - Local: Use Docker Redis

- [ ] **AWS RDS PostgreSQL** - `DATABASE_URL=postgresql+psycopg2://...`
  - Required: Main application database
  - Production: Use RDS
  - Local: Use Docker PostgreSQL

- [ ] **AWS OpenSearch Serverless** - Optional
  - `OPENSEARCH_COLLECTION_ARN=arn:...`
  - `OPENSEARCH_COLLECTION_ENDPOINT=https://...`
  - `OPENSEARCH_VECTOR_INDEX=vericase-evidence-index`
  - Purpose: Vector search, logging, analytics

- [ ] **AWS QuickSight** - Optional
  - `QUICKSIGHT_DASHBOARD_ID=your-dashboard-id`
  - `QUICKSIGHT_DATASET_ID=your-dataset-id`
  - Purpose: Business intelligence dashboards

### AWS Authentication

Choose ONE method:

- [ ] **IAM Roles (Production - Recommended)**
  - No `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` needed
  - Uses IRSA (IAM Roles for Service Accounts)
  - Automatically rotates credentials
  - Most secure option

- [ ] **IAM User Credentials (Development/Testing)**
  - `AWS_ACCESS_KEY_ID=<your-test-access-key-id>`
  - `AWS_SECRET_ACCESS_KEY=<your-test-secret-access-key>`
  - SECURITY: Create limited IAM user for testing
  - SECURITY: Never commit credentials to Git

### AWS S3 Buckets Configuration

- [ ] **Main Documents Bucket** - `S3_BUCKET=vericase-docs-ACCOUNT_ID`
  - Stores: Uploaded documents, evidence, PST files
  - Required: Always

- [ ] **Knowledge Base Bucket** - `S3_KNOWLEDGE_BASE_BUCKET=vericase-knowledge-base-ACCOUNT_ID`
  - Stores: Bedrock Knowledge Base source documents
  - Required: Only if using Bedrock KB

- [ ] **Transcribe Output Bucket** - `S3_TRANSCRIBE_OUTPUT_BUCKET=vericase-transcribe-ACCOUNT_ID`
  - Stores: AWS Transcribe output files
  - Optional: Only if using Transcribe

---

## 🔧 Additional Services

### Email Threading

- [ ] **SigParser Integration** - `SIGPARSER_ENABLED=true`
  - Purpose: Advanced email conversation threading
  - `SIGPARSER_API_KEY=your-key`
  - `SIGPARSER_BASE_URL=https://ipaas.sigparser.com`
  - Optional: Improves email thread detection

### Apache Tika

- [ ] **Tika Service** - `TIKA_URL=http://tika:9998`
  - Purpose: Document text extraction (fallback for Textract)
  - Local: Use Docker tika container
  - Production: Can skip if using Textract exclusively

### PST Processing

- [ ] **PST Pre-count** - `PST_PRECOUNT_MESSAGES=true`
  - Purpose: Shows progress % during PST ingestion
  - Set to `false` for very large PST files (>10GB)

---

## 📋 Environment-Specific Checklists

### Local Development Setup

```bash
# 1. Copy template
cp vericase/.env.local.example vericase/.env.local

# 2. Edit .env.local and set these:
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_WEB_ACCESS_ENABLED=true
AI_TASK_COMPLEXITY_DEFAULT=advanced
MULTI_VECTOR_ENABLED=true

# 3. Add at least one AI provider key:
GEMINI_API_KEY=your-actual-key
# OR
CLAUDE_API_KEY=your-actual-key
# OR
OPENAI_API_KEY=your-actual-key

# 4. Keep AWS features disabled for local:
USE_AWS_SERVICES=false
USE_TEXTRACT=false
USE_COMPREHEND=false
BEDROCK_ENABLED=false

# 5. Start services
docker-compose up -d
```

**Checklist:**
- [x] Template copied to `.env.local`
- [ ] All AI feature flags set to `true`
- [ ] At least one AI provider key added
- [ ] AWS features disabled (using local MinIO, PostgreSQL, Redis)
- [ ] Docker Compose services started
- [ ] Application accessible at http://localhost:8010

### AWS Testing Setup

```bash
# 1. Copy template
cp vericase/.env.aws.example vericase/.env.aws

# 2. Edit .env.aws and set these:
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2
AWS_ACCOUNT_ID=your-account-id

# 3. Add AWS credentials for testing:
AWS_ACCESS_KEY_ID=your-test-iam-user-key
AWS_SECRET_ACCESS_KEY=your-test-iam-user-secret
#    (use a limited-scope IAM user; rotate after testing; never reuse production credentials)

# 4. Configure S3 buckets:
S3_BUCKET=vericase-docs-your-account-id
MINIO_BUCKET=vericase-docs-your-account-id
S3_KNOWLEDGE_BASE_BUCKET=vericase-knowledge-base-your-account-id

# 5. Enable AWS AI services:
USE_TEXTRACT=true
USE_COMPREHEND=true
BEDROCK_ENABLED=true
USE_KNOWLEDGE_BASE=true

# 6. Enable all AI features:
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_WEB_ACCESS_ENABLED=true
MULTI_VECTOR_ENABLED=true

# 7. Add AI provider keys:
GEMINI_API_KEY=your-key
# (or use AWS Secrets Manager)
```

**Checklist:**
- [ ] Template copied to `.env.aws`
- [ ] AWS account ID added
- [ ] AWS credentials configured (IAM user for testing)
- [ ] S3 buckets exist and IAM user has access
- [ ] Bedrock models enabled in AWS console
- [ ] All AI feature flags enabled
- [ ] AI provider keys added
- [ ] Test file upload to S3
- [ ] Test Textract on a PDF

### Production Setup

```bash
# 1. Create AWS Secrets Manager secret
aws secretsmanager create-secret \
  --name vericase/ai-api-keys \
  --region eu-west-2 \
  --secret-string '{
    "GEMINI_API_KEY": "your-gemini-key",
    "CLAUDE_API_KEY": "your-claude-key",
    "OPENAI_API_KEY": "your-openai-key",
    "BEDROCK_ENABLED": "true",
    "BEDROCK_REGION": "eu-west-2"
  }'

# 2. Copy template
cp vericase/.env.production.example vericase/.env.production

# 3. Configure in .env.production:
ENVIRONMENT=production
USE_AWS_SERVICES=true
AWS_REGION=eu-west-2
AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys

# 4. Enable ALL features:
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_WEB_ACCESS_ENABLED=true
AI_TASK_COMPLEXITY_DEFAULT=advanced
MULTI_VECTOR_ENABLED=true
USE_TEXTRACT=true
USE_COMPREHEND=true
BEDROCK_ENABLED=true
USE_KNOWLEDGE_BASE=true
EMBEDDING_PROVIDER=bedrock

# 5. Do NOT set AWS_ACCESS_KEY_ID - use IAM roles!
```

**Checklist:**
- [ ] AWS Secrets Manager secret created with all AI keys
- [ ] IAM role has Secrets Manager GetSecretValue permission
- [ ] IAM role has S3, Bedrock, Textract, Comprehend permissions
- [ ] RDS database created and accessible
- [ ] ElastiCache Redis created and accessible
- [ ] S3 buckets created
- [ ] All AI feature flags enabled
- [ ] Secrets Manager integration configured
- [ ] Application logs show successful key loading
- [ ] Test all AI features in production
- [ ] Monitor costs in AWS Cost Explorer

---

## 🔍 Verification Commands

### Check AI Keys Loaded

```bash
# In container
docker-compose exec api python -c "
from app.config import settings
print(f'Gemini: {bool(settings.GEMINI_API_KEY)}')
print(f'Claude: {bool(settings.CLAUDE_API_KEY)}')
print(f'OpenAI: {bool(settings.OPENAI_API_KEY)}')
print(f'Bedrock: {settings.BEDROCK_ENABLED}')
"
```

### Check Feature Flags

```bash
# In container
docker-compose exec api python -c "
from app.config import settings
print(f'Auto Classify: {settings.ENABLE_AI_AUTO_CLASSIFY}')
print(f'Dataset Insights: {settings.ENABLE_AI_DATASET_INSIGHTS}')
print(f'NL Query: {settings.ENABLE_AI_NATURAL_LANGUAGE_QUERY}')
print(f'Multi-Vector: {settings.MULTI_VECTOR_ENABLED}')
print(f'Web Access: {settings.AI_WEB_ACCESS_ENABLED}')
"
```

### Check AWS Services

```bash
# Test S3 access
aws s3 ls s3://vericase-docs-YOUR_ACCOUNT_ID/ --profile your-profile

# Test Secrets Manager metadata (avoid printing secret values)
aws secretsmanager describe-secret \
  --secret-id vericase/ai-api-keys \
  --region eu-west-2
# For the secret value, inspect in AWS console or use a scoped session; avoid get-secret-value in shared terminals.

# Check Bedrock models
aws bedrock list-foundation-models --region eu-west-2
```

### Check Application Logs

```bash
# Look for these in startup logs:
# [config_production] ✓ Loaded GEMINI_API_KEY from Secrets Manager
# [config_production] ✓ Loaded CLAUDE_API_KEY from Secrets Manager
# [config_production] ✓ Loaded OPENAI_API_KEY from Secrets Manager
# Successfully loaded 3 AI API keys from Secrets Manager

docker-compose logs api | grep -i "config_production\|secret"
```

---

## 📊 Feature Status Summary

Create your status summary:

**AI Providers:**
- [ ] Gemini: ❌ Not configured / ✅ Configured
- [ ] Claude: ❌ Not configured / ✅ Configured
- [ ] OpenAI: ❌ Not configured / ✅ Configured
- [ ] Bedrock: ❌ Not configured / ✅ Configured

**AI Features:**
- [ ] Auto-Classification: ❌ Disabled / ✅ Enabled
- [ ] Dataset Insights: ❌ Disabled / ✅ Enabled
- [ ] Natural Language Query: ❌ Disabled / ✅ Enabled
- [ ] Multi-Vector Search: ❌ Disabled / ✅ Enabled
- [ ] Web Access: ❌ Disabled / ✅ Enabled

**AWS Services:**
- [ ] S3: ❌ Not configured / ✅ Configured
- [ ] Textract: ❌ Disabled / ✅ Enabled
- [ ] Comprehend: ❌ Disabled / ✅ Enabled
- [ ] Bedrock KB: ❌ Not configured / ✅ Configured
- [ ] Macie: ❌ Disabled / ✅ Enabled

---

## 🎯 Quick Reference: Fully Enabled Configuration

For a **complete, all-features-enabled** setup, here's what you need:

```bash
# AI Feature Flags (ALL TRUE)
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
AI_WEB_ACCESS_ENABLED=true
AI_TASK_COMPLEXITY_DEFAULT=advanced
MULTI_VECTOR_ENABLED=true

# AI Providers (AT LEAST ONE)
GEMINI_API_KEY=your-key
CLAUDE_API_KEY=your-key
OPENAI_API_KEY=your-key

# AWS Services (ALL TRUE)
USE_AWS_SERVICES=true
USE_TEXTRACT=true
USE_COMPREHEND=true
BEDROCK_ENABLED=true
USE_KNOWLEDGE_BASE=true
MACIE_ENABLED=true  # Optional: High cost

# AWS Configuration
AWS_REGION=eu-west-2
EMBEDDING_PROVIDER=bedrock
```

**That's it!** With these settings, all AI and AWS features are fully enabled.

---

## 📚 Additional Resources

- **AI Key Management**: See `AI_KEY_MANAGEMENT.md`
- **Environment Files**: See `ENV_FILE_GUIDE.md`
- **AWS Setup**: See `docs/VERICASE_AWS_INTEGRATION.md`
- **Deployment**: See `DEPLOYMENT_GUIDE.md`
