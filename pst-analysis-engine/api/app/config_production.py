"""
Production configuration helper for AWS deployment
This file helps map AWS environment variables to the app's expected format
"""
import os

def update_production_config():
    """Update configuration for AWS production deployment"""
    
    # If running in AWS, set USE_AWS_SERVICES
    if os.getenv('AWS_EXECUTION_ENV') or os.getenv('AWS_REGION'):
        os.environ['USE_AWS_SERVICES'] = 'true'
    
    # Map AWS S3 variables to expected format
    if os.getenv('AWS_STORAGE_BUCKET_NAME'):
        os.environ['S3_BUCKET'] = os.getenv('AWS_STORAGE_BUCKET_NAME')
        os.environ['MINIO_BUCKET'] = os.getenv('AWS_STORAGE_BUCKET_NAME')
    
    # Map AWS credentials if not already set
    if os.getenv('AWS_ACCESS_KEY_ID') and not os.getenv('S3_ACCESS_KEY'):
        os.environ['S3_ACCESS_KEY'] = os.getenv('AWS_ACCESS_KEY_ID')
        os.environ['MINIO_ACCESS_KEY'] = os.getenv('AWS_ACCESS_KEY_ID')
    
    if os.getenv('AWS_SECRET_ACCESS_KEY') and not os.getenv('S3_SECRET_KEY'):
        os.environ['S3_SECRET_KEY'] = os.getenv('AWS_SECRET_ACCESS_KEY')
        os.environ['MINIO_SECRET_KEY'] = os.getenv('AWS_SECRET_ACCESS_KEY')
    
    # Set S3 endpoint to None for AWS (uses default AWS endpoints)
    if os.getenv('USE_AWS_SERVICES') == 'true':
        os.environ['S3_ENDPOINT'] = ''
        os.environ['MINIO_ENDPOINT'] = ''
    
    # Ensure region is set
    if os.getenv('AWS_S3_REGION_NAME'):
        os.environ['AWS_REGION'] = os.getenv('AWS_S3_REGION_NAME')
    elif not os.getenv('AWS_REGION'):
        os.environ['AWS_REGION'] = 'us-east-1'

# Call this before importing the main app
update_production_config()
