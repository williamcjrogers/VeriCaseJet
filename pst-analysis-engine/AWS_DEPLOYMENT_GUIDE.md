# AWS App Runner Deployment Guide for VeriCase

This guide will help you deploy VeriCase to AWS App Runner with automatic redeployment on every git push.

## Prerequisites

1. AWS Account
2. GitHub Account
3. Your code pushed to a GitHub repository

## Step 1: Prepare Your GitHub Repository

```bash
# If you haven't already initialized git
git init
git add .
git commit -m "Initial commit for AWS deployment"

# Create a new repository on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/vericase-pst-analysis.git
git push -u origin main
```

## Step 2: Set Up AWS Services

### 2.1 Create RDS PostgreSQL Database

1. Go to AWS RDS Console
2. Click "Create database"
3. Choose:
   - PostgreSQL
   - Free tier (for development)
   - DB instance identifier: `vericase-db`
   - Master username: `postgres`
   - Master password: (save this securely)
   - Database name: `vericase`
4. In Security Group, allow inbound traffic on port 5432

### 2.2 Create S3 Bucket

1. Go to S3 Console
2. Create bucket: `vericase-production`
3. Block all public access (we'll use presigned URLs)
4. Enable versioning (recommended)

### 2.3 Create ElastiCache Redis (Optional for Development)

1. Go to ElastiCache Console
2. Create Redis cluster
3. Choose t3.micro for development
4. Note the endpoint

## Step 3: Deploy to App Runner

1. Go to AWS App Runner Console: https://console.aws.amazon.com/apprunner

2. Click "Create service"

3. **Source and deployment**:
   - Repository type: Source code repository
   - Connect to GitHub
   - Select your repository
   - Branch: main
   - Source directory: / (root)
   - ✅ Automatic deployment (deploys on every push!)

4. **Build settings**:
   - Configuration source: Use configuration file
   - The `apprunner.yaml` file will be detected

5. **Service settings**:
   - Service name: `vericase-pst-analysis`
   - Virtual CPU: 0.25 vCPU (for development)
   - Virtual memory: 0.5 GB (for development)
   - Environment variables - Add ALL of these:

   ```
   SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@YOUR_RDS_ENDPOINT:5432/vericase
   AWS_ACCESS_KEY_ID=<your-iam-access-key>
   AWS_SECRET_ACCESS_KEY=<your-iam-secret-key>
   AWS_STORAGE_BUCKET_NAME=vericase-production
   AWS_S3_REGION_NAME=us-east-1
   REDIS_URL=redis://YOUR_ELASTICACHE_ENDPOINT:6379
   
   # Email
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_HOST_USER=your-email@gmail.com
   EMAIL_HOST_PASSWORD=your-app-specific-password
   EMAIL_FROM=noreply@vericase.com
   
   # AI Keys
   OPENAI_API_KEY=<your-key>
   ANTHROPIC_API_KEY=<your-key>
   GEMINI_API_KEY=<your-key>
   GROK_API_KEY=<your-key>
   
   # Admin
   ADMIN_EMAIL=admin@vericase.com
   ADMIN_PASSWORD=<choose-strong-password>
   ```

6. **Health check**:
   - Path: `/api/health`
   - Interval: 10 seconds
   - Timeout: 5 seconds

7. Click "Create & deploy"

## Step 4: Post-Deployment Setup

1. Your app will be available at: `https://[random-id].awsapprunner.com`

2. Update your website integration:
   - In your marketing website, update the login/signup links to point to your App Runner URL
   - Example: `https://your-app-id.awsapprunner.com/login.html`

3. Initialize the database:
   ```bash
   # SSH into your instance or run via AWS Systems Manager
   cd api
   alembic upgrade head
   python init_admin.py  # Create admin user
   ```

## Step 5: Configure Auto-Deployment

Auto-deployment is already enabled! Every time you push to GitHub:

```bash
git add .
git commit -m "Your changes"
git push
```

App Runner will automatically:
1. Detect the push
2. Build your application
3. Deploy the new version
4. Keep the old version running until the new one is ready (zero downtime!)

## Monitoring & Logs

- **Logs**: App Runner Console → Your service → Logs
- **Metrics**: App Runner Console → Your service → Metrics
- **Health**: Automatic health checks on `/api/health`

## Cost Estimate (Development)

- App Runner: ~$5/month (0.25 vCPU)
- RDS PostgreSQL (t3.micro): ~$15/month
- S3: <$1/month for development
- ElastiCache Redis: ~$13/month (optional)
- **Total**: ~$20-35/month for development

## Production Scaling

When ready for production:
1. Increase App Runner CPU/Memory
2. Upgrade RDS to larger instance
3. Enable RDS Multi-AZ for high availability
4. Add CloudFront CDN for static files
5. Enable AWS WAF for security

## Troubleshooting

### Common Issues:

1. **Database Connection Error**:
   - Check RDS security group allows App Runner
   - Verify DATABASE_URL is correct

2. **S3 Access Denied**:
   - Check IAM permissions for App Runner role
   - Verify bucket name and region

3. **Build Fails**:
   - Check apprunner.yaml syntax
   - Review build logs in App Runner console

### Support Commands:

```bash
# View deployment status
aws apprunner list-services

# Check logs
aws apprunner list-operations --service-arn <your-service-arn>

# Force redeploy
git commit --allow-empty -m "Force deploy"
git push
```

## Security Checklist

- [ ] Changed all default passwords
- [ ] Enabled HTTPS (automatic with App Runner)
- [ ] Set strong SECRET_KEY
- [ ] Restricted RDS security group
- [ ] Enabled S3 bucket encryption
- [ ] Set up IAM roles with minimal permissions
- [ ] Enabled AWS CloudTrail for auditing

## Next Steps

1. Push your code to GitHub
2. Follow this guide to deploy
3. Test the deployment
4. Update your marketing website links
5. Monitor logs for any issues

Your VeriCase app will be live and auto-deploying within minutes!
