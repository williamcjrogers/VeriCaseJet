# VeriCase Environment Configuration Guide

## Overview

This guide explains the consolidated environment file structure for VeriCase. We've consolidated 7+ environment files into 3 clear templates for different deployment scenarios.

## 🔐 Security First

**IMPORTANT:** Never commit files containing real credentials to version control!

- ✅ **Safe to commit:** `*.example` files (templates with placeholders)
- ❌ **Never commit:** `.env`, `.env.local`, `.env.aws`, `.env.production`

## Environment File Structure

### 1. Local Development: `.env.local`

**Template:** `.env.local.example`  
**Use case:** Local development with Docker Compose  
**Services:** PostgreSQL, MinIO, OpenSearch, Redis (all in Docker)

```bash
# Setup
cp .env.local.example .env.local
# Edit .env.local with your local settings (usually defaults work)
docker-compose up -d
```

**Key Features:**
- `USE_AWS_SERVICES=false` - Uses MinIO instead of S3
- All services run locally in Docker
- Safe default credentials for local development
- No real API keys needed for basic functionality

### 2. AWS Development/Testing: `.env.aws`

**Template:** `.env.aws.example`  
**Use case:** Testing AWS integrations (S3, Bedrock, Textract, etc.)  
**Services:** Mix of local and AWS services

```bash
# Setup
cp .env.aws.example .env.aws
# Edit .env.aws with your AWS credentials and resource IDs
# Fill in: AWS_ACCOUNT_ID, bucket names, AWS credentials
```

**Key Features:**
- `USE_AWS_SERVICES=true` - Uses real AWS S3
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` for local testing
- Bedrock, Textract, and other AWS AI services enabled
- Can mix local database with AWS storage

**Security Note:** Use IAM users with limited permissions for testing. Never share these credentials.

### 3. Production: `.env.production`

**Template:** `.env.production.example`  
**Use case:** Production deployment (App Runner, ECS, EKS, EC2)  
**Services:** All AWS managed services

```bash
# Setup (do this in secure environment only)
cp .env.production.example .env.production
# Fill in ALL production values
# Use AWS Secrets Manager for sensitive values
```

**Key Features:**
- `USE_AWS_SERVICES=true`
- No `AWS_ACCESS_KEY_ID` - uses IAM roles/IRSA
- RDS PostgreSQL for database
- ElastiCache Redis
- S3 for storage
- Optional: OpenSearch, Lambda, EventBridge
- AWS Secrets Manager integration

**Production Checklist:**
- [ ] Use IAM roles (IRSA/instance profile) instead of access keys
- [ ] Rotate all JWT secrets (generate new 64-char random strings)
- [ ] Use AWS Secrets Manager for API keys
- [ ] Configure proper CORS origins (no wildcards)
- [ ] Set secure admin password (hashed)
- [ ] Enable SSL/TLS for database and Redis
- [ ] Review all feature flags
- [ ] Set up monitoring and logging

## Quick Start Commands

### Local Development
```bash
# First time setup
cp .env.local.example .env.local
docker-compose up -d
docker-compose exec api python create_admin.py

# Daily development
docker-compose up -d
# Access UI at http://localhost:8010
```

### AWS Testing
```bash
cp .env.aws.example .env.aws
# Edit .env.aws with your AWS details
docker-compose -f docker-compose.yml -f docker-compose.aws.yml up -d
```

### Production Deployment
```bash
# Never do this on your local machine!
# Set environment variables in AWS service (App Runner, ECS, etc.)
# Or use .env.production in secure deployment environment
```

## Environment Variable Priority

VeriCase loads environment variables in this order (later overrides earlier):

1. System environment variables
2. `.env` file (if present)
3. `.env.local` / `.env.aws` / `.env.production` (based on context)
4. AWS Secrets Manager (in production)

## Migration from Old Files

If you have existing environment files, here's how to migrate:

| Old File | New File | Action |
|----------|----------|--------|
| `.env` | `.env.local` | Review and migrate custom settings |
| `.env.example` | `.env.local.example` | Use new template |
| `.env.aws` | `.env.aws` | Review for security issues |
| `.env.aws-deployed` | `.env.production` | Migrate to new template |
| `.env.bedrock-simple` | `.env.aws` | Merge Bedrock settings |
| `.env.production` | `.env.production` | Review for security issues |
| `.env.production.template` | `.env.production.example` | Use new template |

## Key Environment Variables

### Critical (Always Required)
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET` - Minimum 32 characters, use 64+ in production
- `USE_AWS_SERVICES` - true/false flag for S3 vs MinIO

