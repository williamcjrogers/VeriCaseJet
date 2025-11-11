# VeriCase Deployment Failure - Fix Required

## Problem
Your App Runner deployment is **failing at runtime** because it cannot connect to:
- PostgreSQL RDS (database-1.cv8uwu0uqr7fau-west-2.rds.amazonaws.com)
- Redis ElastiCache (clustercfg.vericase-redis.dbbgbx.euw2.cache.amazonaws.com)
- OpenSearch (vpc-vericase-opensearch-sl2a3zd5dnrbt64bssyocnrofu.eu-west-2.es.amazonaws.com)

## Root Cause
**App Runner VPC Connector is NOT configured**. Your services are in a VPC but App Runner is trying to access them from outside the VPC.

## Solution: Configure VPC Networking

### Step 1: Create VPC Connector
1. Go to AWS App Runner Console
2. Select your service
3. Go to **Configuration** → **Networking**
4. Click **Add VPC connector**

### Step 2: VPC Connector Settings
```
VPC: vpc-0880b8ccf488f527e (your VPC from README)
Subnets: Select 2+ subnets in DIFFERENT availability zones
Security Groups: Create/select security group with these rules:
```

### Step 3: Security Group Rules (CRITICAL)
**Outbound Rules (from App Runner to services):**
```
Type: PostgreSQL  | Port: 5432 | Destination: RDS security group
Type: Redis       | Port: 6379 | Destination: ElastiCache security group  
Type: HTTPS       | Port: 443  | Destination: OpenSearch security group
Type: HTTP        | Port: 9998 | Destination: Tika ELB (if in VPC)
Type: All Traffic | Port: All  | Destination: 0.0.0.0/0 (for internet access)
```

**Inbound Rules (on RDS/Redis/OpenSearch security groups):**
```
Type: PostgreSQL  | Port: 5432 | Source: App Runner security group
Type: Redis       | Port: 6379 | Source: App Runner security group
Type: HTTPS       | Port: 443  | Source: App Runner security group
```

### Step 4: Verify Connectivity
After configuring VPC connector, redeploy and check logs for:
- ✅ "Running database migrations..." 
- ✅ "Starting application..."
- ✅ "Application startup complete"

## Alternative: Quick Test Without Migrations

If you want to test the deployment first, temporarily disable migrations:

**Edit pst-analysis-engine/api/start.sh:**
```bash
#!/bin/bash
set -e

echo "Skipping migrations for now..."
# cd pst-analysis-engine/api
# alembic upgrade head

echo "Starting application..."
cd pst-analysis-engine/api
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

⚠️ **WARNING**: This will start the app but database tables won't exist. Only use for testing VPC connectivity.

## Security Issues Found

Your `apprunner.yaml` contains **EXPOSED CREDENTIALS**:
- Database password
- AWS access keys  
- API keys
- Admin password

### URGENT: Move to AWS Secrets Manager

1. **Store secrets in AWS Secrets Manager:**
```bash
aws secretsmanager create-secret --name vericase/database-url \
  --secret-string "postgresql://VericaseDocsAdmin:Sunnyday8?!@database-1..."

aws secretsmanager create-secret --name vericase/jwt-secret \
  --secret-string "vK9mP2xR7nQ4wL8jF6hD3sA5tY1uE0iO9pM7nB4vC2xZ8wQ6rT3yU5gH1kJ4fN"
```

2. **Update apprunner.yaml to reference secrets:**
```yaml
env:
  - name: DATABASE_URL
    value-from: "arn:aws:secretsmanager:eu-west-2:ACCOUNT:secret:vericase/database-url"
  - name: JWT_SECRET
    value-from: "arn:aws:secretsmanager:eu-west-2:ACCOUNT:secret:vericase/jwt-secret"
```

3. **Grant App Runner IAM role access to Secrets Manager**

## Next Steps

1. ✅ Configure VPC Connector (REQUIRED)
2. ✅ Update security groups (REQUIRED)
3. ✅ Redeploy App Runner service
4. ⚠️ Move secrets to Secrets Manager (URGENT)
5. ⚠️ Rotate all exposed credentials (URGENT)

## Reference Documentation
- VPC_NETWORKING_GUIDE.md (in your repo)
- AWS_QUICK_START.md (Step 4: VPC Configuration)
