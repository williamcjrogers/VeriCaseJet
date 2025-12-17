"""
Amazon Bedrock AI Provider
Provides access to Claude, Nova, Titan, Llama, and Mistral models via AWS Bedrock
"""

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Check if boto3 is available
try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError, NoCredentialsError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not installed - Bedrock provider unavailable")


# Bedrock model catalog
BEDROCK_MODELS = {
    # Anthropic Claude via Bedrock
    "anthropic.claude-sonnet-4-5-20250929-v1:0": {
        "name": "Claude 4.5 Sonnet (Bedrock)",
        "type": "chat",
        "provider_family": "anthropic",
        "max_tokens": 8192,
        "supports_streaming": True,
    },
    "anthropic.claude-haiku-4-5-20251001-v1:0": {
        "name": "Claude 4.5 Haiku (Bedrock)",
        "type": "chat",
        "provider_family": "anthropic",
        "max_tokens": 4096,
        "supports_streaming": True,
    },
    "anthropic.claude-opus-4-5-20251101-v1:0": {
        "name": "Claude 4.5 Opus (Bedrock)",
        "type": "chat",
        "provider_family": "anthropic",
        "max_tokens": 8192,
        "supports_streaming": True,
    },
    "anthropic.claude-3-5-sonnet-20241022-v2:0": {
        "name": "Claude 3.5 Sonnet v2 (Bedrock)",
        "type": "chat",
        "provider_family": "anthropic",
        "max_tokens": 8192,
        "supports_streaming": True,
    },
    # Amazon Nova models
    "amazon.nova-2-pro-v1:0": {
        "name": "Amazon Nova 2 Pro",
        "type": "chat",
        "provider_family": "amazon",
        "max_tokens": 5000,
        "supports_streaming": True,
    },
    "amazon.nova-2-lite-v1:0": {
        "name": "Amazon Nova 2 Lite",
        "type": "chat",
        "provider_family": "amazon",
        "max_tokens": 5000,
        "supports_streaming": True,
    },
    "amazon.nova-pro-v1:0": {
        "name": "Amazon Nova Pro",
        "type": "chat",
        "provider_family": "amazon",
        "max_tokens": 5000,
        "supports_streaming": True,
    },
    "amazon.nova-lite-v1:0": {
        "name": "Amazon Nova Lite",
        "type": "chat",
        "provider_family": "amazon",
        "max_tokens": 5000,
        "supports_streaming": True,
    },
    "amazon.nova-micro-v1:0": {
        "name": "Amazon Nova Micro",
        "type": "chat",
        "provider_family": "amazon",
        "max_tokens": 5000,
        "supports_streaming": True,
    },
    # Amazon Titan
    "amazon.titan-text-express-v1": {
        "name": "Titan Text Express",
        "type": "chat",
        "provider_family": "amazon",
        "max_tokens": 8000,
        "supports_streaming": True,
    },
    "amazon.titan-embed-text-v2:0": {
        "name": "Titan Embeddings v2",
        "type": "embedding",
        "provider_family": "amazon",
        "dimensions": 1024,
    },
    # Meta Llama
    "meta.llama3-3-70b-instruct-v1:0": {
        "name": "Llama 3.3 70B Instruct",
        "type": "chat",
        "provider_family": "meta",
        "max_tokens": 2048,
        "supports_streaming": True,
    },
    # Mistral
    "mistral.mistral-large-2407-v1:0": {
        "name": "Mistral Large (24.07)",
        "type": "chat",
        "provider_family": "mistral",
        "max_tokens": 8192,
        "supports_streaming": True,
    },
}


def bedrock_available() -> bool:
    """Check if Bedrock is available (boto3 installed and credentials present)"""
    if not BOTO3_AVAILABLE:
        return False

    # Check for AWS credentials
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None
    except Exception:
        return False


