from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from typing import Any

import httpx


class VeriCaseAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class VeriCaseAPIConfig:
    base_url: str
    token: str
    timeout_s: float = 30.0
    max_retries: int = 3
    max_connections: int = 20
    max_keepalive_connections: int = 10

    @staticmethod
    def from_env() -> "VeriCaseAPIConfig":
        base_url = os.getenv("VERICASE_API_BASE_URL", "http://localhost:8010")
        token = os.getenv("VERICASE_API_TOKEN", "").strip()
        if not token:
            raise VeriCaseAPIError(
                "Missing VERICASE_API_TOKEN (Bearer token required for VeriCase API)."
            )

        timeout_s = float(os.getenv("VERICASE_API_TIMEOUT_S", "30"))
        max_retries = int(os.getenv("VERICASE_API_MAX_RETRIES", "3"))
        max_connections = int(os.getenv("VERICASE_API_MAX_CONNECTIONS", "20"))
        max_keepalive_connections = int(
            os.getenv("VERICASE_API_MAX_KEEPALIVE_CONNECTIONS", "10")
        )

        return VeriCaseAPIConfig(
            base_url=base_url.rstrip("/"),
            token=token,
            timeout_s=timeout_s,
            max_retries=max_retries,
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )


class VeriCaseAPIClient:
    def __init__(
        self, config: VeriCaseAPIConfig, *, client: httpx.AsyncClient | None = None
    ):
        self._config = config
        self._owned_client = client is None

        if client is None:
            timeout = httpx.Timeout(
                timeout=config.timeout_s,
                connect=min(5.0, config.timeout_s),
                read=config.timeout_s,
                write=config.timeout_s,
                pool=min(5.0, config.timeout_s),
            )
            limits = httpx.Limits(
                max_connections=config.max_connections,
                max_keepalive_connections=config.max_keepalive_connections,
                keepalive_expiry=30.0,
            )
            headers = {
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/json",
                "User-Agent": "vericase-mcp/1",
            }
            client = httpx.AsyncClient(
                base_url=config.base_url,
                timeout=timeout,
                limits=limits,
                headers=headers,
                follow_redirects=True,
            )

        self._client = client

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return await self._request_json("GET", path, params=params)

    async def post_json(
        self,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request_json(
            "POST", path, json_body=json_body, params=params
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        path_norm = path if path.startswith("/") else f"/{path}"

        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                resp = await self._client.request(
                    method,
                    path_norm,
                    params=params,
                    json=json_body,
                )

                if (
                    resp.status_code in (429, 502, 503, 504)
                    and attempt < self._config.max_retries
                ):
                    await self._sleep_backoff(resp, attempt)
                    continue

                if resp.status_code == 401:
                    raise VeriCaseAPIError("Unauthorized (check VERICASE_API_TOKEN)")

                resp.raise_for_status()

                if not resp.content:
                    return None
                return resp.json()

            except (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
            ) as e:
                last_exc = e
                if attempt >= self._config.max_retries:
                    break
                await self._sleep_backoff(None, attempt)
            except httpx.HTTPStatusError as e:
                # Non-retryable status (or out of retries)
                detail = None
                try:
                    detail = e.response.json()
                except Exception:
                    detail = e.response.text
                raise VeriCaseAPIError(
                    f"VeriCase API error {e.response.status_code}: {detail}"
                ) from e

        raise VeriCaseAPIError(f"VeriCase API request failed: {last_exc}")

    async def _sleep_backoff(
        self, response: httpx.Response | None, attempt: int
    ) -> None:
        retry_after_s: float | None = None
        if response is not None:
            ra = response.headers.get("retry-after")
            if ra:
                try:
                    retry_after_s = float(ra)
                except ValueError:
                    retry_after_s = None

        base = 0.25 * (2**attempt)
        jitter = random.random() * 0.25
        delay = min(2.0, base + jitter)
        if retry_after_s is not None:
            delay = max(delay, retry_after_s)

        await asyncio.sleep(delay)
