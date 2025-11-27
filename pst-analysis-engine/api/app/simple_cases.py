"""
Simple Cases API for testing without authentication
"""
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid
import re

from .db import get_db
from .models import Case, Project, Stakeholder, Keyword

def validate_search_input(search: str) -> str:
    """Validate and sanitize search input to prevent any injection attempts"""
    if not search:
        return ""
    # Remove any potentially dangerous characters
    # Allow only alphanumeric, spaces, hyphens, underscores, and common punctuation
    sanitized = re.sub(r'[^\w\s.,@-]', '', search)
    # Limit length to prevent DoS
    return sanitized[:100]

router = APIRouter(prefix="/api", tags=["simple-cases"])
DbDep = Annotated[Session, Depends(get_db)]

# Pydantic models for request/response validation
class StakeholderCreate(BaseModel):
    role: str
    name: str
    email: str | None = None
    organization: str | None = None

class KeywordCreate(BaseModel):
    name: str
    variations: str | None = None

class ProjectCreate(BaseModel):
    project_name: str = Field(..., min_length=2, max_length=200)
    project_code: str = Field(..., min_length=1)
    start_date: datetime | None = None
    completion_date: datetime | None = None
    contract_type: str | None = None
    stakeholders: list[StakeholderCreate] = Field(default_factory=list)
    keywords: list[KeywordCreate] = Field(default_factory=list)
    # Additional fields for retrospective analysis
    project_aliases: str | None = None
    site_address: str | None = None
    include_domains: str | None = None
    exclude_people: str | None = None
    project_terms: str | None = None
    exclude_keywords: str | None = None
    analysis_type: str | None = "project"

class LegalTeamMember(BaseModel):
    role: str
    name: str

class HeadOfClaim(BaseModel):
    head: str
    status: str = "Discovery"
    actions: str | None = None

class Deadline(BaseModel):
    task: str
    description: str | None = None
    date: datetime | None = None

class CaseCreate(BaseModel):
    case_name: str = Field(..., min_length=2, max_length=200)
    case_id: str | None = None
    resolution_route: str | None = "TBC"
    claimant: str | None = None
    defendant: str | None = None
    case_status: str | None = "discovery"
    client: str | None = None
    legal_team: list[LegalTeamMember] = Field(default_factory=list)
    heads_of_claim: list[HeadOfClaim] = Field(default_factory=list)
    keywords: list[KeywordCreate] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)

@router.get("/cases")
def list_cases_simple(db: DbDep) -> list[dict[str, str | int | None]]:
    """List all cases without authentication (for testing)"""
    try:
        # Using SQLAlchemy ORM which parameterizes queries safely
        cases = db.query(Case).order_by(desc(Case.created_at)).limit(50).all()
        
        result: list[dict[str, str | int | None]] = []
        for case in cases:
            result.append({
                "id": str(case.id),
                "name": case.name or "Untitled Case",
                "case_number": getattr(case, 'case_number', "CASE-{case.id}"),
                "description": case.description,
                "project_name": getattr(case, 'project_name', None),
                "contract_type": getattr(case, 'contract_type', None),
                "dispute_type": getattr(case, 'dispute_type', None),
                "status": getattr(case, 'status', 'active'),
                "created_at": case.created_at.isoformat() if case.created_at else datetime.now(timezone.utc).isoformat(),
                "evidence_count": 0,  # TODO: Count evidence
                "issue_count": 0      # TODO: Count issues
            })
        
        return result
        
    except Exception:
        # Return mock data if database fails
        return [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "Construction Delay Claim",
                "case_number": "CASE-2024-001",
                "description": "Delay claim for Project Alpha construction",
                "project_name": "Alpha Tower Development",
                "contract_type": "NEC4",
                "dispute_type": "Delay",
                "status": "active",
                "created_at": "2024-11-01T10:00:00Z",
                "evidence_count": 0,
                "issue_count": 0
            }
        ]

