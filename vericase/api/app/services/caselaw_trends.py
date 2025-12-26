from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import CaseLaw


def _normalize_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        items = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    text_value = str(value).strip()
    return [text_value] if text_value else []


def _top_counts(counter: Counter[str], top_n: int) -> List[Dict[str, Any]]:
    return [
        {"value": value, "count": count} for value, count in counter.most_common(top_n)
    ]


def _issue_names(issues: Any) -> List[str]:
    if not isinstance(issues, list):
        return []
    names: List[str] = []
    for issue in issues:
        if isinstance(issue, dict):
            name = str(issue.get("issue_name") or "").strip()
            if name:
                names.append(name)
    return names


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_key(value: str) -> str:
    if not value:
        return ""
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    return normalized


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


def _parse_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _iter_quant_facts(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    facts = analysis.get("quant_facts")
    if not isinstance(facts, list):
        return []
    items: List[Dict[str, Any]] = []
    for item in facts:
        if isinstance(item, dict):
            items.append(item)
    return items


def _best_quant_metric_value(
    analysis: Dict[str, Any],
    *,
    metric_types: List[str],
) -> Optional[float]:
    values: List[float] = []
    for fact in _iter_quant_facts(analysis):
        metric_type = str(fact.get("metric_type") or "").strip().upper()
        if not metric_type or metric_type not in {m.upper() for m in metric_types}:
            continue
        value = _parse_optional_float(fact.get("normalized_value"))
        if value is None:
            value = _parse_optional_float(fact.get("value"))
        if value is None:
            continue
        values.append(value)
    if not values:
        return None
    return max(values)


def _case_numeric_value(analysis: Dict[str, Any], numeric_key: str) -> Optional[float]:
    """
    Return a single best numeric value per case for the requested numeric key.
    Falls back to quant_facts when top-level indicators are missing.
    """
    if numeric_key in {"rfi_count", "change_order_count", "delay_days"}:
        direct = _parse_optional_int(analysis.get(numeric_key))
        if direct is not None:
            return float(direct)

    metric_map: Dict[str, List[str]] = {
        "rfi_count": ["RFI_COUNT"],
        "change_order_count": ["CHANGE_ORDER_COUNT", "VARIATION_COUNT"],
        "delay_days": ["DELAY_DAYS"],
        "eot_days_claimed": ["EOT_DAYS_CLAIMED"],
        "eot_days_granted": ["EOT_DAYS_GRANTED"],
        "claim_value_gbp": ["CLAIM_VALUE_GBP"],
        "award_amount_gbp": ["AWARD_AMOUNT_GBP"],
        "contract_sum_gbp": ["CONTRACT_SUM_GBP"],
        "lad_total_gbp": ["LAD_TOTAL_GBP"],
        "remediation_cost_gbp": ["REMEDIATION_COST_GBP"],
        "defect_count": ["DEFECT_COUNT"],
        "payment_application_count": ["PAYMENT_APPLICATION_COUNT"],
        "adjudication_count": ["ADJUDICATION_COUNT"],
    }

    metric_types = metric_map.get(numeric_key)
    if not metric_types:
        direct_float = _parse_optional_float(analysis.get(numeric_key))
        return direct_float

    return _best_quant_metric_value(analysis, metric_types=metric_types)


def _percentile(values: List[int], percentile: float) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percentile))
    index = max(0, min(index, len(ordered) - 1))
    return ordered[index]


def _round_threshold(value: int, step: int, minimum: int) -> Optional[int]:
    if value <= 0:
        return None
    if step <= 1:
        return max(value, minimum)
    rounded = int(round(value / step) * step)
    if rounded < minimum:
        rounded = minimum
    return rounded


