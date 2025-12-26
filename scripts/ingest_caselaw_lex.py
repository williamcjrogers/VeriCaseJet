#!/usr/bin/env python3
"""
Ingest case law from the Lex API into VeriCase S3 + DB.

Usage examples:
  python scripts/ingest_caselaw_lex.py --max-cases 50
  python scripts/ingest_caselaw_lex.py --query "JCT payment notice" --query "design liability" --max-cases 30
  python scripts/ingest_caselaw_lex.py --courts ewhc --division tcc --year-from 2010 --max-cases 40
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

import boto3
import httpx
from botocore.exceptions import ClientError

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vericase.api.app.config import settings
from vericase.api.app.db import SessionLocal
from vericase.api.app.models import CaseLaw


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_QUERIES = [
    "JCT payment notice",
    "pay less notice construction",
    "design liability negligent design",
    "design delay contractor claim",
    "fire safety cladding Grenfell",
    "building regulations approved document B",
    "external wall system combustible materials",
    "omission of work replacement contractor",
    "defective work employer completes",
]


def _parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _safe_key(prefix: str, identifier: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", identifier).strip("_")
    if not slug:
        slug = uuid.uuid4().hex
    if len(slug) > 180:
        suffix = uuid.uuid4().hex[:12]
        slug = f"{slug[:120]}_{suffix}"
    return f"{prefix}/{slug}.json"


class LexClient:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = httpx.Timeout(30.0)

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            return {}
        header = settings.LEX_API_AUTH_HEADER or "Authorization"
        scheme = settings.LEX_API_AUTH_SCHEME or ""
        value = f"{scheme} {self.token}".strip() if scheme else self.token
        return {header: value}

    def search_caselaw(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/caselaw/search"
        headers = self._headers()
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


class LexIngestor:
    def __init__(
        self,
        base_url: str,
        token: str,
        max_cases: int,
        per_query: int,
        queries: Iterable[str],
        courts: List[str],
        divisions: List[str],
        year_from: Optional[int],
        year_to: Optional[int],
        semantic: bool,
        skip_db: bool,
    ):
        self.client = LexClient(base_url, token)
        self.max_cases = max_cases
        self.per_query = per_query
        self.queries = list(queries)
        self.courts = courts
        self.divisions = divisions
        self.year_from = year_from
        self.year_to = year_to
        self.semantic = semantic
        self.skip_db = skip_db

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
            region_name=settings.AWS_REGION,
        )
        self.bucket_raw = "vericase-caselaw-raw"
        self.bucket_curated = "vericase-caselaw-curated"
        self.db = None if skip_db else SessionLocal()
        self.seen: Set[str] = set()

    def ensure_buckets_exist(self):
        for bucket in [self.bucket_raw, self.bucket_curated]:
            try:
                self.s3.head_bucket(Bucket=bucket)
                logger.info("Bucket %s exists.", bucket)
            except ClientError:
                logger.info("Creating bucket %s...", bucket)
                try:
                    if settings.AWS_REGION == "us-east-1":
                        self.s3.create_bucket(Bucket=bucket)
                    else:
                        self.s3.create_bucket(
                            Bucket=bucket,
                            CreateBucketConfiguration={
                                "LocationConstraint": settings.AWS_REGION
                            },
                        )
                except Exception as e:
                    logger.error("Failed to create bucket %s: %s", bucket, e)

    def _build_search_payload(
        self, query: str, offset: int, size: int
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "query": query,
            "is_semantic_search": self.semantic,
            "offset": offset,
            "size": size,
        }
        if self.courts:
            payload["court"] = self.courts
        if self.divisions:
            payload["division"] = self.divisions
        if self.year_from:
            payload["year_from"] = self.year_from
        if self.year_to:
            payload["year_to"] = self.year_to
        return payload

    def fetch_cases(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for query in self.queries:
            if len(results) >= self.max_cases:
                break

            offset = 0
            per_query_count = 0
            size = min(20, self.per_query)
            while per_query_count < self.per_query and len(results) < self.max_cases:
                payload = self._build_search_payload(query, offset, size)
                logger.info("Lex query '%s' offset %s size %s", query, offset, size)
                response = self.client.search_caselaw(payload)
                batch = response.get("results", [])
                if not batch:
                    break

                for item in batch:
                    case_id = str(item.get("id") or "")
                    if not case_id or case_id in self.seen:
                        continue
                    self.seen.add(case_id)
                    results.append(item)
                    per_query_count += 1
                    if (
                        per_query_count >= self.per_query
                        or len(results) >= self.max_cases
                    ):
                        break

                offset += len(batch)
                if len(batch) < size:
                    break

                time.sleep(0.25)

        return results

    def _parse_date(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def _prepare_case_record(self, item: Dict[str, Any]) -> Dict[str, Any]:
        case_id = str(item.get("id") or "")
        citation = item.get("cite_as") or case_id
        case_name = item.get("name") or citation
        court = item.get("court")
        division = item.get("division")
        date_value = item.get("date")
        text = item.get("text") or ""

        summary = text[:500] + ("..." if len(text) > 500 else "")
        preview = text[:4000] + ("..." if len(text) > 4000 else "")

        meta = {
            "source": "lex",
            "lex_id": case_id,
            "court": court,
            "division": division,
            "year": item.get("year"),
            "number": item.get("number"),
            "date": date_value,
            "references": {
                "caselaw": item.get("caselaw_references", []),
                "legislation": item.get("legislation_references", []),
            },
        }

        return {
            "case_id": case_id,
            "citation": citation,
            "case_name": case_name,
            "court": str(court) if court is not None else None,
            "judgment_date": self._parse_date(date_value),
            "summary": summary,
            "preview": preview,
            "text": text,
            "meta": meta,
        }

    def _upload_json(self, bucket: str, key: str, payload: Dict[str, Any]):
        self.s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(payload),
            ContentType="application/json",
        )

    def ingest(self):
        self.ensure_buckets_exist()
        cases = self.fetch_cases()
        logger.info("Fetched %s unique cases from Lex", len(cases))

        ingested = 0
        for item in cases:
            record = self._prepare_case_record(item)
            citation = record["citation"]

            if self.db:
                existing = (
                    self.db.query(CaseLaw)
                    .filter(CaseLaw.neutral_citation == citation)
                    .first()
                )
                if existing:
                    logger.info("Case already exists: %s", citation)
                    continue

            raw_key = _safe_key("lex/raw", record["case_id"])
            curated_key = _safe_key("lex/curated", record["case_id"])

            raw_payload = {"source": "lex", "data": item}
            curated_payload = {
                "metadata": {
                    "citation": citation,
                    "name": record["case_name"],
                    "court": record["court"],
                    "division": record["meta"].get("division"),
                    "date": record["meta"].get("date"),
                    "lex_id": record["case_id"],
                },
                "text": record["text"],
            }

            self._upload_json(self.bucket_raw, raw_key, raw_payload)
            self._upload_json(self.bucket_curated, curated_key, curated_payload)

            if self.db:
                case_law = CaseLaw(
                    id=uuid.uuid4(),
                    neutral_citation=citation,
                    case_name=record["case_name"],
                    court=record["court"],
                    judgment_date=record["judgment_date"],
                    judge=None,
                    s3_bucket=self.bucket_curated,
                    s3_key_raw=raw_key,
                    s3_key_curated=curated_key,
                    summary=record["summary"],
                    full_text_preview=record["preview"],
                    embedding_status="pending",
                    extraction_status="pending",
                    meta=record["meta"],
                )
                try:
                    self.db.add(case_law)
                    self.db.commit()
                except Exception as e:
                    logger.error("DB insert failed for %s: %s", citation, e)
                    self.db.rollback()
                    continue

            ingested += 1
            logger.info("Ingested: %s", citation)

        logger.info("Ingestion complete. Added %s cases.", ingested)
        if self.db:
            self.db.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest Case Law from Lex API")
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Query term (repeatable). If omitted, defaults are used.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=50,
        help="Total maximum cases to ingest across all queries.",
    )
    parser.add_argument(
        "--per-query",
        type=int,
        default=15,
        help="Maximum cases to ingest per query.",
    )
    parser.add_argument(
        "--courts", type=str, default="", help="Comma-separated courts."
    )
    parser.add_argument(
        "--division", type=str, default="", help="Comma-separated divisions."
    )
    parser.add_argument("--year-from", type=int, default=None)
    parser.add_argument("--year-to", type=int, default=None)
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="Use keyword search instead of semantic search.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database writes; only upload to S3.",
    )
    args = parser.parse_args()

    base_url = os.getenv("LEX_API_BASE_URL", "https://lex.lab.i.ai.gov.uk")
    token = os.getenv("LEX_API_TOKEN", "")
    queries = args.queries or DEFAULT_QUERIES

    ingestor = LexIngestor(
        base_url=base_url,
        token=token,
        max_cases=args.max_cases,
        per_query=args.per_query,
        queries=queries,
        courts=_parse_csv(args.courts),
        divisions=_parse_csv(args.division),
        year_from=args.year_from,
        year_to=args.year_to,
        semantic=not args.no_semantic,
        skip_db=args.skip_db,
    )
    ingestor.ingest()


if __name__ == "__main__":
    main()
