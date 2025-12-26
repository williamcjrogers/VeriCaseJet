#!/usr/bin/env python3
"""
Extract FIDIC case table rows and links from the PDF into CSV/JSON.

Usage:
  python scripts/extract_fidic_cases.py --input "C:/path/to/table-of-fidic-cases.pdf"
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber


def _clean(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\u00a0", " ").split())


def _safe_row(row: List[Any], index: int) -> str:
    try:
        return _clean(row[index])
    except Exception:
        return ""


def _match_link_words(page: pdfplumber.page.Page) -> List[str]:
    link_words = [
        w
        for w in page.extract_words()
        if w["text"].strip().lower() in {"link", "link*"}
    ]
    link_words.sort(key=lambda w: w["top"])
    uris: List[str] = []
    for word in link_words:
        uri = ""
        for h in page.hyperlinks:
            if not h.get("uri"):
                continue
            if abs(float(h.get("top", 0)) - float(word["top"])) < 2.5:
                uri = h["uri"]
                break
        uris.append(uri)
    return uris


def extract_rows(pdf_path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            if not tables:
                continue
            page_links = _match_link_words(page)
            link_idx = 0

            for table in tables:
                if not table or len(table) < 2:
                    continue
                header = " ".join(_clean(c).lower() for c in table[0])
                if "case name" not in header:
                    continue

                data_rows = [
                    row
                    for row in table[1:]
                    if row and any((cell or "").strip() for cell in row)
                ]
                if not data_rows:
                    continue

                if (
                    len(page_links) > len(data_rows)
                    and page_links
                    and not page_links[0]
                ):
                    page_links = page_links[1:]

                for row in data_rows:
                    link = page_links[link_idx] if link_idx < len(page_links) else ""
                    link_idx += 1
                    record = {
                        "page": page_number,
                        "year": _safe_row(row, 0),
                        "case_name": _safe_row(row, 1),
                        "jurisdiction": _safe_row(row, 2),
                        "fidic_books": _safe_row(row, 3),
                        "summary": _safe_row(row, 4),
                        "link_label": _safe_row(row, 5),
                        "link": link,
                    }
                    records.append(record)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract FIDIC cases from PDF")
    parser.add_argument("--input", required=True, help="Path to PDF file")
    parser.add_argument(
        "--output-csv",
        default="docs/fidic_cases.csv",
        help="CSV output path",
    )
    parser.add_argument(
        "--output-json",
        default="docs/fidic_cases.json",
        help="JSON output path",
    )
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    records = extract_rows(pdf_path)

    csv_path = Path(args.output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "page",
                "year",
                "case_name",
                "jurisdiction",
                "fidic_books",
                "summary",
                "link_label",
                "link",
            ],
        )
        writer.writeheader()
        writer.writerows(records)

    json_path = Path(args.output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    print(f"Wrote {len(records)} rows to {csv_path} and {json_path}")


if __name__ == "__main__":
    main()