def _build_numeric_thresholds(
    values: List[int],
    *,
    step: int,
    minimum: int,
    fixed: List[int],
) -> List[int]:
    if not values:
        return []
    thresholds: set[int] = set()
    for pct in (0.5, 0.75, 0.9):
        pct_value = _percentile(values, pct)
        if pct_value is None:
            continue
        rounded = _round_threshold(pct_value, step, minimum)
        if rounded:
            thresholds.add(rounded)

    max_value = max(values)
    for fixed_value in fixed:
        if fixed_value <= max_value and fixed_value >= minimum:
            thresholds.add(fixed_value)

    return sorted(thresholds)


def _format_gbp(value: int) -> str:
    if value >= 1_000_000_000:
        scaled = value / 1_000_000_000
        return f"{scaled:.1f}".rstrip("0").rstrip(".") + "bn"
    if value >= 1_000_000:
        scaled = value / 1_000_000
        return f"{scaled:.1f}".rstrip("0").rstrip(".") + "m"
    if value >= 1_000:
        return f"{int(round(value / 1_000))}k"
    return f"{value:,}"


def _format_numeric_threshold(numeric_key: str, threshold: int) -> str:
    key = _normalize_key(numeric_key)
    if key.endswith("_gbp"):
        return f">= £{_format_gbp(threshold)}"
    if key.endswith("_days"):
        return f">= {threshold} days"
    return f">= {threshold}"


def _collect_case_features(
    analysis: Dict[str, Any],
    feature_display: Dict[Tuple[str, str], str],
) -> Dict[str, set[str]]:
    features: Dict[str, set[str]] = {}

    def add_values(feature_type: str, values: List[str]) -> None:
        if not values:
            return
        bucket = features.setdefault(feature_type, set())
        for value in values:
            cleaned = _clean_text(value)
            if not cleaned:
                continue
            key = _normalize_key(cleaned)
            if not key:
                continue
            bucket.add(key)
            feature_display.setdefault((feature_type, key), cleaned)

    add_values("theme", _normalize_list(analysis.get("themes")))
    add_values("contentious_issue", _normalize_list(analysis.get("contentious_issues")))
    add_values("tag", _normalize_list(analysis.get("tags")))
    add_values("issue", _issue_names(analysis.get("issues")))
    add_values("delay_cause", _normalize_list(analysis.get("delay_causes")))
    add_values("defect_type", _normalize_list(analysis.get("defect_types")))
    add_values("key_clause", _normalize_list(analysis.get("key_clauses")))
    add_values(
        "construction_bucket",
        _normalize_list(analysis.get("construction_buckets")),
    )

    contract_form = _clean_text(analysis.get("contract_form"))
    if contract_form:
        add_values("contract_form", [contract_form])

    procurement_route = _clean_text(analysis.get("procurement_route"))
    if procurement_route:
        add_values("procurement_route", [procurement_route])

    return features


