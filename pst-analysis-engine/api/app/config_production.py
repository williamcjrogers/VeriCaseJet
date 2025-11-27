"""
Production configuration helper for AWS deployment
This file helps map AWS environment variables to the app's expected format
"""
import os

def update_production_config():
    """Update configuration for AWS production deployment"""
    
    # If running in actual AWS environment (not just having AWS_REGION set), enable AWS mode
    # AWS_EXECUTION_ENV is set by AWS Lambda/ECS/etc.
    # Only enable AWS mode if explicitly in AWS execution environment
    if os.getenv('AWS_EXECUTION_ENV'):
        os.environ['USE_AWS_SERVICES'] = 'true'
    
    # Map AWS S3 variables to expected format
    storage_bucket = os.getenv('AWS_STORAGE_BUCKET_NAME')
    if storage_bucket:
        os.environ['S3_BUCKET'] = storage_bucket
        os.environ['MINIO_BUCKET'] = storage_bucket
    
    # Map AWS credentials if not already set
    aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
    if aws_access_key and not os.getenv('S3_ACCESS_KEY'):
        os.environ['S3_ACCESS_KEY'] = aws_access_key
        os.environ['MINIO_ACCESS_KEY'] = aws_access_key
    
    aws_secret = os.getenv('AWS_SECRET_ACCESS_KEY')
    if aws_secret and not os.getenv('S3_SECRET_KEY'):
        os.environ['S3_SECRET_KEY'] = aws_secret
        os.environ['MINIO_SECRET_KEY'] = aws_secret
    
    # Set S3 endpoint to None for AWS (uses default AWS endpoints)
    if os.getenv('USE_AWS_SERVICES') == 'true':
        os.environ['S3_ENDPOINT'] = ''
        os.environ['MINIO_ENDPOINT'] = ''
    
    # Ensure region is set
    aws_s3_region = os.getenv('AWS_S3_REGION_NAME')
    if aws_s3_region:
        os.environ['AWS_REGION'] = aws_s3_region
    elif not os.getenv('AWS_REGION'):
        os.environ['AWS_REGION'] = 'us-east-1'

# Call this before importing the main app
update_production_config()
