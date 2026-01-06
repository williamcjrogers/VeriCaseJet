from __future__ import annotations

from functools import lru_cache
import hashlib
import html
import json
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

NORMALIZER_VERSION = "2026-01-06-v1"

_BANNER_PATTERNS = [
    # EXACT match for common external email banners (highest priority)
    r"(?mi)^\s*EXTERNAL\s+EMAIL\s*:\s*Don'?t\s+click\s+links\s+or\s+open\s+attachments\s+unless\s+the\s+content\s+is\s+expected\s+and\s+known\s+to\s+be\s+safe\.?\s*$",
    r"(?mi)^\s*\[?\s*EXTERNAL\s*\]?\s*:?\s*Don'?t\s+click\s+links.*$",
    # Catch ANY line containing "EXTERNAL EMAIL" followed by warning text
    r"(?mi)^.*EXTERNAL\s+EMAIL\s*:.*(?:click|links?|attachments?|safe).*$",
    # Original patterns
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
    r"(?mi)^\s*this email originated outside the organisation.*$",
    r"(?mi)^\s*this email originated outside the organization.*$",
    r"(?mi)^\s*do not (?:click|open) (?:links?|attachments?).*$",
    r"(?mi)^\s*don'?t (?:click|open) (?:links?|attachments?).*$",
    r"(?mi)^\s*(?:click|open) (?:links?|attachments?) (?:unless|only).*$",
    r"(?mi)^\s*attachments? and links? .* (?:unsafe|suspicious|dangerous).*$",
    r"(?mi)^\s*unless (?:you|the) (?:recogni[sz]e|content is expected).*$",
    r"(?mi)^\s*unless (?:the )?(?:content is expected|sender).*safe.*$",
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
    """Strip footer/disclaimer noise from email body.

    FIXED: Now finds the EARLIEST footer marker position in a single pass,
    instead of iteratively cutting at each pattern (which caused progressive
    truncation). Also requires minimum 50 alphanumeric characters before cutting
    to avoid stripping legitimate short emails.
    """
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove banner patterns (these are inline removals, not truncation)
    for pattern in _BANNER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned)

    # Find the EARLIEST footer marker position across ALL patterns (single pass)
    earliest_cut = len(cleaned)
    for pattern in _FOOTER_MARKERS:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE | re.MULTILINE)
        if match and match.start() < earliest_cut:
            earliest_cut = match.start()

    # Only cut if we have meaningful content before the footer
    # Require at least 50 alphanumeric characters to prevent over-stripping
    if earliest_cut < len(cleaned):
        candidate = cleaned[:earliest_cut].rstrip()
        alphanumeric_count = len(re.sub(r"[^0-9A-Za-z]+", "", candidate))
        if alphanumeric_count >= 50:
            cleaned = candidate
        # Otherwise keep the full text - footer is part of a short email

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


try:
    # Best-in-class reply parsing (headers/quotes/signatures/disclaimers), with multi-language support.
    # Optional dependency; code falls back to lightweight heuristics if missing.
    from mailparser_reply import EmailReplyParser as _EmailReplyParser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _EmailReplyParser = None


@lru_cache(maxsize=16)
def _get_reply_parser(languages_key: str) -> object | None:
    if _EmailReplyParser is None:
        return None
    languages = [lang for lang in (languages_key or "").split(",") if lang]
    if not languages:
        languages = ["en"]
    try:
        return _EmailReplyParser(languages=languages)
    except Exception:
        return None


def _display_score(value: str) -> int:
    if not value:
        return 0
    core = re.sub(r"[^0-9A-Za-z]+", "", value)
    return len(core)


def _is_mostly_boilerplate(text: str) -> bool:
    """
    Heuristic to detect if text is mostly external-email banner/disclaimer boilerplate.
    Returns True if the text appears to be primarily banner text without meaningful content.
    """
    if not text or len(text) < 20:
        return False

    text_lower = text.lower()
    text_stripped = re.sub(r"[^0-9A-Za-z]+", "", text)
    if len(text_stripped) < 30:
        # Very short text is likely not meaningful content
        return True

    # Count banner marker matches
    banner_matches = 0
    for pattern in _BANNER_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
            banner_matches += 1

    # If multiple banner patterns match and the text is short, likely mostly boilerplate
    if banner_matches >= 2 and len(text_stripped) < 100:
        return True

    # Check for common banner phrases without much other content
    banner_phrases = [
        "external email",
        "caution",
        "do not click",
        "don't click",
        "unless you recognise",
        "unless you recognize",
        "expected and known to be safe",
        "message originated outside",
        "originated from outside",
    ]
    phrase_count = sum(1 for phrase in banner_phrases if phrase in text_lower)
    # If 3+ banner phrases and text is mostly short/structured like a banner, likely boilerplate
    if phrase_count >= 3 and len(text_stripped) < 150:
        return True

    return False


