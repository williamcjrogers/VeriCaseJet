# pyright: reportMissingTypeStubs=false, reportUnknownVariableType=false,
# reportUnknownMemberType=false, reportUnknownArgumentType=false,
# reportPossiblyUnboundVariable=false, reportAny=false
"""
Production configuration helper for AWS deployment
This file helps map AWS environment variables to the app's expected format
"""
import os
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def load_ai_keys_from_secrets_manager() -> bool:
    """Load AI API keys from AWS Secrets Manager"""
    secret_name = os.getenv(
        'AWS_SECRETS_MANAGER_AI_KEYS',
        'vericase/ai-api-keys')
    region = os.getenv('AWS_REGION', 'eu-west-2')

    if not secret_name:
        logger.debug("No Secrets Manager secret configured for AI keys")
        return False

    try:
        import boto3
        from botocore.exceptions import ClientError

        client: Any = boto3.client('secretsmanager', region_name=region)
        response: Any = client.get_secret_value(SecretId=secret_name)

        secret_string: Any = response.get('SecretString')
        if not secret_string:
            logger.warning(f"Secret {secret_name} has no value")
            return False

        secrets: Any = json.loads(secret_string)

        # Map secret keys to environment variables
        key_mapping = {
            'OPENAI_API_KEY': 'OPENAI_API_KEY',
            'ANTHROPIC_API_KEY': 'CLAUDE_API_KEY',  # App uses CLAUDE_API_KEY internally
            'CLAUDE_API_KEY': 'CLAUDE_API_KEY',
            'GEMINI_API_KEY': 'GEMINI_API_KEY',
            'GROK_API_KEY': 'GROK_API_KEY',
            'PERPLEXITY_API_KEY': 'PERPLEXITY_API_KEY',
        }

        loaded_count = 0
        for secret_key, env_key in key_mapping.items():
            value: Any = secrets.get(secret_key)
            if value and str(value).strip():
                os.environ[env_key] = str(value).strip()
                loaded_count += 1
                print(
                    f"[config_production] ✓ Loaded {env_key} from Secrets Manager")
                logger.info(f"✓ Loaded {env_key} from Secrets Manager")

        if loaded_count > 0:
            logger.info(
                f"Successfully loaded {loaded_count} AI API keys from Secrets Manager")
            return True
        else:
            logger.warning("No AI API keys found in Secrets Manager secret")
            return False

    except ImportError:
        print("[config_production] ERROR: boto3 not available")
        logger.warning(
            "boto3 not available - cannot load from Secrets Manager")
        return False
    except ClientError as e:
        error_code: Any = e.response.get('Error', {}).get(
            'Code', '')  # type: ignore[reportPossiblyUnboundVariable]
        print(f"[config_production] ERROR: ClientError {error_code}: {e}")
        if error_code == 'ResourceNotFoundException':
            logger.warning(
                f"Secret {secret_name} not found in Secrets Manager")
        elif error_code == 'AccessDeniedException':
            logger.warning(
                f"Access denied to secret {secret_name} - check IAM permissions"
            )
        else:
            logger.error(f"Failed to load AI keys from Secrets Manager: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"[config_production] ERROR: Invalid JSON: {e}")
        logger.error(f"Invalid JSON in secret {secret_name}: {e}")
        return False
    except Exception as e:
        print(f"[config_production] ERROR: Unexpected: {e}")
        logger.error(f"Unexpected error loading AI keys: {e}")
        return False


def update_production_config() -> None:
    """Update configuration for AWS production deployment"""

    # If running in actual AWS environment (not just having AWS_REGION set),
    # enable AWS mode
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

# Load AI keys from Secrets Manager (after basic config is set)
# Try to load if:
# 1. Running in AWS environment (AWS_EXECUTION_ENV set)
# 2. USE_AWS_SERVICES is true
# 3. AWS_SECRETS_MANAGER_AI_KEYS is explicitly configured
# 4. AWS_REGION is set (indicates AWS deployment)
_should_load = (os.getenv('AWS_EXECUTION_ENV') or
                os.getenv('USE_AWS_SERVICES') == 'true' or
                os.getenv('AWS_SECRETS_MANAGER_AI_KEYS') or
                os.getenv('AWS_REGION'))
print(
    f"[config_production] Should load AI keys from Secrets Manager: "
    f"{_should_load}")
print(
    f"[config_production] AWS_REGION={os.getenv('AWS_REGION')}, "
    f"USE_AWS_SERVICES={os.getenv('USE_AWS_SERVICES')}")
if _should_load:
    print("[config_production] Loading AI keys from Secrets Manager...")
    _ = load_ai_keys_from_secrets_manager()
