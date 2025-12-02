"""
S3/MinIO storage management module.
Handles bucket operations, presigned URLs, and multipart uploads.
"""

from __future__ import annotations

import html
import logging
import time
from typing import Any, BinaryIO, Protocol, cast

import boto3
from boto3 import Session
from botocore.client import Config  # type: ignore[reportMissingTypeStubs]
from botocore.exceptions import ClientError  # type: ignore[reportMissingTypeStubs]

from .config import settings


LOGGER = logging.getLogger(__name__)


class S3ClientProtocol(Protocol):
    """Subset of S3 client methods used in this module."""

    def head_bucket(self, *args: Any, **kwargs: Any) -> Any: ...

    def list_buckets(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def create_bucket(self, *args: Any, **kwargs: Any) -> Any: ...

    def put_bucket_versioning(self, *args: Any, **kwargs: Any) -> Any: ...

    def put_bucket_cors(self, *args: Any, **kwargs: Any) -> Any: ...

    def put_object(self, *args: Any, **kwargs: Any) -> Any: ...

    def get_object(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def download_fileobj(self, *args: Any, **kwargs: Any) -> None: ...

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str: ...

    def create_multipart_upload(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def upload_part(self, *args: Any, **kwargs: Any) -> Any: ...

    def complete_multipart_upload(
        self, *args: Any, **kwargs: Any
    ) -> dict[str, Any]: ...

    def delete_object(self, *args: Any, **kwargs: Any) -> Any: ...


def _normalize_endpoint(url: str | None) -> str | None:
    """Ensure endpoints include a scheme so boto3 accepts them."""
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"http://{url}"


def s3(public: bool = False) -> S3ClientProtocol:
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
        return cast(
            S3ClientProtocol,
            session.client(
                "s3",
                endpoint_url=_normalize_endpoint(settings.MINIO_PUBLIC_ENDPOINT),
                config=Config(signature_version="s3v4"),
            ),
        )

    # For MinIO: Force boto3 to use MinIO credentials by setting environment variables
    if not use_aws:
        access_key = settings.MINIO_ACCESS_KEY or "admin"
        secret_key = settings.MINIO_SECRET_KEY or "changeme"
        endpoint = _normalize_endpoint(settings.MINIO_ENDPOINT)

        os.environ["AWS_ACCESS_KEY_ID"] = access_key
        os.environ["AWS_SECRET_ACCESS_KEY"] = secret_key
        os.environ["AWS_DEFAULT_REGION"] = settings.AWS_REGION or "us-east-1"

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
        return cast(S3ClientProtocol, client)

    # AWS S3 mode
    if getattr(settings, "AWS_ACCESS_KEY_ID", None):
        session = Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        return cast(
            S3ClientProtocol,
            session.client("s3", config=Config(signature_version="s3v4")),
        )

    # Use IRSA for credentials (no explicit keys)
    LOGGER.info(
        "[S3 DEBUG] Creating AWS S3 client with IRSA, region=%s, bucket=%s",
        settings.AWS_REGION,
        settings.MINIO_BUCKET,
    )
    return cast(
        S3ClientProtocol,
        boto3.client(
            "s3",
            config=Config(signature_version="s3v4"),
            region_name=settings.AWS_REGION,
        ),
    )


def ensure_bucket() -> None:
    """Ensure S3 bucket exists and is accessible."""
    # Detect AWS mode: USE_AWS_SERVICES flag or empty MINIO_ENDPOINT
    use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT

    LOGGER.info(
        "[BUCKET DEBUG] ensure_bucket called: USE_AWS_SERVICES=%s, MINIO_ENDPOINT=%s, use_aws=%s",
        settings.USE_AWS_SERVICES,
        settings.MINIO_ENDPOINT,
        use_aws,
    )

    if use_aws:
        # In AWS mode, assume the S3 bucket already exists (managed by infrastructure)
        # Just verify we can access it by attempting a head_bucket call
        try:
            client = s3()
            client.head_bucket(Bucket=settings.MINIO_BUCKET)
            # Bucket exists and we have access
            return
        except ClientError as e:
            response = cast(dict[str, Any], e.response)
            error_dict = cast(dict[str, Any], response.get("Error", {}))
            error_code: str = error_dict.get("Code", "")
            if error_code == "404":
                msg = f"S3 bucket '{settings.MINIO_BUCKET}' does not exist."
                raise S3BucketError(msg) from e
            if error_code == "403":
                msg = f"Access denied to S3 bucket '{settings.MINIO_BUCKET}'."
                raise S3AccessError(msg) from e
            raise
    else:
        # MinIO mode: Wait for MinIO to be reachable and ensure bucket/versioning/CORS
        deadline = time.time() + 60
        last_err = None
        while time.time() < deadline:
            try:
                client = s3()
                buckets: list[dict[str, Any]] = client.list_buckets().get("Buckets", [])
                names = [cast(str, b["Name"]) for b in buckets]
                if settings.MINIO_BUCKET not in names:
                    client.create_bucket(Bucket=settings.MINIO_BUCKET)
                versioning_config = {"Status": "Enabled"}
                client.put_bucket_versioning(
                    Bucket=settings.MINIO_BUCKET,
                    VersioningConfiguration=versioning_config,
                )
                ensure_cors()
                return
            except Exception as e:  # pragma: no cover - transient connectivity
                last_err = e
                time.sleep(2)
        if last_err:
            raise last_err


class S3BucketError(Exception):
    """S3 bucket does not exist."""


class S3AccessError(Exception):
    """S3 access denied."""


def ensure_cors() -> None:
    """Configure CORS for S3 bucket."""
    cfg = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
                "AllowedOrigins": ["*"],
                "ExposeHeaders": ["ETag"],
                "MaxAgeSeconds": 3600,
            }
        ]
    }
    try:
        s3().put_bucket_cors(Bucket=settings.MINIO_BUCKET, CORSConfiguration=cfg)
    except Exception:  # pragma: no cover - best effort
        pass