def _build_predictive_signals(
    cases: List[CaseLaw],
    *,
    top_n: int = 10,
    min_feature_cases: int = 3,
    min_outcome_cases: int = 2,
    min_lift: float = 1.0,
) -> Dict[str, Any]:
    numeric_config = {
        "rfi_count": {"step": 5, "minimum": 5, "fixed": [10, 20, 30]},
        "change_order_count": {"step": 5, "minimum": 2, "fixed": [5, 10, 20]},
        "delay_days": {"step": 10, "minimum": 7, "fixed": [30, 60, 90]},
        "eot_days_granted": {"step": 7, "minimum": 7, "fixed": [28, 56, 84]},
        "claim_value_gbp": {
            "step": 100000,
            "minimum": 100000,
            "fixed": [500000, 1000000, 5000000, 10000000],
        },
        "award_amount_gbp": {
            "step": 100000,
            "minimum": 50000,
            "fixed": [250000, 500000, 1000000, 5000000],
        },
    }
    feature_counts: Counter[Tuple[str, str]] = Counter()
    feature_outcome_counts: Counter[Tuple[str, str, str]] = Counter()
    outcome_counts: Counter[str] = Counter()
    outcome_display: Dict[str, str] = {}
    feature_display: Dict[Tuple[str, str], str] = {}
    numeric_values: Dict[str, List[int]] = {key: [] for key in numeric_config}
    valid_cases: List[Tuple[Dict[str, Any], str]] = []

    total_cases = 0
    for case in cases:
        analysis = case.extracted_analysis or {}
        outcome_label = _clean_text(analysis.get("outcome"))
        if not outcome_label:
            continue
        outcome_key = _normalize_key(outcome_label)
        if not outcome_key or outcome_key in {"unknown", "n/a", "none"}:
            continue

        outcome_display.setdefault(outcome_key, outcome_label)
        outcome_counts[outcome_key] += 1
        total_cases += 1
        valid_cases.append((analysis, outcome_key))

        case_features = _collect_case_features(analysis, feature_display)
        for feature_type, feature_keys in case_features.items():
            for feature_key in feature_keys:
                feature_counts[(feature_type, feature_key)] += 1
                feature_outcome_counts[(feature_type, feature_key, outcome_key)] += 1

        for numeric_key in numeric_values.keys():
            value = _case_numeric_value(analysis, numeric_key)
            if value is None:
                continue
            try:
                numeric_values[numeric_key].append(int(value))
            except Exception:
                continue

    baseline = [
        {
            "outcome": outcome_display.get(outcome_key, outcome_key),
            "count": count,
            "rate": (count / total_cases) if total_cases else 0,
        }
        for outcome_key, count in outcome_counts.most_common()
    ]

    signals: List[Dict[str, Any]] = []
    if not total_cases:
        return {
            "signals": signals,
            "baseline": baseline,
            "case_count": total_cases,
        }

    numeric_thresholds: Dict[str, List[int]] = {}
    for numeric_key, config in numeric_config.items():
        values = numeric_values.get(numeric_key) or []
        if len(values) < min_feature_cases:
            continue
        numeric_thresholds[numeric_key] = _build_numeric_thresholds(
            values,
            step=config["step"],
            minimum=config["minimum"],
            fixed=config["fixed"],
        )

    for analysis, outcome_key in valid_cases:
        for numeric_key, thresholds in numeric_thresholds.items():
            if not thresholds:
                continue
            raw_value = _case_numeric_value(analysis, numeric_key)
            if raw_value is None:
                continue
            value = int(raw_value)
            for threshold in thresholds:
                if value < threshold:
                    continue
                feature_key = f"ge_{threshold}"
                feature_counts[(numeric_key, feature_key)] += 1
                feature_outcome_counts[(numeric_key, feature_key, outcome_key)] += 1
                feature_display.setdefault(
                    (numeric_key, feature_key),
                    _format_numeric_threshold(numeric_key, threshold),
                )

    for (feature_type, feature_key), feature_count in feature_counts.items():
        if feature_count < min_feature_cases:
            continue
        best: Optional[Dict[str, Any]] = None
        for outcome_key, outcome_total in outcome_counts.items():
            outcome_count = feature_outcome_counts.get(
                (feature_type, feature_key, outcome_key),
                0,
            )
            if outcome_count < min_outcome_cases:
                continue

            base_rate = outcome_total / total_cases
            if base_rate <= 0:
                continue

            feature_rate = outcome_count / feature_count
            lift = feature_rate / base_rate if base_rate else 0
            if lift < min_lift:
                continue

            candidate = {
                "feature_type": feature_type,
                "feature": feature_display.get(
                    (feature_type, feature_key), feature_key
                ),
                "outcome": outcome_display.get(outcome_key, outcome_key),
                "support": outcome_count,
                "feature_cases": feature_count,
                "outcome_cases": outcome_total,
                "feature_rate": feature_rate,
                "base_rate": base_rate,
                "lift": lift,
                "delta": feature_rate - base_rate,
            }

            if best is None or (
                candidate["lift"],
                candidate["support"],
            ) > (
                best["lift"],
                best["support"],
            ):
                best = candidate

        if best:
            signals.append(best)

    signals.sort(key=lambda s: (s["lift"], s["support"]), reverse=True)

    return {
        "signals": signals[: max(0, top_n)],
        "baseline": baseline,
        "case_count": total_cases,
    }


