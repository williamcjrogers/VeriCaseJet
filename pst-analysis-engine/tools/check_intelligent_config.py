#!/usr/bin/env python3
"""
Quick verification script for the Intelligent Configuration API.

Usage:
    python tools/check_intelligent_config.py --url http://localhost:8010 --token YOUR_JWT

The script performs:
 1. Health check (`/health`)
 2. Authenticated POST to `/api/ai/intelligent-config` with a dry-run payload
    (expects a 200 or documented error response if AI providers are not configured)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://localhost:8010",
        help="Base URL of the VeriCase API (default: http://localhost:8010)",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Bearer token (JWT) for an authenticated VeriCase user",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds (default: 10)",
    )
    return parser.parse_args()


def pretty_status(ok: bool) -> str:
    return "✓" if ok else "✗"


def call_health(base_url: str, timeout: int) -> bool:
    try:
        response = requests.get(f"{base_url}/health", timeout=timeout)
        print(f"{pretty_status(response.ok)} GET /health -> {response.status_code}")
        if response.ok:
            print(f"  Response: {response.json()}")
        return response.ok
    except requests.RequestException as exc:
        print(f"{pretty_status(False)} GET /health failed: {exc}")
        return False


def call_intelligent_config(
    base_url: str,
    token: str,
    timeout: int,
) -> bool:
    payload: Dict[str, Any] = {
        "message": "Health check ping",
        "conversation_history": [
            {"role": "system", "content": "verification"},
            {"role": "user", "content": "Start intelligent configuration health check"},
        ],
        "current_step": "introduction",
        "configuration_data": {},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            f"{base_url}/api/ai/intelligent-config",
            data=json.dumps(payload),
            headers=headers,
            timeout=timeout,
        )
        ok = response.status_code == 200
        print(
            f"{pretty_status(ok)} POST /api/ai/intelligent-config "
            f"-> {response.status_code}"
        )
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            print(f"  Response: {body}")
        if not ok:
            print(
                "  NOTE: Non-200 responses may indicate missing AI keys or invalid tokens."
            )
        return ok
    except requests.RequestException as exc:
        print(f"{pretty_status(False)} POST intelligent-config failed: {exc}")
        return False


def main() -> int:
    args = parse_args()

    print("=== Intelligent Configuration Health Check ===")
    print(f"Base URL: {args.url}")

    health_ok = call_health(args.url, args.timeout)
    api_ok = call_intelligent_config(args.url, args.token, args.timeout)

    if health_ok and api_ok:
        print("\nOverall status: OK")
        return 0

    print("\nOverall status: FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())

