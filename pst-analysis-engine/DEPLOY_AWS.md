# AWS Deployment Guide

## Quick Setup (15 minutes)

### 1. Create RDS PostgreSQL Database

**Via AWS Console:**
1. Go to [RDS Console](https://console.aws.amazon.com/rds)
2. Click **Create database**
3. Choose:
   - **PostgreSQL** (version 15+)
   - **Free tier** template (or Standard for production)
   - **DB instance identifier**: `vericase-db`
   - **Master username**: `vericase_admin`
   - **Master password**: Generate strong password (save it!)
   - **Public access**: Yes (for now, restrict later)
4. Click **Create database**
5. Wait 5 minutes for creation
6. Copy the **Endpoint** (looks like: `vericase-db.xxxxx.us-east-1.rds.amazonaws.com`)

**Your DATABASE_URL will be:**
```
postgresql://vericase_admin:YOUR_PASSWORD@vericase-db.xxxxx.us-east-1.rds.amazonaws.com:5432/postgres
```

### 2. Create S3 Bucket

```bash
aws s3 mb s3://vericase-docs-YOUR-NAME
```

### 3. Create Redis (ElastiCache)

**Quick option - Use Upstash Redis (Free tier):**
1. Go to [upstash.com](https://upstash.com)
2. Create free Redis database
3. Copy the connection URL

**Or AWS ElastiCache:**
1. Go to ElastiCache Console
2. Create Redis cluster
3. Copy endpoint

### 4. Deploy to App Runner

1. Push code to GitHub
2. Go to [App Runner Console](https://console.aws.amazon.com/apprunner)
3. Click **Create service**
4. Connect to GitHub → Select repo
5. **Build settings**: Use configuration file → `apprunner.yaml`
6. **Environment variables** (click Add):

```
DATABASE_URL=postgresql://vericase_admin:PASSWORD@your-rds-endpoint:5432/postgres
JWT_SECRET=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
REDIS_URL=redis://your-redis-endpoint:6379/0
MINIO_BUCKET=vericase-docs-YOUR-NAME
USE_AWS_SERVICES=true
AWS_REGION=us-east-1
CORS_ORIGINS=*
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
TIKA_URL=http://localhost:9998
```

7. Click **Create & deploy**

### 5. Test Deployment

Once deployed, visit: `https://[your-app-id].awsapprunner.com/health`

You should see:
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "0.3.0"
}
```

## Environment Variables Reference

### Required
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET` - 32+ character secret for auth tokens
- `REDIS_URL` - Redis connection string
- `MINIO_BUCKET` - S3 bucket name

### Optional
- `USE_AWS_SERVICES=true` - Use AWS S3 instead of MinIO
- `AWS_REGION` - AWS region (default: us-east-1)
- `CORS_ORIGINS` - Allowed origins (use * for dev)
- `GEMINI_API_KEY` - For AI features
- `CLAUDE_API_KEY` - For AI features
- `OPENAI_API_KEY` - For AI features

## Cost Estimate

- **RDS Free Tier**: $0/month (first 12 months)
- **App Runner**: ~$5-10/month (pay per use)
- **S3**: ~$1/month (first 5GB free)
- **Redis (Upstash)**: $0/month (free tier)

**Total: ~$6-11/month** (or $0 with free tiers)

## Auto-Deploy

Every `git push` to main branch will auto-deploy in ~3 minutes.

## Troubleshooting

**Database connection fails:**
- Check RDS security group allows inbound on port 5432
- Verify DATABASE_URL format is correct
- Ensure RDS has public access enabled

**App crashes on startup:**
- Check App Runner logs in console
- Verify all required environment variables are set
- Test DATABASE_URL connection locally

**Need help?**
Check App Runner logs: Console → Your service → Logs tab
