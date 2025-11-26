"""
S3/MinIO storage management module.
Handles bucket operations, presigned URLs, and multipart uploads.
"""
import boto3
from boto3 import Session
from botocore.client import Config
from botocore.exceptions import ClientError
from typing import Optional, Union, Any
from .config import settings
import time
import html

class _S3ClientManager:
    """Thread-safe S3 client manager"""
    _s3 = None
    _s3_pub = None

    @property
    def s3(self):
        return self._s3

    @property
    def s3_pub(self):
        return self._s3_pub


def _normalize_endpoint(url: Optional[str]) -> Optional[str]:
    """Ensure endpoints include a scheme so boto3 accepts them."""
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"http://{url}"


def s3(public: bool=False):
    """Get S3 client for AWS S3 or MinIO."""
    import os
    
    # Detect AWS mode: USE_AWS_SERVICES flag or empty MINIO_ENDPOINT
    use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT

    if public and settings.MINIO_PUBLIC_ENDPOINT and not use_aws:
        # Always create fresh client for public endpoint
        # Using public MinIO endpoint for presigned URLs
        session = Session(
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=settings.AWS_REGION,
        )
        return session.client(
            "s3",
            endpoint_url=_normalize_endpoint(settings.MINIO_PUBLIC_ENDPOINT),
            config=Config(signature_version="s3v4"),
        )

    # For MinIO: Force boto3 to use MinIO credentials by setting environment variables
    if not use_aws:
        access_key = settings.MINIO_ACCESS_KEY or "admin"
        secret_key = settings.MINIO_SECRET_KEY or "changeme"
        endpoint = _normalize_endpoint(settings.MINIO_ENDPOINT)
        
        os.environ['AWS_ACCESS_KEY_ID'] = access_key
        os.environ['AWS_SECRET_ACCESS_KEY'] = secret_key
        os.environ['AWS_DEFAULT_REGION'] = settings.AWS_REGION or "us-east-1"
        
        # Always create a fresh session to avoid credential caching issues
        session = Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=settings.AWS_REGION or "us-east-1",
        )
        client = session.client(
            "s3",
            endpoint_url=endpoint,
            config=Config(signature_version="s3v4"),
        )
        return client
    
    # AWS S3 mode
    if hasattr(settings, 'AWS_ACCESS_KEY_ID') and settings.AWS_ACCESS_KEY_ID:
        session = Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        return session.client(
            "s3",
            config=Config(signature_version="s3v4"),
        )
    else:
        # Use IRSA for credentials (no explicit keys)
        return boto3.client(
            "s3",
            config=Config(signature_version="s3v4"),
            region_name=settings.AWS_REGION,
        )

def ensure_bucket():
    """Ensure S3 bucket exists and is accessible."""
    import logging
    logger = logging.getLogger(__name__)
    
    # Detect AWS mode: USE_AWS_SERVICES flag or empty MINIO_ENDPOINT
    use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT
    
    logger.info(f"[BUCKET DEBUG] ensure_bucket called: USE_AWS_SERVICES={settings.USE_AWS_SERVICES}, MINIO_ENDPOINT={settings.MINIO_ENDPOINT}, use_aws={use_aws}")
    
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
                raise S3BucketError(f"S3 bucket '{settings.MINIO_BUCKET}' does not exist. Please create it in AWS first.")
            elif error_code == '403':
                raise S3AccessError(f"Access denied to S3 bucket '{settings.MINIO_BUCKET}'. Check IRSA permissions.")
            else:
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
    """Configure CORS for S3 bucket."""
    cfg={"CORSRules":[{"AllowedHeaders":["*"],"AllowedMethods":["GET","PUT","POST","HEAD"],"AllowedOrigins":["*"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3600}]}
    try: s3().put_bucket_cors(Bucket=settings.MINIO_BUCKET, CORSConfiguration=cfg)
    except Exception:
        pass

def put_object(key: str, data: bytes, content_type: str, *, bucket: Optional[str] = None):
    """Upload object to S3 bucket."""
    target_bucket = bucket or settings.MINIO_BUCKET
    safe_content_type = html.escape(content_type)
    s3().put_object(Bucket=target_bucket, Key=key, Body=data, ContentType=safe_content_type)

def get_object(key: str) -> bytes:
    """Download object from S3 bucket."""
    obj=s3().get_object(Bucket=settings.MINIO_BUCKET, Key=key)
    return obj["Body"].read()


def download_file_streaming(bucket: str, key: str, file_obj):
    """
    Stream download from S3/MinIO directly to file object
    Avoids loading entire file into memory
    """
    s3().download_fileobj(bucket, key, file_obj)

def presign_put(key: str, content_type: str, expires: int=3600, bucket: Optional[str] = None) -> str:
    """Generate presigned PUT URL for uploading to S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    client = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT))
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": target_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
        HttpMethod="PUT",
    )
    return url

def presign_get(key: str, expires: int=300, bucket: Optional[str] = None, response_disposition: str = "inline") -> str:
    """Generate presigned GET URL for downloading from S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    client = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT))
    url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": target_bucket,
            "Key": key,
            "ResponseContentDisposition": response_disposition,
        },
        ExpiresIn=expires,
        HttpMethod="GET",
    )
    return url

def multipart_start(key: str, content_type: str, bucket: Optional[str] = None) -> str:
    """Start multipart upload to S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    resp = s3().create_multipart_upload(Bucket=target_bucket, Key=key, ContentType=content_type)
    return resp["UploadId"]

def presign_part(key: str, upload_id: str, part_number: int, expires: int=3600, bucket: Optional[str] = None) -> str:
    """Generate presigned URL for uploading a part in multipart upload."""
    target_bucket = bucket or settings.MINIO_BUCKET
    client = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT))
    url = client.generate_presigned_url(
        "upload_part",
        Params={"Bucket": target_bucket, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=expires,
        HttpMethod="PUT",
    )
    return url

def multipart_complete(key: str, upload_id: str, parts: list[dict[str, Any]], bucket: Optional[str] = None) -> dict[str, Any]:
    """Complete multipart upload to S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    return s3().complete_multipart_upload(
        Bucket=target_bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )

class S3BucketError(Exception):
    """S3 bucket does not exist"""
    pass

class S3AccessError(Exception):
    """S3 access denied"""
    pass

def delete_object(key: str):
    """Delete object from S3 bucket."""
    client = s3()
    try:
        client.delete_object(Bucket=settings.MINIO_BUCKET, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"NoSuchKey", "404"}:
            import logging
            logging.error("Failed to delete S3 object: %s", key)
            raise
