# PST Upload S3 Credentials Fix

## Problem
PST file uploads fail with `botocore.exceptions.NoCredentialsError: Unable to locate credentials` even though MinIO credentials are configured.

## Root Cause
boto3's credential resolution chain searches for AWS credentials before using the explicitly provided credentials. The issue occurs during `upload_fileobj()` when creating a multipart upload.

## Solution

Replace the entire `s3()` function in `pst-analysis-engine/api/app/storage.py` with this fixed version:

```python
def s3(public: bool=False):
    import os
    # Detect AWS mode: USE_AWS_SERVICES flag or empty MINIO_ENDPOINT
    use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT

    if public and settings.MINIO_PUBLIC_ENDPOINT and not use_aws:
        # Public client for presigned URLs
        if _S3ClientManager._s3_pub is None:
            _S3ClientManager._s3_pub = boto3.client(
                "s3",
                endpoint_url=_normalize_endpoint(settings.MINIO_PUBLIC_ENDPOINT),
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
                config=Config(signature_version="s3v4"),
                region_name=settings.AWS_REGION,
            )
        return _S3ClientManager._s3_pub

    # Force boto3 to use MinIO credentials by setting environment variables
    if not use_aws:
        os.environ['AWS_ACCESS_KEY_ID'] = settings.MINIO_ACCESS_KEY
        os.environ['AWS_SECRET_ACCESS_KEY'] = settings.MINIO_SECRET_KEY

    # Always recreate client to avoid stale credentials
    if use_aws:
        # AWS S3 mode
        if hasattr(settings, 'AWS_ACCESS_KEY_ID') and settings.AWS_ACCESS_KEY_ID:
            _S3ClientManager._s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name=settings.AWS_REGION,
            )
        else:
            # Use IRSA for credentials
            _S3ClientManager._s3 = boto3.client(
                "s3",
                config=Config(signature_version="s3v4"),
                region_name=settings.AWS_REGION,
            )
    else:
        # MinIO mode
        _S3ClientManager._s3 = boto3.client(
            "s3",
            endpoint_url=_normalize_endpoint(settings.MINIO_ENDPOINT),
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name=settings.AWS_REGION,
        )
    return _S3ClientManager._s3
```

## Steps to Apply

1. Edit `pst-analysis-engine/api/app/storage.py`
2. Replace the `s3()` function (starts around line 23) with the code above
3. Rebuild the API container:
   ```bash
   cd "C:\Users\William\Documents\Projects\VeriCase Analysis\pst-analysis-engine"
   docker compose up -d --build api
   ```
4. Wait for container to start (about 30 seconds)
5. Try uploading a PST file again

## Verification

After applying the fix, you should see:
- No "NoCredentialsError" in the logs
- Upload progresses to "Processing..." state
- File appears in MinIO storage
- Worker begins processing the PST file

## What Changed

1. **Added `os.environ` variables** - Forces boto3 to find credentials in environment
2. **Removed caching check** - Always recreates the S3 client to avoid stale credentials
3. **Import `os` inside function** - Ensures environment variables are set before boto3 initialization

## Alternative Fix (if above doesn't work)

Use boto3 Session instead:

```python
from boto3 import Session

def s3(public: bool=False):
    use_aws = settings.USE_AWS_SERVICES or not settings.MINIO_ENDPOINT

    if not use_aws:
        # MinIO mode - use Session for better credential handling
        session = Session(
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=settings.AWS_REGION
        )
        return session.client(
            's3',
            endpoint_url=_normalize_endpoint(settings.MINIO_ENDPOINT),
            config=Config(signature_version="s3v4")
        )
    else:
        # AWS mode
        return boto3.client('s3', config=Config(signature_version="s3v4"), region_name=settings.AWS_REGION)
```

## Current State

- ✅ Correspondence page navigation fixed - redirects to dashboard if no project ID
- ✅ Project creation works - UUID auto-generated
- ✅ Database has "Debug Project" with ID `ccb62a22-b159-4f98-9df9-f8704b578109`
- ❌ PST upload fails due to S3 credentials issue (this fix)
- ⏳ Once upload works, worker will process PST and populate emails

## Next Steps After Fix

1. Upload a PST file
2. Check worker logs: `docker compose logs worker --tail=50`
3. Verify emails appear in database:
   ```sql
   SELECT COUNT(*) FROM email_messages WHERE project_id = 'ccb62a22-b159-4f98-9df9-f8704b578109';
   ```
4. View emails in correspondence page
