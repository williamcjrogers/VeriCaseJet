from __future__ import annotations

import logging
from typing import Any

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


async def send_slack_notification(channel: str, message: str) -> bool:
    """
    Send a Slack notification via incoming webhook.

    Returns True on success. If no webhook configured, returns False.
    """
    if not settings.SLACK_WEBHOOK_URL:
        return False

    payload: dict[str, Any] = {"text": message}
    if channel:
        payload["channel"] = channel

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                settings.SLACK_WEBHOOK_URL, json=payload
            ) as resp:
                if resp.status in (200, 204):
                    return True
                body = await resp.text()
                logger.warning(
                    "Slack webhook returned %s: %s", resp.status, body[:200]
                )
    except Exception as e:
        logger.warning("Slack notification failed: %s", e)

    return False

