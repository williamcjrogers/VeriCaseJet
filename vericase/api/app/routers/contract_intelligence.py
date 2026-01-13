"""
API Router for Contract Intelligence
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..contract_intelligence.embeddings import embedding_service
from ..contract_intelligence.models import (
    ContractType,
    CorrespondenceAnalysis,
    ExtractedContractClause,
    UploadedContract,
)
from ..contract_intelligence.upload_service import contract_upload_service
from ..contract_intelligence.vector_store import vector_store
from ..db import get_db

router = APIRouter(prefix="/contract-intelligence", tags=["contract-intelligence"])


# Pydantic models for requests/responses
class ContractUploadInitRequest(BaseModel):
    filename: str
    file_size: int
    contract_type_id: int
    project_id: Optional[str] = None
    case_id: Optional[str] = None


class ContractUploadInitResponse(BaseModel):
    upload_id: int
    upload_url: str
    s3_key: str
    contract_type: str


class ContractProcessResponse(BaseModel):
    status: str
    upload_id: int
    total_clauses: int
    extracted_metadata: Optional[dict] = None


class ContractStatusResponse(BaseModel):
    upload_id: int
    status: str
    progress_percent: int
    total_clauses: Optional[int] = None
    processed_clauses: Optional[int] = None
    error_message: Optional[str] = None
    filename: str
    created_at: Optional[str] = None
    processed_at: Optional[str] = None


class ContractTypeSuite(BaseModel):
    id: int
    name: str
    version: str
    description: Optional[str] = None


class ContractTypeFamily(BaseModel):
    family: str
    suites: List[ContractTypeSuite]


class ExtractedClauseResponse(BaseModel):
    id: int
    clause_number: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    full_text: Optional[str] = None
    risk_level: Optional[str] = None
    entitlement_types: Optional[List[str]] = None
    keywords: Optional[List[str]] = None
    confidence_score: Optional[float] = None
    matched_standard_clause_id: Optional[int] = None
    match_score: Optional[float] = None


class UploadHistoryItem(BaseModel):
    id: int
    filename: str
    status: str
    progress_percent: int
    total_clauses: Optional[int] = None
    contract_type: Optional[str] = None
    created_at: Optional[str] = None
    processed_at: Optional[str] = None


@router.get("/contracts", response_model=List[Dict[str, Any]])
def list_contracts(db: Session = Depends(get_db)):
    """List available contract types"""
    contracts = db.query(ContractType).filter(ContractType.is_active == True).all()
    return [{"id": c.id, "name": c.name, "version": c.version} for c in contracts]


@router.get("/search", response_model=List[Dict[str, Any]])
async def search_knowledge(query: str, limit: int = 5):
    """Semantic search for contract knowledge"""
    embedding = await embedding_service.generate_embeddings([query])
    if not embedding:
        return []

    results = await vector_store.search(embedding[0], limit=limit)
    return results


@router.get("/analysis/{correspondence_id}", response_model=Dict[str, Any])
def get_analysis(correspondence_id: str, db: Session = Depends(get_db)):
    """Get contract analysis for a specific email"""
    try:
        c_uuid = uuid.UUID(correspondence_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    analysis = (
        db.query(CorrespondenceAnalysis)
        .filter(CorrespondenceAnalysis.correspondence_id == c_uuid)
        .first()
    )

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return analysis.analysis_result or {}


# ================================================================================
# CONTRACT UPLOAD ENDPOINTS
# ================================================================================


@router.get("/contract-types/grouped", response_model=List[ContractTypeFamily])
def list_contract_types_grouped(db: Session = Depends(get_db)):
    """List contract types grouped by family (JCT, NEC, FIDIC)"""
    contracts = db.query(ContractType).filter(ContractType.is_active == True).all()

    # Group by family
    families: Dict[str, List[ContractTypeSuite]] = {}
    for c in contracts:
        # Extract family from name (e.g., "JCT Design and Build 2016" -> "JCT")
        family = c.name.split()[0] if c.name else "Other"
        if family not in families:
            families[family] = []
        families[family].append(
            ContractTypeSuite(
                id=c.id, name=c.name, version=c.version, description=c.description
            )
        )

    return [
        ContractTypeFamily(family=family, suites=suites)
        for family, suites in sorted(families.items())
    ]


@router.post("/upload/init", response_model=ContractUploadInitResponse)
async def init_contract_upload(
    request: ContractUploadInitRequest,
    db: Session = Depends(get_db),
):
    """Initialize contract upload - returns presigned URL for S3 upload"""
    try:
        result = await contract_upload_service.initialize_upload(
            db=db,
            filename=request.filename,
            file_size=request.file_size,
            contract_type_id=request.contract_type_id,
            project_id=request.project_id,
            case_id=request.case_id,
            user_id=None,  # TODO: Get from auth context
        )
        return ContractUploadInitResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize upload: {e}")


async def _process_contract_background(upload_id: int, db: Session):
    """Background task to process uploaded contract"""
    try:
        await contract_upload_service.process_contract(db=db, upload_id=upload_id)
    except Exception:
        # Error is already logged and stored in the upload record
        pass


@router.post("/upload/{upload_id}/process", response_model=ContractProcessResponse)
async def process_contract_upload(
    upload_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start processing an uploaded contract (runs in background)"""
    # Verify upload exists and is in pending state
    uploaded_contract = (
        db.query(UploadedContract).filter(UploadedContract.id == upload_id).first()
    )

    if not uploaded_contract:
        raise HTTPException(status_code=404, detail="Upload not found")

    if uploaded_contract.status not in ("pending", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Upload is already {uploaded_contract.status}",
        )

    # Start background processing
    background_tasks.add_task(_process_contract_background, upload_id, db)

    return ContractProcessResponse(
        status="processing",
        upload_id=upload_id,
        total_clauses=0,
        extracted_metadata=None,
    )


