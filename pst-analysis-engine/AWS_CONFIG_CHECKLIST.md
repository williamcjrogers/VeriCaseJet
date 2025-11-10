# AWS Configuration Checklist

## ✅ Configuration Status

### 1. Environment Variables

#### Required for AWS Mode:
- [ ] `USE_AWS_SERVICES=true` - Enable AWS services
- [ ] `AWS_REGION=us-east-1` (or your region)
- [ ] `S3_BUCKET=your-bucket-name` - S3 bucket for document storage
- [ ] `MINIO_BUCKET=your-bucket-name` - Alias for S3_BUCKET
- [ ] `MINIO_ENDPOINT=""` - Leave empty to trigger AWS mode

#### AWS Credentials (Choose ONE):

**Option A: IRSA (Recommended for EKS)**
- [ ] IAM Role attached to Kubernetes ServiceAccount
- [ ] No explicit credentials needed
- [ ] Leave `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` empty

**Option B: Explicit Credentials (EC2/ECS/Local)**
- [ ] `AWS_ACCESS_KEY_ID=your-access-key`
- [ ] `AWS_SECRET_ACCESS_KEY=your-secret-key`
- [ ] `AWS_DEFAULT_REGION=us-east-1`

#### Database & Services:
- [ ] `DATABASE_URL=postgresql+psycopg2://...` - RDS or external PostgreSQL
- [ ] `REDIS_URL=redis://...` - ElastiCache or external Redis
- [ ] `OPENSEARCH_HOST=your-opensearch-endpoint` - AWS OpenSearch domain
- [ ] `OPENSEARCH_PORT=443` - Use 443 for AWS OpenSearch
- [ ] `OPENSEARCH_USE_SSL=true` - Enable SSL for AWS OpenSearch
- [ ] `OPENSEARCH_VERIFY_CERTS=true` - Verify SSL certificates

#### Security:
- [ ] `JWT_SECRET=<strong-random-secret>` - Change from default!
- [ ] `JWT_EXPIRE_MIN=7200` - Token expiration (120 hours)
- [ ] `CORS_ORIGINS=https://your-domain.com` - Allowed origins

---

## 2. AWS Infrastructure Setup

### S3 Bucket Configuration:
```bash
# Create bucket (if not exists)
aws s3 mb s3://vericase-pst-storage --region us-east-1

# Enable versioning (forensic integrity)
aws s3api put-bucket-versioning \
  --bucket vericase-pst-storage \
  --versioning-configuration Status=Enabled

# Enable encryption
aws s3api put-bucket-encryption \
  --bucket vericase-pst-storage \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'

# Set lifecycle policy (optional - cost optimization)
aws s3api put-bucket-lifecycle-configuration \
  --bucket vericase-pst-storage \
  --lifecycle-configuration file://lifecycle.json
```

**lifecycle.json:**
```json
{
  "Rules": [{
    "ID": "ArchiveOldPSTs",
    "Status": "Enabled",
    "Transitions": [{
      "Days": 90,
      "StorageClass": "GLACIER_IR"
    }],
    "NoncurrentVersionTransitions": [{
      "NoncurrentDays": 30,
      "StorageClass": "GLACIER_IR"
    }]
  }]
}
```

### IAM Policy (Minimum Required Permissions):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetObjectVersion",
        "s3:PutBucketVersioning",
        "s3:GetBucketVersioning"
      ],
      "Resource": [
        "arn:aws:s3:::vericase-pst-storage",
        "arn:aws:s3:::vericase-pst-storage/*"
      ]
    }
  ]
}
```

### RDS PostgreSQL:
- [ ] Database instance created
- [ ] Security group allows inbound on port 5432
- [ ] Database name: `vericase`
- [ ] Connection string configured in `DATABASE_URL`

### ElastiCache Redis:
- [ ] Redis cluster created
- [ ] Security group allows inbound on port 6379
- [ ] Connection string configured in `REDIS_URL`

### AWS OpenSearch:
- [ ] OpenSearch domain created
- [ ] Access policy configured
- [ ] Endpoint configured in `OPENSEARCH_HOST`
- [ ] SSL enabled

---

## 3. Code Configuration Verification

### Check Config Files:

**File: `pst-analysis-engine/src/app/config.py`**
- [x] `USE_AWS_SERVICES` field exists
- [x] `AWS_ACCESS_KEY_ID` field exists
- [x] `AWS_SECRET_ACCESS_KEY` field exists
- [x] `AWS_REGION` validation added
- [x] Proper field validators

**File: `pst-analysis-engine/src/app/storage.py`**
- [x] AWS mode detection: `use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT`
- [x] IRSA support (no explicit credentials)
- [x] Connection pooling configured
- [x] Retry logic with exponential backoff
- [x] Proper error handling

**File: `api/app/config.py`**
- [x] AWS credentials fields exist
- [x] Consistent with main config

---

## 4. Testing AWS Configuration

### Test S3 Connection:
```python
# test_aws_s3.py
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

