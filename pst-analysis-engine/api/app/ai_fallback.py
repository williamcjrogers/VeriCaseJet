"""
AI Fallback Chain - Automatic provider failover for resilient AI operations.

This module provides automatic failover when AI providers fail, trying
alternative providers in a configured order until one succeeds.

Supports 4 providers: OpenAI, Anthropic, Gemini, Amazon Bedrock
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class AllProvidersFailedError(Exception):
    """Raised when all providers in the fallback chain have failed."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"All AI providers failed: {'; '.join(errors)}")


@dataclass
class FallbackResult:
    """Result from a fallback chain execution."""

    response: str
    provider_used: str
    model_used: str
    attempts: int
    total_time_ms: int
    errors: list[str] = field(default_factory=list)


class AIFallbackChain:
    """
    Manages provider fallback with configurable chains.

    Usage:
        chain = AIFallbackChain()
        result = await chain.execute_with_fallback(
            function_name="quick_search",
            prompt="...",
            providers={"openai": openai_client, "anthropic": anthropic_client, ...},
            call_fn=async_call_function,
        )
    """

    # Default fallback chains - BEDROCK FIRST for cost optimization
    # Bedrock models are primary, external APIs are fallbacks only
    FALLBACK_CHAINS: dict[str, list[tuple[str, str]]] = {
        "quick_search": [
            ("bedrock", "amazon.nova-micro-v1:0"),      # Primary: fastest, cheapest
            ("bedrock", "amazon.nova-lite-v1:0"),       # Fallback 1
            ("anthropic", "claude-3-5-haiku-20241022"),  # External fallback
        ],
        "deep_analysis": [
            ("bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0"),  # Primary: Claude via Bedrock
            ("bedrock", "amazon.nova-pro-v1:0"),        # Fallback 1: Nova Pro
            ("anthropic", "claude-sonnet-4-20250514"),  # External fallback
        ],
        "narrative": [
            ("bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0"),  # Primary
            ("bedrock", "amazon.nova-pro-v1:0"),        # Fallback 1
            ("anthropic", "claude-sonnet-4-20250514"),  # External fallback
        ],
        "pattern_recognition": [
            ("bedrock", "amazon.nova-pro-v1:0"),        # Primary
            ("bedrock", "amazon.nova-lite-v1:0"),       # Fallback 1
            ("gemini", "gemini-2.0-flash"),             # External fallback
        ],
        "gap_analysis": [
            ("bedrock", "amazon.nova-pro-v1:0"),        # Primary
            ("bedrock", "amazon.nova-lite-v1:0"),       # Fallback 1
            ("anthropic", "claude-sonnet-4-20250514"),  # External fallback
        ],
        "chat": [
            ("bedrock", "amazon.nova-pro-v1:0"),        # Primary for copilot
            ("bedrock", "amazon.nova-lite-v1:0"),       # Fallback 1
            ("anthropic", "claude-sonnet-4-20250514"),  # External fallback
        ],
        "refinement": [
            ("bedrock", "amazon.nova-lite-v1:0"),       # Primary: cost-effective
            ("bedrock", "amazon.nova-micro-v1:0"),      # Fallback 1: fastest
            ("anthropic", "claude-3-5-haiku-20241022"),  # External fallback
        ],
    }

    def __init__(
        self,
        enabled: bool = True,
        log_attempts: bool = True,
        max_attempts: int | None = None,
    ):
        """
        Initialize the fallback chain.

        Args:
            enabled: Whether fallback is enabled. If False, only tries first available.
            log_attempts: Whether to log each attempt.
            max_attempts: Maximum number of providers to try (None = try all).
        """
        self.enabled = enabled
        self.log_attempts = log_attempts
        self.max_attempts = max_attempts

    def get_chain(self, function_name: str) -> list[tuple[str, str]]:
        """Get the fallback chain for a function, with default fallback."""
        return self.FALLBACK_CHAINS.get(
            function_name,
            self.FALLBACK_CHAINS.get("quick_search", []),
        )

    def is_provider_available(
        self,
        provider_name: str,
        available_providers: dict[str, Any],
    ) -> bool:
        """Check if a provider is configured and available."""
        provider = available_providers.get(provider_name)
        if provider is None:
            return False

        # For Bedrock, check if it's enabled (it's a boolean or object)
        if provider_name == "bedrock":
            if isinstance(provider, bool):
                return provider
            return provider is not None

        # For API-key based providers, check if key exists
        if isinstance(provider, str):
            return bool(provider)

        # For client objects, just check existence
        return provider is not None

    async def execute_with_fallback(
        self,
        function_name: str,
        prompt: str,
        available_providers: dict[str, Any],
        call_fn: Callable[[str, str, str], Awaitable[str]],
        system_prompt: str = "",
    ) -> FallbackResult:
        """
        Execute a prompt with automatic fallback on failure.

        Args:
            function_name: Name of the AI function (e.g., "quick_search", "deep_analysis")
            prompt: The prompt to send
            available_providers: Dict of provider name -> client/key/bool
            call_fn: Async function(provider, model, prompt) -> response
            system_prompt: Optional system prompt

        Returns:
            FallbackResult with response and metadata

        Raises:
            AllProvidersFailedError: If all providers fail
        """
        start_time = time.time()
        chain = self.get_chain(function_name)
        errors: list[str] = []
        attempts = 0
        max_to_try = self.max_attempts or len(chain)

        for provider_name, model in chain:
            if attempts >= max_to_try:
                break

            if not self.is_provider_available(provider_name, available_providers):
                if self.log_attempts:
                    logger.debug(
                        f"Fallback skip: {provider_name} not available for {function_name}"
                    )
                continue

            attempts += 1

            try:
                if self.log_attempts:
                    logger.info(
                        f"Fallback attempt {attempts}: {provider_name}/{model} for {function_name}"
                    )

                response = await call_fn(provider_name, model, prompt)

                elapsed_ms = int((time.time() - start_time) * 1000)

                if self.log_attempts:
                    logger.info(
                        f"Fallback success: {provider_name}/{model} in {elapsed_ms}ms"
                    )

                return FallbackResult(
                    response=response,
                    provider_used=provider_name,
                    model_used=model,
                    attempts=attempts,
                    total_time_ms=elapsed_ms,
                    errors=errors,
                )

            except Exception as e:
                error_msg = f"{provider_name}/{model}: {str(e)}"
                errors.append(error_msg)

                if self.log_attempts:
                    logger.warning(f"Fallback failed: {error_msg}")

                if not self.enabled:
                    # If fallback disabled, don't try other providers
                    break

                continue

        # All providers failed
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(
            f"All providers failed for {function_name} after {attempts} attempts ({elapsed_ms}ms)"
        )
        raise AllProvidersFailedError(errors)

    async def execute_single(
        self,
        provider_name: str,
        model: str,
        prompt: str,
        available_providers: dict[str, Any],
        call_fn: Callable[[str, str, str], Awaitable[str]],
    ) -> FallbackResult:
        """
        Execute with a specific provider (no fallback).

        Useful when you want to use a specific provider but still get
        the FallbackResult structure.
        """
        start_time = time.time()

        if not self.is_provider_available(provider_name, available_providers):
            raise AllProvidersFailedError([f"{provider_name} not available"])

        try:
            response = await call_fn(provider_name, model, prompt)
            elapsed_ms = int((time.time() - start_time) * 1000)

            return FallbackResult(
                response=response,
                provider_used=provider_name,
                model_used=model,
                attempts=1,
                total_time_ms=elapsed_ms,
                errors=[],
            )

        except Exception as e:
            raise AllProvidersFailedError([f"{provider_name}/{model}: {str(e)}"])


# Convenience function for simple usage
async def with_fallback(
    function_name: str,
    prompt: str,
    providers: dict[str, Any],
    call_fn: Callable[[str, str, str], Awaitable[str]],
    enabled: bool = True,
) -> FallbackResult:
    """
    Convenience function for executing with fallback.

    Example:
        result = await with_fallback(
            "quick_search",
            "What happened on March 15?",
            {"openai": api_key, "gemini": api_key, "bedrock": True},
            my_call_function,
        )
    """
    chain = AIFallbackChain(enabled=enabled)
    return await chain.execute_with_fallback(
        function_name=function_name,
        prompt=prompt,
        available_providers=providers,
        call_fn=call_fn,
    )
