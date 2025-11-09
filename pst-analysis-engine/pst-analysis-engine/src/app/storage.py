import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, BotoCoreError
from .config import settings
import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

# Global S3 client cache (singleton pattern for connection pooling)
# These are intentionally global to avoid recreating clients on every request
_s3 = None
_s3_pub = None

def retry_on_connection_error(max_retries=3, delay=1):
    """Decorator to retry S3 operations on connection errors"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ClientError, BotoCoreError, ConnectionError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"S3 operation failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"S3 operation failed after {max_retries} attempts: {e}")
            raise last_error
        return wrapper
    return decorator

def s3(public: bool=False):
    """
    Get S3 client (cached singleton pattern for connection pooling).
    
    Args:
        public: If True and MinIO public endpoint is configured, use public endpoint
        
    Returns:
        boto3 S3 client instance
        
    Raises:
        ClientError: If S3/MinIO connection fails
    """
    global _s3, _s3_pub
    
    try:
        # Detect AWS mode: USE_AWS_SERVICES flag or empty MINIO_ENDPOINT
        use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT
        
        if public and settings.MINIO_PUBLIC_ENDPOINT and not use_aws:
            if _s3_pub is None:
                logger.info("Initializing public S3 client for MinIO")
                _s3_pub = boto3.client(
                    "s3",
                    endpoint_url=settings.MINIO_PUBLIC_ENDPOINT,
                    aws_access_key_id=settings.MINIO_ACCESS_KEY,
                    aws_secret_access_key=settings.MINIO_SECRET_KEY,
                    config=Config(signature_version="s3v4"),
                    region_name=settings.AWS_REGION,
                )
            return _s3_pub
        
        if _s3 is None:
            # Enhanced connection pooling configuration
            s3_config = Config(
                signature_version="s3v4",
                max_pool_connections=50,  # Increase connection pool size
                retries={'max_attempts': 3, 'mode': 'adaptive'},
                connect_timeout=5,
                read_timeout=60
            )
            
            if use_aws:
                # AWS S3 mode: use IRSA for credentials (no endpoint_url, no explicit keys)
                logger.info("Initializing AWS S3 client with connection pooling")
                _s3 = boto3.client(
                    "s3",
                    config=s3_config,
                    region_name=settings.AWS_REGION,
                )
            else:
                # MinIO mode: use explicit endpoint and credentials
                logger.info(f"Initializing MinIO S3 client at {settings.MINIO_ENDPOINT} with connection pooling")
                _s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.MINIO_ENDPOINT,
                    aws_access_key_id=settings.MINIO_ACCESS_KEY,
                    aws_secret_access_key=settings.MINIO_SECRET_KEY,
                    config=s3_config,
                    region_name=settings.AWS_REGION,
                )
        return _s3
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        raise

def ensure_bucket():
    # Detect AWS mode: USE_AWS_SERVICES flag or empty MINIO_ENDPOINT
    use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT
    
    if use_aws:
        # In AWS mode, assume the S3 bucket already exists (managed by infrastructure)
        # Just verify we can access it by attempting a head_bucket call
        try:
            client = s3()
            client.head_bucket(Bucket=settings.MINIO_BUCKET)
            # Bucket exists and we have access
            return
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == '404':
                logger.error(f"S3 bucket '{settings.MINIO_BUCKET}' does not exist")
                raise RuntimeError(f"S3 bucket '{settings.MINIO_BUCKET}' does not exist. Please create it in AWS first.")
            elif error_code == '403':
                logger.error(f"Access denied to S3 bucket '{settings.MINIO_BUCKET}'")
                raise PermissionError(f"Access denied to S3 bucket '{settings.MINIO_BUCKET}'. Check IRSA permissions.")
            else:
                logger.error(f"Error checking S3 bucket: {e}")
                raise
    else:
        # MinIO mode: Wait for MinIO to be reachable and ensure bucket/versioning/CORS
        deadline = time.time() + 60
        last_err = None
        while time.time() < deadline:
            try:
                client = s3()
                names=[b["Name"] for b in client.list_buckets().get("Buckets",[])]
                if settings.MINIO_BUCKET not in names:
                    client.create_bucket(Bucket=settings.MINIO_BUCKET)
                client.put_bucket_versioning(Bucket=settings.MINIO_BUCKET, VersioningConfiguration={"Status":"Enabled"})
                ensure_cors()
                return
            except Exception as e:
                last_err = e
                time.sleep(2)
        if last_err:
            raise last_err

def ensure_cors():
    """Configure CORS for the S3 bucket"""
    cors_config = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
                "AllowedOrigins": ["*"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3600
            }
        ]
    }
    try:
        s3().put_bucket_cors(Bucket=settings.MINIO_BUCKET, CORSConfiguration=cors_config)
    except Exception as e:
        logger.warning(f"Failed to configure CORS: {e}")

def put_object(key: str, data: bytes, content_type: str):
    """Upload an object to S3/MinIO"""
    try:
        s3().put_object(Bucket=settings.MINIO_BUCKET, Key=key, Body=data, ContentType=content_type)
        logger.debug(f"Successfully uploaded object: {key}")
    except Exception as e:
        logger.error(f"Failed to upload object {key}: {e}")
        raise
        
def get_object(key: str) -> bytes:
    """Download an object from S3/MinIO"""
    try:
        obj = s3().get_object(Bucket=settings.MINIO_BUCKET, Key=key)
        return obj["Body"].read()
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') == 'NoSuchKey':
            logger.warning(f"Object not found: {key}")
        else:
            logger.error(f"Failed to get object {key}: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to get object {key}: {e}")
        raise

def presign_put(key: str, content_type: str, expires: int=3600) -> str:
    """Generate a presigned URL for uploading an object"""
    url = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT)).generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.MINIO_BUCKET,
            "Key": key,
            "ContentType": content_type
        },
        ExpiresIn=expires,
        HttpMethod="PUT"
    )
    return url

def presign_get(key: str, expires: int=300) -> str:
    """Generate a presigned URL for downloading an object"""
    url = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT)).generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.MINIO_BUCKET,
            "Key": key,
            "ResponseContentDisposition": "inline"
        },
        ExpiresIn=expires,
        HttpMethod="GET"
    )
    return url

def multipart_start(key: str, content_type: str) -> str:
    """Start a multipart upload"""
    try:
        resp = s3().create_multipart_upload(Bucket=settings.MINIO_BUCKET, Key=key, ContentType=content_type)
        logger.debug(f"Started multipart upload for {key}: {resp['UploadId']}")
        return resp["UploadId"]
    except Exception as e:
        logger.error(f"Failed to start multipart upload for {key}: {e}")
        raise
def presign_part(key: str, upload_id: str, part_number: int, expires: int=3600) -> str:
    """Generate a presigned URL for uploading a part in a multipart upload"""
    url = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT)).generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": settings.MINIO_BUCKET,
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number
        },
        ExpiresIn=expires,
        HttpMethod="PUT"
    )
    return url

def multipart_complete(key: str, upload_id: str, parts: list):
    """Complete a multipart upload"""
    try:
        result = s3().complete_multipart_upload(
            Bucket=settings.MINIO_BUCKET, 
            Key=key, 
            UploadId=upload_id, 
            MultipartUpload={"Parts": parts}
        )
        logger.debug(f"Completed multipart upload for {key}")
        return result
    except Exception as e:
        logger.error(f"Failed to complete multipart upload for {key}: {e}")
        raise

def delete_object(key: str):
    """Delete an object from S3/MinIO"""
    client = s3()
    try:
        client.delete_object(Bucket=settings.MINIO_BUCKET, Key=key)
        logger.debug(f"Deleted object: {key}")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"NoSuchKey", "404"}:
            logger.error(f"Failed to delete object {key}: {exc}")
            raise
        else:
            logger.debug(f"Object already deleted or not found: {key}")