def _derive_risk_targets(analysis: Dict[str, Any]) -> Dict[str, bool]:
    buckets = {
        _normalize_key(b) for b in _normalize_list(analysis.get("construction_buckets"))
    }
    themes = _normalize_list(analysis.get("themes"))
    contentious = _normalize_list(analysis.get("contentious_issues"))
    tags = _normalize_list(analysis.get("tags"))
    key_clauses = _normalize_list(analysis.get("key_clauses"))
    delay_causes = _normalize_list(analysis.get("delay_causes"))
    defect_types = _normalize_list(analysis.get("defect_types"))

    text_blob = " ".join(
        [
            " ".join(themes),
            " ".join(contentious),
            " ".join(tags),
            " ".join(key_clauses),
            " ".join(delay_causes),
            " ".join(defect_types),
            _clean_text(analysis.get("outcome")),
        ]
    ).lower()

    delay_days = _case_numeric_value(analysis, "delay_days")
    change_orders = _case_numeric_value(analysis, "change_order_count")
    rfi_count = _case_numeric_value(analysis, "rfi_count")
    eot_days_granted = _case_numeric_value(analysis, "eot_days_granted")

    has_delay = (
        ("delay" in buckets)
        or bool(delay_causes)
        or (delay_days is not None and delay_days > 0)
        or (eot_days_granted is not None and eot_days_granted > 0)
        or any(
            term in text_blob
            for term in ("delay", "extension of time", "eot", "prolongation")
        )
    )
    has_variation = (
        ("variation" in buckets)
        or (change_orders is not None and change_orders > 0)
        or any(
            term in text_blob
            for term in (
                "variation",
                "change order",
                "instruction",
                "compensation event",
            )
        )
    )
    has_defect = (
        ("defect" in buckets)
        or ("remediation" in buckets)
        or bool(defect_types)
        or any(
            term in text_blob
            for term in ("defect", "remediation", "snag", "cladding", "fire stopping")
        )
    )
    has_payment = ("payment" in buckets) or any(
        term in text_blob
        for term in (
            "payment",
            "pay less",
            "payment notice",
            "smash and grab",
            "hgcra",
            "adjudication",
        )
    )
    has_termination = ("termination" in buckets) or any(
        term in text_blob for term in ("termination", "repudiation")
    )

    has_information_overload = (
        "design" in buckets or "delay" in buckets or "variation" in buckets
    ) and (rfi_count is not None and rfi_count >= 20)

    return {
        "delay": has_delay,
        "variation": has_variation,
        "defect": has_defect,
        "payment": has_payment,
        "termination": has_termination,
        "high_rfi": has_information_overload,
    }


