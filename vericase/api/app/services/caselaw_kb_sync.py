from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..aws_services import aws_services
from ..config import settings
from ..models import CaseLaw

logger = logging.getLogger(__name__)


_CONSTRUCTION_KEYWORDS = [
    "construction",
    "technology and construction court",
    "tcc",
    "building",
    "contractor",
    "employer",
    "architect",
    "engineer",
    "design and build",
    "d&b",
    "jct",
    "nec",
    "fidic",
    "adjudication",
    "pay less",
    "payment notice",
    "extension of time",
    "eot",
    "delay",
    "defect",
    "remedial",
    "remediation",
    "variation",
    "change order",
    "termination",
]


def _has_construction_bucket(analysis: Dict[str, Any]) -> bool:
    buckets = analysis.get("construction_buckets")
    if isinstance(buckets, list):
        return any(str(bucket or "").strip() for bucket in buckets)
    return False


def _is_construction_case(case: CaseLaw) -> bool:
    analysis = case.extracted_analysis or {}
    if _has_construction_bucket(analysis):
        return True

    text = " ".join(
        [
            str(case.case_name or ""),
            str(case.summary or ""),
            str(case.court or ""),
            json.dumps(analysis, default=str),
        ]
    ).lower()

    if not text.strip():
        return False

    return any(keyword in text for keyword in _CONSTRUCTION_KEYWORDS)


def _resolve_case_s3_location(case: CaseLaw) -> Optional[Tuple[str, str]]:
    if not getattr(case, "s3_key_curated", None):
        return None

    curated = str(case.s3_key_curated or "")
    if curated.startswith("s3://"):
        path = curated[5:]
        bucket, _, key = path.partition("/")
        if bucket and key:
            return bucket, key
        return None

    bucket = str(case.s3_bucket or "").strip()
    if not bucket:
        return None

    return bucket, curated.lstrip("/")


def _extract_text_from_curated(payload: bytes) -> str:
    raw_text = payload.decode("utf-8", errors="ignore")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        return raw_text

    if isinstance(data, dict):
        return data.get("text") or data.get("content") or data.get("full_text") or ""

    return raw_text


