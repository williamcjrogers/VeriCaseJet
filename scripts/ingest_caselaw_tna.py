#!/usr/bin/env python3
"""
Ingestion script for The National Archives (TNA) Find Case Law API.
Fetches judgments and ingests them into VeriCase S3 and Database.

Usage:
    python scripts/ingest_caselaw_tna.py --limit 10 --mock

Prerequisites:
    - AWS Credentials configured
    - Database connection string in .env
"""

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
import time
import xml.etree.ElementTree as ET

import boto3
from botocore.exceptions import ClientError
import httpx

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vericase.api.app.db import SessionLocal
from vericase.api.app.models import CaseLaw
from vericase.api.app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# TNA API Endpoint
TNA_BASE_URL = "https://caselaw.nationalarchives.gov.uk"

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "tna": "https://caselaw.nationalarchives.gov.uk",
}


class TNAIngestor:
    def __init__(
        self,
        mock_mode: bool = False,
        queries: Optional[List[str]] = None,
        court: Optional[str] = None,
        subdivision: Optional[str] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        max_pages: int = 5,
        per_page: int = 50,
        order: str = "-date",
        sleep_s: float = 0.25,
    ):
        self.mock_mode = mock_mode
        self.queries = queries or []
        self.court = court or ""
        self.subdivision = subdivision or ""
        self.year_from = year_from
        self.year_to = year_to
        self.max_pages = max_pages
        self.per_page = per_page
        self.order = order
        self.sleep_s = sleep_s
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        self.bucket_raw = "vericase-caselaw-raw"
        self.bucket_curated = "vericase-caselaw-curated"
        self.db = SessionLocal()
        self.http = httpx.Client(timeout=httpx.Timeout(30.0))
        self.seen_uris: set[str] = set()

    def ensure_buckets_exist(self):
        """Ensure S3 buckets exist"""
        for bucket in [self.bucket_raw, self.bucket_curated]:
            try:
                self.s3.head_bucket(Bucket=bucket)
                logger.info(f"Bucket {bucket} exists.")
            except ClientError:
                logger.info(f"Creating bucket {bucket}...")
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
                    logger.error(f"Failed to create bucket {bucket}: {e}")

    def fetch_judgments(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch judgments from TNA API (or mock)"""
        if self.mock_mode:
            logger.info(f"Generating {limit} mock judgments...")
            return self._generate_mock_judgments(limit)

        results: List[Dict[str, Any]] = []
        query_terms = self.queries or [""]

        for query in query_terms:
            if len(results) >= limit:
                break
            for entry in self._iterate_atom_entries(query=query):
                if len(results) >= limit:
                    break
                parsed = self._parse_entry(entry)
                if not parsed:
                    continue
                if not self._within_year_range(parsed.get("date") or ""):
                    continue
                uri = parsed.get("document_uri") or ""
                if uri and uri in self.seen_uris:
                    continue
                if uri:
                    self.seen_uris.add(uri)
                results.append(parsed)

        return results

    def _iterate_atom_entries(self, query: str = "") -> Iterable[ET.Element]:
        base_urls = self._build_feed_urls(query)
        for base_url in base_urls:
            next_url = base_url
            page = 0
            while next_url and page < self.max_pages:
                page += 1
                logger.info("Fetching feed page %s: %s", page, next_url)
                try:
                    resp = self.http.get(next_url)
                    resp.raise_for_status()
                except Exception as exc:
                    logger.warning("Failed to fetch feed: %s", exc)
                    break

                try:
                    root = ET.fromstring(resp.text)
                except ET.ParseError as exc:
                    logger.warning("Failed to parse Atom feed: %s", exc)
                    break

                entries = root.findall("atom:entry", ATOM_NS)
                for entry in entries:
                    yield entry

                next_url = None
                for link in root.findall("atom:link", ATOM_NS):
                    if link.get("rel") == "next":
                        next_url = link.get("href")
                        break

                time.sleep(self.sleep_s)

    def _build_feed_urls(self, query: str) -> List[str]:
        if self.court and self.subdivision and self.year_from:
            end_year = self.year_to or self.year_from
            years = range(self.year_from, end_year + 1)
            return [
                f"{TNA_BASE_URL}/{self.court}/{self.subdivision}/{year}/atom.xml?page=1"
                for year in years
            ]

        params = {
            "order": self.order,
            "page": 1,
            "per_page": self.per_page,
        }
        if query:
            params["query"] = query
        if self.court:
            court_value = (
                f"{self.court}/{self.subdivision}" if self.subdivision else self.court
            )
            params["court"] = court_value

        query_string = str(
            httpx.QueryParams({k: v for k, v in params.items() if v != ""})
        )
        return [f"{TNA_BASE_URL}/atom.xml?{query_string}"]

    def _parse_entry(self, entry: ET.Element) -> Optional[Dict[str, Any]]:
        title = entry.findtext("atom:title", namespaces=ATOM_NS) or ""
        published = entry.findtext("atom:published", namespaces=ATOM_NS) or ""
        court_name = entry.findtext("atom:author/atom:name", namespaces=ATOM_NS) or ""
        doc_uri = entry.findtext("tna:uri", namespaces=ATOM_NS) or ""
        content_hash = entry.findtext("tna:contenthash", namespaces=ATOM_NS) or ""

        xml_url = ""
        pdf_url = ""
        for link in entry.findall("atom:link", ATOM_NS):
            if link.get("rel") != "alternate":
                continue
            if link.get("type") == "application/akn+xml":
                xml_url = link.get("href") or ""
            elif link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""

        citation = ""
        identifiers = []
        for ident in entry.findall("tna:identifier", ATOM_NS):
            ident_type = ident.get("type") or ""
            ident_slug = ident.get("slug") or ""
            ident_value = ident.text or ""
            identifiers.append(
                {"type": ident_type, "slug": ident_slug, "value": ident_value}
            )
            if ident_type == "ukncn" and ident_value:
                citation = ident_value

        if not xml_url:
            return None

        return {
            "neutral_citation": citation or doc_uri or title,
            "name": title or citation or doc_uri,
            "court": court_name or None,
            "date": published,
            "judge": None,
            "document_uri": doc_uri,
            "content_hash": content_hash,
            "identifiers": identifiers,
            "xml_url": xml_url,
            "pdf_url": pdf_url,
        }

    def _within_year_range(self, published: str) -> bool:
        if not (self.year_from or self.year_to):
            return True
        if not published:
            return False
        try:
            date_value = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            return False
        if self.year_from and date_value.year < self.year_from:
            return False
        if self.year_to and date_value.year > self.year_to:
            return False
        return True

    def _fetch_document_xml(self, xml_url: str) -> str:
        resp = self.http.get(xml_url)
        resp.raise_for_status()
        return resp.text

    def _extract_text_from_xml(self, xml_text: str) -> str:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return xml_text
        text = " ".join(root.itertext())
        return " ".join(text.split())

    def _generate_mock_judgments(self, limit: int) -> List[Dict[str, Any]]:
        """Generate dummy data for testing"""
        judgments = []
        for i in range(limit):
            year = 2023 + (i % 3)
            num = 100 + i
            judgments.append(
                {
                    "neutral_citation": f"[{year}] EWHC {num} (TCC)",
                    "name": f"Construction Co Ltd v Developer Plc {i}",
                    "court": "Technology and Construction Court",
                    "date": f"{year}-05-{10 + (i % 20):02d}",
                    "judge": "Mr Justice Smith",
                    "content_xml": f"<judgment><p>This is paragraph 1 of judgment {num}.</p></judgment>",
                    "content_text": f"This is the plain text content of judgment {num}. It involves a dispute about delay and defects.",
                }
            )
        return judgments

    def process_judgment(self, judgment: Dict[str, Any]):
        """Process a single judgment: Upload to S3 and save to DB"""
        citation = judgment["neutral_citation"]
        logger.info(f"Processing {citation}...")

        # Check if exists
        existing = None
        if citation:
            existing = (
                self.db.query(CaseLaw)
                .filter(CaseLaw.neutral_citation == citation)
                .first()
            )
        if not existing and judgment.get("document_uri"):
            try:
                existing = (
                    self.db.query(CaseLaw)
                    .filter(CaseLaw.meta["tna_uri"].astext == judgment["document_uri"])
                    .first()
                )
            except Exception:
                existing = None
        if existing:
            logger.info(f"Judgment {citation} already exists. Skipping.")
            return

        if judgment.get("xml_url"):
            try:
                judgment["content_xml"] = self._fetch_document_xml(judgment["xml_url"])
                judgment["content_text"] = self._extract_text_from_xml(
                    judgment["content_xml"]
                )
            except Exception as exc:
                logger.warning("Failed to fetch XML for %s: %s", citation, exc)
                return

        # 1. Upload Raw (XML)
        raw_key = self._safe_key("tna/raw", judgment.get("document_uri") or citation)
        self.s3.put_object(
            Bucket=self.bucket_raw,
            Key=raw_key,
            Body=judgment["content_xml"],
            ContentType="application/xml",
        )

        # 2. Upload Curated (JSON/Text)
        curated_key = self._safe_key(
            "tna/curated", judgment.get("document_uri") or citation
        )
        curated_data = {
            "metadata": {
                "citation": citation,
                "name": judgment["name"],
                "court": judgment["court"],
                "date": judgment["date"],
                "document_uri": judgment.get("document_uri"),
                "content_hash": judgment.get("content_hash"),
                "identifiers": judgment.get("identifiers", []),
                "pdf_url": judgment.get("pdf_url"),
            },
            "text": judgment["content_text"],
        }
        self.s3.put_object(
            Bucket=self.bucket_curated,
            Key=curated_key,
            Body=json.dumps(curated_data),
            ContentType="application/json",
        )

        # 3. Save to DB
        case_law = CaseLaw(
            id=uuid.uuid4(),
            neutral_citation=citation,
            case_name=judgment["name"],
            court=judgment["court"],
            judgment_date=datetime.strptime(judgment["date"], "%Y-%m-%d"),
            judge=judgment["judge"],
            s3_bucket=self.bucket_curated,  # Pointing to curated for KB
            s3_key_raw=raw_key,
            s3_key_curated=curated_key,
            summary=judgment["content_text"][:200] + "...",
            full_text_preview=judgment["content_text"][:4000],
            embedding_status="pending",
            extraction_status="pending",
            meta={
                "source": "tna",
                "tna_uri": judgment.get("document_uri"),
                "content_hash": judgment.get("content_hash"),
                "identifiers": judgment.get("identifiers", []),
                "xml_url": judgment.get("xml_url"),
                "pdf_url": judgment.get("pdf_url"),
            },
        )
        self.db.add(case_law)
        self.db.commit()
        logger.info(f"Saved {citation} to database.")

    def run(self, limit: int):
        self.ensure_buckets_exist()
        judgments = self.fetch_judgments(limit)
        for j in judgments:
            try:
                self.process_judgment(j)
            except Exception as e:
                logger.error(f"Failed to process {j.get('neutral_citation')}: {e}")

    def _safe_key(self, prefix: str, identifier: str) -> str:
        slug = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in identifier)
        slug = slug.strip("_")
        if not slug:
            slug = uuid.uuid4().hex
        if len(slug) > 180:
            suffix = uuid.uuid4().hex[:12]
            slug = f"{slug[:120]}_{suffix}"
        return (
            f"{prefix}/{slug}.xml"
            if prefix.endswith("raw")
            else f"{prefix}/{slug}.json"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Case Law")
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of cases to ingest"
    )
    parser.add_argument("--mock", action="store_true", help="Use mock data")
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Full-text search term (repeatable).",
    )
    parser.add_argument("--court", type=str, default="", help="Court code (e.g., ewhc)")
    parser.add_argument(
        "--subdivision", type=str, default="", help="Subdivision (e.g., tcc)"
    )
    parser.add_argument("--year-from", type=int, default=None)
    parser.add_argument("--year-to", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--order", type=str, default="-date")
    parser.add_argument("--sleep", type=float, default=0.25)
    args = parser.parse_args()

    ingestor = TNAIngestor(
        mock_mode=args.mock,
        queries=args.queries or [],
        court=args.court,
        subdivision=args.subdivision,
        year_from=args.year_from,
        year_to=args.year_to,
        max_pages=args.max_pages,
        per_page=args.per_page,
        order=args.order,
        sleep_s=args.sleep,
    )
    ingestor.run(args.limit)
