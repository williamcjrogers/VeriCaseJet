import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..aws_services import aws_services
from ..db import SessionLocal, get_db
from ..models import CaseLaw, EvidenceItem, User, UserRole
from ..security import get_current_user
from ..ai_caselaw_agent import caselaw_agent
from ..services.caselaw_trends import (
    summarize_case_law_trends,
    suggest_tags_from_text,
)
from ..services.caselaw_mining import caselaw_miner
from ..services.caselaw_kb_sync import export_caselaw_docs_to_knowledge_base
from ..evidence.services import (
    direct_upload_evidence_service,
    get_evidence_text_content_service,
)

router = APIRouter(prefix="/api/caselaw", tags=["caselaw"])

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


def _require_admin(user: User) -> None:
    if getattr(user, "role", None) != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")


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


async def _mine_case_batch(case_ids: List[str], concurrency: int) -> None:
    concurrency = max(1, min(int(concurrency or 1), 10))
    semaphore = asyncio.Semaphore(concurrency)

    async def mine_one(case_id: str) -> None:
        async with semaphore:
            db = SessionLocal()
            try:
                await caselaw_miner.mine_case(case_id, db)
            finally:
                db.close()

    await asyncio.gather(*(mine_one(cid) for cid in case_ids))


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    enable_trace: bool = False


class SearchRequest(BaseModel):
    query: str
    limit: int = 5


class TagSuggestRequest(BaseModel):
    text: str
    top_n: int = 8


class MiningRunRequest(BaseModel):
    limit: int = 25
    concurrency: int = 2
    include_failed: bool = False
    include_extracted: bool = False
    construction_only: bool = False


class KBExportRequest(BaseModel):
    limit: int = 250
    concurrency: int = 4
    construction_only: bool = True
    extracted_only: bool = False
    chunk_chars: int = 120000
    chunk_overlap: int = 1500
    prefix_override: Optional[str] = None
    trigger_ingest: bool = False


class ContextSuggestRequest(BaseModel):
    tag: str = "caselaw-context"
    top_n: int = 8
    max_items: int = 5
    max_chars: int = 120000
    evidence_ids: List[str] = []


class CaseLawOut(BaseModel):
    id: str
    neutral_citation: str
    case_name: str
    court: Optional[str]
    judgment_date: Optional[str]
    summary: Optional[str]

    class Config:
        from_attributes = True


