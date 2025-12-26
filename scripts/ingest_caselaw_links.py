#!/usr/bin/env python3
"""
Ingest case law from curated link lists into VeriCase S3 + DB.

Sources supported:
  - fidic: uses docs/fidic_cases.json (links extracted from FIDIC table PDF)
  - fenwick: uses Fenwick Elliott sitemap, defaulting to adjudication case notes

Examples:
  python scripts/ingest_caselaw_links.py --source fidic
  python scripts/ingest_caselaw_links.py --source fenwick
  python scripts/ingest_caselaw_links.py --source fenwick --fenwick-prefix research-insight/adjudication-case-notes
  python scripts/ingest_caselaw_links.py --source fidic --max-cases 50 --sleep 0.5
"""

import argparse
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
import httpx
import pdfplumber
from docx import Document
from bs4 import BeautifulSoup
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

FENWICK_SITEMAP = "https://www.fenwickelliott.com/sitemap.xml"
FENWICK_BASE_URL = "https://www.fenwickelliott.com"


def _safe_key(prefix: str, identifier: str, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", identifier).strip("_")
    if not slug:
        slug = uuid.uuid4().hex
    if len(slug) > 180:
        suffix = uuid.uuid4().hex[:12]
        slug = f"{slug[:120]}_{suffix}"
    return f"{prefix}/{slug}{ext}"


def _slugify(value: str) -> str:
    if not value:
        return ""
    ascii_value = value.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_value).strip("-").lower()
    return slug


def _hash_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _extract_bracket_citation(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"(\[[0-9]{4}\][^,;]{3,120})", text)
    return match.group(1).strip() if match else ""


def _extract_parenthetical_citation(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"(\([0-9]{4}\)[^,;]{3,120})", text)
    return match.group(1).strip() if match else ""


def _derive_citation(case_name: str, source: str, link: str) -> str:
    candidate = _extract_bracket_citation(case_name) or _extract_parenthetical_citation(
        case_name
    )
    if candidate:
        # eKLR citations are often formatted as just "[YYYY] eKLR" which is not unique.
        # In those cases, fall back to a stable source-specific identifier.
        if re.match(r"^\[[0-9]{4}\]\s+eklr\b", candidate.strip(), re.IGNORECASE):
            candidate = ""
    if candidate and len(candidate) <= 255:
        return candidate
    slug = _slugify(case_name) or _slugify(link)
    suffix = _hash_id(link or case_name)
    prefix = source.upper()
    if slug:
        base = f"{prefix}:{slug}"
        if len(base) > 230:
            base = f"{prefix}:{slug[:200]}:{suffix}"
        return base[:255]
    return f"{prefix}:{suffix}"


def _with_suffix(citation: str, suffix: str) -> str:
    cleaned_suffix = re.sub(r"[^A-Za-z0-9_-]+", "", suffix)[:16]
    if not cleaned_suffix:
        cleaned_suffix = uuid.uuid4().hex[:12]
    combined = f"{citation}:{cleaned_suffix}"
    return combined[:255]


def _parse_date_from_text(value: str) -> Optional[datetime]:
    if not value:
        return None
    match = re.search(r"(\\d{1,2}\\s+[A-Za-z]{3,9}\\s+\\d{4})", value)
    if not match:
        return None
    date_str = match.group(1)
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _parse_iso_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_html_title(soup: BeautifulSoup) -> str:
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return og_title["content"].strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(strip=True)
    return ""


def _extract_html_published_date(soup: BeautifulSoup) -> Optional[datetime]:
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return _parse_iso_date(meta["content"])
    meta = soup.find("meta", attrs={"name": "dcterms.date"})
    if meta and meta.get("content"):
        return _parse_iso_date(meta["content"])
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        return _parse_iso_date(time_tag["datetime"])
    return None


def _extract_html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", attrs={"role": "main"})
    )
    if main is None:
        main = soup.find("div", class_=re.compile(r"(content|body|main)", re.I))

    target = main if main is not None else soup
    text = target.get_text(" ", strip=True)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


