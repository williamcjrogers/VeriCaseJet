# VeriCase Deployment - FINAL FIX

## Good News! 
✅ VPC Connector is already configured
✅ Subnets are properly set (3 subnets across 3 AZs)

## Problem
❌ Security group `sg-0fe33dbc9d4cf20ba` (default) needs proper rules

## Solution: Fix Security Groups

### Run This Command:

**Windows PowerShell:**
```powershell
cd "c:\Users\William\Documents\Projects\VeriCase Analysis"
.\fix-security-groups.ps1
```

**Linux/Mac:**
```bash
chmod +x fix-security-groups.sh
./fix-security-groups.sh
```

This will:
1. Add outbound rules to App Runner security group (default)
   - PostgreSQL (5432)
   - Redis (6379)
   - HTTPS (443)
   - HTTP (9998)

2. Add inbound rules to service security groups
   - RDS: Allow App Runner on port 5432
   - Redis: Allow App Runner on port 6379
   - OpenSearch: Allow App Runner on port 443

### After Running Script:

1. **Redeploy App Runner:**
   - Go to: https://console.aws.amazon.com/apprunner/home?region=eu-west-2
   - Select your service
   - Click "Deploy"

2. **Watch Logs:**
   - Look for: "✅ Database connected"
   - Look for: "Running database migrations..."
   - Look for: "Starting application on port 8000..."

## Manual Alternative (If Script Fails)

### 1. Update Default Security Group (sg-0fe33dbc9d4cf20ba)

**Add Outbound Rules:**
```
Type: PostgreSQL  | Protocol: TCP | Port: 5432 | Destination: 0.0.0.0/0
Type: Redis       | Protocol: TCP | Port: 6379 | Destination: 0.0.0.0/0
Type: HTTPS       | Protocol: TCP | Port: 443  | Destination: 0.0.0.0/0
Type: Custom TCP  | Protocol: TCP | Port: 9998 | Destination: 0.0.0.0/0
```

### 2. Update RDS Security Group

Find RDS security group:
- Go to RDS → database-1 → Connectivity & security
- Click on VPC security group

**Add Inbound Rule:**
```
Type: PostgreSQL | Port: 5432 | Source: sg-0fe33dbc9d4cf20ba
```

### 3. Update Redis Security Group

Find Redis security group:
- Go to ElastiCache → Redis clusters → vericase-redis
- Click on security group

**Add Inbound Rule:**
```
Type: Custom TCP | Port: 6379 | Source: sg-0fe33dbc9d4cf20ba
```

### 4. Update OpenSearch Security Group

Find OpenSearch security group:
- Go to OpenSearch → vericase-opensearch → Security configuration
- Click on security group

**Add Inbound Rule:**
```
Type: HTTPS | Port: 443 | Source: sg-0fe33dbc9d4cf20ba
```

## Why This Fixes It

Your App Runner is in the VPC but the default security group blocks all outbound traffic except what's explicitly allowed. By adding these rules:

- App Runner can connect to PostgreSQL (database migrations)
- App Runner can connect to Redis (caching)
- App Runner can connect to OpenSearch (document search)
- App Runner can connect to Tika (document processing)

## Expected Result

After fixing security groups and redeploying:

```
=== VeriCase Application Startup ===
Working directory: /app
Python version: Python 3.11.x
Testing database connectivity...
✅ Database connected
Running database migrations...
INFO  [alembic.runtime.migration] Running upgrade -> head
Starting application on port 8000...
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

## Still Having Issues?

Check CloudWatch Logs for specific errors:
- Database connection timeout → RDS security group issue
- Redis connection timeout → ElastiCache security group issue
- OpenSearch connection timeout → OpenSearch security group issue

## Security Note

After deployment works, move credentials from `apprunner.yaml` to AWS Secrets Manager.
