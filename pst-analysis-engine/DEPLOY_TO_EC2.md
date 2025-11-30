# Deploy VeriCase to EC2

## Quick Deploy (After Push to GitHub)

```bash
# SSH into EC2
ssh -i ~/.ssh/vericase.pem ec2-user@18.130.216.34

# Navigate to project
cd ~/vericase

# Pull latest code
git pull origin main

# Pull latest Docker images
docker-compose pull

# Restart services
docker-compose down && docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f api
```

## One-Line Deploy

```bash
ssh -i ~/.ssh/vericase.pem ec2-user@18.130.216.34 "cd ~/vericase && git pull && docker-compose pull && docker-compose down && docker-compose up -d && docker-compose ps"
```

## Automated Deploy Script

Save as `deploy.sh`:

```bash
#!/bin/bash
ssh -i ~/.ssh/vericase.pem ec2-user@18.130.216.34 << 'ENDSSH'
cd ~/vericase
echo "📥 Pulling latest code..."
git pull origin main
echo "🐳 Pulling Docker images..."
docker-compose pull
echo "🔄 Restarting services..."
docker-compose down
docker-compose up -d
echo "✅ Deployment complete!"
docker-compose ps
ENDSSH
```

Run: `chmod +x deploy.sh && ./deploy.sh`

## AWS Resources Now Live

After running `deploy-aws-ai-services.ps1`, you have:

- **S3 Buckets:** vericase-documents-526015377510, vericase-knowledge-base-526015377510
- **Lambda:** vericase-evidence-processor
- **IAM Roles:** VeriCaseBedrockKBRole, VeriCaseLambdaRole

## Activate AWS Services on EC2

```bash
# SSH into EC2
ssh -i ~/.ssh/vericase.pem ec2-user@18.130.216.34

# Update .env with AWS config
cd ~/vericase
cat >> .env << 'EOF'

# AWS Services - DEPLOYED
USE_AWS_SERVICES=true
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=526015377510
S3_BUCKET=vericase-documents-526015377510
KNOWLEDGE_BASE_BUCKET=vericase-knowledge-base-526015377510
TEXTRACT_PROCESSOR_FUNCTION=arn:aws:lambda:us-east-1:526015377510:function:vericase-evidence-processor
ENABLE_AI_AUTO_CLASSIFY=true
ENABLE_AI_DATASET_INSIGHTS=true
ENABLE_AI_NATURAL_LANGUAGE_QUERY=true
EOF

# Restart to apply changes
docker-compose restart
```

## Check Deployment

```bash
# API health
curl http://18.130.216.34:8010/health

# Check logs
docker-compose logs -f api

# Check AWS integration
docker-compose exec api python -c "
from api.app.aws_services import get_aws_services
aws = get_aws_services()
print('✅ AWS services initialized')
"
```