def _build_risk_signals(
    cases: List[CaseLaw],
    *,
    top_n: int = 8,
    min_feature_cases: int = 3,
    min_target_cases: int = 4,
    min_support: int = 2,
    min_lift: float = 1.25,
) -> Dict[str, Any]:
    """
    Build feature -> derived-risk associations (binary targets) to support "day 1" intelligence signals.
    """
    target_labels = {
        "delay": "Delay / EOT",
        "variation": "Variation / Scope",
        "defect": "Defect / Remediation",
        "payment": "Payment / Notices",
        "termination": "Termination",
        "high_rfi": "High RFI Load",
    }

    numeric_config = {
        "rfi_count": {"step": 5, "minimum": 5, "fixed": [10, 20, 30]},
        "change_order_count": {"step": 5, "minimum": 2, "fixed": [5, 10, 20]},
        "eot_days_granted": {"step": 7, "minimum": 7, "fixed": [28, 56, 84]},
        "claim_value_gbp": {
            "step": 100000,
            "minimum": 100000,
            "fixed": [500000, 1000000, 5000000, 10000000],
        },
        "award_amount_gbp": {
            "step": 100000,
            "minimum": 50000,
            "fixed": [250000, 500000, 1000000, 5000000],
        },
    }

    total_cases = len(cases)
    if not total_cases:
        return {"signals": [], "baseline": [], "case_count": 0}

    feature_counts: Counter[Tuple[str, str]] = Counter()
    feature_target_counts: Counter[Tuple[str, str, str]] = Counter()
    target_counts: Counter[str] = Counter()
    feature_display: Dict[Tuple[str, str], str] = {}
    numeric_values: Dict[str, List[int]] = {key: [] for key in numeric_config}
    valid_cases: List[Tuple[Dict[str, Any], List[str]]] = []

    for case in cases:
        analysis = case.extracted_analysis or {}
        targets = [k for k, v in _derive_risk_targets(analysis).items() if v]
        valid_cases.append((analysis, targets))
        for target in targets:
            target_counts[target] += 1

        case_features = _collect_case_features(analysis, feature_display)
        for feature_type, feature_keys in case_features.items():
            for feature_key in feature_keys:
                feature_counts[(feature_type, feature_key)] += 1
                for target in targets:
                    feature_target_counts[(feature_type, feature_key, target)] += 1

        for numeric_key in numeric_values.keys():
            value = _case_numeric_value(analysis, numeric_key)
            if value is None:
                continue
            try:
                numeric_values[numeric_key].append(int(value))
            except Exception:
                continue

    numeric_thresholds: Dict[str, List[int]] = {}
    for numeric_key, config in numeric_config.items():
        values = numeric_values.get(numeric_key) or []
        if len(values) < min_feature_cases:
            continue
        numeric_thresholds[numeric_key] = _build_numeric_thresholds(
            values,
            step=config["step"],
            minimum=config["minimum"],
            fixed=config["fixed"],
        )

    for analysis, targets in valid_cases:
        if not targets:
            continue
        for numeric_key, thresholds in numeric_thresholds.items():
            value = _case_numeric_value(analysis, numeric_key)
            if value is None:
                continue
            for threshold in thresholds:
                if value < threshold:
                    continue
                feature_key = str(threshold)
                feature_counts[(numeric_key, feature_key)] += 1
                feature_display.setdefault(
                    (numeric_key, feature_key),
                    _format_numeric_threshold(numeric_key, threshold),
                )
                for target in targets:
                    feature_target_counts[(numeric_key, feature_key, target)] += 1

    baseline = [
        {
            "target": target_labels.get(target_key, target_key),
            "count": count,
            "rate": (count / total_cases) if total_cases else 0,
        }
        for target_key, count in target_counts.most_common()
    ]

    signals: List[Dict[str, Any]] = []
    for (feature_type, feature_key), feature_case_count in feature_counts.items():
        if feature_case_count < min_feature_cases:
            continue

        for target_key, target_total in target_counts.items():
            if target_total < min_target_cases:
                continue

            support = feature_target_counts.get(
                (feature_type, feature_key, target_key), 0
            )
            if support < min_support:
                continue

            base_rate = target_total / total_cases if total_cases else 0
            if base_rate <= 0:
                continue

            feature_rate = support / feature_case_count if feature_case_count else 0
            lift = feature_rate / base_rate if base_rate else 0
            if lift < min_lift:
                continue

            signals.append(
                {
                    "feature_type": feature_type,
                    "feature": feature_display.get(
                        (feature_type, feature_key), feature_key
                    ),
                    "target": target_labels.get(target_key, target_key),
                    "support": support,
                    "feature_cases": feature_case_count,
                    "target_cases": target_total,
                    "feature_rate": feature_rate,
                    "base_rate": base_rate,
                    "lift": lift,
                    "delta": feature_rate - base_rate,
                }
            )

    signals.sort(key=lambda s: (s["lift"], s["support"]), reverse=True)
    return {
        "signals": signals[: max(0, top_n)],
        "baseline": baseline,
        "case_count": total_cases,
    }


