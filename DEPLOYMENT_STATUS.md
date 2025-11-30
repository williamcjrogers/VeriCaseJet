# VeriCase Deployment Status

## ✅ Production Instance

**URL:** http://18.130.216.34:8010

**Instance ID:** i-0ade6dff1811bdbcb  
**IP Address:** 18.130.216.34  
**Security Group:** sg-07499f7ed552da94d  
**Port 8010:** ✅ Open

### Login Credentials
- **Email:** admin@vericase.com
- **Password:** admin123

## AWS Services Deployed

### S3 Buckets
- **Documents:** vericase-documents-526015377510
- **Knowledge Base:** vericase-knowledge-base-526015377510

### Lambda Functions
- **Evidence Processor:** vericase-evidence-processor

### IAM Roles
- **Bedrock KB Role:** VeriCaseBedrockKBRole
- **Lambda Role:** VeriCaseLambdaRole

### ElastiCache Redis
- **Cluster:** vericase-redis
- **Nodes:** 9 (3 shards, Multi-AZ)
- **Encryption:** Enabled

## Other EC2 Instances

### Instance 1 (Old)
- **Instance ID:** i-0913d878182fa803c
- **IP:** 35.179.167.235
- **Status:** Running (backup)
- **SSM Agent:** ✅ Installed

### Instance 2 (Old)
- **Instance ID:** i-0f664f8c4daefa7e6
- **IP:** 13.40.213.46
- **Status:** Running (backup)

## Monthly Costs
- **AWS Services:** ~£20/month (S3, Lambda, Textract, Comprehend)
- **Redis:** ~£150/month
- **EC2:** Variable based on instance type

## Deployment Scripts
- **Restart Services:** `ops/restart-ec2-services.ps1`
- **AWS Deployment:** `deploy-aws-ai-services.ps1`
- **Bedrock Setup:** `setup-bedrock-simple.ps1`

---
**Last Updated:** November 30, 2025
