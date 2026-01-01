"""
One-off helper to migrate legacy teal literals in the static UI to design tokens.

This keeps the UI consistent with the "Clean Executive" theme:
- Replace legacy teal RGB literals with rgba(var(--vericase-teal-rgb), a)
- Replace legacy teal hex literals with var(--vericase-teal) / var(--vericase-teal-dark)

The script preserves original newlines by reading/writing with newline="".
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "vericase" / "ui"

EXTS = {".html", ".css", ".js"}
SKIP_DIR_PARTS = {"fontawesome", "webfonts"}

REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    # rgba(15, 157, 154, 0.12)  -> rgba(var(--vericase-teal-rgb), 0.12)
    (
        re.compile(r"rgba\(\s*15\s*,\s*157\s*,\s*154\s*,", re.IGNORECASE),
        "rgba(var(--vericase-teal-rgb),",
    ),
    # rgba(23, 181, 163, 0.12)  -> rgba(var(--vericase-teal-rgb), 0.12)
    (
        re.compile(r"rgba\(\s*23\s*,\s*181\s*,\s*163\s*,", re.IGNORECASE),
        "rgba(var(--vericase-teal-rgb),",
    ),
    # Hex fallbacks used before the design system tokens existed
    (re.compile(r"#0f9d9a", re.IGNORECASE), "var(--vericase-teal)"),
    (re.compile(r"#0a7d7a", re.IGNORECASE), "var(--vericase-teal-dark)"),
]


def should_skip(path: Path) -> bool:
    lower_parts = {p.lower() for p in path.parts}
    return any(skip in lower_parts for skip in SKIP_DIR_PARTS)


def migrate_file(path: Path) -> int:
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        original = f.read()

    updated = original
    for pattern, replacement in REPLACEMENTS:
        updated = pattern.sub(replacement, updated)

    if updated == original:
        return 0

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(updated)

    return 1


def main() -> None:
    if not ROOT.exists():
        raise SystemExit(f"UI root not found: {ROOT}")

    changed_files: list[Path] = []
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        if should_skip(path):
            continue
        if path.suffix.lower() not in EXTS:
            continue

        if migrate_file(path):
            changed_files.append(path)

    print(f"Changed {len(changed_files)} file(s).")
    for p in changed_files:
        print(f"- {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
