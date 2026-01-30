from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from ..forensic_integrity import sha256_hex_text
from .email_import_types import ParsedAttachment, ParsedEmail


_LINE_PREFIX_ANDROID = re.compile(
    r"^(?P<date>\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4}),\s+"
    r"(?P<time>\d{1,2}:\d{2})(?::(?P<sec>\d{2}))?\s*"
    r"(?P<ampm>AM|PM|am|pm)?\s*-\s*(?P<rest>.*)$"
)
_LINE_PREFIX_IOS = re.compile(
    r"^\[(?P<date>\d{1,2}[\/\.-]\d{1,2}[\/\.-]\d{2,4}),\s+"
    r"(?P<time>\d{1,2}:\d{2})(?::(?P<sec>\d{2}))?\s*"
    r"(?P<ampm>AM|PM|am|pm)?\]\s*(?P<rest>.*)$"
)

_FILENAME_HINT = re.compile(r"(?i)^whatsapp chat with (.+)$")

_MEDIA_EXTS = {
    "jpg",
    "jpeg",
    "png",
    "gif",
    "bmp",
    "webp",
    "heic",
    "mp4",
    "mov",
    "m4v",
    "avi",
    "mkv",
    "webm",
    "mp3",
    "wav",
    "m4a",
    "aac",
    "flac",
    "ogg",
    "opus",
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "vcf",
    "zip",
}

_ATTACHMENT_NAME_RE = re.compile(
    r"(?i)\b([A-Za-z0-9][A-Za-z0-9 _().-]{0,200}\.(?:"
    + "|".join(sorted(_MEDIA_EXTS))
    + r"))\b"
)


@dataclass
class WhatsAppParseResult:
    messages: list[ParsedEmail]
    chat_name: str | None
    export_format: str | None
    stats: dict[str, Any]
    unmatched_media: list[str]


def _strip_bom_and_marks(text: str) -> str:
    return text.lstrip("\ufeff\u200e\u200f")


def _infer_chat_name(filename: str | None) -> str | None:
    if not filename:
        return None
    base = os.path.splitext(os.path.basename(filename))[0].strip()
    match = _FILENAME_HINT.match(base)
    if match:
        return match.group(1).strip() or base
    return base or None


def _normalize_sender(sender: str) -> tuple[str | None, str | None]:
    raw = (sender or "").strip()
    if not raw:
        return None, None

    # Detect phone-like senders
    digits = re.sub(r"[^\d+]", "", raw)
    digit_count = len(re.sub(r"\D", "", digits))
    if digits.startswith("+") and digit_count >= 6:
        return f"{digits}@whatsapp.local", raw
    if digit_count >= 8:
        return f"{digits}@whatsapp.local", raw

    safe = re.sub(r"[^A-Za-z0-9._+-]+", "", raw.lower()).strip(".")
    if not safe:
        return None, raw
    return f"{safe}@whatsapp.local", raw


def _parse_date_time(
    date_str: str,
    time_str: str,
    ampm: str | None,
    *,
    default_order: str = "DMY",
) -> tuple[datetime | None, str]:
    order_used = default_order
    try:
        parts = re.split(r"[\/\.-]", date_str)
        if len(parts) != 3:
            raise ValueError("Invalid date")
        a, b, c = (p.strip() for p in parts)
        day = int(a)
        month = int(b)
        year = int(c)
        if year < 100:
            year += 2000

        # Resolve day/month order
        if day > 12 and month <= 12:
            order_used = "DMY"
        elif month > 12 and day <= 12:
            order_used = "MDY"
            day, month = month, day
        else:
            if default_order.upper() == "MDY":
                order_used = "MDY"
                day, month = month, day

        hh, mm = (int(x) for x in time_str.split(":"))
        ss = 0
        if ":" in time_str:
            parts_time = time_str.split(":")
            if len(parts_time) == 3:
                ss = int(parts_time[2])
        if ampm:
            ampm_norm = ampm.strip().lower()
            if ampm_norm == "pm" and hh < 12:
                hh += 12
            if ampm_norm == "am" and hh == 12:
                hh = 0

        dt = datetime(year, month, day, hh, mm, ss, tzinfo=timezone.utc)
        return dt, order_used
    except Exception:
        return None, order_used


