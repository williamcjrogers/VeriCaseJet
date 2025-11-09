"""
Case Management API
Handles cases, evidence linking, issues, claims, and chronology
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
import uuid

from .db import get_db
from .models import (
    Case, CaseUser, Issue, Evidence, Claim, ClaimType,
    Document, User, Company, ChronologyItem, Rebuttal, ContractClause, DocStatus
)
from .security import get_current_user

router = APIRouter(prefix="/api/cases", tags=["cases"])

# ============================================================================
# Pydantic Schemas
# ============================================================================

class CaseCreate(BaseModel):
    case_number: str
    name: str
    description: Optional[str] = None
    project_name: Optional[str] = None
    contract_type: Optional[str] = None  # JCT, NEC, FIDIC
    dispute_type: Optional[str] = None   # Delay, Defects, Variation
    company_id: Optional[str] = None

class CaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_name: Optional[str] = None
    contract_type: Optional[str] = None
    dispute_type: Optional[str] = None
    status: Optional[str] = None

class CaseOut(BaseModel):
    id: str
    case_number: str
    name: str
    description: Optional[str]
    project_name: Optional[str]
    contract_type: Optional[str]
    dispute_type: Optional[str]
    status: str
    owner_id: str
    company_id: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    evidence_count: int = 0
    issue_count: int = 0
    
    class Config:
        from_attributes = True

class IssueCreate(BaseModel):
    case_id: str
    title: str
    description: Optional[str] = None
    issue_type: Optional[str] = None
    relevant_contract_clauses: Optional[dict] = None

class IssueOut(BaseModel):
    id: str
    case_id: str
    title: str
    description: Optional[str]
    issue_type: Optional[str]
    status: str
    relevant_contract_clauses: Optional[dict]
    created_at: datetime
    evidence_count: int = 0
    
    class Config:
        from_attributes = True

class EvidenceLink(BaseModel):
    case_id: str
    document_id: str
    issue_id: Optional[str] = None
    evidence_type: Optional[str] = None
    exhibit_number: Optional[str] = None
    notes: Optional[str] = None
    relevance_score: Optional[int] = None

class EvidenceOut(BaseModel):
    id: str
    case_id: str
    document_id: str
    issue_id: Optional[str]
    evidence_type: Optional[str]
    exhibit_number: Optional[str]
    notes: Optional[str]
    relevance_score: Optional[int]
    added_at: datetime
    document_filename: Optional[str]
    document_size: Optional[int]
    document_content_type: Optional[str]
    # Email-specific fields
    email_from: Optional[str] = None
    email_to: Optional[str] = None
    email_cc: Optional[str] = None
    email_subject: Optional[str] = None
    email_date: Optional[datetime] = None
    email_message_id: Optional[str] = None
    content: Optional[str] = None
    content_type: Optional[str] = None
    meta: Optional[dict] = None
    thread_id: Optional[str] = None
    
    class Config:
        from_attributes = True

class ClaimCreate(BaseModel):
    case_id: str
    claim_type: ClaimType
    title: str
    description: Optional[str] = None
    claimed_amount: Optional[int] = None
    currency: str = "GBP"
    claim_date: Optional[datetime] = None

class ClaimOut(BaseModel):
    id: str
    case_id: str
    claim_type: str
    title: str
    description: Optional[str]
    claimed_amount: Optional[int]
    currency: str
    claim_date: Optional[datetime]
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True

# ============================================================================
# Case Endpoints
# ============================================================================

@router.get("", response_model=List[CaseOut])
def list_cases(
    status: Optional[str] = None,
    contract_type: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all cases accessible to the current user"""
    query = db.query(Case).filter(Case.owner_id == current_user.id)
    
    if status:
        query = query.filter(Case.status == status)
    if contract_type:
        query = query.filter(Case.contract_type == contract_type)
    if search:
        query = query.filter(
            or_(
                Case.name.ilike(f"%{search}%"),
                Case.case_number.ilike(f"%{search}%"),
                Case.project_name.ilike(f"%{search}%")
            )
        )
    
    cases = query.order_by(desc(Case.created_at)).offset(skip).limit(limit).all()
    
    # Add counts
    result = []
    for case in cases:
        case_dict = {
            "id": str(case.id),
            "case_number": case.case_number,
            "name": case.name,
            "description": case.description,
            "project_name": case.project_name,
            "contract_type": case.contract_type,
            "dispute_type": case.dispute_type,
            "status": case.status,
            "owner_id": str(case.owner_id),
            "company_id": str(case.company_id) if case.company_id else None,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
            "evidence_count": db.query(Evidence).filter(Evidence.case_id == case.id).count(),
            "issue_count": db.query(Issue).filter(Issue.case_id == case.id).count()
        }
        result.append(CaseOut(**case_dict))
    
    return result

