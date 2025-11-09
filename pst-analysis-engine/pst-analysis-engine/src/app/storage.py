import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from .config import settings
import time
_s3=None
_s3_pub=None
def s3(public: bool=False):
    global _s3, _s3_pub
    
    # Detect AWS mode: USE_AWS_SERVICES flag or empty MINIO_ENDPOINT
    use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT
    
    if public and settings.MINIO_PUBLIC_ENDPOINT and not use_aws:
        if _s3_pub is None:
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
        if use_aws:
            # AWS S3 mode: use IRSA for credentials (no endpoint_url, no explicit keys)
            _s3 = boto3.client(
                "s3",
                config=Config(signature_version="s3v4"),
                region_name=settings.AWS_REGION,
            )
        else:
            # MinIO mode: use explicit endpoint and credentials
            _s3 = boto3.client(
                "s3",
                endpoint_url=settings.MINIO_ENDPOINT,
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
                config=Config(signature_version="s3v4"),
                region_name=settings.AWS_REGION,
            )
    return _s3
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
                raise Exception(f"S3 bucket '{settings.MINIO_BUCKET}' does not exist. Please create it in AWS first.")
            elif error_code == '403':
                raise Exception(f"Access denied to S3 bucket '{settings.MINIO_BUCKET}'. Check IRSA permissions.")
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
    cfg={"CORSRules":[{"AllowedHeaders":["*"],"AllowedMethods":["GET","PUT","POST","HEAD"],"AllowedOrigins":["*"],"ExposeHeaders":["ETag"],"MaxAgeSeconds":3600}]}
    try: s3().put_bucket_cors(Bucket=settings.MINIO_BUCKET, CORSConfiguration=cfg)
    except Exception: pass
def put_object(key: str, data: bytes, content_type: str):
    s3().put_object(Bucket=settings.MINIO_BUCKET, Key=key, Body=data, ContentType=content_type)
def get_object(key: str) -> bytes:
    obj=s3().get_object(Bucket=settings.MINIO_BUCKET, Key=key)
    return obj["Body"].read()
def presign_put(key: str, content_type: str, expires: int=3600) -> str:
    url = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT)).generate_presigned_url("put_object",
        Params={"Bucket": settings.MINIO_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=expires, HttpMethod="PUT")
    return url
def presign_get(key: str, expires: int=300) -> str:
    url = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT)).generate_presigned_url("get_object",
        Params={"Bucket": settings.MINIO_BUCKET, "Key": key, "ResponseContentDisposition": "inline"},
        ExpiresIn=expires, HttpMethod="GET")
    return url
def multipart_start(key: str, content_type: str) -> str:
    resp = s3().create_multipart_upload(Bucket=settings.MINIO_BUCKET, Key=key, ContentType=content_type)
    return resp["UploadId"]
def presign_part(key: str, upload_id: str, part_number: int, expires: int=3600) -> str:
    url = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT)).generate_presigned_url("upload_part",
        Params={"Bucket": settings.MINIO_BUCKET, "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=expires, HttpMethod="PUT")
    return url
def multipart_complete(key: str, upload_id: str, parts: list):
    return s3().complete_multipart_upload(Bucket=settings.MINIO_BUCKET, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts})

def delete_object(key: str):
    client = s3()
    try:
        client.delete_object(Bucket=settings.MINIO_BUCKET, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"NoSuchKey", "404"}:
            raise