class BedrockProvider:
    """
    Amazon Bedrock AI Provider

    Supports:
    - Anthropic Claude models (via Bedrock)
    - Amazon Nova models
    - Amazon Titan models
    - Meta Llama models
    - Mistral models

    Authentication:
    - IAM Role (recommended for production - uses IRSA or instance profile)
    - Explicit credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    - Environment variables
    """

    def __init__(
        self,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ):
        """
        Initialize Bedrock provider

        Args:
            region: AWS region (default: from AWS_REGION env var or us-east-1)
            access_key_id: Optional explicit AWS access key
            secret_access_key: Optional explicit AWS secret key
        """
        if not BOTO3_AVAILABLE:
            raise ImportError("boto3 is required for Bedrock provider")

        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self._client = None
        self._runtime_client = None

        # Store explicit credentials if provided
        self._access_key = access_key_id
        self._secret_key = secret_access_key

        # Configure retry and timeout settings
        self._config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=120,
        )

    def _get_client(self):
        """Get or create Bedrock runtime client"""
        if self._runtime_client is None:
            try:
                if self._access_key and self._secret_key:
                    # Use explicit credentials
                    self._runtime_client = boto3.client(
                        "bedrock-runtime",
                        region_name=self.region,
                        aws_access_key_id=self._access_key,
                        aws_secret_access_key=self._secret_key,
                        config=self._config,
                    )
                else:
                    # Use default credential chain (IAM role, env vars, etc.)
                    self._runtime_client = boto3.client(
                        "bedrock-runtime",
                        region_name=self.region,
                        config=self._config,
                    )
                logger.info(f"Bedrock client initialized for region {self.region}")
            except NoCredentialsError:
                logger.error("No AWS credentials found for Bedrock")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Bedrock client: {e}")
                raise

        return self._runtime_client

    def get_available_models(self) -> dict[str, dict[str, Any]]:
        """Get list of available Bedrock models"""
        return BEDROCK_MODELS.copy()

    def get_model_info(self, model_id: str) -> dict[str, Any] | None:
        """Get info for a specific model"""
        return BEDROCK_MODELS.get(model_id)

    async def invoke(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: str | None = None,
    ) -> str:
        """
        Invoke a Bedrock model

        Args:
            model_id: Bedrock model ID
            prompt: User prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            system_prompt: Optional system prompt

        Returns:
            Generated text response
        """
        model_info = BEDROCK_MODELS.get(model_id)
        if not model_info:
            raise ValueError(f"Unknown Bedrock model: {model_id}")

        provider_family = model_info.get("provider_family", "")

        # Build request body based on provider
        if provider_family == "anthropic":
            body = self._build_anthropic_request(
                prompt, max_tokens, temperature, system_prompt
            )
        elif provider_family == "amazon":
            body = self._build_amazon_request(
                prompt, max_tokens, temperature, system_prompt
            )
        elif provider_family == "meta":
            body = self._build_meta_request(
                prompt, max_tokens, temperature, system_prompt
            )
        elif provider_family == "mistral":
            body = self._build_mistral_request(
                prompt, max_tokens, temperature, system_prompt
            )
        else:
            raise ValueError(f"Unsupported provider family: {provider_family}")

        # Invoke model
        client = self._get_client()

        try:
            response = await asyncio.to_thread(
                client.invoke_model,
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())

            # Parse response based on provider
            return self._parse_response(response_body, provider_family)

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            logger.error(f"Bedrock invocation failed: {error_code} - {error_msg}")
            raise RuntimeError(f"Bedrock error ({error_code}): {error_msg}")
        except Exception as e:
            logger.error(f"Bedrock invocation error: {e}")
            raise

    def _build_anthropic_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> dict[str, Any]:
        """Build request body for Anthropic Claude models"""
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            body["system"] = system_prompt
        return body

    def _build_amazon_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> dict[str, Any]:
        """Build request body for Amazon Nova/Titan models"""
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        return {
            "inputText": full_prompt,
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature,
                "topP": 0.9,
            },
        }

    def _build_meta_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> dict[str, Any]:
        """Build request body for Meta Llama models"""
        full_prompt = prompt
        if system_prompt:
            full_prompt = (
                f"<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n{prompt} [/INST]"
            )
        else:
            full_prompt = f"<s>[INST] {prompt} [/INST]"

        return {
            "prompt": full_prompt,
            "max_gen_len": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
        }

    def _build_mistral_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> dict[str, Any]:
        """Build request body for Mistral models"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
        }

    def _parse_response(
        self, response_body: dict[str, Any], provider_family: str
    ) -> str:
        """Parse response based on provider family"""
        try:
            if provider_family == "anthropic":
                # Anthropic format
                content = response_body.get("content", [])
                if content and isinstance(content, list):
                    return content[0].get("text", "")
                return ""

            elif provider_family == "amazon":
                # Amazon Titan/Nova format
                results = response_body.get("results", [])
                if results:
                    return results[0].get("outputText", "")
                # Alternative format for some Nova models
                return response_body.get("outputText", "")

            elif provider_family == "meta":
                # Meta Llama format
                return response_body.get("generation", "")

            elif provider_family == "mistral":
                # Mistral format
                outputs = response_body.get("outputs", [])
                if outputs:
                    return outputs[0].get("text", "")
                return ""

            else:
                logger.warning(f"Unknown provider family: {provider_family}")
                return str(response_body)

        except Exception as e:
            logger.error(f"Error parsing Bedrock response: {e}")
            return str(response_body)

    async def test_connection(self) -> dict[str, Any]:
        """Test Bedrock connection with a simple query"""
        try:
            # Try with a lightweight model
            test_models = [
                "amazon.nova-micro-v1:0",
                "amazon.titan-text-express-v1",
                "anthropic.claude-3-5-sonnet-20241022-v2:0",
            ]

            for model_id in test_models:
                try:
                    response = await self.invoke(
                        model_id=model_id,
                        prompt="Reply with just 'OK' to confirm the connection works.",
                        max_tokens=10,
                        temperature=0,
                    )
                    return {
                        "success": True,
                        "model": model_id,
                        "response": response[:50] if response else "OK",
                        "region": self.region,
                    }
                except Exception as e:
                    logger.debug(f"Test with {model_id} failed: {e}")
                    continue

            return {
                "success": False,
                "error": "No Bedrock models available",
                "region": self.region,
            }

        except NoCredentialsError:
            return {
                "success": False,
                "error": "No AWS credentials found",
                "region": self.region,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "region": self.region,
            }

    async def get_embeddings(
        self, text: str, model_id: str = "amazon.titan-embed-text-v2:0"
    ) -> list[float]:
        """
        Get text embeddings using Titan Embeddings model

        Args:
            text: Text to embed
            model_id: Embedding model ID

        Returns:
            List of embedding floats
        """
        client = self._get_client()

        body = {"inputText": text}

        try:
            response = await asyncio.to_thread(
                client.invoke_model,
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            return response_body.get("embedding", [])

        except Exception as e:
            logger.error(f"Bedrock embeddings error: {e}")
            raise
