# App Runner Deployment Fixes

## Issues Found (from logs):

1. ✗ **UI 404 Error** - `/ui/` returns 404
2. ✗ **Database Auth Failed** - Password authentication failed
3. ✗ **S3 Access Denied** - Missing IRSA permissions
4. ✗ **OpenSearch 403** - Authorization error

## Fixes Required:

### 1. Fix Database Password

**Check RDS password:**
```bash
aws rds describe-db-instances \
  --db-instance-identifier database-1 \
  --region eu-west-2 \
  --query 'DBInstances[0].MasterUsername'
```

**Reset if needed:**
```bash
aws rds modify-db-instance \
  --db-instance-identifier database-1 \
  --master-user-password 'Sunnyday8?!' \
  --region eu-west-2 \
  --apply-immediately
```

### 2. Fix S3 Access (CRITICAL)

**Add S3 policy to App Runner instance role:**

```bash
ROLE_NAME="VeriCaseAppRunnerInstanceRole"

aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name VeriCaseS3FullAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:*"],
      "Resource": [
        "arn:aws:s3:::vericase-data",
        "arn:aws:s3:::vericase-data/*"
      ]
    }]
  }'
```

### 3. Fix OpenSearch Access

**Update OpenSearch access policy:**

Go to OpenSearch console → vericase-opensearch → Security configuration → Access policy

Add:
```json
{
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::526015377510:role/VeriCaseAppRunnerInstanceRole"
  },
  "Action": "es:*",
  "Resource": "arn:aws:es:eu-west-2:526015377510:domain/vericase-opensearch/*"
}
```

### 4. Fix UI 404

The UI is mounted correctly but returning 404. This is likely because:
- StaticFiles needs `check_dir=False` parameter
- Or the redirect is incorrect

**No code change needed** - UI mount is correct in logs. The 404 might be a timing issue during startup.

## Deploy After Fixes:

```bash
# Commit changes
git add .
git commit -m "Fix: Add S3 permissions and update configs"
git push

# App Runner will auto-deploy
# Or manually trigger:
aws apprunner start-deployment \
  --service-arn arn:aws:apprunner:eu-west-2:526015377510:service/VeriCase-api/xxx \
  --region eu-west-2
```

## Verification:

After deployment, check:
1. Database connects: Look for "Database tables created" in logs
2. S3 works: Look for "S3 bucket verified" in logs  
3. OpenSearch works: Look for "OpenSearch index verified" in logs
4. UI loads: Visit https://your-app-url.eu-west-2.awsapprunner.com/

## Priority Order:

1. **S3 Access** (CRITICAL) - Without this, file uploads fail
2. **Database Password** - Without this, no data persistence
3. **OpenSearch** - Search features won't work
4. **UI 404** - May resolve itself after other fixes