def clean_email_body_for_display(
    *,
    body_text_clean: str | None,
    body_text: str | None,
    body_html: str | None,
    languages: list[str] | None = None,
) -> str | None:
    """
    Produce a best-effort *display* body:
    - Decodes HTML entities / strips HTML tags
    - Removes common external-email banners and disclaimer blocks
    - Attempts to drop quoted reply chains + signatures (best-effort)

    Important: this is UI-facing. Do NOT use this output as a forensic source-of-truth.
    Always preserve the raw `body_text` / `body_html` separately.
    """

    from .email_content import split_reply as _split_reply
    from .email_content import strip_signature as _strip_signature
    from .email_content import html_to_text as _html_to_text

    candidates: list[str] = []
    html_as_text = None
    if body_html and isinstance(body_html, str):
        try:
            html_as_text = _html_to_text(body_html)
        except Exception:
            html_as_text = None

    for value in (body_text_clean, body_text, html_as_text):
        if value and isinstance(value, str):
            candidates.append(value)

    # Fast path: if stored body_text_clean already has meaningful content, prefer it.
    # IMPORTANT: body_text_clean is ALREADY processed during PST ingestion via
    # select_best_body() which calls split_reply() and strip_signature().
    # DO NOT re-apply these transformations - it causes double/triple stripping
    # that destroys short email content while preserving only signatures.
    if body_text_clean:
        # Only apply light cleaning (HTML entities, whitespace normalization)
        # Do NOT call split_reply or strip_signature again!
        cleaned = body_text_clean.strip()
        # Remove any HTML entities and normalize whitespace
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = cleaned.strip()
        if _display_score(cleaned) >= 20:  # Lower threshold - content already processed
            return cleaned

    parser = None
    if languages is None:
        env_langs = os.getenv("EMAIL_REPLY_LANGUAGES", "")
        if env_langs.strip():
            languages = [s.strip() for s in env_langs.split(",") if s.strip()]
        else:
            # Safe default: English + common EU corp mailboxes (kept deterministic).
            languages = ["en", "fr", "de", "es", "it", "pt", "nl"]

    languages_key = ",".join(languages or ["en"])
    parser_obj = _get_reply_parser(languages_key)
    if parser_obj is not None:
        parser = parser_obj

    candidate_results: list[tuple[str, int, bool]] = (
        []
    )  # (display, score, is_boilerplate)
    for value in candidates:
        cleaned = clean_body_text(value) or ""
        if not cleaned:
            continue

        display = ""
        # Use the best-in-class parser when available, but keep robust fallbacks.
        if parser is not None:
            try:
                parsed = parser.parse_reply(text=cleaned)  # type: ignore[attr-defined]
                if isinstance(parsed, str):
                    display = parsed
                elif hasattr(parsed, "body"):
                    display = str(getattr(parsed, "body") or "")
                elif hasattr(parsed, "full_body"):
                    display = str(getattr(parsed, "full_body") or "")
            except Exception:
                display = ""

        if display:
            # Regardless of parser output, apply our conservative signature trimming to
            # remove "Kind regards, Name + contact" blocks that are extremely common in
            # UK/Outlook corp datasets.
            top, _quoted, _marker = _split_reply(display)
            body, _sig = _strip_signature(top)
            display = body.strip()
        else:
            # Fallback: split reply + strip signature heuristics.
            top, _quoted, _marker = _split_reply(cleaned)
            body, _sig = _strip_signature(top)
            display = body.strip()

        score = _display_score(display)
        is_boilerplate = _is_mostly_boilerplate(display)
        candidate_results.append((display, score, is_boilerplate))

    # Boilerplate guard: never return mostly-boilerplate text if a better candidate exists
    # Prefer candidates with meaningful content over banner-only text
    non_boilerplate_candidates = [
        (d, s) for d, s, is_bp in candidate_results if not is_bp
    ]
    if non_boilerplate_candidates:
        # Prefer the highest-scoring non-boilerplate candidate
        best_display, best_score = max(non_boilerplate_candidates, key=lambda x: x[1])
        return best_display.strip() or None

    # Fallback: if all candidates are boilerplate, return the highest-scoring one
    # (better than returning empty)
    if candidate_results:
        best_display, best_score, _ = max(candidate_results, key=lambda x: x[1])
        return best_display.strip() or None

    return None


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
