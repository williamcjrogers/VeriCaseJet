from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

BodySource = Literal["plain", "html", "rtf", "none"]

try:
    # Optional, but pinned in requirements for best-in-class HTML -> text cleaning.
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None


_REPLY_SPLIT_RE = re.compile(
    r"(?mi)^\s*>?\s*On .+ wrote:"
    r"|^\s*>?\s*Le .+ a \xE9crit\s*:"  # FR
    r"|^\s*>?\s*El .+ escribi[o\xF3]\s*:"  # ES
    r"|^\s*>?\s*Am .+ schrieb\s*:"  # DE
    r"|^\s*>?\s*Il .+ ha scritto\s*:"  # IT
    r"|^\s*>?\s*Em .+ escreveu\s*:"  # PT
    r"|^\s*>?\s*Op .+ schreef\s*:"  # NL
    r"|^\s*>?\s*From:\s"
    r"|^\s*>?\s*Von:\s"  # DE
    r"|^\s*>?\s*De:\s"  # FR/ES/PT
    r"|^\s*>?\s*Da:\s"  # IT
    r"|^\s*>?\s*Van:\s"  # NL
    r"|^\s*>?\s*Sent:\s"
    r"|^\s*>?\s*Gesendet:\s"  # DE
    r"|^\s*>?\s*Envoy\xE9:\s"  # FR
    r"|^\s*>?\s*Enviado:\s"  # ES/PT
    r"|^\s*>?\s*Inviato:\s"  # IT
    r"|^\s*>?\s*Verzonden:\s"  # NL
    r"|^\s*>?\s*To:\s"
    r"|^\s*>?\s*An:\s"  # DE
    r"|^\s*>?\s*\xC0:\s"  # FR "À:"
    r"|^\s*>?\s*Para:\s"  # ES/PT
    r"|^\s*>?\s*A:\s"  # IT
    r"|^\s*>?\s*Aan:\s"  # NL
    r"|^\s*>?\s*Cc:\s"
    r"|^\s*>?\s*Bcc:\s"
    r"|^\s*>?\s*Subject:\s"
    r"|^\s*>?\s*Betreff:\s"  # DE
    r"|^\s*>?\s*Objet:\s"  # FR
    r"|^\s*>?\s*Asunto:\s"  # ES
    r"|^\s*>?\s*Oggetto:\s"  # IT
    r"|^\s*>?\s*Onderwerp:\s"  # NL
    r"|^\s*>?\s*Date:\s"
    r"|^\s*>?\s*Datum:\s"  # DE/NL
    r"|^-----Original Message-----"
    r"|^----- Forwarded message -----"
    r"|^Begin forwarded message",
)

_SIGNATURE_SPLIT_RE = re.compile(
    # Be conservative: avoid stripping lines like "Thanks for your email..." at the top of a message.
    r"(?mi)^\s*(--\s*$|__+\s*$|sent from my\b|sent via\b)"
)

