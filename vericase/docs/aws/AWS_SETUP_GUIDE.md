# AWS Services Setup Guide for VeriCase

## 🚨 IMMEDIATE ACTION REQUIRED

### 1. Rotate API Keys (Do This First!)
Your API keys are exposed in the repository. Rotate them immediately:

- **Claude API**: https://console.anthropic.com/settings/keys
- **OpenAI API**: https://platform.openai.com/api-keys
- **Gemini API**: https://aistudio.google.com/app/apikey
- **Grok API**: https://console.x.ai/
- **Perplexity API**: https://www.perplexity.ai/settings/api

After rotating, update `.env.production` with new keys.

---

## Required AWS Services

### ✅ Already Configured
- **RDS PostgreSQL**: `database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com`
- **S3 Bucket**: `vericase-data`

### ❌ Need to Create

#### 1. AWS ElastiCache (Redis) - REQUIRED
**Purpose**: Session management, caching, Celery task queue

**Steps**:
1. Go to: https://console.aws.amazon.com/elasticache/
2. Click "Create" → "Redis cluster"
3. Settings:
   - **Cluster mode**: Disabled
   - **Name**: `vericase-redis`
   - **Node type**: `cache.t3.micro` (dev) or `cache.t3.small` (prod)
   - **Number of replicas**: 0 (dev) or 1+ (prod)
   - **Subnet group**: Same VPC as your EC2/RDS
   - **Security group**: Allow port 6379 from your EC2 security group
4. Click "Create"
5. Wait 5-10 minutes for creation
6. Copy the **Primary Endpoint** (e.g., `vericase-redis.xxxxx.euw2.cache.amazonaws.com:6379`)
7. Update `.env.production`:
   ```
   REDIS_URL=redis://vericase-redis.xxxxx.euw2.cache.amazonaws.com:6379/0
   ```

**Cost**: ~$13/month (t3.micro) or ~$26/month (t3.small)

---

#### 2. AWS OpenSearch - OPTIONAL (Can skip initially)
**Purpose**: Full-text search for emails and documents

**Option A: Create OpenSearch Domain**
1. Go to: https://console.aws.amazon.com/aos/
2. Click "Create domain"
3. Settings:
   - **Deployment type**: Development and testing
   - **Version**: Latest (7.10+)
   - **Instance type**: `t3.small.search`
   - **Number of nodes**: 1
   - **EBS storage**: 10 GB
   - **Network**: VPC access (same VPC as EC2)
   - **Access policy**: Allow from EC2 security group
4. Click "Create"
5. Wait 15-20 minutes for creation
6. Copy the **Domain endpoint** (e.g., `https://vericase-search.eu-west-2.es.amazonaws.com`)
7. Update `.env.production`:
   ```
   OPENSEARCH_HOST=https://vericase-search.eu-west-2.es.amazonaws.com
   ```

**Cost**: ~$50/month (t3.small.search)

**Option B: Skip for now (Use PostgreSQL full-text search)**
```bash
# Comment out in .env.production
# OPENSEARCH_HOST=
# OPENSEARCH_PORT=443
```

---

#### 3. Apache Tika Server - OPTIONAL (Can skip initially)
**Purpose**: Document text extraction (PDF, Word, Excel)

**Option A: Deploy to ECS Fargate**
1. Go to: https://console.aws.amazon.com/ecs/
2. Create ECS Cluster (if not exists)
3. Create Task Definition:
   - **Image**: `apache/tika:latest-full`
   - **Port**: 9998
   - **Memory**: 2GB
   - **CPU**: 1 vCPU
4. Create Service with Application Load Balancer
5. Copy ALB endpoint
6. Update `.env.production`:
   ```
   TIKA_URL=http://your-alb-endpoint:9998
   ```

**Cost**: ~$30/month (Fargate + ALB)

**Option B: Skip for now (Use AWS Textract API instead)**
```bash
# Comment out in .env.production
# TIKA_URL=
```

---

## Update .env.production Checklist

```bash
# 1. Set Redis (REQUIRED)
REDIS_URL=redis://your-elasticache-endpoint:6379/0

# 2. Set OpenSearch (OPTIONAL - can leave commented)
# OPENSEARCH_HOST=https://your-opensearch-endpoint

# 3. Set Tika (OPTIONAL - can leave commented)
# TIKA_URL=http://your-tika-endpoint:9998

# 4. Set secure admin password
ADMIN_PASSWORD=YourSecurePassword123!

# 5. Set your actual domain
CORS_ORIGINS=https://your-actual-domain.com

# 6. Set email credentials (for notifications)
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# 7. ROTATE ALL API KEYS (see above)
GEMINI_API_KEY=NEW_KEY_HERE
CLAUDE_API_KEY=NEW_KEY_HERE
OPENAI_API_KEY=NEW_KEY_HERE
GROK_API_KEY=NEW_KEY_HERE
PERPLEXITY_API_KEY=NEW_KEY_HERE
```

---

## Minimal Setup (Start Here)

To get started quickly, you only need:

1. **ElastiCache Redis** (REQUIRED)
2. **Secure passwords and domain** (REQUIRED)
3. **Rotated API keys** (REQUIRED)

You can skip OpenSearch and Tika initially and add them later.

---

## Cost Estimate

### Minimal Setup
- RDS PostgreSQL (db.t3.micro): ~$15/month
- S3 Storage: ~$1-5/month
- ElastiCache Redis (t3.micro): ~$13/month
- EC2 (t3.small): ~$15/month
- **Total**: ~$44-48/month

### Full Setup
- Add OpenSearch (t3.small): +$50/month
- Add Tika ECS: +$30/month
- **Total**: ~$124-128/month

---

## Next Steps

1. ✅ Rotate API keys immediately
2. ✅ Create ElastiCache Redis
3. ✅ Update `.env.production` with Redis endpoint
4. ✅ Set secure ADMIN_PASSWORD
5. ✅ Set CORS_ORIGINS to your domain
6. ✅ Deploy to EC2 using `./aws-deploy.sh`
7. ⏸️ Add OpenSearch later (optional)
8. ⏸️ Add Tika later (optional)
