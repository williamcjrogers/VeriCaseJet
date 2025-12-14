from __future__ import annotations

import argparse
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)


class HFError(RuntimeError):
    pass


class HFClient:
    def __init__(self, base_url: str, token: str, timeout_s: float = 30.0):
        if not token:
            raise HFError("Missing HUGGINGFACE_API_TOKEN")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def inference(self, model: str, payload: dict[str, Any]) -> Any:
        url = f"/models/{model}"
        resp = await self._client.post(url, json=payload)
        if resp.status_code == 401:
            raise HFError("Unauthorized (check HUGGINGFACE_API_TOKEN)")
        resp.raise_for_status()
        return resp.json()

    async def model_info(self, model: str) -> Any:
        resp = await self._client.get(f"https://huggingface.co/api/models/{model}")
        if resp.status_code == 401:
            raise HFError("Unauthorized (check HUGGINGFACE_API_TOKEN)")
        if resp.status_code == 404:
            raise HFError(f"Model not found: {model}")
        resp.raise_for_status()
        return resp.json()


@asynccontextmanager
async def _lifespan(_app: FastMCP):
    base_url = os.getenv("HUGGINGFACE_API_BASE", "https://api-inference.huggingface.co")
    token = os.getenv("HUGGINGFACE_API_TOKEN", "").strip()
    timeout_s = float(os.getenv("HUGGINGFACE_API_TIMEOUT_S", "30"))
    client = HFClient(base_url=base_url, token=token, timeout_s=timeout_s)
    try:
        yield {"hf": client}
    finally:
        await client.aclose()


def _hf(ctx: Context) -> HFClient:
    lifespan_ctx = ctx.request_context.lifespan_context
    client = lifespan_ctx.get("hf")
    if not isinstance(client, HFClient):
        raise HFError("MCP lifespan not initialized")
    return client


mcp = FastMCP(
    name="HuggingFace",
    instructions="Tools for Hugging Face Inference and metadata. Configure HUGGINGFACE_API_TOKEN.",
    lifespan=_lifespan,
)


@mcp.tool()
async def hf_text_generation(
    ctx: Context,
    prompt: str,
    model: str = "meta-llama/Llama-3.2-1B-Instruct",
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.95,
) -> Any:
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "top_p": top_p,
        },
        "options": {"wait_for_model": True},
    }
    return await _hf(ctx).inference(model, payload)


@mcp.tool()
async def hf_embeddings(
    ctx: Context,
    text: str,
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> Any:
    payload = {
        "inputs": text,
        "parameters": {"truncate": True},
        "options": {"wait_for_model": True},
    }
    return await _hf(ctx).inference(model, payload)


@mcp.tool()
async def hf_model_info(ctx: Context, model: str) -> Any:
    return await _hf(ctx).model_info(model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Hugging Face MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for SSE/HTTP transports")
    parser.add_argument("--port", type=int, default=8011, help="Port for SSE/HTTP transports")
    args = parser.parse_args()

    if args.transport != "stdio":
        mcp.settings.host = args.host  # type: ignore[attr-defined]
        mcp.settings.port = args.port  # type: ignore[attr-defined]

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
