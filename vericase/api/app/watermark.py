from __future__ import annotations

from io import BytesIO

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color


MAX_WATERMARK_LENGTH = 120


def normalize_watermark_text(raw: str) -> str:
    """
    Sanitise user provided watermark text to a concise, single line string.
    Collapses whitespace and limits total length.
    """
    if raw is None:
        return ""
    cleaned = " ".join(raw.strip().split())
    if len(cleaned) > MAX_WATERMARK_LENGTH:
        cleaned = cleaned[:MAX_WATERMARK_LENGTH]
    return cleaned


def _make_watermark_page(text: str, width: float, height: float) -> BytesIO:
    buffer = BytesIO()
    can = canvas.Canvas(buffer, pagesize=(width, height))
    can.saveState()
    font_size = max(min(width, height) * 0.06, 18)
    try:
        # light opacity if backend supports it
        can.setFillColor(Color(0.6, 0.6, 0.6, alpha=0.18))
    except TypeError:
        can.setFillColorRGB(0.6, 0.6, 0.6)
    try:
        can.setFillAlpha(0.18)
    except AttributeError:
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
    """
    reader = PdfReader(BytesIO(original))
    writer = PdfWriter()
    text = normalize_watermark_text(watermark_text)
    if not text:
        raise ValueError("Watermark text is empty after sanitisation.")

    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        wm_stream = _make_watermark_page(text, width, height)
        watermark_pdf = PdfReader(wm_stream)
        watermark_page = watermark_pdf.pages[0]
        page.merge_page(watermark_page)
        writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()
