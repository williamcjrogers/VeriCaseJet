"""
Case Management API
Handles cases, evidence linking, issues, claims, and chronology
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from typing import Dict, List, Optional, cast
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid
import logging
import re

logger = logging.getLogger(__name__)

def sanitize_for_log(value: str) -> str:
    """Sanitize user input for safe logging to prevent log injection"""
    if not value:
        return ""
    # Remove newlines and other control characters
    sanitized = re.sub(r'[\r\n\t]', ' ', str(value))
    # Limit length to prevent log flooding
    return sanitized[:100] if len(sanitized) > 100 else sanitized

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
        # Sanitize search input to prevent any potential issues
        search = search.strip()
        if search:
            # SQLAlchemy's ilike already handles SQL injection prevention
            query = query.filter(
                or_(
                    Case.name.ilike(f"%{search}%"),
                    Case.case_number.ilike(f"%{search}%"),
                    Case.project_name.ilike(f"%{search}%")
                )
            )
    
    try:
        cases = query.order_by(desc(Case.created_at)).offset(skip).limit(limit).all()
    except Exception as e:
        logger.error(f"Failed to query cases: {e}", exc_info=True)
        raise HTTPException(500, "Failed to fetch cases")
    
    # Add counts
    result = []
    for case in cases:
        try:
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
                "evidence_count": 0,
                "issue_count": 0
            }
            result.append(CaseOut(**case_dict))
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Error processing case {case.id}: {e}", exc_info=True)
            continue
    
    return result

@router.post("", response_model=CaseOut)
def create_case(
    data: CaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new case"""
    # Check if case number already exists
    try:
        existing = db.query(Case).filter(Case.case_number == data.case_number).first()
        if existing:
            raise HTTPException(status_code=400, detail="Case number already exists")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to check existing case: {e}", exc_info=True)
        raise HTTPException(500, "Failed to validate case number")
    
    # Validate company_id if provided
    company_uuid = None
    if data.company_id:
        try:
            company_uuid = uuid.UUID(data.company_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid company ID format")
    
    case = Case(
        id=uuid.uuid4(),
        case_number=data.case_number,
        name=data.name,
        description=data.description,
        project_name=data.project_name,
        contract_type=data.contract_type,
        dispute_type=data.dispute_type,
        owner_id=current_user.id,
        company_id=company_uuid,
        status="active"
    )
    try:
        db.add(case)
        db.commit()
        db.refresh(case)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create case: {e}", exc_info=True)
        raise HTTPException(500, "Failed to create case")
    
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
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid case ID format")
    
    case = db.query(Case).filter(Case.id == case_uuid).first()
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
        evidence_count=0,
        issue_count=0
    )