def _build_message_id(
    *,
    source_file_sha256: str,
    chat_name: str | None,
    raw_line_no: int,
    timestamp: datetime | None,
    sender: str | None,
    body: str | None,
) -> str:
    body_hash = sha256_hex_text((body or "").strip())
    ts = timestamp.isoformat() if timestamp else ""
    key = "|".join(
        [
            source_file_sha256 or "",
            chat_name or "",
            str(raw_line_no),
            ts,
            sender or "",
            body_hash,
        ]
    )
    return f"whatsapp-{sha256_hex_text(key)[:16]}@whatsapp.local"


def _parse_whatsapp_text(
    text: str,
    *,
    filename: str | None,
    source_file_sha256: str,
    default_date_order: str = "DMY",
    max_messages: int | None = None,
) -> WhatsAppParseResult:
    chat_name = _infer_chat_name(filename)
    lines = text.splitlines()

    messages: list[ParsedEmail] = []
    export_format: str | None = None
    system_skipped = 0
    multi_line = 0

    current: dict[str, Any] | None = None
    previous_message_id: str | None = None
    thread_group_id = None
    if chat_name:
        thread_group_id = f"whatsapp_{sha256_hex_text(chat_name)[:12]}"

    for idx, raw_line in enumerate(lines, start=1):
        line = _strip_bom_and_marks(raw_line or "")
        if not line:
            if current is not None:
                current["body"] = (current.get("body") or "") + "\n"
            continue

        match = _LINE_PREFIX_ANDROID.match(line) or _LINE_PREFIX_IOS.match(line)
        if match:
            if current is not None:
                messages.append(current)
                current = None

            export_format = (
                "ios" if _LINE_PREFIX_IOS.match(line) else "android"
            )

            date_str = match.group("date")
            time_str = match.group("time")
            ampm = match.group("ampm")
            rest = (match.group("rest") or "").strip()

            if ": " in rest:
                sender, body = rest.split(": ", 1)
            else:
                # System messages have no sender delimiter
                system_skipped += 1
                continue

            sender = sender.strip()
            body = body.strip()

            dt, order_used = _parse_date_time(
                date_str, time_str, ampm, default_order=default_date_order
            )

            current = {
                "raw_line_no": idx,
                "sender": sender,
                "body": body,
                "datetime": dt,
                "date_order": order_used,
            }
        else:
            if current is None:
                continue
            current["body"] = (current.get("body") or "") + "\n" + raw_line
            multi_line += 1

    if current is not None:
        messages.append(current)

    parsed_messages: list[ParsedEmail] = []
    for seq, msg in enumerate(messages, start=1):
        if max_messages and seq > max_messages:
            break
        sender_email, sender_name = _normalize_sender(msg.get("sender") or "")
        body = (msg.get("body") or "").strip()
        date_sent = msg.get("datetime")
        message_id = _build_message_id(
            source_file_sha256=source_file_sha256,
            chat_name=chat_name,
            raw_line_no=int(msg.get("raw_line_no") or 0),
            timestamp=date_sent,
            sender=msg.get("sender"),
            body=body,
        )

        parsed_messages.append(
            ParsedEmail(
                subject=f"WhatsApp: {chat_name}" if chat_name else "WhatsApp Chat",
                sender_email=sender_email,
                sender_name=sender_name,
                recipients_to=None,
                recipients_cc=None,
                recipients_bcc=None,
                recipients_display=None,
                date_sent=date_sent,
                date_received=None,
                message_id=message_id,
                in_reply_to=previous_message_id,
                references=previous_message_id,
                body_plain=body or None,
                body_html=None,
                body_rtf=None,
                attachments=[],
                raw_headers={
                    "whatsapp_raw_line_no": str(msg.get("raw_line_no") or ""),
                    "whatsapp_date_order": msg.get("date_order") or "",
                    "whatsapp_export_format": export_format or "",
                    "whatsapp_chat_name": chat_name or "",
                },
                thread_group_id=thread_group_id,
                thread_position=seq,
            )
        )
        previous_message_id = message_id

    stats = {
        "lines_total": len(lines),
        "messages_parsed": len(parsed_messages),
        "system_skipped": system_skipped,
        "multiline_continuations": multi_line,
    }

    return WhatsAppParseResult(
        messages=parsed_messages,
        chat_name=chat_name,
        export_format=export_format,
        stats=stats,
        unmatched_media=[],
    )


