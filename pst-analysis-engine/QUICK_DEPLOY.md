# Quick Deploy to AWS - 3 Steps

## Step 1: Create Redis (15 min)

```bash
# Go to: https://console.aws.amazon.com/elasticache/
# Click "Create" → "Redis cluster"
# Settings:
#   - Name: vericase-redis
#   - Node type: cache.t3.micro
#   - Region: eu-west-2
#   - VPC: Same as your EC2
#   - Security group: Allow port 6379 from EC2
# 
# Copy the Primary Endpoint (e.g., vericase-redis.abc123.euw2.cache.amazonaws.com:6379)
```

## Step 2: Update .env.production (5 min)

Replace these 3 values:

```bash
# 1. Redis endpoint (from Step 1)
REDIS_URL=redis://vericase-redis.abc123.euw2.cache.amazonaws.com:6379/0

# 2. Your EC2 public IP
CORS_ORIGINS=http://YOUR_EC2_PUBLIC_IP:8000,http://localhost:3000

# 3. Secure admin password
ADMIN_PASSWORD=YourSecurePassword123!
```

**Optional (can skip for now):**
- Email settings (for notifications)
- OpenSearch (already commented out)
- Tika (already commented out)

## Step 3: Deploy (5 min)

```bash
# SSH to EC2
ssh -i your-key.pem ec2-user@YOUR_EC2_IP

# Run deploy script
cd /home/ec2-user
./aws-deploy.sh

# Verify
docker ps
docker logs api --tail 50
```

## Test It

```bash
# Open in browser
http://YOUR_EC2_IP:8000/ui/login.html

# Login with:
# Email: admin@vericase.com
# Password: [what you set in ADMIN_PASSWORD]
```

## 🚨 After Deploy: Rotate API Keys

Your AI API keys are exposed in the repo. Rotate them:

1. **Gemini**: https://aistudio.google.com/app/apikey
2. **Claude**: https://console.anthropic.com/settings/keys
3. **OpenAI**: https://platform.openai.com/api-keys
4. **Grok**: https://console.x.ai/
5. **Perplexity**: https://www.perplexity.ai/settings/api

Update `.env.production` with new keys and redeploy.

## Troubleshooting

**Redis connection failed:**
```bash
# Check security group allows port 6379 from EC2
# Verify REDIS_URL format: redis://endpoint:6379/0
docker logs api | grep -i redis
```

**Can't access UI:**
```bash
# Check CORS_ORIGINS has your EC2 IP
# Verify port 8000 is open in EC2 security group
curl http://localhost:8000/health
```

**Database connection failed:**
```bash
# Check RDS security group allows port 5432 from EC2
docker logs api | grep -i database
```

## Cost

- RDS: ~$15/month
- S3: ~$1-5/month
- Redis: ~$13/month
- EC2: ~$15/month
- **Total: ~$44-48/month**