def put_object(
    key: str, data: bytes, content_type: str, *, bucket: str | None = None
) -> None:
    """Upload object to S3 bucket."""
    target_bucket = bucket or settings.MINIO_BUCKET
    safe_content_type = html.escape(content_type)
    s3().put_object(
        Bucket=target_bucket,
        Key=key,
        Body=data,
        ContentType=safe_content_type,
    )


def get_object(key: str, *, bucket: str | None = None) -> bytes:
    """Download object from S3 bucket."""
    target_bucket = bucket or settings.MINIO_BUCKET
    obj = s3().get_object(Bucket=target_bucket, Key=key)
    body = obj.get("Body")
    if body is None:
        raise S3AccessError(f"Object {key} has no body")
    stream = cast(BinaryIO, body)
    return stream.read()


def download_file_streaming(bucket: str, key: str, file_obj: BinaryIO) -> None:
    """
    Stream download from S3/MinIO directly to file object
    Avoids loading entire file into memory
    """
    s3().download_fileobj(bucket, key, file_obj)


def presign_put(
    key: str,
    content_type: str,
    expires: int = 3600,
    bucket: str | None = None,
) -> str:
    """Generate presigned PUT URL for uploading to S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    client = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT))
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": target_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
        HttpMethod="PUT",
    )


def presign_get(
    key: str,
    expires: int = 300,
    bucket: str | None = None,
    response_disposition: str = "inline",
) -> str:
    """Generate presigned GET URL for downloading from S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    client = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT))
    return client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": target_bucket,
            "Key": key,
            "ResponseContentDisposition": response_disposition,
        },
        ExpiresIn=expires,
        HttpMethod="GET",
    )


def multipart_start(key: str, content_type: str, bucket: str | None = None) -> str:
    """Start multipart upload to S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    resp = s3().create_multipart_upload(
        Bucket=target_bucket,
        Key=key,
        ContentType=content_type,
    )
    return cast(str, resp["UploadId"])


def presign_part(
    key: str,
    upload_id: str,
    part_number: int,
    expires: int = 3600,
    bucket: str | None = None,
) -> str:
    """Generate presigned URL for uploading a part in multipart upload."""
    target_bucket = bucket or settings.MINIO_BUCKET
    client = s3(public=bool(settings.MINIO_PUBLIC_ENDPOINT))
    return client.generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": target_bucket,
            "Key": key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=expires,
        HttpMethod="PUT",
    )


def multipart_complete(
    key: str,
    upload_id: str,
    parts: list[dict[str, Any]],
    bucket: str | None = None,
) -> dict[str, Any]:
    """Complete multipart upload to S3."""
    target_bucket = bucket or settings.MINIO_BUCKET
    return s3().complete_multipart_upload(
        Bucket=target_bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def delete_object(key: str, *, bucket: str | None = None) -> None:
    """Delete object from S3 bucket."""
    target_bucket = bucket or settings.MINIO_BUCKET
    client = s3()
    try:
        client.delete_object(Bucket=target_bucket, Key=key)
    except ClientError as e:
        response = cast(dict[str, Any], e.response)
        error_dict = cast(dict[str, Any], response.get("Error", {}))
        code = error_dict.get("Code")
        if code not in {"NoSuchKey", "404"}:
            LOGGER.error("Failed to delete S3 object: %s", key)
            raise
