# AWS Configuration for VeriCase

## ⚠️ Security Warning
Never commit AWS credentials to Git. Always use environment variables.

## Step 1: Create/Update .env file
Add these AWS settings to your `.env` file (which should be in .gitignore):

```bash
# AWS Configuration
AWS_ACCESS_KEY_ID=your-access-key-here
AWS_SECRET_ACCESS_KEY=your-secret-key-here
AWS_DEFAULT_REGION=us-east-1

# S3 Configuration
AWS_S3_BUCKET=vericase-pst-storage
S3_ENDPOINT_URL=https://s3.amazonaws.com

# Use AWS S3 instead of MinIO for production
USE_AWS_S3=true
```

## Step 2: Update Docker Compose for AWS
Create a production environment file:

```bash
# docker-compose.aws.yml
services:
  api:
    environment:
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
      - USE_AWS_S3=true
      - S3_ENDPOINT_URL=https://s3.amazonaws.com
      
  worker:
    environment:
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}
      - USE_AWS_S3=true
      - S3_ENDPOINT_URL=https://s3.amazonaws.com
```

## Step 3: Create S3 Bucket
Run this script to create your S3 bucket with proper settings:

```python
import boto3

# Create S3 client
s3 = boto3.client('s3')

bucket_name = 'vericase-pst-storage'

# Create bucket
s3.create_bucket(Bucket=bucket_name)

# Enable versioning for forensic integrity
s3.put_bucket_versioning(
    Bucket=bucket_name,
    VersioningConfiguration={'Status': 'Enabled'}
)

# Set lifecycle policy for cost optimization
lifecycle_policy = {
    'Rules': [{
        'ID': 'ArchiveOldPSTs',
        'Status': 'Enabled',
        'Transitions': [{
            'Days': 90,
            'StorageClass': 'GLACIER_IR'
        }],
        'NoncurrentVersionTransitions': [{
            'NoncurrentDays': 30,
            'StorageClass': 'GLACIER_IR'
        }]
    }]
}

s3.put_bucket_lifecycle_configuration(
    Bucket=bucket_name,
    LifecycleConfiguration=lifecycle_policy
)

# Set bucket encryption
s3.put_bucket_encryption(
    Bucket=bucket_name,
    ServerSideEncryptionConfiguration={
        'Rules': [{
            'ApplyServerSideEncryptionByDefault': {
                'SSEAlgorithm': 'AES256'
            }
        }]
    }
)

print(f"Bucket {bucket_name} created successfully!")
```

## Step 4: Update Application Code
The application already supports AWS S3. Just ensure these environment variables are set.

## Step 5: Test AWS Connection
```python
# test_aws.py
import boto3
from botocore.exceptions import NoCredentialsError

try:
    s3 = boto3.client('s3')
    response = s3.list_buckets()
    print("AWS Connection successful!")
    print("Buckets:", [b['Name'] for b in response['Buckets']])
except NoCredentialsError:
    print("AWS credentials not found. Check your .env file.")
```

## Security Best Practices
1. **Never hardcode credentials** in your code
2. **Use IAM roles** when deploying to EC2/ECS
3. **Enable MFA** on your AWS account
4. **Rotate keys regularly**
5. **Use least privilege** - create IAM policies with minimal permissions
6. **Enable CloudTrail** for audit logging

## Required IAM Permissions
Create an IAM policy with these permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:CreateBucket",
                "s3:ListBucket",
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:GetObjectVersion",
                "s3:PutBucketVersioning",
                "s3:PutBucketLifecycle",
                "s3:PutBucketEncryption"
            ],
            "Resource": [
                "arn:aws:s3:::vericase-pst-storage",
                "arn:aws:s3:::vericase-pst-storage/*"
            ]
        }
    ]
}
```

## Next Steps
1. Update your `.env` file with the credentials
2. Run `docker-compose down && docker-compose up -d` to restart with AWS
3. Test PST upload to verify S3 integration works
4. Consider setting up AWS OpenSearch for production search capabilities
