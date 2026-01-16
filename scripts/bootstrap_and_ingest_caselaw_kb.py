#!/usr/bin/env python3
"""Bootstrap CaseLaw DB rows from curated S3, export KB-ready docs into the KB S3 data source, then trigger Bedrock KB ingestion.

This is intended for environments where:
- Curated caselaw JSON exists in S3 (e.g., s3://vericase-caselaw-curated/...) but
- The database has no rows in the case_law table yet, so KB export would write 0 docs.

Safe/idempotent behavior:
- If the CaseLaw table is non-empty, bootstrap is skipped.
- Inserts are best-effort; duplicate citations are skipped.

Typical run (in-cluster):
  python /tmp/bootstrap_and_ingest_caselaw_kb.py --limit-export 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable

import boto3
from sqlalchemy.exc import IntegrityError

# When run via `kubectl exec ... python /tmp/script.py`, Python sets sys.path[0]
# to the script directory (/tmp) which may not include the app code directory.
# In this repo's containers, application code is located under /code.
if "/code" not in sys.path:
    try:
        import os

        if os.path.isdir("/code"):
            sys.path.insert(0, "/code")
    except Exception:
        # Best-effort only; if imports fail below, the error will be explicit.
        pass

# These imports must work inside the API container.
from app.config import settings
from app.db import SessionLocal
from app.models import CaseLaw
from app.services.caselaw_kb_sync import export_caselaw_docs_to_knowledge_base


BUCKET_CURATED_DEFAULT = "vericase-caselaw-curated"
PREFIXES_DEFAULT = ("fenwick_elliott/curated/", "lex/curated/")

# Matches common UK neutral citation forms like:
#   [2015] EWHC 2692 (TCC)
#   [2023] EWCA Civ 123
_CIT_RE = re.compile(
    r"(\[[12]\d{3}\]\s+[A-Z][A-Za-z0-9 .\-/]{1,40}\s+\d{1,6}(?:\s*\([A-Za-z0-9 .\-/]{1,30}\))?)"
)
_DATE_PREFIX_RE = re.compile(
    r"^\s*\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s*[-–—]\s*", re.IGNORECASE
)


def _parse_iso(dt: str | None) -> datetime | None:
    if not dt:
        return None
    s = str(dt).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _extract_neutral_citation(text: str | None) -> str | None:
    if not text:
        return None
    m = _CIT_RE.search(text)
    if not m:
        return None
    return m.group(1).strip()


def _extract_case_name(text: str | None, neutral: str | None) -> str | None:
    if not text:
        return None
    t = str(text).strip()
    if not t:
        return None
    if neutral and neutral in t:
        left = t.split(neutral, 1)[0].strip(" ,;:-")
        if left:
            return left
    return t[:120].strip(" ,;:-") or None


def _clean_case_name(name: str | None) -> str | None:
    if not name:
        return None
    s = str(name).strip()
    s = _DATE_PREFIX_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _safe_neutral_citation(value: str) -> str:
    v = (value or "").strip()
    if len(v) <= 255:
        return v
    # Keep deterministic-ish, but within DB length.
    return v[:240] + "…"


@dataclass
class BootstrapStats:
    scanned: int = 0
    inserted: int = 0
    failed: int = 0
    skipped_duplicates: int = 0


def _iter_s3_keys(
    s3: Any,
    *,
    bucket: str,
    prefix: str,
    limit_keys: int | None,
) -> Iterable[str]:
    paginator = s3.get_paginator("list_objects_v2")
    yielded = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj.get("Key")
            if not key:
                continue
            yield key
            yielded += 1
            if limit_keys is not None and yielded >= int(limit_keys):
                return


def bootstrap_caselaw_from_curated_s3(
    *,
    bucket_curated: str,
    prefixes: tuple[str, ...],
    limit_keys_per_prefix: int | None,
    commit_every: int = 200,
) -> Dict[str, Any]:
    """Populate case_law table from curated S3 objects when DB is empty."""

    db = SessionLocal()
    try:
        existing = db.query(CaseLaw).count()
        if existing:
            return {"skipped": True, "existing": existing}

        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        stats = BootstrapStats()

        for prefix in prefixes:
            for key in _iter_s3_keys(
                s3,
                bucket=bucket_curated,
                prefix=prefix,
                limit_keys=limit_keys_per_prefix,
            ):
                stats.scanned += 1
                try:
                    raw = s3.get_object(Bucket=bucket_curated, Key=key)["Body"].read()
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        payload = {"text": raw.decode("utf-8", errors="ignore")}

                    meta = payload.get("metadata")
                    meta = meta if isinstance(meta, dict) else {}
                    text = (
                        payload.get("text")
                        or payload.get("content")
                        or payload.get("full_text")
                        or ""
                    )
                    summary = payload.get("summary")

                    neutral = (
                        payload.get("neutral_citation")
                        or meta.get("neutral_citation")
                        or _extract_neutral_citation(text)
                        or meta.get("base_citation")
                        or meta.get("citation")
                        or key
                    )
                    neutral = _safe_neutral_citation(str(neutral))

                    case_name = (
                        payload.get("case_name")
                        or meta.get("case_name")
                        or meta.get("name")
                    )
                    case_name = (
                        _clean_case_name(case_name)
                        or _extract_case_name(text, neutral)
                        or key
                    )
                    case_name = str(case_name)[:500]

                    court = payload.get("court") or meta.get("court")
                    jd = (
                        payload.get("judgment_date")
                        or meta.get("judgment_date")
                        or meta.get("published_date")
                        or meta.get("date")
                    )

                    row = CaseLaw(
                        neutral_citation=neutral,
                        case_name=case_name,
                        court=(str(court)[:255] if court else None),
                        judgment_date=_parse_iso(jd),
                        judge=(meta.get("judge") if isinstance(meta, dict) else None),
                        # Required storage fields (use curated key as raw placeholder)
                        s3_bucket=bucket_curated,
                        s3_key_raw=key,
                        s3_key_curated=key,
                        summary=(str(summary)[:20000] if summary else None),
                        full_text_preview=(str(text)[:20000] if text else None),
                        embedding_status="pending",
                        extraction_status="extracted",
                        meta=(meta or {}),
                    )

                    db.add(row)
                    stats.inserted += 1

                    if stats.inserted % commit_every == 0:
                        db.commit()

                except IntegrityError:
                    db.rollback()
                    stats.skipped_duplicates += 1
                except Exception:
                    db.rollback()
                    stats.failed += 1

        db.commit()

        return {
            "bucket": bucket_curated,
            "prefixes": list(prefixes),
            "scanned": stats.scanned,
            "inserted": stats.inserted,
            "skipped_duplicates": stats.skipped_duplicates,
            "failed": stats.failed,
        }

    finally:
        db.close()


async def export_to_kb_and_ingest(
    *,
    limit_export: int,
    prefix_override: str,
    construction_only: bool,
) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        export_result = await export_caselaw_docs_to_knowledge_base(
            db=db,
            limit=limit_export,
            concurrency=4,
            construction_only=bool(construction_only),
            extracted_only=False,
            chunk_chars=120000,
            chunk_overlap=1500,
            prefix_override=prefix_override,
        )
    finally:
        db.close()

    bedrock_region = (
        getattr(settings, "BEDROCK_REGION", None) or settings.AWS_REGION or "eu-west-2"
    )
    kb_id = (getattr(settings, "BEDROCK_KB_ID", "") or "").strip()
    ds_id = (getattr(settings, "BEDROCK_DS_ID", "") or "").strip()
    if not kb_id or not ds_id:
        raise RuntimeError(
            f"Missing BEDROCK_KB_ID/BEDROCK_DS_ID (kb={kb_id!r}, ds={ds_id!r})."
        )

    bedrock_agent = boto3.client("bedrock-agent", region_name=bedrock_region)
    start = bedrock_agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
    job = start.get("ingestionJob") or {}
    job_id = job.get("ingestionJobId")

    status = None
    final: Dict[str, Any] | None = None
    for _ in range(180):  # up to ~30 minutes
        got = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=kb_id, dataSourceId=ds_id, ingestionJobId=job_id
        )
        ij = got.get("ingestionJob") or {}
        if ij.get("status") != status:
            status = ij.get("status")
            print(
                {
                    "ingestionJobId": job_id,
                    "status": status,
                    "statistics": ij.get("statistics"),
                }
            )
        final = ij
        if status in ("COMPLETE", "FAILED"):
            break
        time.sleep(10)

    bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=bedrock_region)
    retrieve = bedrock_runtime.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": "payment notice adjudication extension of time"},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}},
    )

    return {
        "export": export_result,
        "ingestion": {
            "job_id": job_id,
            "status": (final or {}).get("status"),
            "statistics": (final or {}).get("statistics"),
            "failureReasons": (final or {}).get("failureReasons"),
        },
        "retrieve_sample_count": len(retrieve.get("retrievalResults", []) or []),
        "retrieve_sample_locations": [
            r.get("location") for r in (retrieve.get("retrievalResults", []) or [])
        ],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket-curated", default=BUCKET_CURATED_DEFAULT)
    parser.add_argument(
        "--prefix", action="append", dest="prefixes", default=list(PREFIXES_DEFAULT)
    )
    parser.add_argument(
        "--limit-keys-per-prefix",
        type=int,
        default=None,
        help="Limit keys scanned per prefix during bootstrap (for quick tests).",
    )
    parser.add_argument(
        "--limit-export",
        type=int,
        default=500,
        help="How many CaseLaw rows to export into the KB bucket.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--construction-only",
        action="store_true",
        help="Export only cases that look construction-related (keyword heuristic).",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Export all cases (recommended for first-time KB bootstraps).",
    )
    parser.add_argument(
        "--kb-prefix",
        default="caselaw/",
        help="Destination prefix inside the KB bucket (recommended: caselaw/).",
    )
    args = parser.parse_args(argv)

    print(
        {
            "settings": {
                "AWS_REGION": settings.AWS_REGION,
                "BEDROCK_REGION": getattr(settings, "BEDROCK_REGION", None),
                "BEDROCK_KB_ID": getattr(settings, "BEDROCK_KB_ID", None),
                "BEDROCK_DS_ID": getattr(settings, "BEDROCK_DS_ID", None),
            }
        }
    )

    bootstrap = bootstrap_caselaw_from_curated_s3(
        bucket_curated=args.bucket_curated,
        prefixes=tuple(args.prefixes),
        limit_keys_per_prefix=args.limit_keys_per_prefix,
    )
    print({"bootstrap": bootstrap})

    # Verify DB now has rows
    db = SessionLocal()
    try:
        count = db.query(CaseLaw).count()
    finally:
        db.close()
    print({"case_law_count_after": count})

    result = asyncio.run(
        export_to_kb_and_ingest(
            limit_export=args.limit_export,
            prefix_override=args.kb_prefix,
            construction_only=bool(args.construction_only and not args.all),
        )
    )
    print({"result": result})

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