def _score_signal(signal: Dict[str, Any]) -> float:
    lift = float(signal.get("lift") or 0)
    support = float(signal.get("support") or 0)
    delta = float(signal.get("delta") or 0)
    support_weight = 1 + min(support, 20) / 20
    delta_weight = 1 + max(delta, 0)
    return lift * support_weight * delta_weight


def _build_proactive_trends(
    signals: List[Dict[str, Any]],
    *,
    total_cases: int,
    top_n: int = 5,
) -> Dict[str, Any]:
    if total_cases >= 80:
        support_threshold = 6
        lift_threshold = 1.5
        delta_threshold = 0.12
    elif total_cases >= 40:
        support_threshold = 4
        lift_threshold = 1.4
        delta_threshold = 0.1
    elif total_cases >= 20:
        support_threshold = 3
        lift_threshold = 1.3
        delta_threshold = 0.08
    else:
        support_threshold = 2
        lift_threshold = 1.2
        delta_threshold = 0.05

    proactive: List[Dict[str, Any]] = []
    for signal in signals:
        support = int(signal.get("support") or 0)
        lift = float(signal.get("lift") or 0)
        delta = float(signal.get("delta") or 0)
        if support < support_threshold:
            continue
        if lift < lift_threshold:
            continue
        if delta < delta_threshold:
            continue

        level = "medium"
        if lift >= lift_threshold + 0.3 and support >= support_threshold + 2:
            level = "high"

        proactive.append(
            {
                **signal,
                "score": _score_signal(signal),
                "level": level,
            }
        )

    proactive.sort(key=lambda s: (s["score"], s.get("support", 0)), reverse=True)
    fallback = False
    if not proactive:
        fallback = True
        proactive = [
            {
                **signal,
                "score": _score_signal(signal),
                "level": "watch",
            }
            for signal in signals[: max(0, top_n)]
        ]

    return {
        "trends": proactive[: max(0, top_n)],
        "thresholds": {
            "support": support_threshold,
            "lift": lift_threshold,
            "delta": delta_threshold,
        },
        "fallback": fallback,
    }


