from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import get_db
from .forensic_integrity import (
    compute_normalized_text_hash,
    compute_span_hash,
    make_dep_uri,
    parse_dep_uri,
)
from .models import EmailMessage, EvidenceItem, EvidenceSpan, User
from .security import get_current_user

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

router = APIRouter(prefix="/api/forensics", tags=["forensics"])


class CreateSpanRequest(BaseModel):
    source_type: Literal["evidence_item", "email_message"]
    source_id: str
    case_id: str | None = None
    project_id: str | None = None
    start_offset: int = Field(..., ge=0)
    end_offset: int = Field(..., ge=0)
    quote: str | None = None


class EvidenceSpanResponse(BaseModel):
    dep_uri: str
    source_type: str
    source_id: str
    case_id: str | None = None
    project_id: str | None = None
    start_offset: int
    end_offset: int
    quote: str
    span_hash: str
    normalized_text_hash: str
    verified: bool | None = None
    verification: dict[str, Any] | None = None


def _uuid_or_400(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {field}")


def _get_source_text(
    db: Session, source_type: str, source_uuid: uuid.UUID
) -> tuple[str, str | None, str | None]:
    if source_type == "evidence_item":
        item = db.query(EvidenceItem).filter(EvidenceItem.id == source_uuid).first()
        if item is None:
            raise HTTPException(status_code=404, detail="EvidenceItem not found")
        text = item.extracted_text or ""
        return (
            text,
            str(item.case_id) if item.case_id else None,
            str(item.project_id) if item.project_id else None,
        )

    if source_type == "email_message":
        msg = db.query(EmailMessage).filter(EmailMessage.id == source_uuid).first()
        if msg is None:
            raise HTTPException(status_code=404, detail="EmailMessage not found")
        text = msg.body_text_clean or msg.body_text or ""
        return (
            text,
            str(msg.case_id) if msg.case_id else None,
            str(msg.project_id) if msg.project_id else None,
        )

    raise HTTPException(status_code=400, detail="Invalid source_type")


@router.post("/spans", response_model=EvidenceSpanResponse)
def create_span(
    payload: CreateSpanRequest, db: DbSession, user: CurrentUser
) -> EvidenceSpanResponse:  # noqa: ARG001
    source_uuid = _uuid_or_400(payload.source_id, "source_id")

    source_text, source_case_id, source_project_id = _get_source_text(
        db, payload.source_type, source_uuid
    )
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="Source text is empty")

    start = payload.start_offset
    end = payload.end_offset
    if end < start or end > len(source_text):
        raise HTTPException(status_code=400, detail="Invalid offsets for source text")

    normalized_text_hash = compute_normalized_text_hash(source_text)
    span_hash = compute_span_hash(source_text, start, end)

    effective_case_id = payload.case_id or source_case_id
    effective_project_id = payload.project_id or source_project_id

    dep_uri_case_id = effective_case_id or "nocase"
    dep_uri = make_dep_uri(
        case_id=dep_uri_case_id,
        source_type=payload.source_type,
        source_id=str(source_uuid),
        start=start,
        end=end,
        span_hash=span_hash,
    )

    existing = db.query(EvidenceSpan).filter(EvidenceSpan.dep_uri == dep_uri).first()
    if existing:
        return EvidenceSpanResponse(
            dep_uri=existing.dep_uri,
            source_type=existing.source_type,
            source_id=str(source_uuid),
            case_id=str(existing.case_id) if existing.case_id else None,
            project_id=str(existing.project_id) if existing.project_id else None,
            start_offset=existing.start_offset,
            end_offset=existing.end_offset,
            quote=existing.quote,
            span_hash=existing.span_hash,
            normalized_text_hash=existing.normalized_text_hash,
        )

    quote = payload.quote or source_text[start:end]
    quote = quote.strip()
    if len(quote) > 800:
        quote = quote[:800]

    span = EvidenceSpan(
        case_id=(
            _uuid_or_400(effective_case_id, "case_id") if effective_case_id else None
        ),
        project_id=(
            _uuid_or_400(effective_project_id, "project_id")
            if effective_project_id
            else None
        ),
        source_type=payload.source_type,
        source_evidence_id=(
            source_uuid if payload.source_type == "evidence_item" else None
        ),
        source_email_id=source_uuid if payload.source_type == "email_message" else None,
        start_offset=start,
        end_offset=end,
        quote=quote,
        span_hash=span_hash,
        normalized_text_hash=normalized_text_hash,
        dep_uri=dep_uri,
    )
    db.add(span)

    # Opportunistically persist Layer-2 hashes on sources
    if payload.source_type == "evidence_item":
        item = db.query(EvidenceItem).filter(EvidenceItem.id == source_uuid).first()
        if item and not item.normalized_text_hash:
            item.normalized_text_hash = normalized_text_hash
    if payload.source_type == "email_message":
        msg = db.query(EmailMessage).filter(EmailMessage.id == source_uuid).first()
        if msg and not msg.body_text_clean_hash:
            msg.body_text_clean_hash = normalized_text_hash

    db.commit()

    return EvidenceSpanResponse(
        dep_uri=span.dep_uri,
        source_type=span.source_type,
        source_id=str(source_uuid),
        case_id=str(span.case_id) if span.case_id else None,
        project_id=str(span.project_id) if span.project_id else None,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        quote=span.quote,
        span_hash=span.span_hash,
        normalized_text_hash=span.normalized_text_hash,
    )


