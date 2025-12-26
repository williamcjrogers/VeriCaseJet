from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

NORMALIZER_VERSION = "2025-12-22-v1"

_BANNER_PATTERNS = [
    r"(?mi)^\s*\[?\s*caution[:\-]?\s*external email[\s\]]?.*$",
    r"(?mi)^\s*\[?\s*warning[:\-]?\s*external email[\s\]]?.*$",
    r"(?mi)^\s*\[?\s*external sender[\s\]]?.*$",
    r"(?mi)^\s*external email[:\-].*$",
    r"(?mi)^\s*external email\b.*$",
    r"(?mi)^\s*caution[:\s-]*external.*$",
    r"(?mi)^\s*(?:safety|security)\s+tip[:\s-].*$",
    r"(?mi)^.*expected\s+and\s+known\s+to\s+be\s+safe.*$",
    r"(?mi)^.*recogni[sz]e\s+the\s+sender.*safe.*$",
    r"(?mi)^.*safe\s+senders?\s+list.*$",
    r"(?mi)^.*(?:email|message)\s+looks\s+safe.*$",
    r"(?mi)^\s*this email originated outside.*$",
    r"(?mi)^\s*this email originated from outside.*$",
    r"(?mi)^\s*do not (?:click|open) (?:links?|attachments?).*$",
    r"(?mi)^\s*attachments? and links? .* (?:unsafe|suspicious|dangerous).*$",
]

_FOOTER_MARKERS = [
    r"(?mi)^\s*disclaimer from:.*",
    r"(?mi)^\s*this email (and any attachments )?(is|are) confidential.*",
    r"(?mi)^\s*this message (and any attachments )?(contains|may contain) (confidential|privileged).*",
    r"(?mi)^\s*the information (contained|in) this (e-?mail|message).*confidential.*",
    r"(?mi)^\s*this email is intended.*",
    r"(?mi)^\s*this message is intended.*",
    r"(?mi)^\s*if you have received this (e-?mail|message) in error.*",
    r"(?mi)^\s*if you are not the intended recipient.*",
    r"(?mi)^\s*please notify the sender.*",
    r"(?mi)^\s*please delete.*(this email|this message).*",
    r"(?mi)^\s*any views or opinions.*",
    r"(?mi)^\s*views expressed.*",
    r"(?mi)^\s*no liability.*",
    r"(?mi)^\s*company policy.*",
    r"(?mi)^\s*data protection.*",
    r"(?mi)^\s*privacy notice.*",
    r"(?mi)^\s*disclaimer[:\s].*",
    r"(?mi)^\s*registered office.*",
    r"(?mi)^\s*registered address.*",
    r"(?mi)^\s*head office.*",
    r"(?mi)^\s*office address.*",
    r"(?mi)^\s*company (registration|reg\.? no|number).*",
    r"(?mi)^\s*registered in (england|wales|scotland|ireland).*",
    r"(?mi)^\s*vat (registration|reg\.?|number|no\.?).*",
    r"(?mi)^\s*please consider the environment.*",
    r"(?mi)^\s*think before you print.*",
    r"(?mi)^\s*this email has been scanned for viruses.*",
    r"(?mi)^\s*for information about how we process data.*privacy.*",
    r"(?mi)^\s*click here to unsubscribe.*",
]

_RULESET_PAYLOAD = json.dumps(
    {"banner_patterns": _BANNER_PATTERNS, "footer_markers": _FOOTER_MARKERS},
    sort_keys=True,
).encode("utf-8")
NORMALIZER_RULESET_HASH = hashlib.sha256(_RULESET_PAYLOAD).hexdigest()


def strip_footer_noise(text: str | None) -> str:
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")

    for pattern in _BANNER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)

    for pattern in _FOOTER_MARKERS:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            cleaned = cleaned[: match.start()].rstrip()

    cleaned = re.sub(r"(?m)^\s*[-_]{2,}\s*$", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def clean_body_text(text: str | None) -> str | None:
    if not text:
        return text

    # Remove CSS style blocks (VML behaviors, style tags, etc.)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"v\\:\*\s*\{[^}]*\}", "", text)
    text = re.sub(r"o\\:\*\s*\{[^}]*\}", "", text)
    text = re.sub(r"w\\:\*\s*\{[^}]*\}", "", text)
    text = re.sub(r"\.shape\s*\{[^}]*\}", "", text)
    text = re.sub(r"@[a-z-]+\s*\{[^}]*\}", "", text, flags=re.IGNORECASE)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Strip bare CSS fragments that sometimes leak into text
    text = re.sub(r"(?m)^[A-Za-z][A-Za-z0-9_-]*\s*\{[^}]*\}\s*$", "", text)

    # Decode HTML entities
    text = html.unescape(text)

    # Remove zero-width characters that cause display issues
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)

    # Remove other invisible/control characters (but keep newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    text = strip_footer_noise(text)

    # Normalize multiple spaces (but preserve single newlines)
    text = re.sub(r"[^\S\n]+", " ", text)

    # Normalize multiple newlines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def build_content_hash(
    canonical_body: str | None,
    sender_email: str | None,
    sender_name: str | None,
    to_recipients: list[str] | None,
    subject: str | None,
    email_date: datetime | None,
) -> str | None:
    try:
        norm_from = (sender_email or sender_name or "").strip().lower()
        norm_to = (
            ",".join(sorted([r.strip().lower() for r in to_recipients]))
            if to_recipients
            else ""
        )
        norm_subject = (subject or "").strip().lower()
        norm_date = email_date.isoformat() if email_date else ""
        hash_payload = json.dumps(
            {
                "body": canonical_body or "",
                "from": norm_from,
                "to": norm_to,
                "subject": norm_subject,
                "date": norm_date,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()
    except Exception as hash_error:
        logger.debug("Failed to compute content_hash: %s", hash_error)
        return None


def build_source_hash(payload: dict[str, object]) -> str:
    try:
        serialized = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        )
    except (TypeError, ValueError, RecursionError):
        serialized = repr(payload)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
