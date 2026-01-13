"""
API Router for Contract Intelligence
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from ..db import get_db
from ..contract_intelligence.models import (
    ContractType,
    CorrespondenceAnalysis,
)
from ..contract_intelligence.vector_store import vector_store
from ..contract_intelligence.embeddings import embedding_service
import uuid

router = APIRouter(prefix="/contract-intelligence", tags=["contract-intelligence"])


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
