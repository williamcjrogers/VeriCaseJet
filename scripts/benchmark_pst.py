"""
Lightweight PST performance benchmark for VeriCaseJet.

Measures:
  - PST open time
  - Optional pre-count traversal time
  - Message iteration + lightweight header/body extraction
  - Threading reconstruction time (Message-ID / References / Conversation-Index / Subject)

This script does NOT write to the database or S3. It is intended for local profiling
of the libpff/pypff parsing layer and core extraction logic.

Usage (PowerShell):
  python scripts/benchmark_pst.py --pst-path C:\\path\\to\\mailbox.pst
  python scripts/benchmark_pst.py --pst-path mailbox.pst --no-precount --max-messages 50000 --profile
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


try:
    import pypff  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"pypff is required to run this benchmark: {exc}")
    sys.exit(1)


def safe_get_attr(obj: Any, attr_name: str, default: Any | None = None) -> Any:
    try:
        if not hasattr(obj, attr_name):
            return default
        value = getattr(obj, attr_name)
        return value() if callable(value) else value
    except Exception:
        return default


def get_header(message: Any, header_name: str) -> str | None:
    try:
        headers = safe_get_attr(message, "transport_headers")
        if not headers:
            return None
        if isinstance(headers, bytes):
            headers = headers.decode("utf-8", errors="replace")

        current_header: str | None = None
        current_value: list[str] = []
        for line in str(headers).split("\n"):
            if line.startswith((" ", "\t")) and current_header:
                current_value.append(line.strip())
            elif ":" in line:
                if current_header and current_header.lower() == header_name.lower():
                    value = " ".join(current_value).strip()
                    if value.startswith("<") and value.endswith(">"):
                        value = value[1:-1]
                    return value
                colon_idx = line.index(":")
                current_header = line[:colon_idx].strip()
                current_value = [line[colon_idx + 1 :].strip()]

        if current_header and current_header.lower() == header_name.lower():
            value = " ".join(current_value).strip()
            if value.startswith("<") and value.endswith(">"):
                value = value[1:-1]
            return value
    except Exception:
        return None
    return None


def count_messages(folder: Any) -> int:
    try:
        count = int(safe_get_attr(folder, "number_of_sub_messages", 0) or 0)
        num_subfolders = int(safe_get_attr(folder, "number_of_sub_folders", 0) or 0)
        for i in range(num_subfolders):
            try:
                subfolder = folder.get_sub_folder(i)
                count += count_messages(subfolder)
            except Exception:
                continue
        return count
    except Exception:
        return 0


def iter_messages(folder: Any, folder_path: str = "") -> Iterable[tuple[Any, str]]:
    folder_name = safe_get_attr(folder, "name", "Root") or "Root"
    current_path = f"{folder_path}/{folder_name}" if folder_path else folder_name

    num_messages = int(safe_get_attr(folder, "number_of_sub_messages", 0) or 0)
    for i in range(num_messages):
        try:
            yield folder.get_sub_message(i), current_path
        except Exception:
            continue

    num_subfolders = int(safe_get_attr(folder, "number_of_sub_folders", 0) or 0)
    for i in range(num_subfolders):
        try:
            subfolder = folder.get_sub_folder(i)
            yield from iter_messages(subfolder, current_path)
        except Exception:
            continue


@dataclass
class ThreadRecord:
    message_id: str | None
    in_reply_to: str | None
    references: str | None
    conversation_index: str | None
    subject: str
    date_sent: datetime | None


def build_threads(records: list[ThreadRecord]) -> tuple[int, list[str]]:
    message_id_map: dict[str, str] = {}
    conv_index_map: dict[str, str] = {}
    subject_map: dict[str, str] = {}
    thread_ids: list[str] = []

    # Index message-id -> placeholder thread_id (assigned later)
    for rec in records:
        if rec.message_id:
            message_id_map[rec.message_id] = ""

    thread_counter = 0
    for rec in records:
        thread_id: str | None = None
        if rec.in_reply_to and rec.in_reply_to in message_id_map:
            parent_tid = message_id_map.get(rec.in_reply_to)
            if parent_tid:
                thread_id = parent_tid

        if not thread_id and rec.references:
            ref_ids = (
                [r.strip().strip("<>") for r in rec.references.split(",")]
                if "," in rec.references
                else [r.strip().strip("<>") for r in rec.references.split()]
            )
            for ref in ref_ids:
                parent_tid = message_id_map.get(ref)
                if parent_tid:
                    thread_id = parent_tid
                    break

        if not thread_id and rec.conversation_index:
            thread_id = conv_index_map.get(rec.conversation_index)

        if not thread_id and rec.subject:
            norm_subj = re.sub(r"^(re|fw|fwd):\s*", "", rec.subject.lower().strip())
            thread_id = subject_map.get(norm_subj)

        if not thread_id:
            thread_counter += 1
            thread_id = f"thread_{thread_counter}"

        # update indices for future lookups
        if rec.message_id:
            message_id_map[rec.message_id] = thread_id
        if rec.conversation_index and rec.conversation_index not in conv_index_map:
            conv_index_map[rec.conversation_index] = thread_id
        if rec.subject:
            norm_subj = re.sub(r"^(re|fw|fwd):\s*", "", rec.subject.lower().strip())
            if norm_subj and norm_subj not in subject_map:
                subject_map[norm_subj] = thread_id

        thread_ids.append(thread_id)

    unique_threads = len(set(thread_ids))
    return unique_threads, thread_ids


def run_benchmark(args: argparse.Namespace) -> None:
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    pst = pypff.file()
    pst.open(args.pst_path)
    timings["open_s"] = time.perf_counter() - t0

    root = pst.get_root_folder()

    total = None
    if args.precount:
        t1 = time.perf_counter()
        total = count_messages(root)
        timings["precount_s"] = time.perf_counter() - t1

    # Iterate messages
    t2 = time.perf_counter()
    records: list[ThreadRecord] = []
    attachments = 0
    read_bytes = 0

    for idx, (msg, _) in enumerate(iter_messages(root), start=1):
        if args.max_messages and idx > args.max_messages:
            break

        message_id = get_header(msg, "Message-ID")
        in_reply_to = get_header(msg, "In-Reply-To")
        references = get_header(msg, "References")
        subject = safe_get_attr(msg, "subject", "") or ""

        # conversation index
        conversation_index = None
        conv_idx_raw = safe_get_attr(msg, "conversation_index")
        if conv_idx_raw:
            try:
                conversation_index = (
                    conv_idx_raw.hex()
                    if hasattr(conv_idx_raw, "hex")
                    else str(conv_idx_raw)
                )
            except Exception:
                conversation_index = None

        # dates
        email_date = safe_get_attr(msg, "delivery_time") or safe_get_attr(
            msg, "client_submit_time"
        )
        if email_date and getattr(email_date, "tzinfo", None) is None:
            email_date = email_date.replace(tzinfo=timezone.utc)

        # attachments
        num_atts = int(safe_get_attr(msg, "number_of_attachments", 0) or 0)
        attachments += num_atts

        if args.read_attachments and num_atts:
            for i in range(num_atts):
                try:
                    att = msg.get_attachment(i)
                    size = int(safe_get_attr(att, "size", 0) or 0)
                    if size and hasattr(att, "read_buffer"):
                        data = att.read_buffer(size)
                        read_bytes += len(data or b"")
                except Exception:
                    continue

        records.append(
            ThreadRecord(
                message_id=message_id,
                in_reply_to=in_reply_to,
                references=references,
                conversation_index=conversation_index,
                subject=subject,
                date_sent=email_date,
            )
        )

    timings["iterate_s"] = time.perf_counter() - t2

    # Threading
    t3 = time.perf_counter()
    unique_threads, _ = build_threads(records)
    timings["threading_s"] = time.perf_counter() - t3

    pst.close()

    processed = len(records)
    print("\n=== PST Benchmark Results ===")
    print(f"PST: {args.pst_path}")
    if total is not None:
        print(f"Total messages (precount): {total}")
    print(f"Processed messages: {processed}")
    print(f"Attachments seen: {attachments}")
    if args.read_attachments:
        print(f"Attachment bytes read: {read_bytes}")
    print(f"Unique threads: {unique_threads}")
    print("")
    for k, v in timings.items():
        print(f"{k}: {v:.3f}s")
    if processed:
        print(f"throughput_msgs_per_s: {processed / timings['iterate_s']:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PST parsing/extraction.")
    parser.add_argument("--pst-path", required=True, help="Path to local .pst file")
    parser.add_argument(
        "--no-precount",
        dest="precount",
        action="store_false",
        help="Skip pre-count traversal",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=0,
        help="Stop after N messages (0 = all)",
    )
    parser.add_argument(
        "--read-attachments",
        action="store_true",
        help="Read attachment buffers to include I/O cost",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Run under cProfile and print top functions",
    )
    parser.set_defaults(precount=True)
    args = parser.parse_args()

    if args.profile:
        prof = cProfile.Profile()
        prof.enable()
        run_benchmark(args)
        prof.disable()
        s = io.StringIO()
        pstats.Stats(prof, stream=s).sort_stats("cumulative").print_stats(30)
        print("\n=== cProfile top 30 ===")
        print(s.getvalue())
    else:
        run_benchmark(args)


if __name__ == "__main__":
    main()
