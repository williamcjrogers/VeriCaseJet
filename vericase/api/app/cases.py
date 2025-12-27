# pyright: reportAny=false
"""
Case Management API
Handles cases, evidence linking, issues, claims, and chronology
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import logging
from typing import Annotated, Any, cast
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    Case,
    Claim,
    ClaimType,
    DocStatus,
    Document,
    Evidence,
    Issue,
    Keyword,
    Project,
    User,
)
from .security import get_current_user

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cases", tags=["cases"])

# ============================================================================
# Pydantic Schemas
# ============================================================================


class CaseCreate(BaseModel):
    case_number: str
    name: str
    description: str | None = None
    project_name: str | None = None
    project_id: str | None = None
    contract_type: str | None = None  # JCT, NEC, FIDIC
    dispute_type: str | None = None  # Delay, Defects, Variation
    company_id: str | None = None


class LegalTeamMemberSchema(BaseModel):
    role: str
    name: str
    organization: str | None = None


class HeadOfClaimSchema(BaseModel):
    name: str
    status: str | None = "Discovery"
    actions: str | None = None


class CaseKeywordSchema(BaseModel):
    name: str
    variations: str | None = None


class CaseDeadlineSchema(BaseModel):
    task: str
    description: str | None = None
    date: datetime | None = None
    reminder: str | None = "none"


class CaseUpdate(BaseModel):
    name: str | None = None
    case_name: str | None = None  # Alias for name
    description: str | None = None
    project_name: str | None = None
    project_id: str | None = None
    contract_type: str | None = None
    dispute_type: str | None = None
    status: str | None = None
    # New case configuration fields
    case_status: str | None = None
    resolution_route: str | None = None
    position: str | None = None  # Upstream/Downstream
    claimant: str | None = None
    defendant: str | None = None
    client: str | None = None
    # JSON fields
    legal_team: list[LegalTeamMemberSchema] | None = None
    heads_of_claim: list[HeadOfClaimSchema] | None = None
    keywords: list[CaseKeywordSchema] | None = None
    deadlines: list[CaseDeadlineSchema] | None = None

    class Config:
        from_attributes = True


class CaseOut(BaseModel):
    id: str
    case_number: str
    name: str
    description: str | None
    project_name: str | None
    project_id: str | None = None
    contract_type: str | None
    dispute_type: str | None
    status: str
    # New configuration fields
    case_status: str | None = None
    resolution_route: str | None = None
    position: str | None = None
    claimant: str | None = None
    defendant: str | None = None
    client: str | None = None
    legal_team: list[dict] | None = None
    heads_of_claim: list[dict] | None = None
    deadlines: list[dict] | None = None
    keywords: list[dict] | None = None
    # Standard fields
    owner_id: str
    company_id: str | None
    created_at: datetime | None
    updated_at: datetime | None
    evidence_count: int = 0
    issue_count: int = 0

    class Config:
        from_attributes = True


class IssueCreate(BaseModel):
    case_id: str
    title: str
    description: str | None = None
    issue_type: str | None = None
    relevant_contract_clauses: list[str] | None = None


class IssueOut(BaseModel):
    id: str
    case_id: str
    title: str
    description: str | None
    issue_type: str | None
    status: str
    relevant_contract_clauses: list[str] | None
    created_at: datetime
    evidence_count: int = 0

    class Config:
        from_attributes = True


class EvidenceLink(BaseModel):
    case_id: str
    document_id: str
    issue_id: str | None = None
    evidence_type: str | None = None
    exhibit_number: str | None = None
    notes: str | None = None
    relevance_score: int | None = None
    as_planned_date: datetime | None = None
    as_planned_activity: str | None = None
    as_built_date: datetime | None = None
    as_built_activity: str | None = None
    delay_days: int | None = 0
    is_critical_path: bool = False


class EvidenceOut(BaseModel):
    id: str
    case_id: str
    document_id: str
    issue_id: str | None
    evidence_type: str | None
    exhibit_number: str | None
    notes: str | None
    relevance_score: int | None
    added_at: datetime | None
    document_filename: str | None
    document_size: int | None
    document_content_type: str | None
    # Email-specific fields
    email_from: str | None = None
    email_to: str | None = None
    email_cc: str | None = None
    email_subject: str | None = None
    email_date: datetime | None = None
    email_message_id: str | None = None
    content: str | None = None
    content_type: str | None = None
    meta: dict[str, Any] | None = None
    thread_id: str | None = None
    attachments: list[dict[str, Any]] | None = None
    as_planned_date: datetime | None = None
    as_planned_activity: str | None = None
    as_built_date: datetime | None = None
    as_built_activity: str | None = None
    delay_days: int | None = 0
    is_critical_path: bool = False

    class Config:
        from_attributes = True


class ClaimCreate(BaseModel):
    case_id: str
    claim_type: ClaimType
    title: str
    description: str | None = None
    claimed_amount: int | None = None
    currency: str = "GBP"
    claim_date: datetime | None = None


class ClaimOut(BaseModel):
    id: str
    case_id: str
    claim_type: str
    title: str
    description: str | None
    claimed_amount: int | None
    currency: str
    claim_date: datetime | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Case Endpoints
# ============================================================================


@router.get("", response_model=list[CaseOut])
def list_cases(
    db: DbSession,
    current_user: CurrentUser,
    status: str | None = None,
    contract_type: str | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """List all cases accessible to the current user"""
    # Build subqueries for counts
    evidence_count_subq = (
        db.query(Evidence.case_id, func.count(Evidence.id).label("evidence_count"))
        .group_by(Evidence.case_id)
        .subquery()
    )

    issue_count_subq = (
        db.query(Issue.case_id, func.count(Issue.id).label("issue_count"))
        .group_by(Issue.case_id)
        .subquery()
    )

    # Main query with counts
    query = (
        db.query(
            Case,
            func.coalesce(evidence_count_subq.c.evidence_count, 0).label(
                "evidence_count"
            ),
            func.coalesce(issue_count_subq.c.issue_count, 0).label("issue_count"),
        )
        .outerjoin(evidence_count_subq, Case.id == evidence_count_subq.c.case_id)
        .outerjoin(issue_count_subq, Case.id == issue_count_subq.c.case_id)
        .filter(Case.owner_id == current_user.id)
    )

    if status:
        query = query.filter(Case.status == status)
    if contract_type:
        query = query.filter(Case.contract_type == contract_type)
    if search:
        query = query.filter(
            or_(
                Case.name.ilike(f"%{search}%"),
                Case.case_number.ilike(f"%{search}%"),
                Case.project_name.ilike(f"%{search}%"),
            )
        )

    results = query.order_by(desc(Case.created_at)).offset(skip).limit(limit).all()

    # Convert to response model
    result: list[CaseOut] = []
    for case, evidence_count, issue_count in results:
        case_dict = {
            "id": str(case.id),
            "case_number": str(case.case_number),
            "name": str(case.name),
            "description": str(case.description) if case.description else None,
            "project_name": (str(case.project_name) if case.project_name else None),
            "project_id": (
                str(case.project_id) if getattr(case, "project_id", None) else None
            ),
            "contract_type": (str(case.contract_type) if case.contract_type else None),
            "dispute_type": (str(case.dispute_type) if case.dispute_type else None),
            "status": str(case.status),
            "owner_id": str(case.owner_id),
            "company_id": str(case.company_id) if case.company_id else None,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
            "evidence_count": int(evidence_count),
            "issue_count": int(issue_count),
        }
        result.append(CaseOut(**case_dict))

    return result


@router.post("", response_model=CaseOut)
def create_case(data: CaseCreate, db: DbSession, current_user: CurrentUser):
    """Create a new case"""
    # #region agent log
    try:
        from .debug_logger import log_debug

        log_debug(
            "cases.py:create_case",
            "Creating case via cases router",
            {"data": data.model_dump()},
            "H1",
        )
    except Exception:
        pass
    # #endregion

    # Check if case number already exists
    existing = db.query(Case).filter(Case.case_number == data.case_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Case number already exists")

    project_uuid: uuid.UUID | None = None
    if data.project_id:
        try:
            project_uuid = uuid.UUID(str(data.project_id))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid project_id") from exc

        # Validate the project exists (keeps FK clean and improves UX)
        exists = db.query(Project.id).filter(Project.id == project_uuid).first()
        if not exists:
            raise HTTPException(status_code=404, detail="Project not found")

    case = Case(
        id=uuid.uuid4(),
        case_number=data.case_number,
        name=data.name,
        description=data.description,
        project_name=data.project_name,
        project_id=project_uuid,
        contract_type=data.contract_type,
        dispute_type=data.dispute_type,
        owner_id=current_user.id,
        company_id=uuid.UUID(data.company_id) if data.company_id else None,
        status="active",
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
        project_id=str(case.project_id) if getattr(case, "project_id", None) else None,
        contract_type=case.contract_type,
        dispute_type=case.dispute_type,
        status=case.status,
        case_status=getattr(case, "case_status", None),
        resolution_route=getattr(case, "resolution_route", None),
        position=getattr(case, "position", None),
        claimant=getattr(case, "claimant", None),
        defendant=getattr(case, "defendant", None),
        client=getattr(case, "client", None),
        owner_id=str(case.owner_id),
        company_id=str(case.company_id) if case.company_id else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        evidence_count=0,
        issue_count=0,
    )


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: str, db: DbSession, current_user: CurrentUser):
    """Get case details"""
    # Sanitize case_id: convert string "null" to raise error
    if case_id.lower() == "null":
        raise HTTPException(status_code=400, detail="Invalid case ID")

    # Single query to get case with counts
    result = (
        db.query(
            Case,
            func.count(func.distinct(Evidence.id)).label("evidence_count"),
            func.count(func.distinct(Issue.id)).label("issue_count"),
        )
        .outerjoin(Evidence, Case.id == Evidence.case_id)
        .outerjoin(Issue, Case.id == Issue.case_id)
        .filter(Case.id == uuid.UUID(case_id))
        .group_by(Case.id)
        .first()
    )

    if not result:
        raise HTTPException(status_code=404, detail="Case not found")

    case, evidence_count, issue_count = result

    # Check access
    if case.owner_id != current_user.id:
        # TODO: Check if user is in case_users
        raise HTTPException(status_code=403, detail="Access denied")

    # Get keywords for this case
    case_keywords = db.query(Keyword).filter(Keyword.case_id == case.id).all()
    keywords_list = [
        {"id": str(k.id), "keyword_name": k.keyword_name, "variations": k.variations}
        for k in case_keywords
    ]

    return CaseOut(
        id=str(case.id),
        case_number=case.case_number,
        name=case.name,
        description=case.description,
        project_name=case.project_name,
        project_id=str(case.project_id) if getattr(case, "project_id", None) else None,
        contract_type=case.contract_type,
        dispute_type=case.dispute_type,
        status=case.status,
        case_status=getattr(case, "case_status", None),
        resolution_route=getattr(case, "resolution_route", None),
        position=getattr(case, "position", None),
        claimant=getattr(case, "claimant", None),
        defendant=getattr(case, "defendant", None),
        client=getattr(case, "client", None),
        legal_team=getattr(case, "legal_team", None),
        heads_of_claim=getattr(case, "heads_of_claim", None),
        deadlines=getattr(case, "deadlines", None),
        keywords=keywords_list,
        owner_id=str(case.owner_id),
        company_id=str(case.company_id) if case.company_id else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        evidence_count=int(evidence_count or 0),
        issue_count=int(issue_count or 0),
    )


@router.put("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: str, data: CaseUpdate, db: DbSession, current_user: CurrentUser
):
    """Update case details including legal team, heads of claim, keywords, and deadlines"""
    case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Basic fields
    if data.name is not None:
        case.name = data.name
    if data.case_name is not None:
        case.name = data.case_name  # Alias support
    if data.description is not None:
        case.description = data.description
    if data.project_name is not None:
        case.project_name = data.project_name
    if data.project_id is not None:
        if data.project_id == "" or str(data.project_id).lower() in {"null", "none"}:
            case.project_id = None
        else:
            try:
                project_uuid = uuid.UUID(str(data.project_id))
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail="Invalid project_id"
                ) from exc

            exists = db.query(Project.id).filter(Project.id == project_uuid).first()
            if not exists:
                raise HTTPException(status_code=404, detail="Project not found")
            case.project_id = project_uuid
    if data.contract_type is not None:
        case.contract_type = data.contract_type
    if data.dispute_type is not None:
        case.dispute_type = data.dispute_type
    if data.status is not None:
        case.status = data.status

    # New case configuration fields
    if data.case_status is not None:
        case.case_status = data.case_status
    if data.resolution_route is not None:
        case.resolution_route = data.resolution_route
    if data.position is not None:
        case.position = data.position
    if data.claimant is not None:
        case.claimant = data.claimant
    if data.defendant is not None:
        case.defendant = data.defendant
    if data.client is not None:
        case.client = data.client

    # JSON fields (legal_team, heads_of_claim, deadlines)
    if data.legal_team is not None:
        case.legal_team = [
            {"role": lt.role, "name": lt.name, "organization": lt.organization}
            for lt in data.legal_team
        ]
    if data.heads_of_claim is not None:
        case.heads_of_claim = [
            {"name": hoc.name, "status": hoc.status, "actions": hoc.actions}
            for hoc in data.heads_of_claim
        ]
    if data.deadlines is not None:
        case.deadlines = [
            {
                "task": d.task,
                "description": d.description,
                "date": d.date.isoformat() if d.date else None,
                "reminder": d.reminder,
            }
            for d in data.deadlines
        ]

    # Handle keywords via the Keyword table if provided
    if data.keywords is not None:
        from .models import Keyword

        case_uuid = uuid.UUID(case_id)
        # Delete existing keywords for this case
        db.query(Keyword).filter(Keyword.case_id == case_uuid).delete()
        # Create new keywords
        for kw in data.keywords:
            keyword = Keyword(
                case_id=case_uuid,
                keyword_name=kw.name,
                variations=kw.variations,
            )
            db.add(keyword)

    db.commit()
    db.refresh(case)

    # Get counts efficiently
    evidence_count = (
        db.query(func.count(Evidence.id)).filter(Evidence.case_id == case.id).scalar()
        or 0
    )
    issue_count = (
        db.query(func.count(Issue.id)).filter(Issue.case_id == case.id).scalar() or 0
    )

    # Get keywords for response
    case_keywords = db.query(Keyword).filter(Keyword.case_id == case.id).all()
    keywords_list = [
        {"id": str(k.id), "keyword_name": k.keyword_name, "variations": k.variations}
        for k in case_keywords
    ]

    return CaseOut(
        id=str(case.id),
        case_number=case.case_number,
        name=case.name,
        description=case.description,
        project_name=case.project_name,
        project_id=str(case.project_id) if getattr(case, "project_id", None) else None,
        contract_type=case.contract_type,
        dispute_type=case.dispute_type,
        status=case.status,
        case_status=getattr(case, "case_status", None),
        resolution_route=getattr(case, "resolution_route", None),
        position=getattr(case, "position", None),
        claimant=getattr(case, "claimant", None),
        defendant=getattr(case, "defendant", None),
        client=getattr(case, "client", None),
        legal_team=getattr(case, "legal_team", None),
        heads_of_claim=getattr(case, "heads_of_claim", None),
        deadlines=getattr(case, "deadlines", None),
        keywords=keywords_list,
        owner_id=str(case.owner_id),
        company_id=str(case.company_id) if case.company_id else None,
        created_at=case.created_at,
        updated_at=case.updated_at,
        evidence_count=evidence_count,
        issue_count=issue_count,
    )


# ============================================================================
# Evidence Endpoints
# ============================================================================


@router.get("/{case_id}/evidence", response_model=list[EvidenceOut])
def list_case_evidence(
    case_id: str,
    db: DbSession,
    issue_id: str | None = None,
    evidence_type: str | None = None,
):
    """List all evidence for a case"""
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    query = (
        db.query(Evidence, Document)
        .join(Document)
        .filter(Evidence.case_id == case_uuid)
    )

    if issue_id:
        try:
            issue_uuid = uuid.UUID(issue_id)
            query = query.filter(Evidence.issue_id == issue_uuid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid issue ID format")
    if evidence_type:
        query = query.filter(Evidence.evidence_type == evidence_type)

    try:
        results = cast(
            Sequence[tuple[Evidence, Document]],
            query.order_by(desc(Evidence.added_at)).all(),
        )
    except Exception as e:
        logger.error(f"Database error while fetching evidence: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch evidence")

    evidence_list = []
    for evidence, document in results:
        try:
            _issue_id = evidence.issue_id
            evidence_list.append(
                EvidenceOut(
                    id=str(evidence.id),
                    case_id=str(evidence.case_id),
                    document_id=str(evidence.document_id),
                    issue_id=str(_issue_id) if _issue_id is not None else None,
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
                    thread_id=evidence.thread_id,
                    attachments=evidence.attachments,
                    as_planned_date=evidence.as_planned_date,
                    as_planned_activity=evidence.as_planned_activity,
                    as_built_date=evidence.as_built_date,
                    as_built_activity=evidence.as_built_activity,
                    delay_days=evidence.delay_days,
                    is_critical_path=evidence.is_critical_path,
                )
            )
        except Exception as e:
            logger.error(f"Error processing evidence record {evidence.id}: {e}")
            continue

    return evidence_list


@router.post("/{case_id}/evidence", response_model=EvidenceOut)
def link_evidence(
    case_id: str, data: EvidenceLink, db: DbSession, current_user: CurrentUser
):
    """Link a document as evidence to a case"""
    # Verify case exists and user has access
    case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
    if not case or case.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Case not found")

    # Verify document exists
    document = (
        db.query(Document).filter(Document.id == uuid.UUID(data.document_id)).first()
    )
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
        added_by_id=current_user.id,
        as_planned_date=data.as_planned_date,
        as_planned_activity=data.as_planned_activity,
        as_built_date=data.as_built_date,
        as_built_activity=data.as_built_activity,
        delay_days=data.delay_days,
        is_critical_path=data.is_critical_path,
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
        document_content_type=document.content_type,
        attachments=evidence.attachments,
        as_planned_date=evidence.as_planned_date,
        as_planned_activity=evidence.as_planned_activity,
        as_built_date=evidence.as_built_date,
        as_built_activity=evidence.as_built_activity,
        delay_days=evidence.delay_days,
        is_critical_path=evidence.is_critical_path,
    )


# ============================================================================
# Issue Endpoints
# ============================================================================


@router.get("/{case_id}/issues", response_model=list[IssueOut])
def list_case_issues(
    case_id: str, db: DbSession, current_user: CurrentUser, status: str | None = None
):
    """List all issues for a case"""
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    query = db.query(Issue).filter(Issue.case_id == case_uuid)

    if status:
        query = query.filter(Issue.status == status)

    try:
        issues = query.order_by(desc(Issue.created_at)).all()
    except Exception as e:
        logger.error(f"Database error while fetching issues: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch issues")

    result = []
    for issue in issues:
        try:
            evidence_count = (
                db.query(Evidence).filter(Evidence.issue_id == issue.id).count()
            )
            result.append(
                IssueOut(
                    id=str(issue.id),
                    case_id=str(issue.case_id),
                    title=issue.title,
                    description=issue.description,
                    issue_type=issue.issue_type,
                    status=issue.status,
                    relevant_contract_clauses=issue.relevant_contract_clauses,
                    created_at=issue.created_at,
                    evidence_count=evidence_count,
                )
            )
        except Exception as e:
            logger.error(f"Error processing issue record {issue.id}: {e}")
            continue

    return result


@router.post("/{case_id}/issues", response_model=IssueOut)
def create_issue(
    case_id: str, data: IssueCreate, db: DbSession, current_user: CurrentUser
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
        status="open",
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
        evidence_count=0,
    )


# ============================================================================
# Claims Endpoints
# ============================================================================


@router.get("/{case_id}/claims", response_model=list[ClaimOut])
def list_case_claims(
    case_id: str,
    db: DbSession,
    current_user: CurrentUser,
    claim_type: ClaimType | None = None,
):
    """List all claims for a case"""
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    query = db.query(Claim).filter(Claim.case_id == case_uuid)

    if claim_type:
        query = query.filter(Claim.claim_type == claim_type)

    try:
        claims = query.order_by(desc(Claim.created_at)).all()
    except Exception as e:
        logger.error(f"Database error while fetching claims: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch claims")

    result = []
    for c in claims:
        try:
            result.append(
                ClaimOut(
                    id=str(c.id),
                    case_id=str(c.case_id),
                    claim_type=c.claim_type.value,
                    title=c.title,
                    description=c.description,
                    claimed_amount=c.claimed_amount,
                    currency=c.currency,
                    claim_date=c.claim_date,
                    status=c.status,
                    created_at=c.created_at,
                )
            )
        except Exception as e:
            logger.error(f"Error processing claim record {c.id}: {e}")
            continue

    return result


@router.post("/{case_id}/claims", response_model=ClaimOut)
def create_claim(
    case_id: str, data: ClaimCreate, db: DbSession, current_user: CurrentUser
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
        status="draft",
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
        created_at=claim.created_at,
    )


# ============================================================================
# Documents List for Evidence Linking
# ============================================================================


@router.get("/{case_id}/available-documents")
def list_available_documents(
    case_id: str,
    db: DbSession,
    current_user: CurrentUser,
    search: str | None = None,
    limit: int = 50,
):
    """List documents that can be linked as evidence"""
    # Get all user's documents
    query = db.query(Document).filter(
        Document.owner_user_id == current_user.id, Document.status == DocStatus.READY
    )

    if search:
        query = query.filter(
            or_(
                Document.filename.ilike(f"%{search}%"),
                Document.title.ilike(f"%{search}%"),
            )
        )

    documents = query.order_by(desc(Document.created_at)).limit(limit).all()

    return [
        {
            "id": str(doc.id),
            "filename": doc.filename,
            "title": doc.title,
            "content_type": doc.content_type,
            "size": doc.size,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "is_linked": db.query(Evidence)
            .filter(
                Evidence.document_id == doc.id, Evidence.case_id == uuid.UUID(case_id)
            )
            .first()
            is not None,
            "metadata": doc.meta or {},
        }
        for doc in documents
    ]


@router.get("/{case_id}/documents")
def list_case_documents(case_id: str, db: DbSession, current_user: CurrentUser):
    """List all documents uploaded for a case (including PST files)"""
    # For now, return all documents owned by user
    # TODO: Filter by case_id once we add case_id to Document model
    documents = (
        db.query(Document)
        .filter(Document.owner_user_id == current_user.id)
        .order_by(desc(Document.created_at))
        .all()
    )

    return [
        {
            "id": str(doc.id),
            "filename": doc.filename,
            "status": getattr(doc.status, "value", doc.status),
            "size": doc.size,
            "content_type": doc.content_type,
            "uploaded_at": doc.created_at.isoformat() if doc.created_at else None,
            "metadata": doc.meta or {},
            "pst_processing": (
                (doc.meta or {}).get("pst_processing") if doc.meta else None
            ),
        }
        for doc in documents
    ]
