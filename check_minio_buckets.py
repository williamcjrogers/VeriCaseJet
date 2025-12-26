import boto3
from botocore.client import Config

s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9002",
    aws_access_key_id="admin",
    aws_secret_access_key="changeme123",
    config=Config(signature_version="s3v4"),
    region_name="eu-west-2",
)

try:
    response = s3.list_buckets()
    print("Existing buckets:")
    for bucket in response["Buckets"]:
        print(f"- {bucket['Name']}")
except Exception as e:
    print(f"Error listing buckets: {e}")