def _chunk_text(text: str, *, max_chars: int, overlap: int) -> List[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: List[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + max_chars)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


async def _resolve_kb_bucket_and_prefix(
    *,
    kb_id: Optional[str] = None,
    ds_id: Optional[str] = None,
    default_prefix: str = "caselaw/",
) -> Tuple[str, str]:
    knowledge_base_id = (kb_id or settings.BEDROCK_KB_ID or "").strip()
    data_source_id = (ds_id or settings.BEDROCK_DS_ID or "").strip()

    bucket = (settings.S3_KNOWLEDGE_BASE_BUCKET or "").strip() or None
    prefix_from_ds: Optional[str] = None

    if knowledge_base_id and data_source_id:
        try:
            bedrock_agent = aws_services.session.client("bedrock-agent")
            response = await aws_services._run_in_executor(
                bedrock_agent.get_data_source,
                knowledgeBaseId=knowledge_base_id,
                dataSourceId=data_source_id,
            )
            data_source = (response or {}).get("dataSource") or {}
            s3_config = (data_source.get("dataSourceConfiguration") or {}).get(
                "s3Configuration"
            ) or {}

            bucket_arn = str(s3_config.get("bucketArn") or "").strip()
            if bucket_arn.startswith("arn:aws:s3:::"):
                bucket = bucket_arn.split(":::")[-1].strip() or bucket

            prefixes = s3_config.get("inclusionPrefixes")
            if isinstance(prefixes, list) and prefixes:
                prefix_from_ds = str(prefixes[0] or "").strip()
        except Exception as e:
            logger.warning("KB data source lookup failed (non-fatal): %s", e)

    if not bucket:
        raise RuntimeError(
            "Knowledge base bucket not configured (set S3_KNOWLEDGE_BASE_BUCKET or provide BEDROCK_KB_ID/BEDROCK_DS_ID)."
        )

    prefix = prefix_from_ds if prefix_from_ds is not None else default_prefix
    prefix = str(prefix or "").lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    return bucket, prefix


async def export_caselaw_docs_to_knowledge_base(
    *,
    db: Session,
    limit: int = 250,
    concurrency: int = 4,
    construction_only: bool = True,
    extracted_only: bool = False,
    chunk_chars: int = 120_000,
    chunk_overlap: int = 1_500,
    kb_id: Optional[str] = None,
    ds_id: Optional[str] = None,
    prefix_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Export curated case-law text into the Bedrock KB S3 data-source bucket/prefix so ingestion has documents to scan.
    Writes plain-text files with a small metadata header to improve retrieval quality.
    """
    limit = max(1, min(int(limit or 1), 5000))
    concurrency = max(1, min(int(concurrency or 1), 16))

    bucket, base_prefix = await _resolve_kb_bucket_and_prefix(kb_id=kb_id, ds_id=ds_id)
    if prefix_override is not None:
        base_prefix = str(prefix_override or "").lstrip("/")
        if base_prefix and not base_prefix.endswith("/"):
            base_prefix += "/"

    query = db.query(CaseLaw)
    if extracted_only:
        query = query.filter(CaseLaw.extraction_status == "extracted")
    cases = query.order_by(CaseLaw.created_at.asc()).limit(limit).all()

    if construction_only:
        cases = [case for case in cases if _is_construction_case(case)]

    semaphore = asyncio.Semaphore(concurrency)
    exported: List[str] = []
    failed: List[Dict[str, str]] = []

    async def export_one(case: CaseLaw) -> None:
        async with semaphore:
            try:
                text: str = ""
                s3_location = _resolve_case_s3_location(case)
                if s3_location:
                    src_bucket, src_key = s3_location
                    obj = await aws_services._run_in_executor(
                        aws_services.s3.get_object,
                        Bucket=src_bucket,
                        Key=src_key,
                    )
                    body_bytes = await aws_services._run_in_executor(obj["Body"].read)
                    text = _extract_text_from_curated(body_bytes)
                if not text:
                    text = case.full_text_preview or case.summary or ""

                header_lines = [
                    f"Neutral citation: {case.neutral_citation}",
                    f"Case name: {case.case_name}",
                ]
                if case.court:
                    header_lines.append(f"Court: {case.court}")
                if case.judgment_date:
                    header_lines.append(
                        f"Judgment date: {case.judgment_date.date().isoformat()}"
                    )
                analysis = case.extracted_analysis or {}
                buckets = analysis.get("construction_buckets")
                if isinstance(buckets, list) and buckets:
                    cleaned = [
                        str(b or "").strip() for b in buckets if str(b or "").strip()
                    ]
                    if cleaned:
                        header_lines.append(
                            f"Construction buckets: {', '.join(cleaned)}"
                        )
                header_lines.append("---")

                document_text = "\n".join(header_lines) + "\n" + (text or "").strip()
                chunks = _chunk_text(
                    document_text,
                    max_chars=max(10_000, int(chunk_chars)),
                    overlap=max(0, int(chunk_overlap)),
                )
                if not chunks:
                    raise RuntimeError("No text available to export")

                if len(chunks) == 1:
                    dest_key = f"{base_prefix}{case.id}.txt"
                    await aws_services._run_in_executor(
                        aws_services.s3.put_object,
                        Bucket=bucket,
                        Key=dest_key,
                        Body=chunks[0].encode("utf-8"),
                        ContentType="text/plain; charset=utf-8",
                    )
                else:
                    for idx, chunk in enumerate(chunks, start=1):
                        dest_key = f"{base_prefix}{case.id}/part_{idx:03d}.txt"
                        await aws_services._run_in_executor(
                            aws_services.s3.put_object,
                            Bucket=bucket,
                            Key=dest_key,
                            Body=chunk.encode("utf-8"),
                            ContentType="text/plain; charset=utf-8",
                        )

                exported.append(str(case.id))
            except Exception as e:
                failed.append(
                    {
                        "case_id": str(case.id),
                        "citation": str(case.neutral_citation or ""),
                        "error": str(e),
                    }
                )

    await asyncio.gather(*(export_one(case) for case in cases))

    return {
        "destination_bucket": bucket,
        "destination_prefix": base_prefix,
        "requested_limit": limit,
        "exported": len(exported),
        "failed": failed,
        "case_ids": exported,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
