# VeriCase Deployment Status

## ✅ Production EKS Cluster

**URL:** http://a61989df377ff43a5b36d956e82baee8-21465387.eu-west-2.elb.amazonaws.com

**Cluster:** vericase-cluster  
**Region:** eu-west-2  
**Nodes:** 2x m6i.xlarge (vericase-ng node group)  
**API Pods:** 3 replicas (high availability)  
**Worker Pods:** 2 replicas  
**Auto-Deploy:** ✅ Enabled (GitHub Actions → ECR)

### Login Credentials
- **Email:** admin@vericase.com
- **Password:** ChangeMe123

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

## EKS Worker Nodes

### Node 1
- **Instance ID:** i-0913d878182fa803c
- **IP:** 35.179.167.235 (internal: 192.168.62.148)
- **Type:** m6i.xlarge
- **Status:** Ready

### Node 2
- **Instance ID:** i-0f664f8c4daefa7e6
- **IP:** 13.40.213.46 (internal: 192.168.92.103)
- **Type:** m6i.xlarge
- **Status:** Ready

## Old EC2 Instance (Deprecated)
- **Instance ID:** i-0ade6dff1811bdbcb
- **Status:** Unstable (multiple restarts)
- **Note:** Replaced by EKS deployment

## Monthly Costs
- **EKS Cluster:** ~£300/month (2x m6i.xlarge nodes)
- **AWS Services:** ~£20/month (S3, Lambda, Textract, Comprehend)
- **Redis:** ~£150/month
- **LoadBalancer:** ~£20/month

## Deployment Scripts
- **Restart Services:** `ops/restart-ec2-services.ps1`
- **AWS Deployment:** `deploy-aws-ai-services.ps1`
- **Bedrock Setup:** `setup-bedrock-simple.ps1`

## Container Registry
- **ECR Repository:** 526015377510.dkr.ecr.eu-west-2.amazonaws.com/vericase-api
- **Image Tag:** latest
- **Auto-Build:** GitHub Actions on push to main

---
**Last Updated:** December 4, 2025