def test_s3_connection():
    try:
        s3 = boto3.client('s3', region_name='us-east-1')
        
        # Test bucket access
        response = s3.head_bucket(Bucket='vericase-pst-storage')
        print("✅ S3 bucket accessible")
        
        # Test write permission
        s3.put_object(
            Bucket='vericase-pst-storage',
            Key='test.txt',
            Body=b'test'
        )
        print("✅ S3 write permission OK")
        
        # Test read permission
        obj = s3.get_object(Bucket='vericase-pst-storage', Key='test.txt')
        print("✅ S3 read permission OK")
        
        # Cleanup
        s3.delete_object(Bucket='vericase-pst-storage', Key='test.txt')
        print("✅ S3 delete permission OK")
        
        print("\n✅ All S3 tests passed!")
        
    except NoCredentialsError:
        print("❌ AWS credentials not found")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print("❌ Bucket does not exist")
        elif error_code == '403':
            print("❌ Access denied - check IAM permissions")
        else:
            print(f"❌ Error: {e}")

if __name__ == '__main__':
    test_s3_connection()
```

### Test Database Connection:
```python
# test_database.py
from sqlalchemy import create_engine, text
import os

def test_database():
    try:
        db_url = os.getenv('DATABASE_URL')
        engine = create_engine(db_url)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Database connection OK")
            
    except Exception as e:
        print(f"❌ Database connection failed: {e}")

if __name__ == '__main__':
    test_database()
```

### Test Redis Connection:
```python
# test_redis.py
import redis
import os

def test_redis():
    try:
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        r = redis.from_url(redis_url)
        
        # Test connection
        r.ping()
        print("✅ Redis connection OK")
        
        # Test write
        r.set('test_key', 'test_value')
        print("✅ Redis write OK")
        
        # Test read
        value = r.get('test_key')
        print("✅ Redis read OK")
        
        # Cleanup
        r.delete('test_key')
        
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")

if __name__ == '__main__':
    test_redis()
```

---

## 5. Security Best Practices

- [ ] **Never commit credentials** to Git
- [ ] **Use IAM roles** when possible (IRSA for EKS, Instance Profiles for EC2)
- [ ] **Enable MFA** on AWS account
- [ ] **Rotate keys regularly** (if using explicit credentials)
- [ ] **Use least privilege** IAM policies
- [ ] **Enable CloudTrail** for audit logging
- [ ] **Enable S3 bucket logging**
- [ ] **Use VPC endpoints** for S3/OpenSearch (cost savings + security)
- [ ] **Enable encryption at rest** for all services
- [ ] **Use SSL/TLS** for all connections
- [ ] **Set up AWS Secrets Manager** for sensitive configuration

---

## 6. Common Issues & Solutions

### Issue: "Access Denied" to S3 bucket
**Solution:** Check IAM policy allows s3:GetObject, s3:PutObject, s3:ListBucket

### Issue: "Bucket does not exist"
**Solution:** Create bucket with `aws s3 mb s3://bucket-name`

### Issue: "No credentials found"
**Solution:** 
- For IRSA: Verify ServiceAccount has IAM role annotation
- For explicit: Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY

### Issue: Database connection timeout
**Solution:** Check security group allows inbound on port 5432 from your IP/VPC

### Issue: OpenSearch connection refused
**Solution:** 
- Check OPENSEARCH_USE_SSL=true for AWS OpenSearch
- Verify access policy allows your IAM role/user

---

## 7. Deployment Checklist

### Before Deployment:
- [ ] All environment variables set
- [ ] AWS infrastructure created (S3, RDS, Redis, OpenSearch)
- [ ] IAM policies configured
- [ ] Security groups configured
- [ ] SSL certificates configured (if using custom domain)
- [ ] DNS records configured (if using custom domain)

### After Deployment:
- [ ] Run test scripts to verify connectivity
- [ ] Check application logs for errors
- [ ] Test file upload to S3
- [ ] Test database queries
- [ ] Test search functionality (OpenSearch)
- [ ] Monitor CloudWatch metrics
- [ ] Set up CloudWatch alarms

---

## 8. Monitoring & Logging

### CloudWatch Metrics to Monitor:
- S3: NumberOfObjects, BucketSizeBytes
- RDS: CPUUtilization, DatabaseConnections, FreeStorageSpace
- ElastiCache: CPUUtilization, NetworkBytesIn/Out
- OpenSearch: ClusterStatus, SearchableDocuments

### CloudWatch Logs:
- Application logs from ECS/EKS
- RDS slow query logs
- S3 access logs
- OpenSearch logs

---

## Summary

Your AWS configuration is **mostly correct** with the following improvements made:

✅ **Fixed:**
1. Added AWS credentials fields to main config
2. Added AWS region validation
3. Improved error handling in storage module

⚠️ **Recommendations:**
1. Use IRSA for EKS deployments (no hardcoded credentials)
2. Enable CloudWatch monitoring
3. Set up AWS Secrets Manager for sensitive config
4. Use VPC endpoints for cost savings
5. Enable S3 bucket logging for audit trail

**Next Steps:**
1. Copy `env.aws.example` to `.env`
2. Fill in your AWS credentials/settings
3. Run test scripts to verify connectivity
4. Deploy to AWS