@router.post("/chat")
async def chat_with_caselaw(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Chat with the Case Law Intelligence Agent.
    """
    session_id = request.session_id or f"user-{current_user.id}"
    response = await caselaw_agent.chat(
        query=request.query, session_id=session_id, enable_trace=request.enable_trace
    )
    return response


@router.post("/search")
async def search_caselaw(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Semantic search against the Case Law Knowledge Base.
    """
    results = await caselaw_agent.search_knowledge_base(
        request.query, limit=request.limit
    )
    return {"results": results}


@router.post("/context/upload")
async def upload_caselaw_context(
    file: UploadFile = File(...),
    tags: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload claim submissions or supporting documents to steer case-law searches.
    """
    tag_value = tags or "caselaw-context"
    return await direct_upload_evidence_service(
        file=file,
        db=db,
        case_id=None,
        project_id=None,
        collection_id=None,
        evidence_type="caselaw_context",
        tags=tag_value,
    )


@router.post("/context/suggest")
async def suggest_context_queries(
    request: ContextSuggestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Suggest tags/issues based on uploaded context docs.
    """
    tag = request.tag.strip() or "caselaw-context"
    max_items = max(1, min(request.max_items, 25))
    max_chars = max(2000, min(request.max_chars, 400000))

    items: List[EvidenceItem] = []
    if request.evidence_ids:
        ids: List[uuid.UUID] = []
        for raw in request.evidence_ids:
            try:
                ids.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        if ids:
            items = db.query(EvidenceItem).filter(EvidenceItem.id.in_(ids)).all()
    else:
        items = (
            db.query(EvidenceItem)
            .filter(
                or_(
                    EvidenceItem.manual_tags.contains([tag]),
                    EvidenceItem.auto_tags.contains([tag]),
                )
            )
            .order_by(EvidenceItem.created_at.desc())
            .limit(max_items)
            .all()
        )

    combined = []
    total_chars = 0
    for item in items:
        try:
            payload = await get_evidence_text_content_service(
                str(item.id), db, current_user, max_length=40000
            )
            text = payload.get("text") or ""
        except Exception:
            text = item.extracted_text or ""
        if not text:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        snippet = text[:remaining]
        combined.append(snippet)
        total_chars += len(snippet)

    combined_text = "\n\n".join(combined).strip()
    suggestions = suggest_tags_from_text(
        db=db,
        text=combined_text,
        top_n=request.top_n,
    )

    return {
        "tag": tag,
        "evidence_count": len(items),
        "chars_used": total_chars,
        "suggestions": suggestions,
        "evidence_ids": [str(item.id) for item in items],
    }


@router.get("/trends")
def get_caselaw_trends(
    top_n: int = 10,
    court: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    theme: Optional[str] = None,
    outcome: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Aggregate recurring themes, issues, and tags from extracted case law.
    Supports optional theme/outcome filtering for predictive signals.
    """
    return summarize_case_law_trends(
        db=db,
        top_n=top_n,
        court=court,
        year_from=year_from,
        year_to=year_to,
        theme=theme,
        outcome=outcome,
    )


@router.get("/mining/status")
def get_caselaw_mining_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get mining status counts (pending/processing/extracted/failed).
    """
    _require_admin(current_user)
    rows = (
        db.query(CaseLaw.extraction_status, func.count(CaseLaw.id))
        .group_by(CaseLaw.extraction_status)
        .all()
    )
    counts = {str(status or "unknown"): int(count) for status, count in rows}
    return {"total": sum(counts.values()), "counts": counts}


@router.post("/mining/run")
async def run_caselaw_mining(
    request: MiningRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Queue a background batch to mine case-law rows.
    """
    _require_admin(current_user)

    limit = max(1, min(int(request.limit or 1), 500))
    statuses = ["pending"]
    if request.include_failed:
        statuses.append("failed")
    if request.include_extracted:
        statuses.append("extracted")

    query = (
        db.query(CaseLaw)
        .filter(CaseLaw.extraction_status.in_(statuses))
        .order_by(CaseLaw.created_at.asc())
    )

    if request.construction_only:
        candidate_limit = min(limit * 4, 2000)
        candidates = query.limit(candidate_limit).all()
        ids = [case.id for case in candidates if _is_construction_case(case)][:limit]
    else:
        ids = [case.id for case in query.limit(limit).all()]

    if not ids:
        return {"queued": 0, "case_ids": []}

    db.query(CaseLaw).filter(CaseLaw.id.in_(ids)).update(
        {"extraction_status": "processing"},
        synchronize_session=False,
    )
    db.commit()

    case_ids = [str(cid) for cid in ids]
    asyncio.create_task(_mine_case_batch(case_ids, request.concurrency))
    return {"queued": len(case_ids), "case_ids": case_ids}


@router.post("/kb/ingest")
async def ingest_caselaw_kb(
    current_user: User = Depends(get_current_user),
):
    """
    Trigger a Bedrock Knowledge Base ingestion for case-law vectors.
    """
    _require_admin(current_user)
    result = await aws_services.ingest_to_knowledge_base()
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/kb/export")
async def export_caselaw_kb_docs(
    request: KBExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export curated case-law docs into the Bedrock KB S3 data source so ingestion scans non-empty content.
    Optionally triggers an ingestion job once export completes.
    """
    _require_admin(current_user)

    export_result = await export_caselaw_docs_to_knowledge_base(
        db=db,
        limit=request.limit,
        concurrency=request.concurrency,
        construction_only=request.construction_only,
        extracted_only=request.extracted_only,
        chunk_chars=request.chunk_chars,
        chunk_overlap=request.chunk_overlap,
        prefix_override=request.prefix_override,
    )

    ingest_result: Dict[str, Any] | None = None
    if request.trigger_ingest:
        ingest_result = await aws_services.ingest_to_knowledge_base()
        if ingest_result.get("error"):
            raise HTTPException(status_code=500, detail=ingest_result["error"])

    return {"export": export_result, "ingest": ingest_result}


@router.post("/suggest-tags")
def suggest_tags(
    request: TagSuggestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Suggest tags and contentious issues based on extracted case-law themes.
    """
    return suggest_tags_from_text(
        db=db,
        text=request.text,
        top_n=request.top_n,
    )


@router.get("/cases/{citation}", response_model=CaseLawOut)
def get_case_details(
    citation: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get details of a specific case by citation.
    """
    case = db.query(CaseLaw).filter(CaseLaw.neutral_citation == citation).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    return CaseLawOut(
        id=str(case.id),
        neutral_citation=case.neutral_citation,
        case_name=case.case_name,
        court=case.court,
        judgment_date=case.judgment_date.isoformat() if case.judgment_date else None,
        summary=case.summary,
    )
