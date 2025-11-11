# VeriCase Deployment - Quick Fix Steps

## Your deployment BUILT successfully but FAILED at runtime due to missing VPC configuration.

## Option 1: Automated Fix (Recommended)

### Windows (PowerShell):
```powershell
cd "c:\Users\William\Documents\Projects\VeriCase Analysis"
.\fix-deployment.ps1
```

### Linux/Mac (Bash):
```bash
cd ~/VeriCase-Analysis
chmod +x fix-deployment.sh
./fix-deployment.sh
```

This script will:
- ✅ Create App Runner security group
- ✅ Configure outbound rules (PostgreSQL, Redis, OpenSearch)
- ✅ Update RDS security group to allow App Runner access
- ⚠️ Show you how to configure VPC connector (manual step)

## Option 2: Manual Fix (AWS Console)

### Step 1: Create Security Group
1. Go to EC2 → Security Groups
2. Create new security group:
   - Name: `apprunner-vericase-sg`
   - VPC: `vpc-0880b8ccf488f527e`
   - Outbound rules:
     - PostgreSQL (5432) → 0.0.0.0/0
     - Redis (6379) → 0.0.0.0/0
     - HTTPS (443) → 0.0.0.0/0
     - HTTP (9998) → 0.0.0.0/0

### Step 2: Update RDS Security Group
1. Go to RDS → Databases → database-1
2. Click on VPC security group
3. Add inbound rule:
   - Type: PostgreSQL
   - Port: 5432
   - Source: `apprunner-vericase-sg`

### Step 3: Configure App Runner VPC Connector
1. Go to App Runner → Your service
2. Configuration → Networking
3. Click "Add VPC connector"
4. Configure:
   - VPC: `vpc-0880b8ccf488f527e`
   - Subnets: Select 2+ in different AZs
   - Security Group: `apprunner-vericase-sg`
5. Save

### Step 4: Redeploy
1. Go to App Runner → Your service
2. Click "Deploy"
3. Wait for deployment to complete
4. Check logs for success

## Verify Deployment

After VPC configuration, check logs for:
```
✅ Database connected
✅ Running database migrations...
✅ Starting application on port 8000...
```

## Troubleshooting

### Still failing?
1. Check security group rules are correct
2. Verify subnets are in different AZs
3. Ensure RDS allows inbound from App Runner SG
4. Check CloudWatch logs for specific errors

### Need help?
- Review: `VPC_NETWORKING_GUIDE.md`
- Review: `AWS_QUICK_START.md`
- Check AWS App Runner logs in CloudWatch

## Security Warning

Your `apprunner.yaml` contains exposed credentials. After deployment works:

1. Move secrets to AWS Secrets Manager
2. Update apprunner.yaml to reference secrets
3. Rotate all exposed credentials

See `DEPLOYMENT_FIX.md` for details.
