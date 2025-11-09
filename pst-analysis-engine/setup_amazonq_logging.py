#!/usr/bin/env python3
"""
Set up S3 bucket for Amazon Q Developer logging
"""

import boto3
import json
from botocore.exceptions import ClientError

def setup_amazonq_logging_bucket():
    """Create S3 bucket for Amazon Q audit logs"""
    
    s3 = boto3.client('s3')
    bucket_name = 'vericase-audit-logs'
    
    try:
        # Check if bucket exists
        s3.head_bucket(Bucket=bucket_name)
        print(f"✓ Bucket '{bucket_name}' already exists")
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            # Create bucket
            print(f"Creating bucket '{bucket_name}'...")
            s3.create_bucket(Bucket=bucket_name)
            print("✓ Bucket created")
        else:
            raise
    
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
    print("✓ Encryption enabled")
    
    # Set bucket policy for Amazon Q
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowAmazonQLogging",
                "Effect": "Allow",
                "Principal": {
                    "Service": "amazonq.amazonaws.com"
                },
                "Action": [
                    "s3:PutObject",
                    "s3:PutObjectAcl"
                ],
                "Resource": f"arn:aws:s3:::{bucket_name}/amazon-q/*"
            }
        ]
    }
    
    s3.put_bucket_policy(
        Bucket=bucket_name,
        Policy=json.dumps(bucket_policy)
    )
    print("✓ Bucket policy configured for Amazon Q")
    
    # Set lifecycle for log retention (1 year for compliance)
    lifecycle_config = {
        'Rules': [{
            'ID': 'DeleteOldQLogs',
            'Status': 'Enabled',
            'Prefix': 'amazon-q/',
            'Expiration': {
                'Days': 365  # Keep for 1 year
            }
        }]
    }
    
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket_name,
        LifecycleConfiguration=lifecycle_config
    )
    print("✓ Lifecycle policy set (365-day retention)")
    
    print(f"\n✅ Success! Use this S3 location in Amazon Q:")
    print(f"   s3://{bucket_name}/amazon-q/")
    
    return f"s3://{bucket_name}/amazon-q/"

if __name__ == "__main__":
    setup_amazonq_logging_bucket()
