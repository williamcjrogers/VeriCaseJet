from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

LEX_OPERATIONS = [
    "search_for_legislation_sections",
    "search_for_legislation_acts",
    "lookup_legislation",
    "get_legislation_sections",
    "get_legislation_full_text",
    "proxy_legislation_data",
    "search_for_caselaw",
    "search_for_caselaw_section",
    "search_for_caselaw_by_reference",
    "search_caselaw_by_reference",
    "search_caselaw_summaries",
    "proxy_caselaw_data",
    "search_explanatory_note",
    "get_explanatory_note_by_legislation",
    "get_explanatory_note_by_section",
    "search_amendments",
    "search_amendment_sections",
    "get_live_stats_api_stats_get",
    "health_check_healthcheck_get",
]


class LexAPIError(RuntimeError):
    pass


def _build_default_operation_map() -> dict[str, dict[str, str]]:
    return {
        "search_for_legislation_sections": {
            "method": "POST",
            "path": "/legislation/section/search",
        },
        "search_for_legislation_acts": {
            "method": "POST",
            "path": "/legislation/search",
        },
        "lookup_legislation": {
            "method": "POST",
            "path": "/legislation/lookup",
        },
        "get_legislation_sections": {
            "method": "POST",
            "path": "/legislation/section/lookup",
        },
        "get_legislation_full_text": {
            "method": "POST",
            "path": "/legislation/text",
        },
        "proxy_legislation_data": {
            "method": "GET",
            "path": "/legislation/proxy/{legislation_id}",
        },
        "search_for_caselaw": {
            "method": "POST",
            "path": "/caselaw/search",
        },
        "search_for_caselaw_section": {
            "method": "POST",
            "path": "/caselaw/section/search",
        },
        "search_for_caselaw_by_reference": {
            "method": "POST",
            "path": "/caselaw/reference/search",
        },
        "search_caselaw_by_reference": {
            "method": "POST",
            "path": "/caselaw/reference",
        },
        "search_caselaw_summaries": {
            "method": "POST",
            "path": "/caselaw/summary/search",
        },
        "proxy_caselaw_data": {
            "method": "GET",
            "path": "/caselaw/proxy/{case_id}",
        },
        "search_explanatory_note": {
            "method": "POST",
            "path": "/explanatory_note/section/search",
        },
        "get_explanatory_note_by_legislation": {
            "method": "POST",
            "path": "/explanatory_note/legislation/lookup",
        },
        "get_explanatory_note_by_section": {
            "method": "POST",
            "path": "/explanatory_note/section/lookup",
        },
        "search_amendments": {
            "method": "POST",
            "path": "/amendment/search",
        },
        "search_amendment_sections": {
            "method": "POST",
            "path": "/amendment/section/search",
        },
        "get_live_stats_api_stats_get": {
            "method": "GET",
            "path": "/api/stats",
        },
        "health_check_healthcheck_get": {
            "method": "GET",
            "path": "/healthcheck",
        },
    }


def _build_auth_headers() -> dict[str, str]:
    token = settings.LEX_API_TOKEN.strip()
    if not token:
        return {}

    header = settings.LEX_API_AUTH_HEADER or "Authorization"
    scheme = settings.LEX_API_AUTH_SCHEME or ""
    value = f"{scheme} {token}".strip() if scheme else token
    return {header: value}


def _load_operation_map() -> dict[str, dict[str, str]]:
    mapping = _build_default_operation_map()
    raw = settings.LEX_API_OPERATION_MAP
    if not raw:
        return mapping

    try:
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("Invalid LEX_API_OPERATION_MAP JSON: %s", exc)
        return mapping

    if not isinstance(data, dict):
        logger.warning("LEX_API_OPERATION_MAP must be a JSON object")
        return mapping

    for operation, spec in data.items():
        if operation not in LEX_OPERATIONS:
            logger.warning("Ignoring unknown Lex operation override: %s", operation)
            continue

        if isinstance(spec, str):
            mapping[operation] = {
                "method": mapping.get(operation, {}).get("method", "POST"),
                "path": spec,
            }
            continue

        if isinstance(spec, dict):
            path = spec.get("path") or spec.get("url")
            if not path:
                logger.warning("Lex override missing path for %s", operation)
                continue
            method = str(
                spec.get("method") or mapping.get(operation, {}).get("method", "POST")
            ).upper()
            mapping[operation] = {"method": method, "path": str(path)}
            continue

        logger.warning("Invalid Lex override for %s", operation)

    return mapping


class LexAPIClient:
    def __init__(self):
        self.base_url = settings.LEX_API_BASE_URL.rstrip("/")
        self.timeout_s = settings.LEX_API_TIMEOUT_S or 20.0
        self.headers = _build_auth_headers()
        self.operation_map = _load_operation_map()
        if self.base_url.endswith("/mcp"):
            logger.warning(
                "LEX_API_BASE_URL points at the MCP endpoint; use the REST base URL instead."
            )

    async def request(
        self,
        operation: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if operation not in LEX_OPERATIONS:
            raise LexAPIError(f"Unsupported Lex operation: {operation}")
        if not self.base_url:
            raise LexAPIError("LEX_API_BASE_URL not configured")

        spec = self.operation_map[operation]
        method = spec["method"].upper()
        path, params, json_body = self._format_path(
            spec["path"], params=params, json_body=json_body
        )
        if not path.startswith("/"):
            path = f"/{path}"

        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(
            timeout=self.timeout_s, headers=self.headers
        ) as client:
            resp = await client.request(
                method,
                url,
                params=params or None,
                json=json_body,
            )

        if resp.status_code == 401:
            raise LexAPIError("Lex API unauthorized (check LEX_API_TOKEN)")

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = None
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise LexAPIError(f"Lex API error {resp.status_code}: {detail}") from exc

        if not resp.content:
            return None

        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    def _format_path(
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        if "{" not in path:
            return path, params, json_body

        params = dict(params or {})
        body = dict(json_body or {}) if json_body is not None else None
        for name in re.findall(r"{([^}]+)}", path):
            value = params.pop(name, None)
            if value is None and body is not None:
                value = body.pop(name, None)
            if value is None:
                raise LexAPIError(f"Missing path parameter: {name}")
            path = path.replace(f"{{{name}}}", str(value))

        return path, (params or None), (body or None)


lex_client = LexAPIClient()
