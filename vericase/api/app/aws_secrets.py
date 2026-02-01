"""
AWS Secrets Manager Integration
Loads AI API keys and configuration from AWS Secrets Manager
"""

import json
import logging
import threading
from time import monotonic
from typing import Any
import boto3
from botocore.exceptions import ClientError

from .config import settings

logger = logging.getLogger(__name__)

_secrets_cache: dict[str, Any] = {}
_cache_valid = False
_cache_lock = threading.Lock()
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS: float = 3600.0  # 1 hour


class AWSSecretsManager:
    """Manages AI API keys from AWS Secrets Manager"""

    def __init__(self):
        self.client = boto3.client(
            "secretsmanager",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        )
        self.secret_name = settings.AWS_SECRETS_NAME or "vericase/ai-keys"

    def get_secret(self) -> dict[str, Any]:
        """Fetch secrets from AWS Secrets Manager with caching"""
        global _secrets_cache, _cache_valid, _cache_timestamp

        with _cache_lock:
            if (
                _cache_valid
                and _secrets_cache
                and (monotonic() - _cache_timestamp) < _CACHE_TTL_SECONDS
            ):
                return _secrets_cache

        try:
            response = self.client.get_secret_value(SecretId=self.secret_name)
            secret_string = response.get("SecretString")

            if secret_string:
                with _cache_lock:
                    _secrets_cache = json.loads(secret_string)
                    _cache_valid = True
                    _cache_timestamp = monotonic()
                logger.info(
                    f"Loaded AI keys from AWS Secrets Manager: {self.secret_name}"
                )
                return _secrets_cache
            else:
                logger.error("No SecretString found in AWS Secrets Manager response")
                return {}

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ResourceNotFoundException":
                logger.warning(
                    f"Secret {self.secret_name} not found in AWS Secrets Manager"
                )
            elif error_code == "AccessDeniedException":
                logger.warning(f"Access denied to secret {self.secret_name}")
            else:
                logger.error(f"Error fetching secret from AWS: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error fetching secrets: {e}")
            return {}

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a specific provider from AWS Secrets"""
        secrets = self.get_secret()
        key_name = f"{provider.upper()}_API_KEY"
        return secrets.get(key_name)

    def get_all_keys(self) -> dict[str, str]:
        """Get all configured API keys from AWS Secrets"""
        secrets = self.get_secret()
        keys = {}

        # Expected key patterns
        providers = ["OPENAI", "ANTHROPIC", "GEMINI", "XAI", "PERPLEXITY"]
        for provider in providers:
            key_name = f"{provider}_API_KEY"
            if key_name in secrets:
                keys[provider.lower()] = secrets[key_name]

        return keys

    @classmethod
    def invalidate_cache(cls):
        """Invalidate the secrets cache to force refresh"""
        global _cache_valid
        with _cache_lock:
            _cache_valid = False

    @classmethod
    def get_providers_status(cls) -> dict[str, bool]:
        """Check which providers have keys configured in AWS Secrets"""
        manager = cls()
        all_keys = manager.get_all_keys()
        return {
            "openai": "openai" in all_keys,
            "anthropic": "anthropic" in all_keys,
            "gemini": "gemini" in all_keys,
            "xai": "xai" in all_keys,
            "perplexity": "perplexity" in all_keys,
            "bedrock": True,  # Bedrock uses IAM, always available if AWS configured
        }


# Singleton instance
_aws_secrets = None


def get_aws_secrets_manager() -> AWSSecretsManager:
    """Get singleton AWS Secrets Manager instance"""
    global _aws_secrets
    if _aws_secrets is None:
        _aws_secrets = AWSSecretsManager()
    return _aws_secrets
