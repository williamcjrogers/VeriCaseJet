#!/usr/bin/env python3
"""
Set up AWS S3 bucket for VeriCase PST storage
Run this after updating your .env file with AWS credentials
"""

import boto3
import os
import sys
from dotenv import load_dotenv
from botocore.exceptions import ClientError, NoCredentialsError

# Load environment variables
load_dotenv()


def create_vericase_bucket():
    """Create and configure S3 bucket for VeriCase"""

    # Get credentials from environment
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    if not access_key or not secret_key:
        print("❌ Error: AWS credentials not found in .env file")
        print(
            "Please add AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to your .env file"
        )
        return False

    print("🔧 Connecting to AWS S3...")

    try:
        # Create S3 client
        s3 = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

        bucket_name = "vericase-pst-storage"

        # Check if bucket already exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            print(f"✓ Bucket '{bucket_name}' already exists")
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                # Create bucket
                print(f"📦 Creating bucket '{bucket_name}'...")

                # Use different create method for us-east-1
                if region == "us-east-1":
                    s3.create_bucket(Bucket=bucket_name)
                else:
                    s3.create_bucket(
                        Bucket=bucket_name,
                        CreateBucketConfiguration={"LocationConstraint": region},
                    )

                print("✓ Bucket created successfully")
            else:
                raise

        # Enable versioning
        print("🔄 Enabling versioning...")
        s3.put_bucket_versioning(
            Bucket=bucket_name, VersioningConfiguration={"Status": "Enabled"}
        )

        # Set bucket encryption
        print("🔐 Enabling encryption...")
        s3.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            },
        )

        # Set CORS for presigned URLs
        print("🌐 Configuring CORS...")
        s3.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedHeaders": ["*"],
                        "AllowedMethods": ["GET", "PUT", "POST", "HEAD", "DELETE"],
                        "AllowedOrigins": ["*"],
                        "ExposeHeaders": ["ETag", "x-amz-server-side-encryption"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )

        # Set lifecycle policy for cost optimization
        print("💰 Setting lifecycle policy...")
        lifecycle_config = {
            "Rules": [
                {
                    "ID": "ArchiveOldPSTs",
                    "Status": "Enabled",
                    "Transitions": [{"Days": 90, "StorageClass": "GLACIER_IR"}],
                    "NoncurrentVersionTransitions": [
                        {"NoncurrentDays": 30, "StorageClass": "GLACIER_IR"}
                    ],
                    "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
                }
            ]
        }

        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket_name, LifecycleConfiguration=lifecycle_config
        )

        # Test upload
        print("🧪 Testing upload capability...")
        test_key = "test/connection.txt"
        s3.put_object(
            Bucket=bucket_name,
            Key=test_key,
            Body=b"VeriCase S3 connection test successful!",
            ContentType="text/plain",
        )

        # Test read
        response = s3.get_object(Bucket=bucket_name, Key=test_key)
        content = response["Body"].read().decode("utf-8")
        print(f"✓ Test upload/download successful: '{content}'")

        # Cleanup test file
        s3.delete_object(Bucket=bucket_name, Key=test_key)

        print("\n✅ AWS S3 setup complete!")
        print(f"   Bucket: {bucket_name}")
        print(f"   Region: {region}")
        print("   Versioning: Enabled")
        print("   Encryption: AES256")
        print("   CORS: Configured")
        print("   Lifecycle: 90 days to Glacier")

        print("\n📝 Next steps:")
        print("1. Update your .env file with:")
        print("   USE_AWS_S3=true")
        print(f"   AWS_S3_BUCKET={bucket_name}")
        print("   USE_AWS_SERVICES=true")
        print("2. Restart Docker services: docker-compose restart api worker")

        return True

    except NoCredentialsError:
        print("❌ AWS credentials not found. Check your .env file.")
        return False
    except ClientError as e:
        print(f"❌ AWS Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    success = create_vericase_bucket()
    sys.exit(0 if success else 1)