@router.put("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: str,
    data: CaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update case details"""
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid case ID format")
    
    try:
        case = db.query(Case).filter(Case.id == case_uuid).first()
    except Exception as e:
        logger.error(f"Failed to fetch case: {e}", exc_info=True)
        raise HTTPException(500, "Failed to fetch case")
    
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
        evidence_count=0,
        issue_count=0
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
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid case ID format")
    
    query = db.query(Evidence, Document).join(Document).filter(Evidence.case_id == case_uuid)
    
    if issue_id:
        try:
            issue_uuid = uuid.UUID(issue_id)
            query = query.filter(Evidence.issue_id == issue_uuid)
        except (ValueError, AttributeError):
            raise HTTPException(400, "Invalid issue ID format")
    if evidence_type:
        query = query.filter(Evidence.evidence_type == evidence_type)
    
    try:
        results = query.order_by(desc(Evidence.added_at)).all()
    except Exception as e:
        logger.error(f"Database error fetching evidence for case {sanitize_for_log(case_id)}: {e}")
        raise HTTPException(500, "Failed to fetch evidence")
    
    evidence_list = []
    for evidence, document in results:
        try:
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
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Error processing evidence {evidence.id}: {e}", exc_info=True)
            continue
    
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
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError) as e:
        logger.error(f"Invalid case ID format: {sanitize_for_log(case_id)}, error: {e}")
        raise HTTPException(status_code=400, detail="Invalid case ID format")
    
    try:
        case = db.query(Case).filter(Case.id == case_uuid).first()
    except Exception as e:
        logger.error(f"Database error fetching case {sanitize_for_log(case_id)}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch case")
    
    if not case or case.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    
    # Verify document exists
    try:
        doc_uuid = uuid.UUID(data.document_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid document ID format")
    
    document = db.query(Document).filter(Document.id == doc_uuid).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Validate issue_id if provided
    issue_uuid = None
    if data.issue_id:
        try:
            issue_uuid = uuid.UUID(data.issue_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid issue ID format")
    
    # Create evidence link
    evidence = Evidence(
        id=uuid.uuid4(),
        case_id=case_uuid,
        document_id=doc_uuid,
        issue_id=issue_uuid,
        evidence_type=data.evidence_type,
        exhibit_number=data.exhibit_number,
        notes=data.notes,
        relevance_score=data.relevance_score,
        added_by_id=current_user.id
    )
    try:
        db.add(evidence)
        db.commit()
        db.refresh(evidence)
    except (ValueError, TypeError) as e:
        db.rollback()
        logger.error(f"Failed to create evidence: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create evidence")
    
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
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid case ID format")
    
    query = db.query(Issue).filter(Issue.case_id == case_uuid)
    
    if status:
        query = query.filter(Issue.status == status)
    
    try:
        issues = query.order_by(desc(Issue.created_at)).all()
    except Exception as e:
        logger.error(f"Database error fetching issues for case {sanitize_for_log(case_id)}: {e}")
        raise HTTPException(500, "Failed to fetch issues")
    
    # Get evidence counts for all issues in one query to avoid N+1
    from sqlalchemy import func
    # Get all issue IDs using list comprehension
    issue_ids: List[uuid.UUID] = [
        issue_id_obj for issue in issues
        if (issue_id_obj := getattr(issue, "id", None)) and isinstance(issue_id_obj, uuid.UUID)
    ]
    
    evidence_counts: Dict[uuid.UUID, int] = {}
    if issue_ids:
        rows = (
            db.query(Evidence.issue_id, func.count(Evidence.id))
            .filter(Evidence.issue_id.in_(issue_ids))
            .group_by(Evidence.issue_id)
            .all()
        )
        for issue_id_value, count_value in rows:
            if isinstance(issue_id_value, uuid.UUID):
                evidence_counts[issue_id_value] = int(count_value)
    
    result = []
    for issue in issues:
        try:
            issue_id_value = getattr(issue, "id", None)
            case_id_value = getattr(issue, "case_id", None)
            if not isinstance(issue_id_value, uuid.UUID) or not isinstance(case_id_value, uuid.UUID):
                logger.error("Issue %s has invalid UUID fields", getattr(issue, "id", "unknown"))
                continue

            created_at_value = cast(Optional[datetime], getattr(issue, "created_at", None)) or datetime.now(timezone.utc)
            issue_payload = {
                "id": str(issue_id_value),
                "case_id": str(case_id_value),
                "title": cast(Optional[str], getattr(issue, "title", None)),
                "description": cast(Optional[str], getattr(issue, "description", None)),
                "issue_type": cast(Optional[str], getattr(issue, "issue_type", None)),
                "status": cast(Optional[str], getattr(issue, "status", None)) or "open",
                "relevant_contract_clauses": cast(Optional[dict], getattr(issue, "relevant_contract_clauses", None)),
                "created_at": created_at_value,
                "evidence_count": evidence_counts.get(issue_id_value, 0),
            }
            result.append(IssueOut.model_validate(issue_payload))
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Error processing issue {issue.id}: {e}", exc_info=True)
            continue
    
    return result

@router.post("/{case_id}/issues", response_model=IssueOut)
def create_issue(
    case_id: str,
    data: IssueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new issue for a case"""
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Invalid case ID format: {sanitize_for_log(case_id)}")
        raise HTTPException(status_code=400, detail="Invalid case ID format")
    
    case = db.query(Case).filter(Case.id == case_uuid).first()
    if not case or case.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    
    issue = Issue(
        id=uuid.uuid4(),
        case_id=case_uuid,
        title=data.title,
        description=data.description,
        issue_type=data.issue_type,
        relevant_contract_clauses=data.relevant_contract_clauses,
        status="open"
    )
    try:
        db.add(issue)
        db.commit()
        db.refresh(issue)
    except (ValueError, TypeError) as e:
        db.rollback()
        logger.error(f"Failed to create issue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create issue")
    
    issue_id_value = getattr(issue, "id", None)
    case_id_value = getattr(issue, "case_id", None)
    if not isinstance(issue_id_value, uuid.UUID) or not isinstance(case_id_value, uuid.UUID):
        raise HTTPException(status_code=500, detail="Issue saved but has invalid identifiers")

    issue_created_at = cast(Optional[datetime], getattr(issue, "created_at", None)) or datetime.now(timezone.utc)
    issue_payload = {
        "id": str(issue_id_value),
        "case_id": str(case_id_value),
        "title": cast(Optional[str], getattr(issue, "title", None)),
        "description": cast(Optional[str], getattr(issue, "description", None)),
        "issue_type": cast(Optional[str], getattr(issue, "issue_type", None)),
        "status": cast(Optional[str], getattr(issue, "status", None)) or "open",
        "relevant_contract_clauses": cast(Optional[dict], getattr(issue, "relevant_contract_clauses", None)),
        "created_at": issue_created_at,
        "evidence_count": 0,
    }
    return IssueOut.model_validate(issue_payload)

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
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid case ID format")
    
    query = db.query(Claim).filter(Claim.case_id == case_uuid)
    
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
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Invalid case ID format: {sanitize_for_log(case_id)}")
        raise HTTPException(400, "Invalid case ID format")
    
    case = db.query(Case).filter(Case.id == case_uuid).first()
    if not case or case.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")
    
    claim = Claim(
        id=uuid.uuid4(),
        case_id=case_uuid,
        claim_type=data.claim_type,
        title=data.title,
        description=data.description,
        claimed_amount=data.claimed_amount,
        currency=data.currency,
        claim_date=data.claim_date
    )
    try:
        db.add(claim)
        db.commit()
        db.refresh(claim)
    except (ValueError, TypeError) as e:
        db.rollback()
        logger.error(f"Error creating claim for case {case_id}: {e}", exc_info=True)
        raise HTTPException(500, "Failed to create claim")
    
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
    # Validate limit parameter
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 500")
    
    # Get all user's documents that are ready for use
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
    
    try:
        documents = query.order_by(desc(Document.created_at)).limit(limit).all()
    except Exception as e:
        logger.error(f"Failed to query documents: {e}", exc_info=True)
        raise HTTPException(500, "Failed to fetch documents")
    
    # Get all linked document IDs in one query to avoid N+1
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid case ID format")
    doc_ids = [doc.id for doc in documents]
    linked_doc_ids = set(
        doc_id for (doc_id,) in db.query(Evidence.document_id).filter(
            Evidence.case_id == case_uuid,
            Evidence.document_id.in_(doc_ids)
        ).all()
    ) if doc_ids else set()
    
    return [{
        "id": str(doc.id),
        "filename": doc.filename,
        "title": doc.title,
        "content_type": doc.content_type,
        "size": doc.size,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "is_linked": doc.id in linked_doc_ids,
        "metadata": doc.meta or {}
    } for doc in documents]

@router.get("/{case_id}/documents")
def list_case_documents(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all documents uploaded for a case (including PST files)"""
    # Validate case_id format
    try:
        uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid case ID format")
    
    # For now, return all documents owned by user (limited to 1000 for performance)
    # TODO: Filter by case_id once we add case_id to Document model
    try:
        documents = db.query(Document).filter(
            Document.owner_user_id == current_user.id
        ).order_by(desc(Document.created_at)).limit(1000).all()
    except (ValueError, TypeError) as e:
        logger.error(f"Failed to fetch documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch documents")
    
    return [{
        "id": str(doc.id),
        "filename": doc.filename,
        "status": doc.status.value if isinstance(doc.status, DocStatus) else doc.status,
        "size": doc.size,
        "content_type": doc.content_type,
        "uploaded_at": doc.created_at.isoformat() if doc.created_at else None,
        "metadata": doc.meta or {},
        "pst_processing": doc.meta.get('pst_processing') if doc.meta else None
    } for doc in documents]


# ============================================================================
# Project Endpoints
# ============================================================================

class ProjectCreate(BaseModel):
    project_name: str
    project_code: str
    start_date: Optional[datetime] = None
    completion_date: Optional[datetime] = None
    contract_type: Optional[str] = None
    stakeholders: Optional[List[str]] = []
    keywords: Optional[List[str]] = []

class ProjectOut(BaseModel):
    id: str
    project_name: str
    project_code: str
    start_date: Optional[datetime]
    completion_date: Optional[datetime]
    contract_type: Optional[str]
    stakeholders: Optional[List[str]]
    keywords: Optional[List[str]]
    case_id: str
    created_at: datetime
    
    class Config:
        from_attributes = True

@router.post("/{case_id}/projects", response_model=ProjectOut)
def create_project(
    case_id: str,
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create project metadata for a case"""
    from .models import Project
    from pydantic import constr
    
    # Validate project_name length
    if len(data.project_name) < 2 or len(data.project_name) > 200:
        raise HTTPException(400, "project_name must be 2-200 characters")
    
    # Validate project_code
    if not data.project_code or len(data.project_code) < 1:
        raise HTTPException(400, "project_code is required")
    
    try:
        case_uuid = uuid.UUID(case_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid case ID format")
    
    case = db.query(Case).filter(Case.id == case_uuid).first()
    if not case or case.owner_id != current_user.id:
        raise HTTPException(404, "Case not found")
    
    # Check if project_code already exists
    existing = db.query(Project).filter(Project.project_code == data.project_code).first()
    if existing:
        raise HTTPException(400, "project_code already exists")
    
    project = Project(
        id=uuid.uuid4(),
        project_name=data.project_name,
        project_code=data.project_code,
        start_date=data.start_date,
        completion_date=data.completion_date,
        contract_type=data.contract_type,
        stakeholders=data.stakeholders,
        keywords=data.keywords,
        case_id=case_uuid
    )
    try:
        db.add(project)
        db.commit()
        db.refresh(project)
    except (ValueError, TypeError) as e:
        db.rollback()
        logger.error(f"Error creating project: {e}", exc_info=True)
        raise HTTPException(500, "Failed to create project")
    
    return ProjectOut(
        id=str(project.id),
        project_name=project.project_name,
        project_code=project.project_code,
        start_date=project.start_date,
        completion_date=project.completion_date,
        contract_type=project.contract_type,
        stakeholders=project.stakeholders or [],
        keywords=project.keywords or [],
        case_id=str(project.case_id),
        created_at=project.created_at
    )