@router.get("/upload/{upload_id}/status", response_model=ContractStatusResponse)
async def get_upload_status(
    upload_id: int,
    db: Session = Depends(get_db),
):
    """Get processing status for an uploaded contract"""
    try:
        result = await contract_upload_service.get_upload_status(
            db=db, upload_id=upload_id
        )
        return ContractStatusResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/upload/{upload_id}/clauses", response_model=List[ExtractedClauseResponse])
async def get_extracted_clauses(
    upload_id: int,
    db: Session = Depends(get_db),
):
    """Get extracted clauses for an uploaded contract"""
    # Verify upload exists
    uploaded_contract = (
        db.query(UploadedContract).filter(UploadedContract.id == upload_id).first()
    )

    if not uploaded_contract:
        raise HTTPException(status_code=404, detail="Upload not found")

    result = await contract_upload_service.get_extracted_clauses(
        db=db, upload_id=upload_id
    )
    return [ExtractedClauseResponse(**c) for c in result]


@router.get("/uploads/history", response_model=List[UploadHistoryItem])
def get_upload_history(
    project_id: Optional[str] = None,
    case_id: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Get upload history, optionally filtered by project or case"""
    query = db.query(UploadedContract)

    if project_id:
        try:
            query = query.filter(UploadedContract.project_id == uuid.UUID(project_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid project_id UUID")

    if case_id:
        try:
            query = query.filter(UploadedContract.case_id == uuid.UUID(case_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid case_id UUID")

    uploads = query.order_by(UploadedContract.created_at.desc()).limit(limit).all()

    return [
        UploadHistoryItem(
            id=u.id,
            filename=u.filename,
            status=u.status,
            progress_percent=u.progress_percent,
            total_clauses=u.total_clauses,
            contract_type=u.contract_type.name if u.contract_type else None,
            created_at=u.created_at.isoformat() if u.created_at else None,
            processed_at=u.processed_at.isoformat() if u.processed_at else None,
        )
        for u in uploads
    ]


@router.delete("/upload/{upload_id}")
def delete_upload(
    upload_id: int,
    db: Session = Depends(get_db),
):
    """Delete an uploaded contract and its extracted clauses"""
    uploaded_contract = (
        db.query(UploadedContract).filter(UploadedContract.id == upload_id).first()
    )

    if not uploaded_contract:
        raise HTTPException(status_code=404, detail="Upload not found")

    # Delete extracted clauses first (foreign key constraint)
    db.query(ExtractedContractClause).filter(
        ExtractedContractClause.uploaded_contract_id == upload_id
    ).delete()

    # Delete the upload record
    db.delete(uploaded_contract)
    db.commit()

    return {"status": "deleted", "upload_id": upload_id}
