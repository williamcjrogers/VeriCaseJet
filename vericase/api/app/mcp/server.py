from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP

from .client import VeriCaseAPIClient, VeriCaseAPIConfig, VeriCaseAPIError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastMCP):
    client = VeriCaseAPIClient(VeriCaseAPIConfig.from_env())
    try:
        yield {"api": client}
    finally:
        await client.aclose()


mcp = FastMCP(
    name="VeriCase",
    instructions=(
        "Tools for interacting with the VeriCase API (read-only). "
        "Configure VERICASE_API_BASE_URL and VERICASE_API_TOKEN."
    ),
    lifespan=_lifespan,
)


def _api(ctx: Context) -> VeriCaseAPIClient:
    lifespan_ctx = ctx.request_context.lifespan_context
    client = lifespan_ctx.get("api")
    if not isinstance(client, VeriCaseAPIClient):
        raise VeriCaseAPIError("MCP lifespan not initialized")
    return client


@mcp.tool()
async def evidence_list(
    ctx: Context,
    page: int = 1,
    page_size: int = 50,
    case_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    """List evidence items (paginated)."""

    params: dict[str, object] = {
        "page": page,
        "page_size": page_size,
    }
    if case_id:
        params["case_id"] = case_id
    if project_id:
        params["project_id"] = project_id

    return await _api(ctx).get_json("/api/evidence/items", params=params)


@mcp.tool()
async def evidence_get(ctx: Context, evidence_id: str) -> dict:
    """Get full evidence item details by ID."""

    return await _api(ctx).get_json(f"/api/evidence/items/{evidence_id}")


@mcp.tool()
async def evidence_text_content(ctx: Context, evidence_id: str) -> dict:
    """Fetch extracted text content for an evidence item."""

    return await _api(ctx).get_json(f"/api/evidence/items/{evidence_id}/text-content")


@mcp.tool()
async def evidence_download_url(ctx: Context, evidence_id: str) -> dict:
    """Get a presigned download URL for an evidence item."""

    return await _api(ctx).get_json(f"/api/evidence/items/{evidence_id}/download-url")


def main() -> None:
    parser = argparse.ArgumentParser(description="VeriCase MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport to use",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE/HTTP transports",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port for SSE/HTTP transports",
    )
    args = parser.parse_args()

    # For stdio transport, host/port are unused.
    if args.transport != "stdio":
        mcp.settings.host = args.host  # type: ignore[attr-defined]
        mcp.settings.port = args.port  # type: ignore[attr-defined]

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