class LinkIngestor:
    def __init__(
        self,
        source: str,
        skip_db: bool,
        max_cases: Optional[int],
        start_at: int,
        sleep_s: float,
        max_retries: int,
        headers: Dict[str, str],
        cookies: Dict[str, str],
        user_agent: str,
        insecure: bool,
        skip_domains: List[str],
        allow_domains: List[str],
        metadata_only: bool,
        update_existing: bool,
        fallback_to_summary: bool,
    ):
        self.source = source
        self.skip_db = skip_db
        self.max_cases = max_cases
        self.start_at = start_at
        self.sleep_s = sleep_s
        self.max_retries = max_retries
        self.headers = dict(headers)
        if user_agent:
            self.headers["User-Agent"] = user_agent
        self.cookies = dict(cookies)
        self.skip_domains = {d.lower() for d in skip_domains if d}
        self.allow_domains = {d.lower() for d in allow_domains if d}
        self.metadata_only = metadata_only
        self.update_existing = update_existing
        self.fallback_to_summary = fallback_to_summary

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
            region_name=settings.AWS_REGION,
        )
        self.bucket_raw = "vericase-caselaw-raw"
        self.bucket_curated = "vericase-caselaw-curated"
        self.db = None if skip_db else SessionLocal()
        self.http = httpx.Client(
            timeout=httpx.Timeout(45.0),
            follow_redirects=True,
            verify=not insecure,
        )

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
                except Exception as exc:
                    logger.error("Failed to create bucket %s: %s", bucket, exc)

    def _fetch(self, url: str) -> Tuple[bytes, str, str]:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.http.get(url, headers=self.headers, cookies=self.cookies)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    logger.warning(
                        "Retryable HTTP %s for %s (attempt %s/%s)",
                        resp.status_code,
                        url,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(self.sleep_s * attempt)
                    continue
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                return resp.content, resp.text, content_type
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Fetch failed for %s (attempt %s/%s): %s",
                    url,
                    attempt,
                    self.max_retries,
                    exc,
                )
                time.sleep(self.sleep_s * attempt)
        raise RuntimeError(f"Failed to fetch {url}: {last_exc}")

    def _extract_text(
        self, raw: bytes, html_text: str, url: str, content_type: str
    ) -> str:
        lowered = (content_type or "").lower()
        head = raw[:8]
        looks_like_pdf = head.startswith(b"%PDF")
        is_pdf = "application/pdf" in lowered or looks_like_pdf
        if is_pdf:
            try:
                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    pages = [page.extract_text() or "" for page in pdf.pages]
                return re.sub(r"\\s+", " ", " ".join(pages)).strip()
            except Exception as exc:
                logger.warning("PDF extraction failed for %s: %s", url, exc)
                return ""
        looks_like_zip = head.startswith(b"PK\x03\x04")
        is_docx = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            in lowered
            or (url.lower().endswith(".docx") and looks_like_zip)
        )
        if is_docx:
            try:
                doc = Document(io.BytesIO(raw))
                paragraphs = [p.text for p in doc.paragraphs if p.text]
                return re.sub(r"\\s+", " ", " ".join(paragraphs)).strip()
            except Exception as exc:
                logger.warning("DOCX extraction failed for %s: %s", url, exc)
                return ""
        if "text/html" in content_type.lower() or "<html" in html_text.lower():
            return _extract_html_text(html_text)
        if content_type.lower().startswith("text/"):
            return re.sub(r"\\s+", " ", html_text).strip()
        return ""

    def _upload_raw(self, key: str, data: bytes, content_type: str):
        self.s3.put_object(
            Bucket=self.bucket_raw,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )

    def _upload_curated(self, key: str, payload: Dict[str, Any]):
        self.s3.put_object(
            Bucket=self.bucket_curated,
            Key=key,
            Body=json.dumps(payload),
            ContentType="application/json",
        )

    def _build_db_record(
        self,
        citation: str,
        case_name: str,
        court: Optional[str],
        judgment_date: Optional[datetime],
        summary: str,
        preview: str,
        raw_key: str,
        curated_key: str,
        meta: Dict[str, Any],
    ) -> CaseLaw:
        return CaseLaw(
            id=uuid.uuid4(),
            neutral_citation=citation,
            case_name=case_name,
            court=court,
            judgment_date=judgment_date,
            judge=None,
            s3_bucket=self.bucket_curated,
            s3_key_raw=raw_key,
            s3_key_curated=curated_key,
            summary=summary,
            full_text_preview=preview,
            embedding_status="pending",
            extraction_status="pending",
            meta=meta,
        )

    def ingest_items(self, items: Iterable[Dict[str, Any]]):
        self.ensure_buckets_exist()
        total = 0
        ingested = 0
        skipped = 0
        seen_citations: set[str] = set()
        seen_links: set[str] = set()

        for idx, item in enumerate(items):
            if idx < self.start_at:
                continue
            if self.max_cases is not None and total >= self.max_cases:
                break
            total += 1

            link = (item.get("link") or "").strip()
            if not link:
                skipped += 1
                continue
            domain = urlparse(link).netloc.lower()
            if self.allow_domains and domain not in self.allow_domains:
                skipped += 1
                continue
            if domain in self.skip_domains:
                skipped += 1
                continue
            if link in seen_links:
                skipped += 1
                continue
            seen_links.add(link)

            source = item.get("source") or self.source
            identifier = _hash_id(link)
            base_citation = _derive_citation(item.get("case_name") or "", source, link)
            citation = base_citation
            if citation in seen_citations:
                # If this is a source-derived identifier (not a true neutral citation),
                # make it unique per URL.
                if ":" in citation and "[" not in citation:
                    citation = _with_suffix(citation, identifier)
                else:
                    skipped += 1
                    continue
            seen_citations.add(citation)

            if self.db:
                existing = (
                    self.db.query(CaseLaw)
                    .filter(CaseLaw.neutral_citation == citation)
                    .first()
                )
                if existing and not self.update_existing:
                    # Try unique-by-URL for source-derived citations (same case name, different URLs)
                    if ":" in base_citation and "[" not in base_citation:
                        candidate = _with_suffix(base_citation, identifier)
                        existing = (
                            self.db.query(CaseLaw)
                            .filter(CaseLaw.neutral_citation == candidate)
                            .first()
                        )
                        if not existing:
                            citation = candidate
                        else:
                            logger.info("Case exists, skipping: %s", citation)
                            skipped += 1
                            continue
                    else:
                        logger.info("Case exists, skipping: %s", citation)
                        skipped += 1
                        continue

            fetch_error: str | None = None
            if self.metadata_only:
                raw_payload = {
                    "source": source,
                    "url": link,
                    "ingested_at": datetime.utcnow().isoformat() + "Z",
                    "item": item,
                }
                raw_bytes = json.dumps(raw_payload).encode("utf-8")
                html_text = ""
                content_type = "application/json"
            else:
                try:
                    raw_bytes, html_text, content_type = self._fetch(link)
                except Exception as exc:
                    fetch_error = str(exc)
                    if (
                        not self.fallback_to_summary
                        or not (item.get("summary") or "").strip()
                    ):
                        logger.error("Fetch failed, skipping %s: %s", link, exc)
                        skipped += 1
                        continue
                    raw_payload = {
                        "source": source,
                        "url": link,
                        "ingested_at": datetime.utcnow().isoformat() + "Z",
                        "fetch_error": fetch_error,
                        "item": item,
                    }
                    raw_bytes = json.dumps(raw_payload).encode("utf-8")
                    html_text = ""
                    content_type = "application/json"

            text = self._extract_text(raw_bytes, html_text, link, content_type)
            case_name = item.get("case_name") or ""

            if not case_name and html_text:
                soup = BeautifulSoup(html_text, "html.parser")
                case_name = _extract_html_title(soup) or link
                published_date = _extract_html_published_date(soup)
            else:
                published_date = None

            judgment_date = _parse_date_from_text(case_name) or published_date

            summary = (item.get("summary") or "").strip()
            if not summary:
                summary = (text[:500] + ("..." if len(text) > 500 else "")).strip()
            if not text and summary and self.fallback_to_summary:
                text = summary
            preview = (text[:4000] + ("..." if len(text) > 4000 else "")).strip()

            lowered = content_type.lower()
            head = raw_bytes[:8]
            looks_like_pdf = head.startswith(b"%PDF")
            looks_like_zip = head.startswith(b"PK\x03\x04")
            if "application/pdf" in lowered or looks_like_pdf:
                ext = ".pdf"
            elif (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                in lowered
                or (link.lower().endswith(".docx") and looks_like_zip)
            ):
                ext = ".docx"
            elif lowered.startswith("application/json"):
                ext = ".json"
            else:
                ext = ".html"
            raw_key = _safe_key(f"{source}/raw", identifier, ext)
            curated_key = _safe_key(f"{source}/curated", identifier, ".json")

            raw_meta = {
                "source": source,
                "url": link,
                "fetched_at": datetime.utcnow().isoformat() + "Z",
                "content_type": content_type,
            }
            if fetch_error:
                raw_meta["fetch_error"] = fetch_error
            curated_payload = {
                "metadata": {
                    "citation": citation,
                    "base_citation": base_citation,
                    "name": case_name,
                    "court": item.get("court"),
                    "date": judgment_date.isoformat() if judgment_date else None,
                    "source": source,
                    "source_url": link,
                    "jurisdiction": item.get("jurisdiction"),
                    "year": item.get("year"),
                    "fidic_books": item.get("fidic_books"),
                    "published_date": (
                        published_date.isoformat() if published_date else None
                    ),
                },
                "summary": summary,
                "text": text,
            }

            meta = dict(item)
            meta.update(raw_meta)
            meta["citation"] = citation
            meta["base_citation"] = base_citation
            meta["text_hash"] = _hash_id(text) if text else ""

            try:
                self._upload_raw(raw_key, raw_bytes, content_type or "text/html")
                self._upload_curated(curated_key, curated_payload)
            except Exception as exc:
                logger.error("S3 upload failed for %s: %s", link, exc)
                skipped += 1
                continue

            if self.db:
                try:
                    if existing:
                        existing.case_name = case_name or existing.case_name
                        existing.court = item.get("court") or existing.court
                        existing.judgment_date = judgment_date or existing.judgment_date
                        existing.summary = summary or existing.summary
                        existing.full_text_preview = (
                            preview or existing.full_text_preview
                        )
                        existing.s3_key_raw = raw_key
                        existing.s3_key_curated = curated_key
                        existing.meta = meta
                        self.db.add(existing)
                    else:
                        record = self._build_db_record(
                            citation=citation,
                            case_name=case_name or citation,
                            court=item.get("court"),
                            judgment_date=judgment_date,
                            summary=summary,
                            preview=preview,
                            raw_key=raw_key,
                            curated_key=curated_key,
                            meta=meta,
                        )
                        self.db.add(record)
                    self.db.commit()
                except Exception as exc:
                    logger.error("DB insert failed for %s: %s", citation, exc)
                    self.db.rollback()
                    skipped += 1
                    continue

            ingested += 1
            logger.info("Ingested: %s (%s)", citation, link)
            time.sleep(self.sleep_s)

        logger.info(
            "Ingestion complete. Total considered: %s. Added: %s. Skipped: %s.",
            total,
            ingested,
            skipped,
        )
        if self.db:
            self.db.close()