### Storage
- `S3_BUCKET` / `MINIO_BUCKET` - Primary document storage bucket
- `KNOWLEDGE_BASE_BUCKET` - Bedrock knowledge base bucket (AWS only)

### AI Features
- `GEMINI_API_KEY` - Google Gemini API
- `CLAUDE_API_KEY` - Anthropic Claude API
- `OPENAI_API_KEY` - OpenAI API
- `ENABLE_AI_AUTO_CLASSIFY` - Enable AI classification
- `ENABLE_AI_DATASET_INSIGHTS` - Enable AI insights

### AWS Services (when USE_AWS_SERVICES=true)
- `AWS_REGION` - Primary AWS region
- `BEDROCK_KB_ID` - Bedrock Knowledge Base ID
- `USE_TEXTRACT` - Enable AWS Textract for OCR
- `USE_COMPREHEND` - Enable AWS Comprehend for NLP

## Troubleshooting

### "Missing DATABASE_URL"
- Ensure `.env.local` (or appropriate file) exists
- Check DATABASE_URL is set and formatted correctly

### "S3 Access Denied"
- For local: Check MinIO is running: `docker-compose ps`
- For AWS: Verify IAM role has S3 permissions

### "Invalid JWT Secret"
- JWT_SECRET must be at least 32 characters
- Generate secure secret: `openssl rand -base64 48`

### "CORS Errors"
- Check `CORS_ORIGINS` includes your frontend URL
- Use comma-separated list: `http://localhost:3000,http://localhost:8010`

## Security Best Practices

1. **Never commit real credentials**
   - Use `.example` files as templates
   - Keep actual `.env.*` files in `.gitignore`

2. **Rotate secrets regularly**
   - JWT secrets every 90 days
   - API keys every 180 days
   - Database passwords annually

3. **Use AWS Secrets Manager in production**
   ```python
   # The app automatically loads from Secrets Manager when:
   AWS_SECRETS_MANAGER_AI_KEYS=vericase/ai-api-keys
   ```

4. **Limit AWS permissions**
   - Use least-privilege IAM policies
   - Separate dev/staging/prod accounts
   - Enable CloudTrail logging

5. **Audit environment files**
   ```bash
   # Check for accidentally committed secrets
   git log --all --full-history -- "*.env"
   
   # If found, use git-filter-repo to remove
   ```

## Getting Help

- Review logs: `docker-compose logs api`
- Check configuration: `docker-compose config`
- Validate environment: `docker-compose exec api env | grep -E '(DATABASE|AWS|S3|JWT)'`

## Migration Checklist

- [x] Create new template files
  - [x] `.env.local.example`
  - [x] `.env.aws.example`
  - [x] `.env.production.example`
- [ ] Copy appropriate template to working file
- [ ] Fill in required values (marked with YOUR_* or REPLACE_*)
- [ ] Test local setup: `docker-compose up -d`
- [ ] Verify database connection
- [ ] Test file upload (S3/MinIO)
- [ ] Archive old environment files
- [ ] Update team documentation
- [ ] Remove hardcoded credentials from old files

## Support

For issues or questions:
1. Check this guide first
2. Review application logs
3. Consult team documentation
4. Raise issue in project tracker