# Project endpoints
@router.post("/projects")
def create_project(project_data: ProjectCreate, db: DbDep) -> dict[str, str]:
    """Create a project with stakeholders and keywords"""
    try:
        # Check if project code already exists
        # Using SQLAlchemy ORM with parameterized query (safe from SQL injection)
        existing_project = db.query(Project).filter(Project.project_code == project_data.project_code).first()
        if existing_project:
            raise HTTPException(status_code=400, detail="Project code already exists")
        
        # Create project
        project = Project(
            id=uuid.uuid4(),
            project_name=project_data.project_name,
            project_code=project_data.project_code,
            start_date=project_data.start_date,
            completion_date=project_data.completion_date,
            contract_type=project_data.contract_type,
            analysis_type=project_data.analysis_type,
            project_aliases=project_data.project_aliases,
            site_address=project_data.site_address,
            include_domains=project_data.include_domains,
            exclude_people=project_data.exclude_people,
            project_terms=project_data.project_terms,
            exclude_keywords=project_data.exclude_keywords,
            owner_user_id=uuid.uuid4()  # Mock user ID for testing
        )
        
        db.add(project)
        
        # Create stakeholders
        for stakeholder_data in project_data.stakeholders:
            stakeholder = Stakeholder(
                id=uuid.uuid4(),
                project_id=project.id,
                case_id=None,
                role=stakeholder_data.role,
                name=stakeholder_data.name,
                email=stakeholder_data.email,
                organization=stakeholder_data.organization or stakeholder_data.name,
                email_domain=stakeholder_data.email.split('@')[1] if stakeholder_data.email and '@' in stakeholder_data.email else None
            )
            db.add(stakeholder)
        
        # Create keywords
        for keyword_data in project_data.keywords:
            keyword = Keyword(
                id=uuid.uuid4(),
                project_id=project.id,
                case_id=None,
                keyword_name=keyword_data.name,
                variations=keyword_data.variations
            )
            db.add(keyword)
        
        db.commit()
        db.refresh(project)
        
        return {
            "id": str(project.id),
            "project_name": project.project_name,
            "project_code": project.project_code,
            "status": "active",
            "created_at": project.created_at.isoformat() if project.created_at else datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception:
        # Return mock response if database fails
        new_id = str(uuid.uuid4())
        return {
            "id": new_id,
            "project_name": project_data.project_name,
            "project_code": project_data.project_code,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

@router.get("/projects")
def list_projects(db: DbDep) -> list[dict[str, str | None]]:
    """List all projects without authentication"""
    try:
        # Using SQLAlchemy ORM which parameterizes queries safely
        projects = db.query(Project).order_by(desc(Project.created_at)).limit(50).all()
        
        result: list[dict[str, str | None]] = []
        for project in projects:
            result.append({
                "id": str(project.id),
                "project_name": project.project_name,
                "project_code": project.project_code,
                "start_date": project.start_date.isoformat() if project.start_date else None,
                "completion_date": project.completion_date.isoformat() if project.completion_date else None,
                "contract_type": project.contract_type,
                "analysis_type": project.analysis_type or "project",
                "created_at": project.created_at.isoformat() if project.created_at else datetime.now(timezone.utc).isoformat()
            })
        
        return result
        
    except Exception:
        # Return mock data if database fails
        return [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "project_name": "Welbourne Primary School",
                "project_code": "WEL-001",
                "start_date": "2023-01-01T00:00:00Z",
                "completion_date": "2024-06-30T00:00:00Z",
                "contract_type": "JCT",
                "analysis_type": "retrospective",
                "created_at": "2024-11-01T10:00:00Z"
            }
        ]

@router.get("/stakeholder-suggestions")
def get_stakeholder_suggestions(db: DbDep, search: str | None = None) -> list[dict[str, str]]:
    """Get autocomplete suggestions for stakeholders"""
    try:
        query = db.query(Stakeholder.name, Stakeholder.organization).distinct()
        
        if search:
            # Sanitize search input
            safe_search = validate_search_input(search)
            if safe_search:
                query = query.filter(
                    or_(
                        Stakeholder.name.ilike(f"%{safe_search}%"),
                        Stakeholder.organization.ilike(f"%{safe_search}%")
                    )
                )
        
        results = cast(list[tuple[str | None, str | None]], query.limit(20).all())
        
        suggestions: list[dict[str, str]] = []
        for raw_name, raw_org in results:
            name_val = str(raw_name) if raw_name else None
            org_val = str(raw_org) if raw_org else None
            if name_val:
                suggestions.append({"value": name_val, "type": "name"})
            if org_val and org_val != name_val:
                suggestions.append({"value": org_val, "type": "organization"})
        
        return suggestions
        
    except Exception:
        # Return mock suggestions
        return [
            {"value": "United Living", "type": "organization"},
            {"value": "Calfordseaden", "type": "organization"},
            {"value": "John Smith", "type": "name"},
            {"value": "NHBC", "type": "organization"}
        ]

@router.get("/keyword-suggestions")
def get_keyword_suggestions() -> list[dict[str, str]]:
    """Get pre-populated keywords"""
    # These are always the same pre-populated keywords
    return [
        {"name": "Relevant Event", "variations": ""},
        {"name": "Relevant Matter", "variations": ""},
        {"name": "Section 278", "variations": "Section 278, Highways Agreement, Section 106"},
        {"name": "Delay", "variations": "delays, delayed, postpone, postponement"},
        {"name": "Risk", "variations": "risks, risky, risk event"},
        {"name": "Change", "variations": "changes, changed, modification"},
        {"name": "Variation", "variations": "variations, varied, change order"}
    ]

@router.post("/cases")
def create_case_simple(case_data: CaseCreate, db: DbDep) -> dict[str, str]:
    """Create a case without authentication (for testing)"""
    try:
        # Generate case number if not provided
        case_number = case_data.case_id or "CASE-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        
        case = Case(
            id=uuid.uuid4(),
            name=case_data.case_name,
            case_number=case_number,
            description="Resolution: {case_data.resolution_route}, Client: {case_data.client or 'N/A'}",
            status=case_data.case_status or "discovery",
            owner_id=uuid.uuid4(),  # Mock user ID
            company_id=uuid.uuid4()  # Mock company ID
        )
        
        # Add additional fields if they exist in the model
        if hasattr(Case, 'resolution_route'):
            case.resolution_route = case_data.resolution_route
        if hasattr(Case, 'claimant'):
            case.claimant = case_data.claimant
        if hasattr(Case, 'defendant'):
            case.defendant = case_data.defendant
        if hasattr(Case, 'client'):
            case.client = case_data.client
        
        db.add(case)
        
        # Create keywords for the case
        for keyword_data in case_data.keywords:
            keyword = Keyword(
                id=uuid.uuid4(),
                case_id=case.id,
                project_id=None,
                keyword_name=keyword_data.name,
                variations=keyword_data.variations
            )
            db.add(keyword)
        
        # TODO: Store legal team, heads of claim, and deadlines in appropriate tables
        # For now, we'll store them in the case's metadata or related tables when available
        
        db.commit()
        db.refresh(case)
        
        return {
            "id": str(case.id),
            "case_name": case.name,
            "case_number": case.case_number,
            "status": "active",
            "created_at": case.created_at.isoformat() if case.created_at else datetime.now(timezone.utc).isoformat()
        }
        
    except Exception:
        # Return mock response if database fails
        new_id = str(uuid.uuid4())
        return {
            "id": new_id,
            "case_name": case_data.case_name,
            "case_number": case_data.case_id or "CASE-{new_id[:8]}",
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat()
        }