@router.post("", response_model=CaseOut)
def create_case(
    data: CaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new case"""
    # Check if case number already exists
    existing = db.query(Case).filter(Case.case_number == data.case_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Case number already exists")
    
    case = Case(
        id=uuid.uuid4(),
        case_number=data.case_number,
        name=data.name,
        description=data.description,
        project_name=data.project_name,
        contract_type=data.contract_type,
        dispute_type=data.dispute_type,
        owner_id=current_user.id,
        company_id=uuid.UUID(data.company_id) if data.company_id else None,
        status="active"
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    
    return CaseOut(
        id=str(case.id),
        case_number=case.case_number,
        name=case.name,
        description=case.description,
        project_name=case.project_name,
        contract_type=case.contract_type,
        dispute_type=case.dispute_type,
        status=case.status,
        owner_id=str(case.owner_id),
        company_id=str(case.company_id) if case.company_id else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        evidence_count=0,
        issue_count=0
    )

@router.get("/{case_id}", response_model=CaseOut)
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get case details"""
    case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Check access
    if case.owner_id != current_user.id:
        # TODO: Check if user is in case_users
        raise HTTPException(status_code=403, detail="Access denied")
    
    return CaseOut(
        id=str(case.id),
        case_number=case.case_number,
        name=case.name,
        description=case.description,
        project_name=case.project_name,
        contract_type=case.contract_type,
        dispute_type=case.dispute_type,
        status=case.status,
        owner_id=str(case.owner_id),
        company_id=str(case.company_id) if case.company_id else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        evidence_count=db.query(Evidence).filter(Evidence.case_id == case.id).count(),
        issue_count=db.query(Issue).filter(Issue.case_id == case.id).count()
    )

@router.put("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: str,
    data: CaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update case details"""
    case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if data.name is not None:
        case.name = data.name
    if data.description is not None:
        case.description = data.description
    if data.project_name is not None:
        case.project_name = data.project_name
    if data.contract_type is not None:
        case.contract_type = data.contract_type
    if data.dispute_type is not None:
        case.dispute_type = data.dispute_type
    if data.status is not None:
        case.status = data.status
    
    db.commit()
    db.refresh(case)
    
    return CaseOut(
        id=str(case.id),
        case_number=case.case_number,
        name=case.name,
        description=case.description,
        project_name=case.project_name,
        contract_type=case.contract_type,
        dispute_type=case.dispute_type,
        status=case.status,
        owner_id=str(case.owner_id),
        company_id=str(case.company_id) if case.company_id else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        evidence_count=db.query(Evidence).filter(Evidence.case_id == case.id).count(),
        issue_count=db.query(Issue).filter(Issue.case_id == case.id).count()
    )

# ============================================================================
# Evidence Endpoints
# ============================================================================

@router.get("/{case_id}/evidence", response_model=List[EvidenceOut])
def list_case_evidence(
    case_id: str,
    issue_id: Optional[str] = None,
    evidence_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List all evidence for a case"""
    query = db.query(Evidence, Document).join(Document).filter(Evidence.case_id == uuid.UUID(case_id))
    
    if issue_id:
        query = query.filter(Evidence.issue_id == uuid.UUID(issue_id))
    if evidence_type:
        query = query.filter(Evidence.evidence_type == evidence_type)
    
    results = query.order_by(desc(Evidence.added_at)).all()
    
    evidence_list = []
    for evidence, document in results:
        evidence_list.append(EvidenceOut(
            id=str(evidence.id),
            case_id=str(evidence.case_id),
            document_id=str(evidence.document_id),
            issue_id=str(evidence.issue_id) if evidence.issue_id else None,
            evidence_type=evidence.evidence_type,
            exhibit_number=evidence.exhibit_number,
            notes=evidence.notes,
            relevance_score=evidence.relevance_score,
            added_at=evidence.added_at,
            document_filename=document.filename,
            document_size=document.size,
            document_content_type=document.content_type,
            # Email-specific fields
            email_from=evidence.email_from,
            email_to=evidence.email_to,
            email_cc=evidence.email_cc,
            email_subject=evidence.email_subject,
            email_date=evidence.email_date,
            email_message_id=evidence.email_message_id,
            content=evidence.content,
            content_type=evidence.content_type,
            meta=evidence.meta,
            thread_id=evidence.thread_id
        ))
    
    return evidence_list

@router.post("/{case_id}/evidence", response_model=EvidenceOut)
def link_evidence(
    case_id: str,
    data: EvidenceLink,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Link a document as evidence to a case"""
    # Verify case exists and user has access
    case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    if not case or case.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Verify document exists
    document = db.query(Document).filter(Document.id == uuid.UUID(data.document_id)).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Create evidence link
    evidence = Evidence(
        id=uuid.uuid4(),
        case_id=uuid.UUID(case_id),
        document_id=uuid.UUID(data.document_id),
        issue_id=uuid.UUID(data.issue_id) if data.issue_id else None,
        evidence_type=data.evidence_type,
        exhibit_number=data.exhibit_number,
        notes=data.notes,
        relevance_score=data.relevance_score,
        added_by_id=current_user.id
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    
    return EvidenceOut(
        id=str(evidence.id),
        case_id=str(evidence.case_id),
        document_id=str(evidence.document_id),
        issue_id=str(evidence.issue_id) if evidence.issue_id else None,
        evidence_type=evidence.evidence_type,
        exhibit_number=evidence.exhibit_number,
        notes=evidence.notes,
        relevance_score=evidence.relevance_score,
        added_at=evidence.added_at,
        document_filename=document.filename,
        document_size=document.size,
        document_content_type=document.content_type
    )

# ============================================================================
# Issue Endpoints
# ============================================================================

@router.get("/{case_id}/issues", response_model=List[IssueOut])
def list_case_issues(
    case_id: str,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all issues for a case"""
    query = db.query(Issue).filter(Issue.case_id == uuid.UUID(case_id))
    
    if status:
        query = query.filter(Issue.status == status)
    
    issues = query.order_by(desc(Issue.created_at)).all()
    
    result = []
    for issue in issues:
        result.append(IssueOut(
            id=str(issue.id),
            case_id=str(issue.case_id),
            title=issue.title,
            description=issue.description,
            issue_type=issue.issue_type,
            status=issue.status,
            relevant_contract_clauses=issue.relevant_contract_clauses,
            created_at=issue.created_at,
            evidence_count=db.query(Evidence).filter(Evidence.issue_id == issue.id).count()
        ))
    
    return result

@router.post("/{case_id}/issues", response_model=IssueOut)
def create_issue(
    case_id: str,
    data: IssueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new issue for a case"""
    case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    if not case or case.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    
    issue = Issue(
        id=uuid.uuid4(),
        case_id=uuid.UUID(case_id),
        title=data.title,
        description=data.description,
        issue_type=data.issue_type,
        relevant_contract_clauses=data.relevant_contract_clauses,
        status="open"
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    
    return IssueOut(
        id=str(issue.id),
        case_id=str(issue.case_id),
        title=issue.title,
        description=issue.description,
        issue_type=issue.issue_type,
        status=issue.status,
        relevant_contract_clauses=issue.relevant_contract_clauses,
        created_at=issue.created_at,
        evidence_count=0
    )

# ============================================================================
# Claims Endpoints
# ============================================================================

@router.get("/{case_id}/claims", response_model=List[ClaimOut])
def list_case_claims(
    case_id: str,
    claim_type: Optional[ClaimType] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all claims for a case"""
    query = db.query(Claim).filter(Claim.case_id == uuid.UUID(case_id))
    
    if claim_type:
        query = query.filter(Claim.claim_type == claim_type)
    
    claims = query.order_by(desc(Claim.created_at)).all()
    
    return [ClaimOut(
        id=str(c.id),
        case_id=str(c.case_id),
        claim_type=c.claim_type.value,
        title=c.title,
        description=c.description,
        claimed_amount=c.claimed_amount,
        currency=c.currency,
        claim_date=c.claim_date,
        status=c.status,
        created_at=c.created_at
    ) for c in claims]

@router.post("/{case_id}/claims", response_model=ClaimOut)
def create_claim(
    case_id: str,
    data: ClaimCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new claim for a case"""
    case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    if not case or case.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    
    claim = Claim(
        id=uuid.uuid4(),
        case_id=uuid.UUID(case_id),
        claim_type=data.claim_type,
        title=data.title,
        description=data.description,
        claimed_amount=data.claimed_amount,
        currency=data.currency,
        claim_date=data.claim_date,
        status="draft"
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    
    return ClaimOut(
        id=str(claim.id),
        case_id=str(claim.case_id),
        claim_type=claim.claim_type.value,
        title=claim.title,
        description=claim.description,
        claimed_amount=claim.claimed_amount,
        currency=claim.currency,
        claim_date=claim.claim_date,
        status=claim.status,
        created_at=claim.created_at
    )

# ============================================================================
# Documents List for Evidence Linking
# ============================================================================

@router.get("/{case_id}/available-documents")
def list_available_documents(
    case_id: str,
    search: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List documents that can be linked as evidence"""
    # Get all user's documents
    query = db.query(Document).filter(
        Document.owner_user_id == current_user.id,
        Document.status == DocStatus.READY
    )
    
    if search:
        query = query.filter(
            or_(
                Document.filename.ilike(f"%{search}%"),
                Document.title.ilike(f"%{search}%")
            )
        )
    
    documents = query.order_by(desc(Document.created_at)).limit(limit).all()
    
    return [{
        "id": str(doc.id),
        "filename": doc.filename,
        "title": doc.title,
        "content_type": doc.content_type,
        "size": doc.size,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "is_linked": db.query(Evidence).filter(
            Evidence.document_id == doc.id,
            Evidence.case_id == uuid.UUID(case_id)
        ).first() is not None,
        "metadata": doc.meta or {}
    } for doc in documents]

@router.get("/{case_id}/documents")
def list_case_documents(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all documents uploaded for a case (including PST files)"""
    # For now, return all documents owned by user
    # TODO: Filter by case_id once we add case_id to Document model
    documents = db.query(Document).filter(
        Document.owner_user_id == current_user.id
    ).order_by(desc(Document.created_at)).all()
    
    return [{
        "id": str(doc.id),
        "filename": doc.filename,
        "status": doc.status.value if isinstance(doc.status, DocStatus) else doc.status,
        "size": doc.size,
        "content_type": doc.content_type,
        "uploaded_at": doc.created_at.isoformat() if doc.created_at else None,
        "metadata": doc.meta or {},
        "pst_processing": (doc.meta or {}).get('pst_processing') if doc.meta else None
    } for doc in documents]
