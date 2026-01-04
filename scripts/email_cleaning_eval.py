from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


def _tokenize(value: str) -> list[str]:
    if not value:
        return []
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    toks = [t for t in value.split() if t]
    return toks


def _f1(pred: str, gold: str) -> float:
    pt = _tokenize(pred)
    gt = _tokenize(gold)
    if not gt and not pt:
        return 1.0
    if not gt or not pt:
        return 0.0
    ps = set(pt)
    gs = set(gt)
    inter = len(ps & gs)
    if inter <= 0:
        return 0.0
    precision = inter / max(len(ps), 1)
    recall = inter / max(len(gs), 1)
    denom = precision + recall
    return (2 * precision * recall / denom) if denom else 0.0


@dataclass
class GoldenCase:
    id: str
    description: str
    body_text: str | None
    body_html: str | None
    must_contain: list[str]
    must_not_contain: list[str]
    expected_clean: str | None = None
    min_f1: float | None = None


def load_cases(path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            cases.append(
                GoldenCase(
                    id=str(obj["id"]),
                    description=str(obj.get("description") or obj["id"]),
                    body_text=(obj.get("input") or {}).get("body_text"),
                    body_html=(obj.get("input") or {}).get("body_html"),
                    must_contain=list(
                        (obj.get("expect") or {}).get("must_contain") or []
                    ),
                    must_not_contain=list(
                        (obj.get("expect") or {}).get("must_not_contain") or []
                    ),
                    expected_clean=(obj.get("expect") or {}).get("expected_clean"),
                    min_f1=(obj.get("expect") or {}).get("min_f1"),
                )
            )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate email display-body cleaning")
    parser.add_argument(
        "--dataset",
        default=str(
            Path("vericase/tests/fixtures/email_cleaning_golden.jsonl").as_posix()
        ),
        help="Path to JSONL dataset",
    )
    args = parser.parse_args()

    dataset = Path(args.dataset)
    if not dataset.exists():
        print(f"Dataset not found: {dataset}", file=sys.stderr)
        return 2

    # Allow callers to tune languages without changing code.
    if not os.getenv("EMAIL_REPLY_LANGUAGES"):
        os.environ["EMAIL_REPLY_LANGUAGES"] = "en,fr,de,es,it,pt,nl"

    from vericase.api.app.email_normalizer import clean_email_body_for_display

    cases = load_cases(dataset)
    failed: list[tuple[str, str]] = []
    f1_scores: list[float] = []

    for c in cases:
        out = (
            clean_email_body_for_display(
                body_text_clean=None,
                body_text=c.body_text,
                body_html=c.body_html,
            )
            or ""
        )

        out_l = out.lower()
        ok = True
        for needle in c.must_contain:
            if needle.lower() not in out_l:
                ok = False
                failed.append((c.id, f"missing must_contain: {needle!r}"))
        for needle in c.must_not_contain:
            if needle.lower() in out_l:
                ok = False
                failed.append((c.id, f"found must_not_contain: {needle!r}"))

        if c.expected_clean and c.min_f1 is not None:
            score = _f1(out, c.expected_clean)
            f1_scores.append(score)
            if score < c.min_f1:
                ok = False
                failed.append((c.id, f"F1 {score:.3f} < {c.min_f1:.3f}"))

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {c.id}: {c.description}")
        if not ok:
            preview = out.replace("\n", "\\n")
            print(f"  output_preview={preview[:240]}")

    total = len(cases)
    fails = len({cid for cid, _ in failed})
    pass_count = total - fails
    avg_f1 = (sum(f1_scores) / len(f1_scores)) if f1_scores else None

    print("\n=== Summary ===")
    print(f"cases={total} pass={pass_count} fail={fails}")
    if avg_f1 is not None:
        print(f"avg_f1={avg_f1:.3f}")

    if fails:
        print("\n=== Failures ===")
        for cid, msg in failed:
            print(f"- {cid}: {msg}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
