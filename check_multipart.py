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

bucket = "vericase-docs"
print(f"Checking bucket: {bucket}")

try:
    response = s3.list_multipart_uploads(Bucket=bucket)
    if "Uploads" in response:
        print("Found multipart uploads:")
        for upload in response["Uploads"]:
            print(f"- Key: {upload['Key']}, UploadId: {upload['UploadId']}")
    else:
        print("No multipart uploads found.")
except Exception as e:
    print(f"Error: {e}")
