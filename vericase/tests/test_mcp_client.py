import sys
from pathlib import Path

import pytest
import httpx

# Add the vericase project root to the path (so `import api.app...` works)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api.app.mcp.client import VeriCaseAPIClient, VeriCaseAPIConfig, VeriCaseAPIError


@pytest.mark.asyncio
async def test_client_retries_on_503_then_succeeds():
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    cfg = VeriCaseAPIConfig(
        base_url="http://test",
        token="t",
        timeout_s=1.0,
        max_retries=1,
        max_connections=2,
        max_keepalive_connections=1,
    )

    async with httpx.AsyncClient(base_url=cfg.base_url, transport=transport) as http:
        client = VeriCaseAPIClient(cfg, client=http)
        result = await client.get_json("/api/evidence/items")

    assert result == {"ok": True}
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_client_raises_on_unauthorized():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unauthorized"})

    transport = httpx.MockTransport(handler)

    cfg = VeriCaseAPIConfig(
        base_url="http://test",
        token="t",
        timeout_s=1.0,
        max_retries=0,
        max_connections=2,
        max_keepalive_connections=1,
    )

    async with httpx.AsyncClient(base_url=cfg.base_url, transport=transport) as http:
        client = VeriCaseAPIClient(cfg, client=http)
        with pytest.raises(VeriCaseAPIError):
            await client.get_json("/api/evidence/items")