def parse_whatsapp_bytes(
    raw: bytes,
    *,
    filename: str | None,
    source_file_sha256: str,
    default_date_order: str = "DMY",
    max_messages: int | None = None,
) -> WhatsAppParseResult:
    if not raw:
        raise HTTPException(status_code=400, detail="Empty WhatsApp export")
    try:
        text = raw.decode("utf-8")
    except Exception:
        text = raw.decode("utf-8", errors="replace")

    result = _parse_whatsapp_text(
        text,
        filename=filename,
        source_file_sha256=source_file_sha256,
        default_date_order=default_date_order,
        max_messages=max_messages,
    )

    if not result.messages:
        raise HTTPException(
            status_code=400, detail="Text file does not match WhatsApp export format"
        )
    return result


def parse_whatsapp_zip_bytes(
    raw: bytes,
    *,
    filename: str | None,
    source_file_sha256: str,
    default_date_order: str = "DMY",
    max_messages: int | None = None,
    max_files: int = 2000,
    max_uncompressed_bytes: int = 1024 * 1024 * 500,
    max_ratio: float = 200.0,
) -> WhatsAppParseResult:
    if not raw:
        raise HTTPException(status_code=400, detail="Empty WhatsApp zip")

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid zip: {exc}") from exc

    infos = zf.infolist()
    if len(infos) > max_files:
        raise HTTPException(
            status_code=400,
            detail=f"Zip contains too many files ({len(infos)} > {max_files})",
        )

    total_uncompressed = 0
    chat_files: list[zipfile.ZipInfo] = []
    media_files: dict[str, zipfile.ZipInfo] = {}

    for info in infos:
        name = info.filename or ""
        norm = name.replace("\\", "/").lstrip("/")
        if not norm or ".." in norm:
            raise HTTPException(status_code=400, detail="Unsafe zip path detected")

        total_uncompressed += int(info.file_size or 0)
        if total_uncompressed > max_uncompressed_bytes:
            raise HTTPException(status_code=400, detail="Zip is too large to process")

        if info.compress_size and info.file_size:
            ratio = float(info.file_size) / max(1, info.compress_size)
            if ratio > max_ratio:
                raise HTTPException(
                    status_code=400,
                    detail="Zip compression ratio is suspicious (possible zip bomb)",
                )

        if norm.lower().endswith(".txt"):
            chat_files.append(info)
        else:
            base = os.path.basename(norm).lower()
            if base:
                media_files[base] = info

    if not chat_files:
        raise HTTPException(status_code=400, detail="No chat .txt found in zip")

    all_messages: list[ParsedEmail] = []
    unmatched_media = set(media_files.keys())
    export_format: str | None = None
    chat_name: str | None = None
    stats: dict[str, Any] = {
        "chat_files": len(chat_files),
        "media_files": len(media_files),
        "messages_parsed": 0,
        "system_skipped": 0,
        "multiline_continuations": 0,
    }

    for chat_info in chat_files:
        with zf.open(chat_info, "r") as handle:
            chat_raw = handle.read()

        sub_filename = chat_info.filename
        parsed = parse_whatsapp_bytes(
            chat_raw,
            filename=sub_filename,
            source_file_sha256=source_file_sha256,
            default_date_order=default_date_order,
            max_messages=max_messages,
        )

        export_format = export_format or parsed.export_format
        chat_name = chat_name or parsed.chat_name
        stats["messages_parsed"] += parsed.stats.get("messages_parsed", 0)
        stats["system_skipped"] += parsed.stats.get("system_skipped", 0)
        stats["multiline_continuations"] += parsed.stats.get(
            "multiline_continuations", 0
        )

        for message in parsed.messages:
            body = message.body_plain or ""
            matches = _ATTACHMENT_NAME_RE.findall(body)
            attachments: list[ParsedAttachment] = []
            for fname in matches:
                base = os.path.basename(fname).lower()
                info = media_files.get(base)
                if not info:
                    continue
                with zf.open(info, "r") as media_handle:
                    data = media_handle.read()
                content_type = (
                    "application/octet-stream"
                )
                guessed = None
                try:
                    import mimetypes

                    guessed = mimetypes.guess_type(fname)[0]
                except Exception:
                    guessed = None
                if guessed:
                    content_type = guessed
                attachments.append(
                    ParsedAttachment(
                        filename=fname,
                        content_type=content_type,
                        data=data,
                        is_inline=False,
                        content_id=None,
                    )
                )
                unmatched_media.discard(base)

            if attachments:
                message.attachments = attachments
            all_messages.append(message)

    return WhatsAppParseResult(
        messages=all_messages,
        chat_name=chat_name,
        export_format=export_format,
        stats=stats,
        unmatched_media=sorted(unmatched_media),
    )
