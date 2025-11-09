from __future__ import annotations

from io import BytesIO
import logging

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color

logger = logging.getLogger(__name__)

MAX_WATERMARK_LENGTH = 120


def normalize_watermark_text(raw: str) -> str:
    """
    Sanitize user-provided watermark text to a concise, single-line string.
    
    Collapses whitespace, removes control characters, and limits total length
    to prevent injection attacks and ensure safe display.
    
    Args:
        raw: User-provided watermark text
        
    Returns:
        Sanitized watermark text
    """
    if raw is None:
        return ""
    
    # Remove control characters and normalize whitespace
    cleaned = " ".join(raw.strip().split())
    
    # Remove any potentially dangerous characters
    cleaned = cleaned.replace('\x00', '').replace('\r', '').replace('\n', '')
    
    if len(cleaned) > MAX_WATERMARK_LENGTH:
        logger.info(f"Watermark text truncated from {len(cleaned)} to {MAX_WATERMARK_LENGTH} characters")
        cleaned = cleaned[:MAX_WATERMARK_LENGTH]
    
    return cleaned


def _make_watermark_page(text: str, width: float, height: float) -> BytesIO:
    """
    Create a watermark page with diagonal text.
    
    Args:
        text: Sanitized watermark text
        width: Page width in points
        height: Page height in points
        
    Returns:
        BytesIO buffer containing the watermark PDF page
    """
    buffer = BytesIO()
    can = canvas.Canvas(buffer, pagesize=(width, height))
    can.saveState()
    
    # Calculate font size proportional to page dimensions
    font_size = max(min(width, height) * 0.06, 18)
    
    try:
        # Set light opacity if backend supports it
        can.setFillColor(Color(0.6, 0.6, 0.6, alpha=0.18))
    except TypeError:
        logger.debug("Alpha channel not supported, using RGB only")
        can.setFillColorRGB(0.6, 0.6, 0.6)
    
    try:
        can.setFillAlpha(0.18)
    except AttributeError:
        logger.debug("setFillAlpha not supported")
        pass
    
    can.setFont("Helvetica-Bold", font_size)
    can.translate(width / 2, height / 2)
    can.rotate(45)
    can.drawCentredString(0, 0, text)
    can.restoreState()
    can.save()
    buffer.seek(0)
    return buffer


def build_watermarked_pdf(original: bytes, watermark_text: str) -> bytes:
    """
    Embed a textual watermark diagonally across every page of a PDF.
    
    Args:
        original: Original PDF file content as bytes
        watermark_text: Text to watermark (will be sanitized)
        
    Returns:
        Watermarked PDF as bytes
        
    Raises:
        ValueError: If watermark text is empty after sanitization
        RuntimeError: If PDF processing fails
    """
    try:
        reader = PdfReader(BytesIO(original))
    except Exception as e:
        logger.error(f"Failed to read PDF: {e}")
        raise ValueError(f"Invalid PDF file: {e}")
    
    writer = PdfWriter()
    text = normalize_watermark_text(watermark_text)
    
    if not text:
        logger.warning("Watermark text is empty after sanitization")
        raise ValueError("Watermark text is empty after sanitization.")
    
    logger.info(f"Applying watermark to {len(reader.pages)} page(s)")

    try:
        for page in reader.pages:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            wm_stream = _make_watermark_page(text, width, height)
            watermark_pdf = PdfReader(wm_stream)
            watermark_page = watermark_pdf.pages[0]
            page.merge_page(watermark_page)
            writer.add_page(page)
    except Exception as e:
        logger.error(f"Failed to apply watermark: {e}")
        raise RuntimeError(f"Failed to apply watermark: {e}")
    
    try:
        out = BytesIO()
        writer.write(out)
        out.seek(0)
        result = out.read()
        logger.debug(f"Successfully created watermarked PDF ({len(result)} bytes)")
        return result
    except Exception as e:
        logger.error(f"Failed to write watermarked PDF: {e}")
        raise RuntimeError(f"Failed to write watermarked PDF: {e}")
