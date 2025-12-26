from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..ai_runtime import complete_chat
from ..schemas.caselaw import QuantFact

logger = logging.getLogger(__name__)


_JSON_START = re.compile(r"\{")


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def extract_numeric_excerpts(
    text: str,
    *,
    max_excerpts: int = 60,
    window_chars: int = 260,
) -> List[str]:
    """
    Pull short verbatim excerpts likely to contain quantitative indicators.
    This is used to steer the LLM toward grounded numeric extraction without
    sending the entire judgment.
    """
    if not text:
        return []

    haystack = text
    patterns: List[Tuple[str, re.Pattern[str]]] = [
        (
            "rfi",
            re.compile(r"(?i)\b\d{1,4}\s*(?:rfis?\b|requests?\s+for\s+information\b)"),
        ),
        (
            "variation",
            re.compile(
                r"(?i)\b\d{1,4}\s*(?:variations?\b|change\s+orders?\b|variation\s+orders?\b|instructions?\b)"
            ),
        ),
        (
            "delay",
            re.compile(
                r"(?i)\b(?:delay(?:ed)?|slippage|extension\s+of\s+time|eot)\b.{0,40}\b\d{1,5}\b.{0,10}\b(?:days?|weeks?|months?)\b"
            ),
        ),
        (
            "money",
            re.compile(
                r"(?i)(?:£\s?\d[\d,]*(?:\.\d+)?\s*(?:m|bn|k|million|billion|thousand)?|\b\d+(?:\.\d+)?\s*(?:million|billion|thousand)\s+pounds\b|\bgbp\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:m|bn|k|million|billion|thousand))?\b)"
            ),
        ),
        (
            "lads",
            re.compile(
                r"(?i)\b(?:lad(?:s)?|liquidated\s+damages?)\b.{0,60}\b(?:£\s?\d[\d,]*(?:\.\d+)?|\b\d{1,5}\b)\b"
            ),
        ),
        ("time", re.compile(r"(?i)\b\d{1,5}\b\s*(?:days?|weeks?|months?)\b")),
    ]

    seen: set[str] = set()
    excerpts: List[str] = []

    for _, pattern in patterns:
        for match in pattern.finditer(haystack):
            if len(excerpts) >= max_excerpts:
                break
            start = max(0, match.start() - window_chars)
            end = min(len(haystack), match.end() + window_chars)
            snippet = _collapse_whitespace(haystack[start:end])
            if not snippet:
                continue
            if snippet in seen:
                continue
            seen.add(snippet)
            excerpts.append(snippet)
        if len(excerpts) >= max_excerpts:
            break

    # Fallback: if we found nothing, include the first few numeric sentences.
    if not excerpts:
        for match in re.finditer(r"(?i)\b\d{1,5}\b", haystack):
            if len(excerpts) >= min(12, max_excerpts):
                break
            start = max(0, match.start() - window_chars)
            end = min(len(haystack), match.end() + window_chars)
            snippet = _collapse_whitespace(haystack[start:end])
            if snippet and snippet not in seen:
                seen.add(snippet)
                excerpts.append(snippet)

    return excerpts


def _build_quant_prompt(excerpts: List[str]) -> str:
    excerpt_block = "\n".join(
        f"{idx+1}. {excerpt}" for idx, excerpt in enumerate(excerpts)
    )
    return f"""
You extract quantitative indicators from construction/engineering case law.
Use ONLY the excerpts provided. Do NOT guess. If unsure, omit the fact.

Allowed metric_type values (use exactly):
- RFI_COUNT
- VARIATION_COUNT
- CHANGE_ORDER_COUNT
- DELAY_DAYS
- EOT_DAYS_CLAIMED
- EOT_DAYS_GRANTED
- CLAIM_VALUE_GBP
- AWARD_AMOUNT_GBP
- CONTRACT_SUM_GBP
- LAD_RATE_GBP_PER_DAY
- LAD_RATE_GBP_PER_WEEK
- LAD_TOTAL_GBP
- REMEDIATION_COST_GBP
- DEFECT_COUNT
- PAYMENT_APPLICATION_COUNT
- ADJUDICATION_COUNT

Normalization rules:
- For *_DAYS: if the excerpt states weeks/months, convert to days for normalized_value (weeks=7 days, months=30 days). Keep unit/value as stated.
- For *_GBP: normalize to whole GBP (e.g., £2.5m => 2500000). Use normalized_unit = \"gbp\".
- For *_COUNT: unit/normalized_unit should be \"count\".

Return strict JSON in this shape:
{{
  \"rfi_count\": integer|null,
  \"change_order_count\": integer|null,
  \"delay_days\": integer|null,
  \"quant_facts\": [
    {{
      \"metric_type\": string,
      \"value\": number|null,
      \"unit\": string|null,
      \"normalized_value\": number|null,
      \"normalized_unit\": string|null,
      \"qualifier\": string|null,
      \"court_accepted\": boolean|null,
      \"source_quote\": string|null,
      \"confidence\": number
    }}
  ]
}}

Excerpts:
{excerpt_block}

Output ONLY the JSON object. No Markdown.
"""


def _normalize_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"\d+", text.replace(",", ""))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


class CaseLawQuantExtractor:
    async def extract(
        self,
        *,
        db: Session,
        provider: str,
        model_id: str,
        text: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        excerpts = extract_numeric_excerpts(text)
        if not excerpts:
            return {
                "rfi_count": None,
                "change_order_count": None,
                "delay_days": None,
                "quant_facts": [],
            }

        prompt = _build_quant_prompt(excerpts)
        completion = await complete_chat(
            provider=provider,
            model_id=model_id,
            prompt=prompt,
            system_prompt="Return strict JSON only.",
            db=db,
            max_tokens=4096,
            temperature=0,
            task_type="caselaw_quant",
            metadata=metadata,
        )

        payload = _extract_json_object(completion or "")
        if not isinstance(payload, dict):
            raise RuntimeError("Quant extraction did not return valid JSON")

        quant_items: List[Dict[str, Any]] = []
        for item in _normalize_list(payload.get("quant_facts")):
            if not isinstance(item, dict):
                continue
            metric_type = str(item.get("metric_type") or "").strip()
            if not metric_type:
                continue
            item["metric_type"] = metric_type
            try:
                quant_fact = QuantFact(**item)
            except Exception:
                continue
            quant_items.append(quant_fact.model_dump())

        return {
            "rfi_count": _parse_optional_int(payload.get("rfi_count")),
            "change_order_count": _parse_optional_int(
                payload.get("change_order_count")
            ),
            "delay_days": _parse_optional_int(payload.get("delay_days")),
            "quant_facts": quant_items,
        }


caselaw_quant_extractor = CaseLawQuantExtractor()