@router.get("/spans/resolve", response_model=EvidenceSpanResponse)
def resolve_span(
    db: DbSession,
    user: CurrentUser,  # noqa: ARG001
    dep_uri: str = Query(...),
    verify: bool = Query(default=True),
) -> EvidenceSpanResponse:
    parsed = parse_dep_uri(dep_uri)
    span = db.query(EvidenceSpan).filter(EvidenceSpan.dep_uri == dep_uri).first()
    if span is None:
        raise HTTPException(status_code=404, detail="EvidenceSpan not found")

    response = EvidenceSpanResponse(
        dep_uri=span.dep_uri,
        source_type=span.source_type,
        source_id=str(
            span.source_evidence_id or span.source_email_id or parsed.source_id
        ),
        case_id=str(span.case_id) if span.case_id else None,
        project_id=str(span.project_id) if span.project_id else None,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        quote=span.quote,
        span_hash=span.span_hash,
        normalized_text_hash=span.normalized_text_hash,
    )

    if not verify:
        return response

    source_uuid = _uuid_or_400(parsed.source_id, "source_id")
    source_text, _, _ = _get_source_text(db, parsed.source_type, source_uuid)
    recomputed_span_hash = compute_span_hash(
        source_text, span.start_offset, span.end_offset
    )
    recomputed_norm_hash = compute_normalized_text_hash(source_text)

    response.verified = (recomputed_span_hash == span.span_hash) and (
        recomputed_norm_hash == span.normalized_text_hash
    )
    response.verification = {
        "span_hash_match": recomputed_span_hash == span.span_hash,
        "normalized_text_hash_match": recomputed_norm_hash == span.normalized_text_hash,
    }
    return response


@router.get("/sources/{source_type}/{source_id}/spans")
def list_spans_for_source(
    source_type: Literal["evidence_item", "email_message"],
    source_id: str,
    db: DbSession,
    user: CurrentUser,  # noqa: ARG001
) -> dict[str, Any]:
    source_uuid = _uuid_or_400(source_id, "source_id")

    query = db.query(EvidenceSpan).filter(EvidenceSpan.source_type == source_type)
    if source_type == "evidence_item":
        query = query.filter(EvidenceSpan.source_evidence_id == source_uuid)
    else:
        query = query.filter(EvidenceSpan.source_email_id == source_uuid)

    spans = query.order_by(EvidenceSpan.created_at.desc()).limit(200).all()
    return {
        "total": len(spans),
        "items": [
            {
                "dep_uri": s.dep_uri,
                "start_offset": s.start_offset,
                "end_offset": s.end_offset,
                "quote": s.quote,
                "span_hash": s.span_hash,
                "normalized_text_hash": s.normalized_text_hash,
                "created_at": s.created_at,
            }
            for s in spans
        ],
    }
