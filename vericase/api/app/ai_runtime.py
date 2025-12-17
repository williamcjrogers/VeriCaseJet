"""
Unified provider runtime for chat completions.

All AI calls should route through `complete_chat` to keep provider
behavior, retries, and parameter handling consistent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import Session

from .ai_settings import get_ai_api_key, is_bedrock_enabled, get_bedrock_region
from .ai_providers import BedrockProvider, bedrock_available

logger = logging.getLogger(__name__)


def normalize_provider(provider: str) -> str:
    """Normalize provider names to canonical keys."""
    p = (provider or "").lower().strip()
    if p == "google":
        return "gemini"
    return p


def _is_o_series_model(model_id: str) -> bool:
    """Detect OpenAI o-series models that require max_completion_tokens."""
    mid = (model_id or "").lower()
    return mid.startswith(("o1", "o3", "o4", "o5"))


async def complete_chat(
    provider: str,
    model_id: str,
    prompt: str,
    system_prompt: str = "",
    *,
    db: Session | None = None,
    api_key: str | None = None,
    bedrock_provider: BedrockProvider | None = None,
    bedrock_region: str | None = None,
    max_tokens: int = 4000,
    temperature: float = 0.3,
) -> str:
    """
    Execute a chat-style completion against a provider/model.

    Args:
        provider: openai|anthropic|gemini|bedrock (google accepted as alias)
        model_id: provider-specific model ID
        prompt: user prompt
        system_prompt: optional system prompt
        db: optional DB session to fetch settings
        api_key: optional explicit API key for key-based providers
        bedrock_provider: optional BedrockProvider instance
        bedrock_region: optional AWS region for BedrockProvider
        max_tokens: max generation tokens
        temperature: sampling temperature where supported
    """
    provider_norm = normalize_provider(provider)

    if (
        provider_norm in {"openai", "anthropic", "gemini"}
        and api_key is None
        and db is not None
    ):
        api_key = get_ai_api_key(provider_norm, db) or ""

    if provider_norm == "openai":
        if not api_key:
            raise RuntimeError("OpenAI API key not configured")
        import openai  # local import

        client = openai.AsyncOpenAI(api_key=api_key)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        is_o_series = _is_o_series_model(model_id)
        if is_o_series:
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
        else:
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        return response.choices[0].message.content or ""

    if provider_norm == "anthropic":
        if not api_key:
            raise RuntimeError("Anthropic API key not configured")
        import anthropic  # local import
        import httpx  # local import

        def sync_call() -> str:
            http_client = httpx.Client(timeout=httpx.Timeout(60.0))
            try:
                client = anthropic.Anthropic(api_key=api_key, http_client=http_client)
                response = client.messages.create(
                    model=model_id,
                    max_tokens=max_tokens,
                    system=system_prompt or "You are a helpful assistant.",
                    messages=[{"role": "user", "content": prompt}],
                )
                text = ""
                for block in response.content:
                    piece = getattr(block, "text", "")
                    if piece:
                        text += str(piece)
                return text
            finally:
                http_client.close()

        return await asyncio.to_thread(sync_call)

    if provider_norm == "gemini":
        if not api_key:
            raise RuntimeError("Gemini API key not configured")
        import google.generativeai as genai  # pyright: ignore[reportMissingTypeStubs]

        configure_fn: Any = getattr(genai, "configure")
        generative_model_cls: Any = getattr(genai, "GenerativeModel")
        configure_fn(api_key=api_key)
        model: Any = generative_model_cls(model_id)
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response_obj: Any = await asyncio.to_thread(model.generate_content, full_prompt)
        return str(getattr(response_obj, "text", "") or "")

    if provider_norm == "bedrock":
        if bedrock_provider is None:
            if bedrock_region is None:
                bedrock_region = get_bedrock_region(db) if db is not None else None
            region = bedrock_region or "us-east-1"
            if db is not None and not is_bedrock_enabled(db):
                raise RuntimeError("Bedrock is disabled")
            if not bedrock_available():
                raise RuntimeError("Bedrock provider not available")
            bedrock_provider = BedrockProvider(region=region)

        return await bedrock_provider.invoke(
            model_id=model_id,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=system_prompt if system_prompt else None,
        )

    # xAI / Grok — OpenAI-compatible API
    if provider_norm in {"xai", "grok"}:
        if not api_key:
            raise RuntimeError("xAI (Grok) API key not configured")
        import openai  # local import

        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        is_o_series = _is_o_series_model(model_id)
        if is_o_series:
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_completion_tokens=max_tokens,
                temperature=temperature,
            )
        else:
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        return response.choices[0].message.content or ""

    # Perplexity Sonar — OpenAI-compatible API
    if provider_norm == "perplexity":
        if not api_key:
            raise RuntimeError("Perplexity API key not configured")
        import openai  # local import

        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai",
        )
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        is_o_series = _is_o_series_model(model_id)
        if is_o_series:
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_completion_tokens=max_tokens,
                temperature=temperature,
            )
        else:
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        return response.choices[0].message.content or ""

    raise ValueError(f"Unknown provider: {provider}")
