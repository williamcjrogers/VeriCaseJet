# VeriCase AWS Deployment Checklist

## Before Deployment

### 1. Create AWS ElastiCache Redis (REQUIRED)
```bash
# Go to: https://console.aws.amazon.com/elasticache/
# Create Redis cluster:
# - Name: vericase-redis
# - Node type: cache.t3.micro
# - Region: eu-west-2
# - VPC: Same as your EC2
# - Security group: Allow port 6379 from EC2

# Copy the Primary Endpoint, example:
# vericase-redis.abc123.euw2.cache.amazonaws.com:6379
```

### 2. Update .env.production

Replace these values:

```bash
# 1. Redis endpoint (from step 1)
REDIS_URL=redis://vericase-redis.abc123.euw2.cache.amazonaws.com:6379/0

# 2. Your actual domain
CORS_ORIGINS=https://your-domain.com

# 3. Secure admin password
ADMIN_PASSWORD=YourSecurePassword123!

# 4. Your email for notifications
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-gmail-app-password

# 5. NEW API keys (rotate the exposed ones!)
GEMINI_API_KEY=your-new-key
CLAUDE_API_KEY=your-new-key
OPENAI_API_KEY=your-new-key
GROK_API_KEY=your-new-key
PERPLEXITY_API_KEY=your-new-key
```

### 3. Optional Services (Can Skip Initially)

**OpenSearch** - Uncomment if you create it:
```bash
OPENSEARCH_HOST=https://your-opensearch.eu-west-2.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_INDEX=emails
```

**Tika** - Uncomment if you deploy it:
```bash
TIKA_URL=http://your-tika-alb:9998
```

## Deploy to EC2

```bash
# 1. SSH to your EC2 instance
ssh -i your-key.pem ec2-user@your-ec2-ip

# 2. Run deployment script
cd /home/ec2-user
./aws-deploy.sh

# 3. Verify deployment
docker ps
docker logs api
docker logs worker
```

## Verify Deployment

```bash
# Check API health
curl http://localhost:8000/health

# Check logs
docker logs api --tail 50
docker logs worker --tail 50

# Check Redis connection
docker exec api python -c "import redis; r=redis.from_url('$REDIS_URL'); print(r.ping())"
```

## Post-Deployment

1. ✅ Test login at: http://your-ec2-ip:8000/ui/login.html
2. ✅ Upload a test PST file
3. ✅ Verify email extraction works
4. ✅ Check AI features work
5. ✅ Monitor logs for errors

## Troubleshooting

**Redis connection failed:**
```bash
# Check security group allows port 6379
# Verify REDIS_URL format: redis://endpoint:6379/0
```

**Database connection failed:**
```bash
# Check RDS security group allows port 5432
# Verify DATABASE_URL credentials
```

**API won't start:**
```bash
# Check logs
docker logs api

# Verify .env file
docker exec api cat .env | grep REDIS_URL
```

## Cost Summary

- RDS PostgreSQL: ~$15/month
- S3 Storage: ~$1-5/month
- ElastiCache Redis: ~$13/month
- EC2 t3.small: ~$15/month
- **Total: ~$44-48/month**

Optional:
- OpenSearch: +$50/month
- Tika ECS: +$30/month
