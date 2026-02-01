"""API endpoints for OCR corrections and feedback loop."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from .db import get_db
from .security import current_user
from .models import User, OcrCorrection

router = APIRouter(prefix="/api/ocr", tags=["OCR Feedback"])


class OcrCorrectionCreate(BaseModel):
    source_type: str = Field(..., description="document | email_attachment")
    source_id: str = Field(..., description="UUID of the source item")
    original_text: str
    corrected_text: str
    field_type: str | None = None
    page: int | None = None
    bbox: dict[str, Any] | None = None
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    scope: str = "project"
    project_id: str | None = None
    case_id: str | None = None


class OcrCorrectionResponse(BaseModel):
    id: int
    source_type: str
    source_id: str
    original_text: str
    corrected_text: str
    created_at: str
    created_by: str | None


@router.post("/corrections", response_model=OcrCorrectionResponse)
def create_ocr_correction(
    payload: OcrCorrectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Submit a manual OCR correction."""
    # Validate source_id if possible (loose check as we store as string for flexibility)
    # Logic could be expanded here to enforce strict referential integrity check

    # Create correction
    correction = OcrCorrection(
        doc_id=payload.source_id,
        source_type=payload.source_type,
        page=payload.page,
        bbox=payload.bbox,
        field_type=payload.field_type,
        original_text=payload.original_text,
        corrected_text=payload.corrected_text,
        ocr_engine=payload.ocr_engine,
        ocr_confidence=payload.ocr_confidence,
        scope=payload.scope,
        project_id=uuid.UUID(payload.project_id) if payload.project_id else None,
        case_id=uuid.UUID(payload.case_id) if payload.case_id else None,
        created_by=user.id,
    )
    db.add(correction)
    db.commit()
    db.refresh(correction)

    return {
        "id": correction.id,
        "source_type": correction.source_type,
        "source_id": correction.doc_id,
        "original_text": correction.original_text,
        "corrected_text": correction.corrected_text,
        "created_at": (
            correction.created_at.isoformat() if correction.created_at else ""
        ),
        "created_by": str(correction.created_by) if correction.created_by else None,
    }


@router.get("/corrections", response_model=list[OcrCorrectionResponse])
def list_ocr_corrections(
    source_id: str | None = Query(None),
    project_id: str | None = Query(None),
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """List OCR corrections with optional filtering."""
    query = db.query(OcrCorrection)

    if source_id:
        query = query.filter(OcrCorrection.doc_id == source_id)

    if project_id:
        try:
            pid = uuid.UUID(project_id)
            query = query.filter(OcrCorrection.project_id == pid)
        except ValueError:
            pass

    items = query.order_by(OcrCorrection.created_at.desc()).limit(limit).all()

    return [
        {
            "id": c.id,
            "source_type": c.source_type,
            "source_id": c.doc_id,
            "original_text": c.original_text,
            "corrected_text": c.corrected_text,
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "created_by": str(c.created_by) if c.created_by else None,
        }
        for c in items
    ]