def load_fidic_cases(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items: List[Dict[str, Any]] = []
    for row in data:
        link = (row.get("link") or "").strip()
        if not link:
            continue
        items.append(
            {
                "source": "fidic",
                "case_name": row.get("case_name") or "",
                "summary": row.get("summary") or "",
                "jurisdiction": row.get("jurisdiction"),
                "fidic_books": row.get("fidic_books"),
                "year": row.get("year"),
                "link": link,
                "link_label": row.get("link_label"),
            }
        )
    return items


def load_fenwick_urls(
    sitemap_url: str, base_url: str, prefix: str, max_urls: Optional[int]
) -> List[Dict[str, Any]]:
    resp = httpx.get(sitemap_url, timeout=httpx.Timeout(30.0))
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    seen: set[str] = set()

    for url in root.findall("sm:url", ns):
        loc = url.findtext("sm:loc", default="", namespaces=ns)
        if not loc:
            continue
        if loc.startswith("http://default"):
            loc = loc.replace("http://default", base_url, 1)
        if prefix:
            path = urlparse(loc).path.lstrip("/")
            if not path.startswith(prefix.rstrip("/")):
                continue
        if loc in seen:
            continue
        seen.add(loc)
        urls.append(
            {
                "source": "fenwick_elliott",
                "link": loc,
            }
        )
        if max_urls is not None and len(urls) >= max_urls:
            break

    return urls


def _parse_headers(values: Optional[List[str]]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for raw in values or []:
        if ":" not in raw:
            continue
        name, value = raw.split(":", 1)
        if name.strip():
            headers[name.strip()] = value.strip()
    return headers


def _parse_cookies(values: Optional[List[str]]) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        if name.strip():
            cookies[name.strip()] = value.strip()
    return cookies


def main():
    parser = argparse.ArgumentParser(description="Ingest case law from link sources")
    parser.add_argument(
        "--source",
        choices=["fidic", "fenwick"],
        required=True,
        help="Source list to ingest (fidic or fenwick).",
    )
    parser.add_argument(
        "--input",
        default="docs/fidic_cases.json",
        help="Input JSON path for fidic source.",
    )
    parser.add_argument(
        "--fenwick-sitemap",
        default=FENWICK_SITEMAP,
        help="Fenwick Elliott sitemap URL.",
    )
    parser.add_argument(
        "--fenwick-base-url",
        default=FENWICK_BASE_URL,
        help="Base URL to replace http://default in sitemap entries.",
    )
    parser.add_argument(
        "--fenwick-prefix",
        default="research-insight/adjudication-case-notes",
        help="Path prefix filter for Fenwick Elliott case notes.",
    )
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--start-at", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--header",
        action="append",
        help="Custom HTTP header (repeatable). Format: Name: Value",
    )
    parser.add_argument(
        "--cookie",
        action="append",
        help="Custom cookie (repeatable). Format: name=value",
    )
    parser.add_argument(
        "--user-agent",
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        help="HTTP User-Agent string.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (use only if needed).",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database writes; only upload to S3.",
    )
    parser.add_argument(
        "--skip-domain",
        action="append",
        default=[],
        help="Skip a domain (repeatable). Example: --skip-domain jusmundi.com",
    )
    parser.add_argument(
        "--allow-domain",
        action="append",
        default=[],
        help="Only allow a domain (repeatable). Example: --allow-domain www.bailii.org",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Do not fetch remote content; ingest just metadata/summary and the link.",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update existing DB rows/S3 objects for matching citations.",
    )
    parser.add_argument(
        "--no-fallback-summary",
        action="store_true",
        help="If fetch fails, do not ingest using summary fallback.",
    )
    args = parser.parse_args()

    headers = _parse_headers(args.header)
    cookies = _parse_cookies(args.cookie)

    ingestor = LinkIngestor(
        source=args.source,
        skip_db=args.skip_db,
        max_cases=args.max_cases,
        start_at=args.start_at,
        sleep_s=args.sleep,
        max_retries=args.max_retries,
        headers=headers,
        cookies=cookies,
        user_agent=args.user_agent,
        insecure=args.insecure,
        skip_domains=args.skip_domain,
        allow_domains=args.allow_domain,
        metadata_only=args.metadata_only,
        update_existing=args.update_existing,
        fallback_to_summary=not args.no_fallback_summary,
    )

    if args.source == "fidic":
        items = load_fidic_cases(args.input)
    else:
        items = load_fenwick_urls(
            sitemap_url=args.fenwick_sitemap,
            base_url=args.fenwick_base_url,
            prefix=args.fenwick_prefix,
            max_urls=args.max_cases,
        )

    ingestor.ingest_items(items)


if __name__ == "__main__":
    main()
