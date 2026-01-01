from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import timezone
from email.message import Message
from email.parser import HeaderParser
from email.policy import default as default_policy
from email.utils import parsedate_to_datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedReceivedHop:
    index: int
    raw: str
    date: str | None
    parsed_ok: bool
    received_from: str | None = None
    received_by: str | None = None
    received_with: str | None = None
    received_id: str | None = None
    received_for: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "raw": self.raw,
            "date": self.date,
            "parsed_ok": self.parsed_ok,
            "from": self.received_from,
            "by": self.received_by,
            "with": self.received_with,
            "id": self.received_id,
            "for": self.received_for,
        }


def decode_header_blob(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("utf-8", errors="replace")
    text = str(value)
    return text if text else None


def sha256_text(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_rfc822_headers(raw_headers: str | None) -> Message | None:
    if not raw_headers:
        return None
    try:
        parser = HeaderParser(policy=default_policy)
        return parser.parsestr(raw_headers)
    except Exception as exc:
        logger.debug("Failed to parse RFC822 headers: %s", exc)
        return None


def get_header_first(msg: Message | None, name: str) -> str | None:
    if msg is None:
        return None
    value = msg.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def get_header_all(msg: Message | None, name: str) -> list[str]:
    if msg is None:
        return []
    values = msg.get_all(name, [])
    cleaned: list[str] = []
    for v in values:
        if v is None:
            continue
        text = str(v).strip()
        if text:
            cleaned.append(text)
    return cleaned


_RECEIVED_TOKEN_RE = re.compile(
    r"(?is)\b(from|by|with|id|for)\b\s+([^;]+?)(?=\bfrom\b|\bby\b|\bwith\b|\bid\b|\bfor\b|;|$)"
)


def parse_date_header(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def parse_received_headers(received_values: list[str]) -> list[ParsedReceivedHop]:
    hops: list[ParsedReceivedHop] = []
    for idx, raw in enumerate(received_values):
        unfolded = re.sub(r"\s+", " ", raw).strip()
        parts = unfolded.split(";", 1)
        route = parts[0].strip() if parts else unfolded
        date_raw = parts[1].strip() if len(parts) > 1 else None
        parsed_date = parse_date_header(date_raw)
        tokens = {k.lower(): v.strip() for k, v in _RECEIVED_TOKEN_RE.findall(route)}
        hop = ParsedReceivedHop(
            index=idx,
            raw=unfolded,
            date=parsed_date,
            parsed_ok=bool(parsed_date),
            received_from=tokens.get("from"),
            received_by=tokens.get("by"),
            received_with=tokens.get("with"),
            received_id=tokens.get("id"),
            received_for=tokens.get("for"),
        )
        hops.append(hop)
    return hops


def received_time_bounds(
    hops: list[ParsedReceivedHop],
) -> tuple[str | None, str | None]:
    dates: list[str] = [h.date for h in hops if h.date]
    if not dates:
        return None, None
    # ISO-8601 sort works with uniform tz offsets; we normalize via parse_date_header.
    return min(dates), max(dates)
