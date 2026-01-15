"""Evidence auto-categorization helpers.

This module intentionally keeps categorization lightweight and deterministic.
It is designed to be fast, explainable, and dependency-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryRule:
    pattern: re.Pattern[str]
    category: str


# NOTE: Keep these aligned with the UI defaults in `vericase/ui/evidence.html`.
_DEFAULT_RULES: tuple[CategoryRule, ...] = (
    CategoryRule(re.compile(r"meeting|minutes|mom", re.IGNORECASE), "Meeting Minutes"),
    CategoryRule(
        re.compile(
            r"progress\s*.*report|monthly\s*.*report|weekly\s*.*report", re.IGNORECASE
        ),
        "Progress Reports",
    ),
    CategoryRule(
        re.compile(
            r"client\s*.*valuation|valuation\s*.*cert|interim\s*.*cert", re.IGNORECASE
        ),
        "Client Valuations",
    ),
    CategoryRule(
        re.compile(r"client\s*.*payment|payment\s*.*cert", re.IGNORECASE),
        "Client Payment Certificates",
    ),
    CategoryRule(
        re.compile(r"change|variation|\bvo\b|instruction", re.IGNORECASE), "Change"
    ),
    CategoryRule(
        re.compile(
            r"subcontractor\s*.*valuation|sub\s*.*valuation|subc\s*.*val", re.IGNORECASE
        ),
        "Subcontractor Valuations",
    ),
    CategoryRule(
        re.compile(
            r"subcontractor\s*.*payment|sub\s*.*payment|subc\s*.*pay", re.IGNORECASE
        ),
        "Subcontractor Payment Certificates",
    ),
    CategoryRule(
        re.compile(
            r"site\s*.*instruction|\bsi\d+\b|architect\s*.*instruction|\bai\d+\b",
            re.IGNORECASE,
        ),
        "Site Instructions",
    ),
    CategoryRule(
        re.compile(r"drawing|\bdwg\b|plan|elevation|section|detail", re.IGNORECASE),
        "Drawings",
    ),
    CategoryRule(re.compile(r"spec|specification", re.IGNORECASE), "Specifications"),
)


_EVIDENCE_TYPE_FALLBACK: dict[str, str] = {
    "meeting_minutes": "Meeting Minutes",
    "drawing": "Drawings",
    "specification": "Specifications",
    "payment_certificate": "Client Payment Certificates",
    "valuation": "Client Valuations",
}


def infer_document_category(
    *,
    filename: str | None,
    title: str | None,
    evidence_type: str | None,
) -> str | None:
    """Infer a human-friendly document category.

    This is intentionally conservative: if nothing matches, return None.
    """

    haystack = f"{filename or ''} {title or ''}".strip()
    if haystack:
        for rule in _DEFAULT_RULES:
            if rule.pattern.search(haystack):
                return rule.category

    et = (evidence_type or "").strip().lower()
    if et:
        return _EVIDENCE_TYPE_FALLBACK.get(et)

    return None
