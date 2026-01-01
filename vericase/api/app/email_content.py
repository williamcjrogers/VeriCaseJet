from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

BodySource = Literal["plain", "html", "rtf", "none"]


_REPLY_SPLIT_RE = re.compile(
    r"(?mi)^\s*>?\s*On .+ wrote:"
    r"|^\s*>?\s*From:\s"
    r"|^\s*>?\s*Sent:\s"
    r"|^\s*>?\s*To:\s"
    r"|^\s*>?\s*Cc:\s"
    r"|^\s*>?\s*Bcc:\s"
    r"|^\s*>?\s*Subject:\s"
    r"|^\s*>?\s*Date:\s"
    r"|^-----Original Message-----"
    r"|^----- Forwarded message -----"
    r"|^Begin forwarded message",
)

_SIGNATURE_SPLIT_RE = re.compile(
    # Be conservative: avoid stripping lines like "Thanks for your email..." at the top of a message.
    r"(?mi)^\s*(--\s*$|__+\s*$|sent from my\b|sent via\b)"
)

_HTML_QUOTE_BLOCK_RE = re.compile(
    r"(?is)<blockquote\b[^>]*>.*?</blockquote>|<div\b[^>]*(?:gmail_quote|yahoo_quoted|WordSection1|divRplyFwdMsg)[^>]*>.*?</div>"
)

_HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
_HTML_BREAK_RE = re.compile(r"(?is)<\s*(br|/p|/div|/tr|/li)\s*>")
_HTML_STYLE_RE = re.compile(r"(?is)<\s*(script|style)\b[^>]*>.*?</\1\s*>")


@dataclass(frozen=True)
class BodySelection:
    selected_source: BodySource
    full_text: str
    top_text: str
    quoted_text: str
    signature_text: str
    diagnostics: dict[str, Any]


def decode_maybe_bytes(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        for encoding in ("utf-8", "windows-1252", "iso-8859-1", "cp1252"):
            try:
                text = value.decode(encoding)
                return text.replace("\x00", "").replace("\u0000", "")
            except (UnicodeDecodeError, LookupError):
                continue
        text = value.decode("utf-8", errors="replace")
        return text.replace("\x00", "").replace("\u0000", "")
    text = str(value)
    if not text:
        return None
    return text.replace("\x00", "").replace("\u0000", "")


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    # Keep it deterministic and dependency-light; bs4 can be added later if needed.
    cleaned = _HTML_STYLE_RE.sub(" ", html)
    cleaned = _HTML_BREAK_RE.sub("\n", cleaned)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_html_quote_blocks(html: str | None) -> str:
    if not html:
        return ""
    return _HTML_QUOTE_BLOCK_RE.sub(" ", html)


def rtf_to_text(rtf: str | None) -> str:
    if not rtf:
        return ""
    try:
        # Optional best-in-class conversion if installed.
        from striprtf.striprtf import rtf_to_text as _rtf_to_text  # type: ignore

        return _rtf_to_text(rtf).replace("\r\n", "\n").replace("\r", "\n").strip()
    except Exception:
        # Fallback: basic control-code stripping (lossy but deterministic).
        text = rtf
        text = re.sub(r"\\par[d]?\b", "\n", text)
        text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
        text = re.sub(r"\\[a-z]+\d*\s?", " ", text)
        text = text.replace("{", " ").replace("}", " ")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[^\S\n]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def split_reply(text: str) -> tuple[str, str, str | None]:
    if not text:
        return "", "", None
    match = _REPLY_SPLIT_RE.search(text)
    if match:
        top = text[: match.start()].strip()
        quoted = text[match.start() :].strip()
        return top, quoted, match.group(0).strip()
    # Fallback: treat leading non-quoted lines as "top" when the rest is quoted.
    lines = text.splitlines()
    top_lines: list[str] = []
    quoted_lines: list[str] = []
    for line in lines:
        if line.lstrip().startswith(">"):
            quoted_lines.append(line)
        else:
            if quoted_lines:
                quoted_lines.append(line)
            else:
                top_lines.append(line)
    top = "\n".join(top_lines).strip()
    quoted = "\n".join(quoted_lines).strip()
    return top, quoted, None


def strip_signature(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    match = _SIGNATURE_SPLIT_RE.search(text)
    if not match:
        return text.strip(), ""
    body = text[: match.start()].rstrip()
    signature = text[match.start() :].strip()
    return body, signature


def _new_content_score(text: str) -> int:
    if not text:
        return 0
    # Prefer alpha-numeric density over raw length (reduces false positives from whitespace/markup).
    core = re.sub(r"[^0-9A-Za-z]+", "", text)
    return len(core)


def select_best_body(
    *,
    plain_text: str | None,
    html_body: str | None,
    rtf_body: str | None,
) -> BodySelection:
    plain_full = (plain_text or "").replace("\r\n", "\n").replace("\r", "\n")

    html_full_text = html_to_text(html_body)
    html_top_hint_text = html_to_text(strip_html_quote_blocks(html_body))

    rtf_text = rtf_to_text(rtf_body)

    plain_top, plain_quoted, plain_marker = split_reply(plain_full)
    html_top, html_quoted, html_marker = split_reply(
        html_top_hint_text or html_full_text
    )
    rtf_top, rtf_quoted, rtf_marker = split_reply(rtf_text)

    candidates: list[tuple[BodySource, str, str, str, str | None]] = [
        ("plain", plain_full, plain_top, plain_quoted, plain_marker),
        ("html", html_full_text, html_top, html_quoted, html_marker),
        ("rtf", rtf_text, rtf_top, rtf_quoted, rtf_marker),
    ]

    scored: list[tuple[int, BodySource]] = []
    diag: dict[str, Any] = {"candidates": {}}
    for source, full, top, quoted, marker in candidates:
        score = _new_content_score(top)
        scored.append((score, source))
        diag["candidates"][source] = {
            "full_len": len(full or ""),
            "top_len": len(top or ""),
            "quoted_len": len(quoted or ""),
            "score": score,
            "reply_marker": marker,
        }

    scored.sort(key=lambda item: (item[0], item[1]))
    best_score, best_source = scored[-1] if scored else (0, "none")
    if all(
        diag["candidates"][source]["full_len"] == 0 for source in diag["candidates"]
    ):
        best_score = 0
        best_source = "none"
    selected = (
        next(c for c in candidates if c[0] == best_source)
        if best_source != "none"
        else ("none", "", "", "", None)
    )

    diag["selected_source"] = best_source
    diag["selected_score"] = best_score

    _, full, top, quoted, _ = selected
    if best_score <= 0 and plain_full:
        # Deterministic fallback: keep plain text as source-of-truth for quotes even when no "new content" is detected.
        best_source = "plain"
        full = plain_full
        top = plain_top
        quoted = plain_quoted
        diag["selected_source"] = best_source
        diag["selected_score"] = _new_content_score(top)

    top_wo_sig, signature = strip_signature(top)
    diag["signature_len"] = len(signature)

    return BodySelection(
        selected_source=best_source,
        full_text=full or "",
        top_text=top_wo_sig,
        quoted_text=quoted or "",
        signature_text=signature,
        diagnostics=diag,
    )
