"""
Evidence Metadata Extraction Service

Extracts rich metadata from various file types:
- PDFs: Author, title, creation date, page count, producer
- Images: EXIF data (camera, date taken, GPS), dimensions
- Office docs: Author, title, company, created/modified dates
- Audio/Video: Duration, codec, bitrate
- General: Size, MIME type, hash, encoding

Uses Tika for text extraction and PyPDF2/Pillow for type-specific metadata.
"""

import os
import io
import re
import hashlib
import logging
import mimetypes
from datetime import datetime, timezone
from typing import Any
from dataclasses import dataclass, asdict
import httpx
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import PyPDF2

from .storage import get_object
from .config import settings
from .evidence.text_extract import extract_text_from_bytes, tika_url_candidates
from .email_normalizer import (
    NORMALIZER_RULESET_HASH,
    NORMALIZER_VERSION,
    clean_body_text,
)

logger = logging.getLogger(__name__)

# Tika server URL (from docker-compose)
TIKA_URL = os.getenv("TIKA_URL", "http://tika:9998")


@dataclass
class FileMetadata:
    """Comprehensive file metadata structure"""

    # Basic info
    filename: str
    file_size: int
    mime_type: str
    extension: str

    # Hash for integrity/dedup
    sha256: str | None = None
    md5: str | None = None

    # Document metadata
    title: str | None = None
    author: str | None = None
    creator: str | None = None
    producer: str | None = None
    subject: str | None = None
    keywords: list[str] | None = None
    description: str | None = None

    # Dates
    created_date: datetime | None = None
    modified_date: datetime | None = None

    # PDF specific
    page_count: int | None = None
    pdf_version: str | None = None
    is_encrypted: bool | None = None
    has_forms: bool | None = None

    # Image specific
    width: int | None = None
    height: int | None = None
    color_mode: str | None = None
    dpi: tuple[int, int] | None = None

    # EXIF data for images
    camera_make: str | None = None
    camera_model: str | None = None
    date_taken: datetime | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    exposure_time: str | None = None
    f_number: float | None = None
    iso_speed: int | None = None
    focal_length: float | None = None

    # Office document specific
    company: str | None = None
    manager: str | None = None
    category: str | None = None
    revision: int | None = None
    last_author: str | None = None
    word_count: int | None = None
    char_count: int | None = None
    paragraph_count: int | None = None
    slide_count: int | None = None

    # Audio/Video specific
    duration_seconds: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str | None = None

    # Email specific (for .msg/.eml)
    email_from: str | None = None
    email_to: list[str] | None = None
    email_cc: list[str] | None = None
    email_subject: str | None = None
    email_date: datetime | None = None
    has_attachments: bool | None = None
    attachment_count: int | None = None
    normalizer_version: str | None = None
    normalizer_ruleset_hash: str | None = None

    # Text content preview
    text_preview: str | None = None
    text_length: int | None = None
    language: str | None = None
    encoding: str | None = None

    # Construction/Legal specific
    document_reference: str | None = None
    project_reference: str | None = None
    drawing_number: str | None = None
    revision_number: str | None = None

    # Extraction status
    extraction_status: str = "pending"
    extraction_error: str | None = None
    extracted_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, handling datetime and special type serialization"""
        result = {}
        for key, value in asdict(self).items():
            if value is None:
                continue
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, (int, float, str, bool)):
                result[key] = value
            elif isinstance(value, (list, tuple)):
                # Convert tuple to list and ensure all elements are serializable
                result[key] = [self._serialize_value(v) for v in value]
            elif isinstance(value, dict):
                result[key] = {k: self._serialize_value(v) for k, v in value.items()}
            else:
                # Try to convert to a basic type
                result[key] = self._serialize_value(value)
        return result

    def _serialize_value(self, value):
        """Convert any value to a JSON-serializable type"""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            # Remove null characters and other problematic unicode
            return value.replace("\x00", "").replace("\u0000", "")
        if isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        # Handle PIL/EXIF special types (IFDRational, etc.)
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            # It's a rational/fraction type
            try:
                return float(value)
            except (ValueError, TypeError, AttributeError) as e:
                logger.debug(f"Parse failed for rational: {e}")
                return self._sanitize_string(str(value))
        # Last resort: convert to string
        try:
            return self._sanitize_string(str(value))
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"String conversion failed: {e}")
            return None

    def _sanitize_string(self, s: str) -> str:
        """Remove null characters and other problematic unicode from string"""
        if not s:
            return s
        # Remove null characters that can't be stored in PostgreSQL
        return s.replace("\x00", "").replace("\u0000", "")


class MetadataExtractor:
    """
    Extracts metadata from files stored in S3/MinIO.

    Uses a combination of:
    - Native Python libraries (PyPDF2, Pillow)
    - Apache Tika for rich text extraction
    - Custom parsers for construction documents
    """

    def __init__(self):
        self.tika_url: str | None = None
        self.tika_available = self._check_tika()

    def _check_tika(self) -> bool:
        """Check if Tika server is available"""
        last_error: str | None = None
        for base in tika_url_candidates(TIKA_URL):
            try:
                response = httpx.get(f"{base}/tika", timeout=5.0)
                if response.status_code == 200:
                    self.tika_url = base
                    return True
                last_error = f"HTTP {response.status_code}"
            except Exception as e:
                last_error = str(e)
                continue
        logger.warning(f"Tika server not available: {last_error or 'unknown'}")
        self.tika_url = None
        return False

    def _normalize_email_metadata(self, metadata: FileMetadata) -> None:
        metadata.normalizer_version = NORMALIZER_VERSION
        metadata.normalizer_ruleset_hash = NORMALIZER_RULESET_HASH

        if not metadata.text_preview:
            return

        cleaned = clean_body_text(metadata.text_preview)
        if cleaned is None:
            return

        metadata.text_preview = cleaned[:2000]
        metadata.text_length = len(cleaned)

    async def extract_metadata(
        self, s3_key: str, bucket: str | None = None
    ) -> FileMetadata:
        """
        Extract comprehensive metadata from a file.

        Args:
            s3_key: S3 object key
            bucket: Optional bucket name (uses default if not provided)

        Returns:
            FileMetadata object with all extracted data
        """
        bucket = bucket or settings.MINIO_BUCKET
        filename = os.path.basename(s3_key)
        extension = os.path.splitext(filename)[1].lower()
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Initialize metadata with basic info
        metadata = FileMetadata(
            filename=filename,
            file_size=0,
            mime_type=mime_type,
            extension=extension,
            extraction_status="processing",
        )

        try:
            # Get file content from S3
            file_content = get_object(s3_key, bucket=bucket)
            if not file_content:
                metadata.extraction_status = "error"
                metadata.extraction_error = "File not found in storage"
                return metadata

            metadata.file_size = len(file_content)

            # Calculate hashes
            metadata.sha256 = hashlib.sha256(file_content).hexdigest()
            metadata.md5 = hashlib.md5(file_content).hexdigest()

            # Extract based on file type
            if mime_type.startswith("image/"):
                await self._extract_image_metadata(file_content, metadata)
            elif mime_type == "application/pdf":
                await self._extract_pdf_metadata(file_content, metadata)
            elif mime_type in [
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ]:
                await self._extract_word_metadata(file_content, metadata)
            elif mime_type in [
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ]:
                await self._extract_excel_metadata(file_content, metadata)
            elif mime_type in [
                "application/vnd.ms-powerpoint",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ]:
                await self._extract_ppt_metadata(file_content, metadata)
            elif mime_type == "application/vnd.ms-outlook" or extension == ".msg":
                await self._extract_msg_metadata(file_content, metadata)
            elif mime_type == "message/rfc822" or extension == ".eml":
                await self._extract_eml_metadata(file_content, metadata)
            elif mime_type.startswith("text/") or extension in [
                ".txt",
                ".csv",
                ".json",
                ".xml",
                ".html",
            ]:
                await self._extract_text_metadata(file_content, metadata)

            # Use Tika for additional extraction if available
            if self.tika_available:
                await self._extract_tika_metadata(file_content, metadata)

            if mime_type in [
                "application/vnd.ms-outlook",
                "message/rfc822",
            ] or extension in [".msg", ".eml"]:
                self._normalize_email_metadata(metadata)

            # Extract construction-specific references
            self._extract_construction_references(metadata)

            metadata.extraction_status = "complete"
            metadata.extracted_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Error extracting metadata from {s3_key}: {e}")
            metadata.extraction_status = "error"
            metadata.extraction_error = str(e)

        return metadata

    def _parse_date_flexible(self, date_str: str) -> datetime | None:
        """Try to parse date from various formats"""
        if not date_str:
            return None

        # Clean up string
        date_str = date_str.strip()

        # Try ISO format first
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            pass

        # Try common formats
        formats = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y:%m:%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822
            "%a, %d %b %Y %H:%M:%S GMT",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None

    async def _extract_image_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from images including EXIF"""
        try:
            img = Image.open(io.BytesIO(content))

            metadata.width = img.width
            metadata.height = img.height
            metadata.color_mode = img.mode

            # Get DPI if available (convert IFDRational to regular floats)
            if "dpi" in img.info:
                dpi = img.info["dpi"]
                try:
                    if isinstance(dpi, (list, tuple)) and len(dpi) >= 2:
                        dpi_x = (
                            float(dpi[0])
                            if hasattr(dpi[0], "__float__")
                            else float(str(dpi[0]))
                        )
                        dpi_y = (
                            float(dpi[1])
                            if hasattr(dpi[1], "__float__")
                            else float(str(dpi[1]))
                        )
                        metadata.dpi = (int(dpi_x), int(dpi_y))
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug(f"DPI parse failed: {e}")

            # Extract EXIF data
            exif_data = img._getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)

                    try:
                        if tag == "Make":
                            metadata.camera_make = (
                                str(value).replace("\x00", "").strip()
                            )
                        elif tag == "Model":
                            metadata.camera_model = (
                                str(value).replace("\x00", "").strip()
                            )
                        elif tag in [
                            "DateTimeOriginal",
                            "DateTime",
                            "DateTimeDigitized",
                        ]:
                            # Try to get date from any of these tags, prioritizing Original
                            if not metadata.date_taken or tag == "DateTimeOriginal":
                                try:
                                    # Handle potential null bytes
                                    val_str = str(value).replace("\x00", "").strip()
                                    metadata.date_taken = datetime.strptime(
                                        val_str, "%Y:%m:%d %H:%M:%S"
                                    )
                                except (ValueError, TypeError) as e:
                                    logger.debug(f"{tag} parse failed: {e}")
                        elif tag == "ExposureTime":
                            # Convert to float safely (handles IFDRational)
                            fval = (
                                float(value)
                                if hasattr(value, "__float__")
                                else float(str(value))
                            )
                            metadata.exposure_time = (
                                f"1/{int(1 / fval)}" if fval < 1 else str(fval)
                            )
                        elif tag == "FNumber":
                            # Convert to float safely
                            metadata.f_number = (
                                float(value)
                                if hasattr(value, "__float__")
                                else float(str(value))
                            )
                        elif tag == "ISOSpeedRatings":
                            if isinstance(value, (list, tuple)):
                                metadata.iso_speed = int(value[0])
                            else:
                                metadata.iso_speed = (
                                    int(float(value))
                                    if hasattr(value, "__float__")
                                    else int(str(value))
                                )
                        elif tag == "FocalLength":
                            # Convert to float safely
                            metadata.focal_length = (
                                float(value)
                                if hasattr(value, "__float__")
                                else float(str(value))
                            )
                        elif tag == "GPSInfo":
                            gps = self._parse_gps_info(value)
                            if gps:
                                metadata.gps_latitude = gps.get("latitude")
                                metadata.gps_longitude = gps.get("longitude")
                    except (ValueError, TypeError, AttributeError) as e:
                        logger.debug(f"EXIF tag {tag} parse failed: {e}")

            img.close()
        except Exception as e:
            logger.warning(f"Error extracting image metadata: {e}")

    def _parse_gps_info(self, gps_info: dict) -> dict[str, float] | None:
        """Parse GPS EXIF data to lat/lon coordinates"""
        try:
            gps_tags = {GPSTAGS.get(key, key): value for key, value in gps_info.items()}

            def safe_float(v):
                """Safely convert value to float (handles IFDRational)"""
                if hasattr(v, "__float__"):
                    return float(v)
                return float(str(v))

            def convert_to_degrees(value):
                d, m, s = value
                return safe_float(d) + safe_float(m) / 60 + safe_float(s) / 3600

            lat_values = gps_tags.get("GPSLatitude")
            lon_values = gps_tags.get("GPSLongitude")

            if not lat_values or not lon_values:
                return None

            lat = convert_to_degrees(lat_values)
            lon = convert_to_degrees(lon_values)

            if gps_tags.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_tags.get("GPSLongitudeRef") == "W":
                lon = -lon

            return {"latitude": lat, "longitude": lon}
        except Exception as e:
            logger.debug(f"Could not parse GPS info: {e}")
            return None

    async def _extract_pdf_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from PDF files"""
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))

            metadata.page_count = len(pdf_reader.pages)
            metadata.is_encrypted = pdf_reader.is_encrypted

            # Get document info
            info = pdf_reader.metadata
            if info:
                metadata.title = info.get("/Title")
                metadata.author = info.get("/Author")
                metadata.creator = info.get("/Creator")
                metadata.producer = info.get("/Producer")
                metadata.subject = info.get("/Subject")

                # Parse dates
                if "/CreationDate" in info:
                    metadata.created_date = self._parse_pdf_date(
                        str(info["/CreationDate"])
                    )
                if "/ModDate" in info:
                    metadata.modified_date = self._parse_pdf_date(str(info["/ModDate"]))

            # Check for forms
            if "/AcroForm" in pdf_reader.trailer.get("/Root", {}):
                metadata.has_forms = True

            # Extract text preview from first page
            if pdf_reader.pages:
                first_page_text = pdf_reader.pages[0].extract_text()
                if first_page_text:
                    metadata.text_preview = first_page_text[:2000]
                    metadata.text_length = len(first_page_text)

        except Exception as e:
            logger.warning(f"Error extracting PDF metadata: {e}")

    def _parse_pdf_date(self, date_str: str) -> datetime | None:
        """Parse PDF date format (D:YYYYMMDDHHmmSS)"""
        try:
            if date_str.startswith("D:"):
                date_str = date_str[2:]
            # Remove timezone info for simplicity
            date_str = date_str[:14]
            return datetime.strptime(date_str, "%Y%m%d%H%M%S")
        except ValueError as e:
            logger.debug(f"Could not parse PDF date: {e}")
            return None

    async def _extract_word_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from Word documents"""
        # Best-effort local text preview so the Evidence UI can render something
        # even if Tika is unavailable.
        if not metadata.text_preview:
            text = extract_text_from_bytes(
                content,
                filename=metadata.filename,
                mime_type=metadata.mime_type,
                max_chars=4000,
            )
            if text:
                metadata.text_preview = text[:2000]
                metadata.text_length = len(text)
                metadata.word_count = len(text.split())

    async def _extract_excel_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from Excel documents"""
        if not metadata.text_preview:
            text = extract_text_from_bytes(
                content,
                filename=metadata.filename,
                mime_type=metadata.mime_type,
                max_chars=4000,
            )
            if text:
                metadata.text_preview = text[:2000]
                metadata.text_length = len(text)

    async def _extract_ppt_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from PowerPoint documents"""
        # Will be enhanced by Tika extraction
        pass

    async def _extract_msg_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from Outlook .msg files"""
        # Basic extraction - Tika provides more comprehensive parsing
        pass

    async def _extract_eml_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from .eml email files"""
        import email
        from email import policy
        from email.utils import getaddresses, parsedate_to_datetime

        try:
            msg = email.message_from_bytes(content, policy=policy.default)
            metadata.email_from = msg.get("From")
            metadata.email_to = [
                addr for _, addr in getaddresses([msg.get("To", "")]) if addr
            ]
            metadata.email_cc = [
                addr for _, addr in getaddresses([msg.get("Cc", "")]) if addr
            ]
            metadata.email_subject = msg.get("Subject")

            # Parse date
            date_str = msg.get("Date")
            if date_str:
                try:
                    metadata.email_date = parsedate_to_datetime(date_str)
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug(f"Could not parse {date_str}: {e}")

            # Check for attachments
            metadata.has_attachments = msg.is_multipart()
            if msg.is_multipart():
                attachment_count = sum(
                    1
                    for part in msg.walk()
                    if part.get_content_disposition() == "attachment"
                )
                metadata.attachment_count = attachment_count

            def _decode_payload(payload: bytes, charset: str | None) -> str | None:
                if not payload:
                    return None
                for encoding in [charset, "utf-8", "latin-1", "cp1252"]:
                    if not encoding:
                        continue
                    try:
                        return payload.decode(encoding)
                    except (UnicodeDecodeError, LookupError):
                        continue
                return payload.decode("utf-8", errors="replace")

            def _get_part_text(part: email.message.Message) -> str | None:
                try:
                    content = part.get_content()
                    if isinstance(content, str):
                        return content
                except Exception:
                    pass
                payload = part.get_payload(decode=True)
                if payload is None:
                    return None
                return _decode_payload(payload, part.get_content_charset())

            body_text = None
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_disposition() == "attachment":
                        continue
                    if part.get_content_type() == "text/plain":
                        body_text = _get_part_text(part)
                        if body_text:
                            break
                if not body_text:
                    for part in msg.walk():
                        if part.get_content_disposition() == "attachment":
                            continue
                        if part.get_content_type() == "text/html":
                            body_text = _get_part_text(part)
                            if body_text:
                                break
            else:
                body_text = _get_part_text(msg)

            if body_text:
                metadata.text_preview = body_text[:4000]
                metadata.text_length = len(body_text)

        except Exception as e:
            logger.warning(f"Error extracting EML metadata: {e}")

    async def _extract_text_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Extract metadata from text files"""
        try:
            # Try common encodings
            for encoding in ["utf-8", "latin-1", "cp1252"]:
                try:
                    text = content.decode(encoding)
                    metadata.encoding = encoding
                    break
                except (ValueError, TypeError, AttributeError) as e:
                    logger.debug(f"Could not decode {encoding}: {e}")
                    continue
            else:
                text = content.decode("utf-8", errors="ignore")
                metadata.encoding = "utf-8 (lossy)"

            metadata.text_preview = text[:2000]
            metadata.text_length = len(text)
            metadata.char_count = len(text)
            metadata.word_count = len(text.split())

        except Exception as e:
            logger.warning(f"Error extracting text metadata: {e}")

    async def _extract_tika_metadata(
        self, content: bytes, metadata: FileMetadata
    ) -> None:
        """Use Apache Tika for comprehensive metadata extraction"""
        if not self.tika_url:
            return
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get metadata
                response = await client.put(
                    f"{self.tika_url}/meta",
                    content=content,
                    headers={"Accept": "application/json"},
                )

                if response.status_code == 200:
                    tika_meta = response.json()

                    # Map Tika fields to our metadata structure
                    if not metadata.title:
                        metadata.title = tika_meta.get("dc:title") or tika_meta.get(
                            "title"
                        )
                    if not metadata.author:
                        metadata.author = (
                            tika_meta.get("dc:creator")
                            or tika_meta.get("Author")
                            or tika_meta.get("meta:author")
                        )
                    if not metadata.created_date:
                        created = (
                            tika_meta.get("dcterms:created")
                            or tika_meta.get("Creation-Date")
                            or tika_meta.get("meta:creation-date")
                        )
                        if created:
                            metadata.created_date = self._parse_date_flexible(created)

                    if not metadata.modified_date:
                        modified = (
                            tika_meta.get("dcterms:modified")
                            or tika_meta.get("Last-Modified")
                            or tika_meta.get("meta:save-date")
                        )
                        if modified:
                            metadata.modified_date = self._parse_date_flexible(modified)

                    # Office-specific
                    if not metadata.company:
                        metadata.company = tika_meta.get("extended-properties:Company")
                    if not metadata.last_author:
                        metadata.last_author = tika_meta.get("meta:last-author")
                    if not metadata.revision:
                        rev = tika_meta.get("extended-properties:Revision")
                        if rev:
                            try:
                                metadata.revision = int(rev)
                            except (ValueError, TypeError) as e:
                                logger.debug(f"Could not parse revision {rev}: {e}")
                    if not metadata.word_count:
                        wc = tika_meta.get("meta:word-count")
                        if wc:
                            try:
                                metadata.word_count = int(wc)
                            except (ValueError, TypeError) as e:
                                logger.debug(f"Could not parse word count {wc}: {e}")
                    if not metadata.page_count:
                        pc = tika_meta.get("xmpTPg:NPages") or tika_meta.get(
                            "meta:page-count"
                        )
                        if pc:
                            try:
                                metadata.page_count = int(pc)
                            except (ValueError, TypeError) as e:
                                logger.debug(f"Could not parse page count {pc}: {e}")

                    # Language detection
                    metadata.language = tika_meta.get("language")

                # Get text content if not already extracted
                if not metadata.text_preview:
                    text_response = await client.put(
                        f"{self.tika_url}/tika",
                        content=content,
                        headers={"Accept": "text/plain"},
                    )
                    if text_response.status_code == 200:
                        text = text_response.text
                        metadata.text_preview = text[:2000]
                        metadata.text_length = len(text)

        except Exception as e:
            logger.warning(f"Tika extraction failed: {e}")

    def _extract_construction_references(self, metadata: FileMetadata) -> None:
        """Extract construction-specific reference numbers from text/filename"""
        if not metadata.text_preview and not metadata.filename:
            return

        text = (metadata.text_preview or "") + " " + (metadata.filename or "")
        text = text.upper()

        # Common construction document patterns
        patterns = {
            "drawing_number": [
                r"(?:DRG|DWG|DRAWING)[-_\s]?(?:NO\.?)?[-_\s]?([A-Z0-9]+-[A-Z0-9]+(?:-[A-Z0-9]+)*)",
                r"([A-Z]{2,4}[-_][0-9]{3,}[-_][A-Z0-9]+)",
            ],
            "revision_number": [
                r"REV(?:ISION)?[-_\s]?(?:NO\.?)?[-_\s]?([A-Z0-9]+)",
                r"(?:R|REV)([0-9]+|[A-Z])",
            ],
            "project_reference": [
                r"(?:PROJECT|PROJ|JOB)[-_\s]?(?:NO\.?|REF\.?)?[-_\s]?([A-Z0-9]+-?[A-Z0-9]+)",
            ],
            "document_reference": [
                r"(?:DOC|REF|REFERENCE)[-_\s]?(?:NO\.?)?[-_\s]?([A-Z0-9]+-[A-Z0-9]+)",
                r"(?:RFI|SI|AI|TQ|VO|CCN|CO|PCO)[-_\s]?([0-9]+)",
            ],
        }

        for field, pattern_list in patterns.items():
            for pattern in pattern_list:
                match = re.search(pattern, text)
                if match:
                    setattr(metadata, field, match.group(1))
                    break


# Singleton instance
_extractor = None


def get_metadata_extractor() -> MetadataExtractor:
    """Get or create the metadata extractor singleton"""
    global _extractor
    if _extractor is None:
        _extractor = MetadataExtractor()
    return _extractor


async def extract_evidence_metadata(
    s3_key: str, bucket: str | None = None
) -> dict[str, Any]:
    """
    Convenience function to extract metadata and return as dict.

    Args:
        s3_key: S3 object key
        bucket: Optional bucket name

    Returns:
        Dictionary with all extracted metadata
    """
    extractor = get_metadata_extractor()
    metadata = await extractor.extract_metadata(s3_key, bucket)
    return metadata.to_dict()
