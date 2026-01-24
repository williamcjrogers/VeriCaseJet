"""
Unified provider runtime for chat completions.

All AI calls should route through `complete_chat` to keep provider
behavior, retries, and parameter handling consistent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from .ai_settings import get_ai_api_key, is_bedrock_enabled, get_bedrock_region
from .ai_providers import BedrockProvider, bedrock_available
from .config import settings
from .ai_optimization import log_ai_event
from .trace_context import ensure_chain_id, get_trace_context

logger = logging.getLogger(__name__)


def normalize_provider(provider: str) -> str:
    """Normalize provider names to canonical keys."""
    p = (provider or "").lower().strip()
    if p == "google":
        return "gemini"
    return p


def _is_o_series_model(model_id: str) -> bool:
    """Detect models that require max_completion_tokens."""
    mid = (model_id or "").lower()
    return mid.startswith(("o1", "o3", "o4", "o5", "gpt-5"))


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_json(obj: Any) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


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
    user_id=None,
    function_name: str | None = None,
    task_type: str | None = None,
    chain_id: str | None = None,
    run_id: str | None = None,
    node: str | None = None,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
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
        user_id: optional user ID for optimization tracking
        function_name: optional function name for optimization tracking
        task_type: optional task type for optimization tracking
    """
    provider_norm = normalize_provider(provider)
    start_time = time.time()
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None
    success = False
    error_message = None
    result = ""

    trace = get_trace_context()
    effective_chain_id = ensure_chain_id(chain_id or trace.chain_id)
    effective_run_id = run_id or trace.run_id
    effective_node = node or trace.node or function_name or task_type
    effective_input_refs = input_refs if input_refs is not None else trace.input_refs
    effective_output_refs = (
        output_refs if output_refs is not None else trace.output_refs
    )

    prompt_hash = _sha256_hex(
        _stable_json(
            {
                "provider": provider_norm,
                "model_id": model_id,
                "system_prompt": system_prompt,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
    )

    if (
        provider_norm in {"openai", "anthropic", "gemini"}
        and api_key is None
        and db is not None
    ):
        api_key = get_ai_api_key(provider_norm, db) or ""

    try:
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
            result = response.choices[0].message.content or ""
            if hasattr(response, "usage") and response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens
            success = True
            return result

        if provider_norm == "anthropic":
            if not api_key:
                raise RuntimeError("Anthropic API key not configured")
            import anthropic  # local import
            import httpx  # local import

            def sync_call() -> tuple[str, int | None, int | None, int | None]:
                http_client = httpx.Client(timeout=httpx.Timeout(60.0))
                try:
                    client = anthropic.Anthropic(
                        api_key=api_key, http_client=http_client
                    )
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
                    p_tokens = (
                        getattr(response.usage, "input_tokens", None)
                        if hasattr(response, "usage")
                        else None
                    )
                    c_tokens = (
                        getattr(response.usage, "output_tokens", None)
                        if hasattr(response, "usage")
                        else None
                    )
                    t_tokens = (
                        (p_tokens + c_tokens) if (p_tokens and c_tokens) else None
                    )
                    return text, p_tokens, c_tokens, t_tokens
                finally:
                    http_client.close()

            result, prompt_tokens, completion_tokens, total_tokens = (
                await asyncio.to_thread(sync_call)
            )
            success = True
            return result

        if provider_norm == "gemini":
            if not api_key:
                raise RuntimeError("Gemini API key not configured")
            import google.generativeai as genai  # pyright: ignore[reportMissingTypeStubs]

            configure_fn: Any = getattr(genai, "configure")
            generative_model_cls: Any = getattr(genai, "GenerativeModel")
            configure_fn(api_key=api_key)
            model: Any = generative_model_cls(model_id)
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response_obj: Any = await asyncio.to_thread(
                model.generate_content, full_prompt
            )
            result = str(getattr(response_obj, "text", "") or "")
            # Gemini may expose usage metadata
            if hasattr(response_obj, "usage_metadata"):
                usage = response_obj.usage_metadata
                prompt_tokens = getattr(usage, "prompt_token_count", None)
                completion_tokens = getattr(usage, "candidates_token_count", None)
                total_tokens = getattr(usage, "total_token_count", None)
            success = True
            return result

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

            guardrail_id = (settings.BEDROCK_GUARDRAIL_ID or "").strip()
            guardrail_version = (settings.BEDROCK_GUARDRAIL_VERSION or "").strip()
            use_guardrails = bool(
                getattr(settings, "BEDROCK_GUARDRAILS_ENABLED", False)
                and guardrail_id
                and guardrail_version
            )

            result = await bedrock_provider.invoke(
                model_id=model_id,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt if system_prompt else None,
                guardrail_identifier=guardrail_id if use_guardrails else None,
                guardrail_version=guardrail_version if use_guardrails else None,
            )
            success = True
            return result

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
            result = response.choices[0].message.content or ""
            if hasattr(response, "usage") and response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens
            success = True
            return result

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
            result = response.choices[0].message.content or ""
            if hasattr(response, "usage") and response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens
            success = True
            return result

        raise ValueError(f"Unknown provider: {provider}")
    except Exception as e:
        error_message = str(e)
        success = False
        raise
    finally:
        # Log the AI event
        response_time_ms = int((time.time() - start_time) * 1000)
        response_hash = (
            _sha256_hex(result.encode("utf-8")) if result and success else None
        )
        envelope = {
            "chain_id": effective_chain_id,
            "run_id": effective_run_id,
            "node": effective_node,
            "prompt_hash": f"sha256:{prompt_hash}",
            "response_hash": f"sha256:{response_hash}" if response_hash else None,
            "input_refs": effective_input_refs or [],
            "output_refs": effective_output_refs or [],
            "prompt_chars": len(prompt or ""),
            "system_prompt_chars": len(system_prompt or ""),
        }

        combined_meta: dict[str, Any] = dict(metadata or {})
        combined_meta.update(envelope)

        db_for_log = db
        created_session = None
        if db_for_log is None:
            try:
                from .db import SessionLocal

                created_session = SessionLocal()
                db_for_log = created_session
            except Exception as e:
                logger.warning("AI event logging disabled (db unavailable): %s", e)
                db_for_log = None

        if db_for_log is not None:
            log_ai_event(
                db=db_for_log,
                provider=provider_norm,
                model_id=model_id,
                response_time_ms=response_time_ms,
                success=success,
                user_id=user_id,
                function_name=function_name,
                task_type=task_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error_message=error_message,
                metadata=combined_meta,
            )

        if created_session is not None:
            try:
                created_session.close()
            except Exception:
                pass
