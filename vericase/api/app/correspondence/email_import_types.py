from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    data: bytes
    is_inline: bool
    content_id: str | None


@dataclass
class ParsedEmail:
    subject: str | None
    sender_email: str | None
    sender_name: str | None
    recipients_to: list[str] | None
    recipients_cc: list[str] | None
    recipients_bcc: list[str] | None
    recipients_display: dict[str, str] | None
    date_sent: datetime | None
    date_received: datetime | None
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    body_plain: str | None
    body_html: str | None
    body_rtf: str | None
    attachments: list[ParsedAttachment]
    raw_headers: dict[str, str]
    thread_group_id: str | None = None
    thread_position: int | None = None
    thread_path: str | None = None
