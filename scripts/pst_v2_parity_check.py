"""
Ruthless V2 cutover parity checks: compare a "baseline" PST ingest vs a "candidate" PST ingest.

This script is intentionally DB-schema-aware of the current VeriCase models:
- Emails: email_messages
- Attachments: email_attachments (hash column is attachment_hash)
- OCR docs: documents (attachments are Documents where metadata->>'is_email_attachment' = 'true')
- Transport headers presence is tracked in email_messages.metadata->>'transport_headers_present'

Usage (PowerShell):
  python scripts/pst_v2_parity_check.py `
    --baseline-pst-file-id <uuid> `
    --candidate-pst-file-id <uuid> `
    --database-url $env:DATABASE_URL

Exit code:
  0 = all BLOCKER gates pass
  2 = one or more BLOCKER gates fail
  3 = script error / could not run checks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg2
import psycopg2.extras


@dataclass
class GateResult:
    name: str
    severity: str  # "BLOCKER" | "WARNING"
    passed: bool
    details: dict[str, Any]


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _pct(n: int, d: int) -> float:
    if d <= 0:
        return 0.0
    return (float(n) * 100.0) / float(d)


def _connect(database_url: str):
    # Use dict cursors for clarity in queries.
    return psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)


def _q1(conn, sql: str, params: dict[str, Any]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else {}


def _qall(conn, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _email_counts(conn, pst_file_id: str) -> dict[str, int]:
    row = _q1(
        conn,
        """
        SELECT
          COUNT(*)::bigint AS total_emails,
          COUNT(DISTINCT message_id)::bigint AS distinct_message_id,
          COUNT(*) FILTER (WHERE body_text IS NOT NULL)::bigint AS emails_with_body_text
        FROM email_messages
        WHERE pst_file_id = %(pst_file_id)s::uuid
        """,
        {"pst_file_id": pst_file_id},
    )
    return {k: int(row.get(k, 0) or 0) for k in row.keys()}


def _pst_file_status(conn, pst_file_id: str) -> dict[str, Any]:
    row = _q1(
        conn,
        """
        SELECT
          id::text AS pst_file_id,
          processing_status,
          error_message,
          processing_started_at,
          processing_completed_at,
          total_emails,
          processed_emails
        FROM pst_files
        WHERE id = %(pst_file_id)s::uuid
        """,
        {"pst_file_id": pst_file_id},
    )
    return row


def _attachment_counts(conn, pst_file_id: str) -> dict[str, int]:
    row = _q1(
        conn,
        """
        SELECT COUNT(a.*)::bigint AS total_attachments
        FROM email_attachments a
        JOIN email_messages m ON m.id = a.email_message_id
        WHERE m.pst_file_id = %(pst_file_id)s::uuid
        """,
        {"pst_file_id": pst_file_id},
    )
    return {"total_attachments": int(row.get("total_attachments", 0) or 0)}


def _field_presence(conn, pst_file_id: str) -> dict[str, Any]:
    # Note: "transport headers presence" is tracked in metadata JSON (not a dedicated column).
    row = _q1(
        conn,
        """
        SELECT
          COUNT(*)::bigint AS total,
          COUNT(*) FILTER (WHERE metadata ? 'transport_headers_present' AND (metadata->>'transport_headers_present')::boolean = true)::bigint AS transport_headers_present,
          COUNT(*) FILTER (WHERE conversation_index IS NOT NULL)::bigint AS conversation_index_present,
          COUNT(*) FILTER (WHERE in_reply_to IS NOT NULL)::bigint AS in_reply_to_present,
          COUNT(*) FILTER (WHERE email_references IS NOT NULL)::bigint AS email_references_present,
          COUNT(*) FILTER (WHERE pst_message_path IS NOT NULL)::bigint AS pst_message_path_present
        FROM email_messages
        WHERE pst_file_id = %(pst_file_id)s::uuid
        """,
        {"pst_file_id": pst_file_id},
    )
    total = int(row.get("total", 0) or 0)
    out = {"total": total}
    for k in [
        "transport_headers_present",
        "conversation_index_present",
        "in_reply_to_present",
        "email_references_present",
        "pst_message_path_present",
    ]:
        out[k] = int(row.get(k, 0) or 0)
        out[k.replace("_present", "_pct")] = _pct(out[k], total)
    return out


def _threading_stats(conn, pst_file_id: str) -> dict[str, int]:
    row = _q1(
        conn,
        """
        SELECT
          COUNT(DISTINCT thread_id)::bigint FILTER (WHERE thread_id IS NOT NULL) AS thread_count,
          COUNT(*)::bigint FILTER (WHERE thread_id IS NULL) AS orphan_emails,
          COUNT(*)::bigint FILTER (WHERE parent_message_id IS NOT NULL) AS parent_links
        FROM email_messages
        WHERE pst_file_id = %(pst_file_id)s::uuid
        """,
        {"pst_file_id": pst_file_id},
    )
    return {
        k: int(row.get(k, 0) or 0)
        for k in ["thread_count", "orphan_emails", "parent_links"]
    }


def _multiset_diff_counts(
    conn,
    *,
    baseline_pst_file_id: str,
    candidate_pst_file_id: str,
    table_sql: str,
    key_expr_sql: str,
    where_sql: str,
    params: dict[str, Any],
) -> dict[str, int]:
    """
    Compare multisets of key_expr for baseline vs candidate, returning:
      - mismatched_keys: number of keys whose counts differ
      - total_count_delta: sum(abs(delta)) across keys
    """
    # Important: NULLs do not join in SQL (NULL != NULL). Coalesce keys to a sentinel so NULL counts compare correctly.
    key_sql = f"COALESCE(({key_expr_sql})::text, '__VC_NULL__')"
    sql = f"""
    WITH
      a AS (
        SELECT {key_sql} AS k, COUNT(*)::bigint AS n
        FROM {table_sql}
        WHERE {where_sql}
        GROUP BY {key_sql}
      ),
      b AS (
        SELECT {key_sql} AS k, COUNT(*)::bigint AS n
        FROM {table_sql}
        WHERE {where_sql.replace('%(pst_file_id)s', '%(candidate_pst_file_id)s')}
        GROUP BY {key_sql}
      ),
      diff AS (
        SELECT COALESCE(a.k, b.k) AS k, COALESCE(a.n, 0)::bigint AS a_n, COALESCE(b.n, 0)::bigint AS b_n
        FROM a
        FULL OUTER JOIN b USING (k)
        WHERE COALESCE(a.n, 0) <> COALESCE(b.n, 0)
      )
    SELECT
      COUNT(*)::bigint AS mismatched_keys,
      COALESCE(SUM(ABS(b_n - a_n))::bigint, 0) AS total_count_delta
    FROM diff
    """
    row = _q1(
        conn,
        sql,
        {
            **params,
            "pst_file_id": baseline_pst_file_id,
            "candidate_pst_file_id": candidate_pst_file_id,
        },
    )
    return {
        "mismatched_keys": int(row.get("mismatched_keys", 0) or 0),
        "total_count_delta": int(row.get("total_count_delta", 0) or 0),
    }


def _content_hash_multiset(conn, baseline: str, candidate: str) -> dict[str, int]:
    # Strong check: content_hash includes canonical body + from + to + subject + date (see email_normalizer.build_content_hash).
    return _multiset_diff_counts(
        conn,
        baseline_pst_file_id=baseline,
        candidate_pst_file_id=candidate,
        table_sql="email_messages",
        key_expr_sql="content_hash",
        where_sql="pst_file_id = %(pst_file_id)s::uuid",
        params={},
    )


def _message_id_multiset(conn, baseline: str, candidate: str) -> dict[str, int]:
    # Stronger than "distinct count": verifies the multiset of message_id values matches (including NULL counts).
    return _multiset_diff_counts(
        conn,
        baseline_pst_file_id=baseline,
        candidate_pst_file_id=candidate,
        table_sql="email_messages",
        key_expr_sql="message_id",
        where_sql="pst_file_id = %(pst_file_id)s::uuid",
        params={},
    )


def _attachment_hash_multiset(conn, baseline: str, candidate: str) -> dict[str, int]:
    # Compare attachment_hash across the two ingests (joined via pst_file_id through email_messages).
    return _multiset_diff_counts(
        conn,
        baseline_pst_file_id=baseline,
        candidate_pst_file_id=candidate,
        table_sql="email_attachments a JOIN email_messages m ON m.id = a.email_message_id",
        key_expr_sql="a.attachment_hash",
        where_sql="m.pst_file_id = %(pst_file_id)s::uuid",
        params={},
    )


def _attachments_per_email_multiset(
    conn, baseline: str, candidate: str
) -> dict[str, int]:
    # Compare distribution of attachment counts per email by using email content_hash as a stable-ish grouping key.
    # This avoids relying on email_message_id which differs across ingests.
    sql = """
    WITH
      a AS (
        SELECT COALESCE(m.content_hash::text, '__VC_NULL__') AS k, COUNT(a.*)::bigint AS n
        FROM email_messages m
        LEFT JOIN email_attachments a ON a.email_message_id = m.id
        WHERE m.pst_file_id = %(baseline)s::uuid
        GROUP BY COALESCE(m.content_hash::text, '__VC_NULL__')
      ),
      b AS (
        SELECT COALESCE(m.content_hash::text, '__VC_NULL__') AS k, COUNT(a.*)::bigint AS n
        FROM email_messages m
        LEFT JOIN email_attachments a ON a.email_message_id = m.id
        WHERE m.pst_file_id = %(candidate)s::uuid
        GROUP BY COALESCE(m.content_hash::text, '__VC_NULL__')
      ),
      diff AS (
        SELECT COALESCE(a.k, b.k) AS k, COALESCE(a.n, 0)::bigint AS a_n, COALESCE(b.n, 0)::bigint AS b_n
        FROM a
        FULL OUTER JOIN b USING (k)
        WHERE COALESCE(a.n, 0) <> COALESCE(b.n, 0)
      )
    SELECT
      COUNT(*)::bigint AS mismatched_keys,
      COALESCE(SUM(ABS(b_n - a_n))::bigint, 0) AS total_count_delta
    FROM diff
    """
    row = _q1(conn, sql, {"baseline": baseline, "candidate": candidate})
    return {
        "mismatched_keys": int(row.get("mismatched_keys", 0) or 0),
        "total_count_delta": int(row.get("total_count_delta", 0) or 0),
    }


def _ocr_stats(conn, pst_file_id: str) -> dict[str, int]:
    # Attachment documents are linked to the PST via documents.metadata->>'email_message_id' -> email_messages.id
    row = _q1(
        conn,
        """
        SELECT
          COUNT(d.*)::bigint AS docs_total,
          COUNT(d.*)::bigint FILTER (WHERE d.status = 'NEW') AS docs_new,
          COUNT(d.*)::bigint FILTER (WHERE d.status = 'READY') AS docs_ready,
          COUNT(d.*)::bigint FILTER (WHERE d.status = 'FAILED') AS docs_failed,
          COUNT(d.*)::bigint FILTER (WHERE d.text_excerpt IS NOT NULL AND length(btrim(d.text_excerpt)) > 0) AS docs_text_present
        FROM documents d
        JOIN email_messages m
          ON m.id::text = (d.metadata->>'email_message_id')
        WHERE
          (d.metadata->>'is_email_attachment')::boolean = true
          AND m.pst_file_id = %(pst_file_id)s::uuid
        """,
        {"pst_file_id": pst_file_id},
    )
    return {k: int(row.get(k, 0) or 0) for k in row.keys()}


def _compare_exact(a: int, b: int) -> tuple[bool, dict[str, Any]]:
    return (a == b), {"baseline": a, "candidate": b, "delta": int(b - a)}


def _compare_pct(
    candidate_pct: float, baseline_pct: float, tolerance_pp: float = 1.0
) -> tuple[bool, dict[str, Any]]:
    # Pass if candidate >= baseline - tolerance
    passed = candidate_pct + 1e-9 >= (baseline_pct - tolerance_pp)
    return passed, {
        "baseline_pct": baseline_pct,
        "candidate_pct": candidate_pct,
        "tolerance_pp": tolerance_pp,
        "delta_pp": candidate_pct - baseline_pct,
    }


def _compare_ratio(
    candidate: int, baseline: int, max_delta_ratio: float
) -> tuple[bool, dict[str, Any]]:
    if baseline <= 0 and candidate <= 0:
        return True, {"baseline": baseline, "candidate": candidate, "delta_ratio": 0.0}
    if baseline <= 0:
        # Baseline has nothing; treat any candidate data as fine for threading metrics (not a blocker by itself).
        return True, {"baseline": baseline, "candidate": candidate, "delta_ratio": None}
    delta_ratio = abs(candidate - baseline) / float(baseline)
    return (delta_ratio <= max_delta_ratio), {
        "baseline": baseline,
        "candidate": candidate,
        "delta_ratio": delta_ratio,
        "max_delta_ratio": max_delta_ratio,
    }


def run_checks(
    database_url: str, baseline: str, candidate: str, run_s3_head: bool
) -> dict[str, Any]:
    started_at = _now_iso()
    gates: list[GateResult] = []
    meta: dict[str, Any] = {
        "started_at": started_at,
        "baseline_pst_file_id": baseline,
        "candidate_pst_file_id": candidate,
    }

    with _connect(database_url) as conn:
        conn.autocommit = True

        # ---------------------------
        # Gate 0: Both runs completed without error_message
        # ---------------------------
        b_pst = _pst_file_status(conn, baseline)
        c_pst = _pst_file_status(conn, candidate)

        def _ok_completed(pst_row: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
            status = (pst_row.get("processing_status") or "").lower()
            err = pst_row.get("error_message")
            return (status == "completed" and not err), {
                "processing_status": pst_row.get("processing_status"),
                "error_message": err,
                "processing_started_at": str(pst_row.get("processing_started_at")),
                "processing_completed_at": str(pst_row.get("processing_completed_at")),
                "total_emails": pst_row.get("total_emails"),
                "processed_emails": pst_row.get("processed_emails"),
            }

        ok, details = _ok_completed(b_pst)
        gates.append(
            GateResult(
                "PST status: baseline completed with no error_message",
                "BLOCKER",
                ok,
                details,
            )
        )

        ok, details = _ok_completed(c_pst)
        gates.append(
            GateResult(
                "PST status: candidate completed with no error_message",
                "BLOCKER",
                ok,
                details,
            )
        )

        # ---------------------------
        # Gate 1: Extraction counts
        # ---------------------------
        b_emails = _email_counts(conn, baseline)
        c_emails = _email_counts(conn, candidate)
        b_atts = _attachment_counts(conn, baseline)
        c_atts = _attachment_counts(conn, candidate)

        ok, details = _compare_exact(b_emails["total_emails"], c_emails["total_emails"])
        gates.append(
            GateResult("Extraction: total emails exact", "BLOCKER", ok, details)
        )

        ok, details = _compare_exact(
            b_atts["total_attachments"], c_atts["total_attachments"]
        )
        gates.append(
            GateResult("Extraction: total attachments exact", "BLOCKER", ok, details)
        )

        ok, details = _compare_exact(
            b_emails["distinct_message_id"], c_emails["distinct_message_id"]
        )
        gates.append(
            GateResult("Extraction: distinct message_id exact", "BLOCKER", ok, details)
        )

        msg_diff = _message_id_multiset(conn, baseline, candidate)
        ok = (msg_diff["mismatched_keys"] == 0) and (msg_diff["total_count_delta"] == 0)
        gates.append(
            GateResult("Integrity: message_id multiset exact", "BLOCKER", ok, msg_diff)
        )

        ok, details = _compare_exact(
            b_emails["emails_with_body_text"], c_emails["emails_with_body_text"]
        )
        gates.append(
            GateResult(
                "Extraction: emails with body_text exact", "BLOCKER", ok, details
            )
        )

        # -----------------------------------------
        # Gate 2: Forensic metadata presence >= V1
        # -----------------------------------------
        b_pres = _field_presence(conn, baseline)
        c_pres = _field_presence(conn, candidate)
        for field in [
            "transport_headers_pct",
            "conversation_index_pct",
            "in_reply_to_pct",
            "email_references_pct",
            "pst_message_path_pct",
        ]:
            ok, details = _compare_pct(c_pres[field], b_pres[field], tolerance_pp=1.0)
            gates.append(
                GateResult(
                    f"Forensics: {field} >= baseline (-1pp)", "BLOCKER", ok, details
                )
            )

        # -----------------------------------------
        # Gate 3: Content integrity via content_hash
        # -----------------------------------------
        ch_diff = _content_hash_multiset(conn, baseline, candidate)
        ok = (ch_diff["mismatched_keys"] == 0) and (ch_diff["total_count_delta"] == 0)
        gates.append(
            GateResult("Integrity: content_hash multiset exact", "BLOCKER", ok, ch_diff)
        )

        # -----------------------------------------
        # Gate 4: Attachment integrity (hash + per-email distribution)
        # -----------------------------------------
        ah_diff = _attachment_hash_multiset(conn, baseline, candidate)
        ok = (ah_diff["mismatched_keys"] == 0) and (ah_diff["total_count_delta"] == 0)
        gates.append(
            GateResult(
                "Integrity: attachment_hash multiset exact", "BLOCKER", ok, ah_diff
            )
        )

        per_email_diff = _attachments_per_email_multiset(conn, baseline, candidate)
        ok = (per_email_diff["mismatched_keys"] == 0) and (
            per_email_diff["total_count_delta"] == 0
        )
        gates.append(
            GateResult(
                "Integrity: attachments-per-email distribution exact (by content_hash)",
                "BLOCKER",
                ok,
                per_email_diff,
            )
        )

        # Optional: S3 head checks are expensive; keep as an explicit on-demand gate.
        if run_s3_head:
            # Pull distinct S3 objects for candidate and verify existence.
            objs = _qall(
                conn,
                """
                SELECT DISTINCT a.s3_bucket, a.s3_key
                FROM email_attachments a
                JOIN email_messages m ON m.id = a.email_message_id
                WHERE
                  m.pst_file_id = %(pst_file_id)s::uuid
                  AND a.s3_bucket IS NOT NULL
                  AND a.s3_key IS NOT NULL
                """,
                {"pst_file_id": candidate},
            )
            # We do the boto3 check in-process (single AWS auth context).
            try:
                import boto3
                from botocore.exceptions import ClientError
                from concurrent.futures import ThreadPoolExecutor

                s3 = boto3.client("s3")

                missing: list[dict[str, str]] = []

                def _head(bucket: str, key: str) -> tuple[bool, str]:
                    try:
                        s3.head_object(Bucket=bucket, Key=key)
                        return True, ""
                    except ClientError as e:
                        code = str(e.response.get("Error", {}).get("Code", ""))
                        return False, code

                with ThreadPoolExecutor(max_workers=32) as ex:
                    futs = [ex.submit(_head, o["s3_bucket"], o["s3_key"]) for o in objs]
                    for o, fut in zip(objs, futs):
                        ok_head, code = fut.result()
                        if not ok_head:
                            missing.append(
                                {
                                    "bucket": o["s3_bucket"],
                                    "key": o["s3_key"],
                                    "error": code,
                                }
                            )

                ok = len(missing) == 0
                gates.append(
                    GateResult(
                        "Integrity: S3 HEAD exists for all candidate attachments",
                        "BLOCKER",
                        ok,
                        {
                            "checked": len(objs),
                            "missing": len(missing),
                            "missing_samples": missing[:10],
                        },
                    )
                )
            except Exception as e:
                gates.append(
                    GateResult(
                        "Integrity: S3 HEAD exists for all candidate attachments",
                        "BLOCKER",
                        False,
                        {
                            "error": f"Could not run S3 head checks: {e.__class__.__name__}: {e}"
                        },
                    )
                )

        # ---------------------------
        # Gate 5: Threading parity
        # ---------------------------
        b_thr = _threading_stats(conn, baseline)
        c_thr = _threading_stats(conn, candidate)

        ok_warn, details = _compare_ratio(
            c_thr["thread_count"], b_thr["thread_count"], max_delta_ratio=0.01
        )
        gates.append(
            GateResult(
                "Threading: distinct thread_id delta <= 1%", "WARNING", ok_warn, details
            )
        )

        ok_warn, details = _compare_ratio(
            c_thr["orphan_emails"], b_thr["orphan_emails"], max_delta_ratio=0.01
        )
        gates.append(
            GateResult(
                "Threading: orphan emails delta <= 1%", "WARNING", ok_warn, details
            )
        )

        ok_warn, details = _compare_ratio(
            c_thr["parent_links"], b_thr["parent_links"], max_delta_ratio=0.01
        )
        gates.append(
            GateResult(
                "Threading: parent links delta <= 1%", "WARNING", ok_warn, details
            )
        )

        ok_block, details = _compare_ratio(
            c_thr["thread_count"], b_thr["thread_count"], max_delta_ratio=0.05
        )
        gates.append(
            GateResult(
                "Threading: distinct thread_id delta <= 5% (hard stop)",
                "BLOCKER",
                ok_block,
                details,
            )
        )

        # ---------------------------
        # Gate 6: OCR coverage
        # ---------------------------
        b_ocr = _ocr_stats(conn, baseline)
        c_ocr = _ocr_stats(conn, candidate)

        ok, details = _compare_exact(b_ocr["docs_total"], c_ocr["docs_total"])
        gates.append(
            GateResult(
                "OCR: attachment Document records created exact", "BLOCKER", ok, details
            )
        )

        # Completed coverage is not a correctness blocker unless it drops too far.
        # Compare text_present ratio as the practical proxy for "OCR completed with usable text".
        b_ratio = _pct(b_ocr["docs_text_present"], b_ocr["docs_total"])
        c_ratio = _pct(c_ocr["docs_text_present"], c_ocr["docs_total"])
        ok_warn, details = _compare_pct(c_ratio, b_ratio, tolerance_pp=5.0)
        gates.append(
            GateResult(
                "OCR: text present ratio within 5pp of baseline",
                "WARNING",
                ok_warn,
                details,
            )
        )

        # Hard stop if < 90% of baseline (or if baseline itself is high and candidate collapses).
        ok_block, details = _compare_pct(c_ratio, b_ratio, tolerance_pp=10.0)
        gates.append(
            GateResult(
                "OCR: text present ratio within 10pp of baseline (hard stop)",
                "BLOCKER",
                ok_block,
                details,
            )
        )

        # ---------------------------
        # Gate 7: Performance (warning only)
        # ---------------------------
        def _duration_seconds(pst_row: dict[str, Any]) -> float | None:
            s = pst_row.get("processing_started_at")
            e = pst_row.get("processing_completed_at")
            if s and e and hasattr(e, "__sub__"):
                try:
                    return float((e - s).total_seconds())
                except Exception:
                    return None
            return None

        b_dur = _duration_seconds(b_pst)
        c_dur = _duration_seconds(c_pst)
        if b_dur is not None and c_dur is not None and b_dur > 0:
            ok_warn = c_dur <= b_dur
            gates.append(
                GateResult(
                    "Performance: candidate duration <= baseline (informational warning)",
                    "WARNING",
                    ok_warn,
                    {
                        "baseline_s": b_dur,
                        "candidate_s": c_dur,
                        "ratio": (c_dur / b_dur) if b_dur else None,
                    },
                )
            )

        meta.update(
            {
                "pst_files": {"baseline": b_pst, "candidate": c_pst},
                "baseline": {
                    "emails": b_emails,
                    "attachments": b_atts,
                    "presence": b_pres,
                    "threading": b_thr,
                    "ocr": b_ocr,
                },
                "candidate": {
                    "emails": c_emails,
                    "attachments": c_atts,
                    "presence": c_pres,
                    "threading": c_thr,
                    "ocr": c_ocr,
                },
            }
        )

    ended_at = _now_iso()
    blockers_failed = [g for g in gates if g.severity == "BLOCKER" and not g.passed]
    warnings_failed = [g for g in gates if g.severity == "WARNING" and not g.passed]

    return {
        "version": "v2-parity-1",
        "started_at": started_at,
        "ended_at": ended_at,
        "meta": meta,
        "summary": {
            "blockers_failed": len(blockers_failed),
            "warnings_failed": len(warnings_failed),
            "total_gates": len(gates),
        },
        "gates": [
            {
                "name": g.name,
                "severity": g.severity,
                "passed": g.passed,
                "details": g.details,
            }
            for g in gates
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="VeriCase PST V2 cutover parity checks (baseline vs candidate)."
    )
    ap.add_argument(
        "--baseline-pst-file-id",
        required=True,
        help="Baseline PST file UUID (V1 output).",
    )
    ap.add_argument(
        "--candidate-pst-file-id",
        required=True,
        help="Candidate PST file UUID (V2 output).",
    )
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Postgres URL (or set DATABASE_URL env var).",
    )
    ap.add_argument(
        "--json-out", default="", help="Write full JSON report to this path."
    )
    ap.add_argument(
        "--s3-head",
        action="store_true",
        help="Verify S3 objects exist for all candidate attachments (slow, requires AWS creds).",
    )

    args = ap.parse_args()
    if not args.database_url:
        print(
            "ERROR: Missing --database-url and DATABASE_URL env var is not set.",
            file=sys.stderr,
        )
        return 3

    try:
        report = run_checks(
            database_url=args.database_url,
            baseline=args.baseline_pst_file_id,
            candidate=args.candidate_pst_file_id,
            run_s3_head=bool(args.s3_head),
        )
    except Exception as e:
        print(
            f"ERROR: Parity check failed to run: {e.__class__.__name__}: {e}",
            file=sys.stderr,
        )
        return 3

    blockers_failed = int(report["summary"]["blockers_failed"])

    # Console summary (human-friendly).
    print(f"== VeriCase V2 Parity Report == ({report['version']})")
    print(f"Started: {report['started_at']}  Ended: {report['ended_at']}")
    print(f"Baseline PST:   {args.baseline_pst_file_id}")
    print(f"Candidate PST:  {args.candidate_pst_file_id}")
    print("")

    for g in report["gates"]:
        status = "PASS" if g["passed"] else "FAIL"
        print(f"[{status}] ({g['severity']}) {g['name']}")
        if not g["passed"]:
            print(f"       details: {json.dumps(g['details'], default=str)[:500]}")
    print("")

    print(f"Blockers failed: {report['summary']['blockers_failed']}")
    print(f"Warnings failed: {report['summary']['warnings_failed']}")

    if args.json_out:
        try:
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
            print(f"Wrote JSON report: {args.json_out}")
        except Exception as e:
            print(f"WARNING: Failed to write JSON report: {e}", file=sys.stderr)

    return 0 if blockers_failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
