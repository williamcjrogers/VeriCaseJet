#!/usr/bin/env python
"""
Quick PST benchmark helper.

Usage:
  python scripts/pst_benchmark.py --pst /path/to/file.pst

What it does:
  - Opens the PST with pypff
  - Traverses all folders/messages once
  - Counts messages/attachments and reports elapsed time + throughput
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pypff  # type: ignore


def walk(folder: any) -> tuple[int, int]:
    """Return (message_count, attachment_count) recursively."""
    msg_count = int(getattr(folder, "number_of_sub_messages", 0) or 0)
    att_count = 0
    for i in range(msg_count):
        try:
            msg = folder.get_sub_message(i)
            att_count += int(getattr(msg, "number_of_attachments", 0) or 0)
        except Exception:
            continue
    for i in range(int(getattr(folder, "number_of_sub_folders", 0) or 0)):
        try:
            sub = folder.get_sub_folder(i)
            m, a = walk(sub)
            msg_count += m
            att_count += a
        except Exception:
            continue
    return msg_count, att_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PST traversal speed.")
    parser.add_argument("--pst", required=True, help="Path to PST file")
    args = parser.parse_args()

    pst_path = Path(args.pst)
    if not pst_path.exists():
        raise SystemExit(f"PST not found: {pst_path}")

    pst = pypff.file()
    pst.open(str(pst_path))

    root = pst.get_root_folder()
    start = time.time()
    messages, attachments = walk(root)
    elapsed = time.time() - start

    throughput = messages / elapsed if elapsed > 0 else 0
    print(f"PST: {pst_path}")
    print(f"Messages: {messages:,}")
    print(f"Attachments: {attachments:,}")
    print(f"Elapsed: {elapsed:.2f}s")
    print(f"Messages/sec: {throughput:.1f}")


if __name__ == "__main__":
    main()