def summarize_case_law_trends(
    db: Session,
    top_n: int = 10,
    court: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    theme: Optional[str] = None,
    outcome: Optional[str] = None,
) -> Dict[str, Any]:
    query = db.query(CaseLaw).filter(CaseLaw.extraction_status == "extracted")
    if court:
        query = query.filter(CaseLaw.court == court)
    if year_from:
        query = query.filter(CaseLaw.judgment_date >= datetime(year_from, 1, 1))
    if year_to:
        query = query.filter(
            CaseLaw.judgment_date <= datetime(year_to, 12, 31, 23, 59, 59)
        )

    cases = query.all()

    theme_key = _normalize_key(theme or "")
    outcome_key = _normalize_key(outcome or "")
    if theme_key or outcome_key:
        filtered: List[CaseLaw] = []
        for case in cases:
            analysis = case.extracted_analysis or {}
            if theme_key:
                themes = _normalize_list(analysis.get("themes"))
                theme_keys = {_normalize_key(t) for t in themes}
                if theme_key not in theme_keys:
                    continue
            if outcome_key:
                case_outcome = _normalize_key(_clean_text(analysis.get("outcome")))
                if case_outcome != outcome_key:
                    continue
            filtered.append(case)
        cases = filtered

    has_bucketed = any(
        _normalize_list((case.extracted_analysis or {}).get("construction_buckets"))
        for case in cases
    )
    if has_bucketed:
        cases = [
            case
            for case in cases
            if _normalize_list(
                (case.extracted_analysis or {}).get("construction_buckets")
            )
        ]

    theme_counts: Counter[str] = Counter()
    contentious_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    contract_counts: Counter[str] = Counter()
    delay_counts: Counter[str] = Counter()
    defect_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    year_counts: Counter[int] = Counter()

    for case in cases:
        analysis = case.extracted_analysis or {}
        theme_counts.update(_normalize_list(analysis.get("themes")))
        contentious_counts.update(_normalize_list(analysis.get("contentious_issues")))
        tag_counts.update(_normalize_list(analysis.get("tags")))
        issue_counts.update(_issue_names(analysis.get("issues")))
        delay_counts.update(_normalize_list(analysis.get("delay_causes")))
        defect_counts.update(_normalize_list(analysis.get("defect_types")))
        bucket_counts.update(_normalize_list(analysis.get("construction_buckets")))

        outcome = str(analysis.get("outcome") or "").strip()
        if outcome:
            outcome_counts[outcome] += 1

        contract_form = str(analysis.get("contract_form") or "").strip()
        if contract_form:
            contract_counts[contract_form] += 1

        if case.judgment_date:
            year_counts[case.judgment_date.year] += 1

    predictive = _build_predictive_signals(cases, top_n=top_n)
    proactive = _build_proactive_trends(
        predictive["signals"],
        total_cases=predictive["case_count"],
        top_n=min(5, top_n),
    )
    risk = _build_risk_signals(cases, top_n=min(6, top_n))

    return {
        "total_cases": len(cases),
        "themes": _top_counts(theme_counts, top_n),
        "contentious_issues": _top_counts(contentious_counts, top_n),
        "tags": _top_counts(tag_counts, top_n),
        "issue_names": _top_counts(issue_counts, top_n),
        "outcomes": _top_counts(outcome_counts, top_n),
        "contract_forms": _top_counts(contract_counts, top_n),
        "delay_causes": _top_counts(delay_counts, top_n),
        "defect_types": _top_counts(defect_counts, top_n),
        "construction_buckets": _top_counts(bucket_counts, top_n),
        "by_year": [
            {"year": year, "count": count}
            for year, count in sorted(year_counts.items())
        ],
        "predictive_case_count": predictive["case_count"],
        "predictive_baseline": predictive["baseline"],
        "predictive_signals": predictive["signals"],
        "proactive_trends": proactive["trends"],
        "proactive_thresholds": proactive["thresholds"],
        "proactive_fallback": proactive["fallback"],
        "risk_case_count": risk["case_count"],
        "risk_baseline": risk["baseline"],
        "risk_signals": risk["signals"],
    }


def _term_in_text(text: str, term: str) -> bool:
    if not term:
        return False
    escaped = re.escape(term.lower())
    return bool(re.search(rf"\\b{escaped}\\b", text))


def suggest_tags_from_text(
    db: Session,
    text: str,
    top_n: int = 8,
    min_length: int = 4,
) -> Dict[str, List[str]]:
    if not text or not isinstance(text, str):
        return {"tags": [], "contentious_issues": []}

    query = db.query(CaseLaw).filter(CaseLaw.extraction_status == "extracted")
    cases = query.all()

    tag_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    for case in cases:
        analysis = case.extracted_analysis or {}
        tag_counts.update(_normalize_list(analysis.get("tags")))
        issue_counts.update(_normalize_list(analysis.get("contentious_issues")))

    normalized_text = text.lower()
    matched_tags = [
        tag
        for tag in tag_counts.keys()
        if len(tag) >= min_length and _term_in_text(normalized_text, tag)
    ]
    matched_issues = [
        issue
        for issue in issue_counts.keys()
        if len(issue) >= min_length and _term_in_text(normalized_text, issue)
    ]

    matched_tags.sort(key=lambda t: (tag_counts[t], len(t)), reverse=True)
    matched_issues.sort(key=lambda t: (issue_counts[t], len(t)), reverse=True)

    return {
        "tags": matched_tags[:top_n],
        "contentious_issues": matched_issues[:top_n],
    }