# NOTE: Removed WordSection1 - it's MS Word's main content container, not a quote block
_HTML_QUOTE_BLOCK_RE = re.compile(
    r"(?is)<blockquote\b[^>]*>.*?</blockquote>|<div\b[^>]*(?:gmail_quote|yahoo_quoted|divRplyFwdMsg)[^>]*>.*?</div>"
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


def _html_to_text_bs4(html_body: str) -> str:
    # Decode entities early so downstream heuristics see real whitespace.
    decoded = html_lib.unescape(html_body or "")
    soup = BeautifulSoup(decoded, "html.parser")  # type: ignore[misc]

    # Remove non-content
    for tag in soup.find_all(
        ["script", "style", "head", "title", "meta", "link", "noscript"]
    ):
        try:
            tag.decompose()
        except Exception:
            pass

    # Remove common quoted/reply blocks
    for tag in soup.find_all("blockquote"):
        try:
            tag.decompose()
        except Exception:
            pass

    def _is_quoteish_class(value: object) -> bool:
        """Check if class indicates a quoted/reply block (NOT main content)."""
        try:
            if value is None:
                return False
            parts: list[str] = []
            if isinstance(value, str):
                parts = [value]
            elif isinstance(value, (list, tuple)):
                parts = [str(v) for v in value]
            joined = " ".join(parts).lower()
            # NOTE: Removed "wordsection1" and "mso" - these are MS Word/Outlook
            # content containers, NOT quoted reply blocks. Removing them was
            # stripping all email body content from Word-generated emails.
            return any(
                k in joined
                for k in (
                    "gmail_quote",
                    "yahoo_quoted",
                    "divrplyfwdmsg",
                )
            )
        except Exception:
            return False

    for tag in soup.find_all(["div", "span"], class_=_is_quoteish_class):
        try:
            tag.decompose()
        except Exception:
            pass

    # Normalize line breaks
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # Block-level tags should end with a newline to preserve paragraph structure
    block_names = {
        "p",
        "div",
        "tr",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "section",
        "article",
        "header",
        "footer",
        "pre",
    }
    for tag in soup.find_all(list(block_names)):
        try:
            tag.append("\n")
        except Exception:
            pass

    # Lists: add simple bullet prefixes
    for li in soup.find_all("li"):
        try:
            li.insert(0, "- ")
            li.append("\n")
        except Exception:
            pass

    text = soup.get_text()  # uses inserted newlines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(html_body: str | None) -> str:
    if not html_body:
        return ""
    if BeautifulSoup is not None:
        try:
            return _html_to_text_bs4(html_body)
        except Exception:
            # Fall back to deterministic regex stripping below.
            pass

    # Deterministic fallback (dependency-light)
    cleaned = _HTML_STYLE_RE.sub(" ", html_body)
    cleaned = _HTML_BREAK_RE.sub("\n", cleaned)
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    # Decode entities early so downstream heuristics (banners/signatures) see real whitespace.
    cleaned = html_lib.unescape(cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def strip_html_quote_blocks(html: str | None) -> str:
    if not html:
        return ""
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")  # type: ignore[misc]
            for tag in soup.find_all("blockquote"):
                tag.decompose()
            # NOTE: Removed wordsection1 - it's MS Word's main content container, not a quote
            for tag in soup.find_all(["div", "span"], class_=lambda c: c and any(k in " ".join(c).lower() for k in ("gmail_quote", "yahoo_quoted", "divrplyfwdmsg"))):  # type: ignore[arg-type]
                tag.decompose()
            return str(soup)
        except Exception:
            pass
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
        # Heuristic signature stripping for common corporate signatures that don't use "--".
        # This is intentionally conservative: it only strips when we detect clear contact info
        # clustered at the bottom of the message.
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln.rstrip() for ln in normalized.split("\n")]
        if len(lines) < 6:
            return text.strip(), ""

        # Work backwards from the last non-empty line, up to a bounded window.
        end = len(lines) - 1
        while end >= 0 and not lines[end].strip():
            end -= 1
        if end <= 2:
            return text.strip(), ""

        start_search = max(0, end - 14)
        window = lines[start_search : end + 1]

        email_re = re.compile(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
        )
        url_re = re.compile(r"(?i)\b(?:https?://\S+|www\.\S+)\b")
        phone_re = re.compile(r"(?i)(?:\+?\d[\d\s().-]{7,}\d)")
        postcode_re = re.compile(r"(?i)\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")  # UK-ish
        title_re = re.compile(
            r"(?i)\b(manager|director|engineer|assistant|contracts?|commercial|project|site|qs|surveyor)\b"
        )
        signoff_re = re.compile(
            r"(?i)^\s*(kind regards|regards|best regards|many thanks|thanks|cheers|yours sincerely|yours faithfully)\b"
        )

        def line_sig_score(line: str) -> int:
            if not line or not line.strip():
                return 0
            s = 0
            if email_re.search(line):
                s += 3
            if url_re.search(line):
                s += 2
            if phone_re.search(line):
                s += 2
            if postcode_re.search(line):
                s += 1
            if title_re.search(line):
                s += 1
            if re.search(r"(?i)\b(ltd|limited|inc|plc)\b", line):
                s += 1
            return s

        # Identify a candidate signature block at the bottom.
        sig_end = end
        sig_start = sig_end
        strong_lines = 0
        any_signoff = False

        # Walk upwards until lines stop looking like signature/contact info.
        for i in range(len(window) - 1, -1, -1):
            line = window[i].strip()
            if not line:
                # Allow a single blank line inside the block, but stop if we've already
                # collected something and hit a "separator" gap.
                if sig_start < sig_end:
                    break
                continue

            if signoff_re.search(line):
                any_signoff = True
                sig_start = start_search + i
                continue

            score = line_sig_score(line)
            if score <= 0:
                break
            if score >= 2:
                strong_lines += 1
            sig_start = start_search + i

        # Validate: require strong contact signal(s) and enough separation from body.
        # Also pull in any immediately preceding sign-off/name lines (common pattern:
        # "Kind regards,\nJohn Smith\n<contact info>").
        def looks_like_name(line: str) -> bool:
            stripped = (line or "").strip()
            if not stripped:
                return False
            if len(stripped) > 50:
                return False
            # Avoid swallowing real content lines; keep to "name-ish" tokens.
            if re.search(r"[@:/\\d]", stripped):
                return False
            return bool(re.fullmatch(r"[A-Za-z][A-Za-z .'\-]{1,49}", stripped))

        pull_idx = sig_start - 1
        pulled_signoff = False
        while pull_idx >= 0 and pull_idx >= sig_start - 3:
            prev = lines[pull_idx].strip()
            if not prev:
                pull_idx -= 1
                continue
            if signoff_re.search(prev):
                sig_start = pull_idx
                pulled_signoff = True
                pull_idx -= 1
                continue
            if looks_like_name(prev):
                sig_start = pull_idx
                pull_idx -= 1
                continue
            break

        # CRITICAL: do not treat pulled name/title lines as proof of a sign-off.
        # We only consider a "signoff" present when we actually matched a signoff phrase
        # like "Kind regards,". Otherwise, blocks like "John Smith\nSoftware Engineer\nABC Ltd"
        # (no signoff) can be incorrectly stripped as a signature.
        if pulled_signoff:
            any_signoff = True

        sig_block = "\n".join(lines[sig_start : sig_end + 1]).strip()
        body_block = "\n".join(lines[:sig_start]).rstrip()

        # Require at least one "hard" contact indicator (email/url/phone) and either:
        # - a signoff line, or
        # - 2+ strong signature lines (e.g., phone + email).
        hard = bool(email_re.search(sig_block) or url_re.search(sig_block))
        has_phone = bool(phone_re.search(sig_block))
        sig_lines = [ln.strip() for ln in sig_block.splitlines() if ln.strip()]
        # Some signatures have no explicit contact info (no email/URL/phone), but do have:
        # "Kind regards," + Name + Title/Company. Treat these as signatures only when there's
        # meaningful body content above them.
        soft_sig_lines = sum(
            1
            for ln in sig_lines
            if looks_like_name(ln)
            or title_re.search(ln)
            or re.search(r"(?i)\b(ltd|limited|inc|plc)\b", ln)
        )
        contactless_signature = bool(
            any_signoff and soft_sig_lines >= 2 and len(sig_lines) <= 10
        )

        if contactless_signature or (
            (hard or has_phone) and (any_signoff or strong_lines >= 2)
        ):
            # Also ensure we don't strip when the remaining body would be empty.
            if len(re.sub(r"[^0-9A-Za-z]+", "", body_block)) >= 20:
                return body_block.strip(), sig_block

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
