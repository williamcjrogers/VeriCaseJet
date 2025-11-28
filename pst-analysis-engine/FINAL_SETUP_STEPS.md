# Final Setup Steps - You're Almost Done!

## ✅ What You Already Have

- ✅ RDS PostgreSQL: `database-1.cv8uwu0uqr7f.eu-west-2.rds.amazonaws.com`
- ✅ S3 Bucket: `vericase-data`
- ✅ Redis Cluster: `vericase-redis.dbbgbx.euw2.cache.amazonaws.com` (9 nodes!)
- ✅ VPC: `vpc-0880b8ccf488f327e`

## ❌ What You Still Need to Set

### 1. Set Admin Password (REQUIRED)

Edit `.env.production`:
```bash
ADMIN_PASSWORD=YourSecurePassword123!
```

### 2. Set CORS Origins (REQUIRED)

Get your EC2 public IP:
```bash
curl -s http://checkip.amazonaws.com
```

Then update `.env.production`:
```bash
CORS_ORIGINS=http://YOUR_EC2_IP:8000,http://localhost:3000
```

### 3. Rotate API Keys (REQUIRED - Security!)

Your API keys are exposed in the repo. Get new ones:

1. **Gemini**: https://aistudio.google.com/app/apikey
2. **Claude**: https://console.anthropic.com/settings/keys
3. **OpenAI**: https://platform.openai.com/api-keys
4. **Grok**: https://console.x.ai/
5. **Perplexity**: https://www.perplexity.ai/settings/api

Update `.env.production`:
```bash
GEMINI_API_KEY=your-new-key
CLAUDE_API_KEY=your-new-key
OPENAI_API_KEY=your-new-key
GROK_API_KEY=your-new-key
PERPLEXITY_API_KEY=your-new-key
```

## Optional Services (Can Skip)

### OpenSearch (~$50/month)
Already commented out. Your app will use PostgreSQL full-text search instead.

To enable later:
```bash
./create-opensearch-in-vpc.sh
```

### Tika (~$30/month)
Already commented out. Your app will work without it for PST processing.

To enable later:
```bash
./create-tika-in-vpc.sh
```

### Email Notifications
Already commented out. You can add later if needed.

## Deploy to EC2

Once you've updated the 3 required values above:

```bash
# SSH to your EC2
ssh -i your-key.pem ec2-user@YOUR_EC2_IP

# Deploy
cd /home/ec2-user
./aws-deploy.sh
```

## Verify Deployment

```bash
# Check containers are running
docker ps

# Check API logs
docker logs api --tail 50

# Check Redis connection
docker exec api python -c "import redis; r=redis.from_url('redis://vericase-redis.dbbgbx.euw2.cache.amazonaws.com:6379/0'); print('Redis OK:', r.ping())"

# Test API
curl http://localhost:8000/health
```

## Access Your App

Open in browser:
```
http://YOUR_EC2_IP:8000/ui/login.html
```

Login with:
- Email: `admin@vericase.com`
- Password: `[what you set in ADMIN_PASSWORD]`

## Current Monthly Cost

- RDS PostgreSQL (db.t3.micro): ~$15
- S3 Storage: ~$1-5
- Redis Cluster (r7g.xlarge x9): ~$1,350 🚨
- EC2 (t3.small): ~$15
- **Total: ~$1,386/month**

### 🚨 WARNING: Your Redis is EXPENSIVE!

You have a **production-grade Redis cluster** with:
- 3 shards
- 9 nodes (r7g.xlarge)
- Multi-AZ replication
- Cost: ~$1,350/month

**For development, you should use:**
- 1 node (cache.t3.micro)
- Cost: ~$13/month

**To switch to cheaper Redis:**
1. Delete current cluster in AWS Console
2. Run: `./create-redis-in-vpc.sh` (creates t3.micro)
3. Update `.env.production` with new endpoint

## Summary

**Required now:**
1. Set `ADMIN_PASSWORD`
2. Set `CORS_ORIGINS` with your EC2 IP
3. Rotate all 5 API keys

**Optional later:**
- OpenSearch (if search gets slow)
- Tika (if processing many PDFs)
- Email notifications
- Downgrade Redis to save $1,337/month!
