from __future__ import annotations

import re
from dataclasses import dataclass

import hashlib


_WHITESPACE_RUN = re.compile(r"[ \t]+")
_DEP_URI_RE = re.compile(
    r"^dep://(?P<case_id>[^/]+)/(?P<source_type>[^/]+)/(?P<source_id>[^/]+)/chars_(?P<start>\d+)-(?P<end>\d+)#(?P<hash_prefix>[a-f0-9]+)$"
)


def sha256_hex_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_hex_text(text: str) -> str:
    return sha256_hex_bytes(text.encode("utf-8"))


def normalize_text_for_hash(text: str) -> str:
    """
    Deterministic text normalization for hashing.

    Offsets for DEP spans are based on the *stored* source text; normalization is
    used only for computing Layer-2 hashes and span hashes.
    """
    if not text:
        return ""

    # Newlines
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Common OCR oddities
    normalized = normalized.replace("\u00a0", " ")  # NBSP

    # Whitespace normalization (keep newlines)
    normalized = _WHITESPACE_RUN.sub(" ", normalized)

    # Trim line ends, then trim overall
    normalized = "\n".join(line.strip() for line in normalized.split("\n")).strip()
    return normalized


def compute_normalized_text_hash(text: str) -> str:
    return sha256_hex_text(normalize_text_for_hash(text))


def compute_span_hash(source_text: str, start: int, end: int) -> str:
    if start < 0 or end < 0 or end < start:
        raise ValueError("Invalid span offsets")
    snippet = source_text[start:end]
    return sha256_hex_text(normalize_text_for_hash(snippet))


def make_dep_uri(
    *,
    case_id: str,
    source_type: str,
    source_id: str,
    start: int,
    end: int,
    span_hash: str,
    hash_prefix_len: int = 10,
) -> str:
    hash_prefix = (span_hash or "")[:hash_prefix_len]
    return (
        f"dep://{case_id}/{source_type}/{source_id}/chars_{start}-{end}#{hash_prefix}"
    )


@dataclass(frozen=True)
class ParsedDEP:
    case_id: str
    source_type: str
    source_id: str
    start: int
    end: int
    hash_prefix: str


def parse_dep_uri(dep_uri: str) -> ParsedDEP:
    match = _DEP_URI_RE.match(dep_uri or "")
    if not match:
        raise ValueError("Invalid dep_uri")

    start = int(match.group("start"))
    end = int(match.group("end"))
    if end < start:
        raise ValueError("Invalid dep_uri offsets")

    return ParsedDEP(
        case_id=match.group("case_id"),
        source_type=match.group("source_type"),
        source_id=match.group("source_id"),
        start=start,
        end=end,
        hash_prefix=match.group("hash_prefix"),
    )
