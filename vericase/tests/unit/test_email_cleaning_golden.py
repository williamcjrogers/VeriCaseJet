from __future__ import annotations

import json
from pathlib import Path

import pytest

from vericase.api.app.email_normalizer import clean_email_body_for_display


DATASET = Path("vericase/tests/fixtures/email_cleaning_golden.jsonl")


@pytest.mark.parametrize("raw", DATASET.read_text(encoding="utf-8").splitlines())
def test_email_cleaning_golden_cases(raw: str) -> None:
    raw = (raw or "").strip()
    if not raw:
        return
    obj = json.loads(raw)

    body_text = (obj.get("input") or {}).get("body_text")
    body_html = (obj.get("input") or {}).get("body_html")
    must_contain = list((obj.get("expect") or {}).get("must_contain") or [])
    must_not_contain = list((obj.get("expect") or {}).get("must_not_contain") or [])

    out = (
        clean_email_body_for_display(
            body_text_clean=None,
            body_text=body_text,
            body_html=body_html,
        )
        or ""
    )
    out_l = out.lower()

    for needle in must_contain:
        assert needle.lower() in out_l, f"missing must_contain={needle!r}, out={out!r}"
    for needle in must_not_contain:
        assert (
            needle.lower() not in out_l
        ), f"found must_not_contain={needle!r}, out={out!r}"
