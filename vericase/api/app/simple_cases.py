"""
Simple Cases APIE for testing without authentication
"""

from typing import Annotated, Any, cast
import logging
import os
import uuid
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, model_validator

from .db import get_db
from .models import (
    Case,
    Company,
    UserCompany,
    Project,
    Workspace,
    User,
    UserRole,
    Stakeholder,
    Keyword,
    PSTFile,
    EmailMessage,
    Programme,
    EvidenceSource,
    EvidenceCollection,
    EvidenceItem,
    EmailAttachment,
    EvidenceCorrespondenceLink,
    EvidenceRelation,
    EvidenceCollectionItem,
    EvidenceActivityLog,
    ItemClaimLink,
    ContentiousMatter,
    HeadOfClaim,
    RefinementSessionDB,
)

logger = logging.getLogger(__name__)


def _get_default_owner_user_id(db: Session) -> uuid.UUID:
    """Pick a valid user id to satisfy FK/NOT NULL constraints.

    Prefers an ADMIN user; falls back to the newest user.
    """

    owner = (
        db.query(User)
        .filter(User.role == UserRole.ADMIN)
        .order_by(desc(User.created_at))
        .first()
    )
    if owner:
        return owner.id

    owner = db.query(User).order_by(desc(User.created_at)).first()
    if owner:
        return owner.id

    raise HTTPException(
        status_code=500,
        detail="No users exist to assign as project owner. Create an admin user first.",
    )


def _get_or_create_company_id_for_user(db: Session, user_id: uuid.UUID) -> uuid.UUID:
    """Return a company_id usable for new Case rows.

    Preference order:
    1) The user's primary company (UserCompany.is_primary)
    2) Any company the user belongs to
    3) The newest Company in the system
    4) Create a new default Company and membership

    Uses the caller's DB session and only flushes (does not commit).
    """

    membership = (
        db.query(UserCompany)
        .filter(UserCompany.user_id == user_id)
        .order_by(desc(UserCompany.is_primary), desc(UserCompany.joined_at))
        .first()
    )
    if membership:
        return membership.company_id

    company = db.query(Company).order_by(desc(Company.created_at)).first()
    if not company:
        company = Company(id=uuid.uuid4(), company_name="Default Company")
        db.add(company)
        db.flush()

    existing_membership = (
        db.query(UserCompany)
        .filter(UserCompany.user_id == user_id, UserCompany.company_id == company.id)
        .first()
    )
    if not existing_membership:
        db.add(
            UserCompany(
                id=uuid.uuid4(),
                user_id=user_id,
                company_id=company.id,
                role="admin",
                is_primary=True,
            )
        )
        db.flush()

    return company.id


def validate_search_input(search: str) -> str:
    """Validate and sanitize search input to prevent any injection attempts"""
    if not search:
        return ""
    # Remove any potentially dangerous characters
    # Allow only alphanumeric, spaces, hyphens, underscores, and common punctuation
    sanitized = re.sub(r"[^\w\s.,@-]", "", search)
    # Limit length to prevent DoS
    return sanitized[:100]


router = APIRouter(prefix="/api", tags=["simple-cases"])
DbDep = Annotated[Session, Depends(get_db)]

# Avoid importing app Settings here (keeps this module usable in isolation).
JWT_SECRET = os.getenv(
    "JWT_SECRET",
    "c3bef73578895c08045f8848192958b2dbfaf55a57f97509553c3d5324a7d2b1",
)
JWT_ISSUER = os.getenv("JWT_ISSUER", "vericase-docs")

_optional_bearer = HTTPBearer(auto_error=False)
OptionalBearerCreds = Annotated[
    HTTPAuthorizationCredentials | None, Depends(_optional_bearer)
]


def get_optional_current_user(creds: OptionalBearerCreds, db: DbDep) -> User | None:
    """Best-effort auth for the "simple" endpoints.

    If a Bearer token is present and valid, return the corresponding active user.
    Otherwise return None.

    This keeps the no-auth testing endpoints usable, while letting logged-in UI
    flows correctly attribute created/returned data to the current user.
    """

    if not creds or not creds.credentials:
        return None

    try:
        payload = jwt.decode(
            creds.credentials,
            JWT_SECRET,
            algorithms=["HS256"],
            issuer=JWT_ISSUER,
        )
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            return None
        user = db.query(User).filter(User.id == uuid.UUID(str(user_id_raw))).first()
        if user and user.is_active:
            return user
        return None
    except JWTError:
        return None
    except Exception:
        return None


class ProjectStateResponse(BaseModel):
    id: str
    project_name: str
    project_code: str
    meta: dict[str, Any] = Field(default_factory=dict)
    analysis_type: str | None = None


class ProjectDetailResponse(ProjectStateResponse):
    start_date: str | None = None
    completion_date: str | None = None
    contract_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


# Pydantic models for request/response validation
class StakeholderCreate(BaseModel):
    role: str
    name: str
    email: str | None = None
    organization: str | None = None


class KeywordCreate(BaseModel):
    name: str
    definition: str | None = None
    variations: str | None = None


class ProjectCreate(BaseModel):
    model_config = {"populate_by_name": True}

    project_name: str = Field(..., min_length=2, max_length=200)
    project_code: str = Field(..., min_length=1)
    start_date: datetime | None = None
    completion_date: datetime | None = None
    contract_type: str | None = None
    workspace_id: str | None = None
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

    @model_validator(mode="before")
    @classmethod
    def flatten_payload(cls, data: Any) -> Any:
        """Accept multiple UI payload shapes (wizard + quick-start).

        Supports keys like projectName/projectCode/contractType and nested `details`.
        """

        if not isinstance(data, dict):
            return data

        details = data.get("details", {}) or {}

        def get_val(keys: list[str]):
            for k in keys:
                if k in data and data[k]:
                    return data[k]
                if k in details and details[k]:
                    return details[k]
            return None

        # Map common alias keys into snake_case used by this schema.
        if "project_name" not in data:
            v = get_val(["projectName", "project_name", "name"])
            if v:
                data["project_name"] = v

        if "project_code" not in data:
            v = get_val(["projectCode", "project_code", "code"])
            if v:
                data["project_code"] = v

        if "contract_type" not in data:
            v = get_val(["contractType", "contract_type"])
            if v:
                data["contract_type"] = v

        if "start_date" not in data:
            v = get_val(["startDate", "start_date"])
            if v:
                data["start_date"] = v

        if "completion_date" not in data:
            v = get_val(["completionDate", "completion_date"])
            if v:
                data["completion_date"] = v

        if "workspace_id" not in data:
            v = get_val(["workspaceId", "workspace_id"])
            if v:
                data["workspace_id"] = v

        if "analysis_type" not in data:
            v = get_val(["analysisType", "analysis_type"])
            if v:
                data["analysis_type"] = v

        return data


class LegalTeamMember(BaseModel):
    role: str
    name: str


class HeadOfClaimSchema(BaseModel):
    head: str
    status: str = "Discovery"
    actions: str | None = None


class Deadline(BaseModel):
    task: str
    description: str | None = None
    date: datetime | None = None


class CaseCreate(BaseModel):
    model_config = {"populate_by_name": True}

    case_name: str = Field(..., min_length=2, max_length=200)
    case_number: str | None = None
    case_id: str | None = None  # Backwards compatibility alias
    project_id: str | None = None
    workspace_id: str | None = None
    contract_type: str | None = None
    description: str | None = None
    stakeholders: list[StakeholderCreate] = Field(default_factory=list)
    resolution_route: str | None = "TBC"
    claimant: str | None = None
    defendant: str | None = None
    case_status: str | None = "discovery"
    client: str | None = None
    legal_team: list[LegalTeamMember] = Field(default_factory=list)
    heads_of_claim: list[HeadOfClaimSchema] = Field(default_factory=list)
    keywords: list[KeywordCreate] = Field(default_factory=list)
    deadlines: list[Deadline] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, data: Any) -> Any:
        """Accept multiple UI payload shapes (wizard + quick-start)."""
        if not isinstance(data, dict):
            return data

        details = data.get("details", {}) or {}

        def get_val(keys: list[str]):
            for key in keys:
                if key in data and data[key]:
                    return data[key]
                if key in details and details[key]:
                    return details[key]
            return None

        if "case_name" not in data:
            name_val = get_val(["caseName", "case_name", "name"])
            if name_val:
                data["case_name"] = name_val

        if "case_number" not in data:
            number_val = get_val(
                ["caseNumber", "case_number", "caseId", "case_id", "code"]
            )
            if number_val:
                data["case_number"] = number_val

        if "project_id" not in data:
            project_val = get_val(["projectId", "project_id"])
            if project_val:
                data["project_id"] = project_val

        if "workspace_id" not in data:
            workspace_val = get_val(["workspaceId", "workspace_id"])
            if workspace_val:
                data["workspace_id"] = workspace_val

        if "contract_type" not in data:
            contract_val = get_val(["contractType", "contract_type"])
            if contract_val:
                data["contract_type"] = contract_val

        if "description" not in data:
            desc_val = get_val(["description", "caseDescription"])
            if desc_val:
                data["description"] = desc_val

        if "case_number" not in data and data.get("case_id"):
            data["case_number"] = data.get("case_id")

        return data


@router.get("/cases")
def list_cases_simple(
    db: DbDep,
    current_user: User | None = Depends(get_optional_current_user),
) -> list[dict[str, str | int | None]]:
    """List cases.

    - Without auth: returns the newest 50 cases (testing/dev convenience).
    - With auth: returns only cases owned by the user (admins see all).
    """
    try:
        query = db.query(Case)

        if current_user:
            role_val = (
                current_user.role.value
                if hasattr(current_user.role, "value")
                else str(current_user.role)
            )
            if str(role_val).upper() != "ADMIN":
                query = query.filter(Case.owner_id == current_user.id)

        # Using SQLAlchemy ORM which parameterizes queries safely
        cases = query.order_by(desc(Case.created_at)).limit(50).all()

        result: list[dict[str, str | int | None]] = []
        for case in cases:
            result.append(
                {
                    "id": str(case.id),
                    "name": case.name or "Untitled Case",
                    "case_number": getattr(case, "case_number", f"CASE-{case.id}"),
                    "description": case.description,
                    "project_name": getattr(case, "project_name", None),
                    "contract_type": getattr(case, "contract_type", None),
                    "dispute_type": getattr(case, "dispute_type", None),
                    "status": getattr(case, "status", "active"),
                    "created_at": (
                        case.created_at.isoformat()
                        if case.created_at
                        else datetime.now(timezone.utc).isoformat()
                    ),
                    "evidence_count": 0,  # TODO: Count evidence
                    "issue_count": 0,  # TODO: Count issues
                }
            )

        return result

    except Exception as e:
        logger.error(f"Error listing cases: {e}")
        raise HTTPException(status_code=500, detail="Failed to list cases")


@router.get("/projects")
def list_projects(db: DbDep) -> list[dict[str, str | None]]:
    """List all projects without authentication"""
    try:
        # Using SQLAlchemy ORM which parameterizes queries safely
        projects = db.query(Project).order_by(desc(Project.created_at)).limit(50).all()

        result: list[dict[str, str | None]] = []
        for project in projects:
            result.append(
                {
                    "id": str(project.id),
                    "project_name": project.project_name,
                    "project_code": project.project_code,
                    "start_date": (
                        project.start_date.isoformat() if project.start_date else None
                    ),
                    "completion_date": (
                        project.completion_date.isoformat()
                        if project.completion_date
                        else None
                    ),
                    "contract_type": project.contract_type,
                    "analysis_type": project.analysis_type or "project",
                    "created_at": (
                        project.created_at.isoformat()
                        if project.created_at
                        else datetime.now(timezone.utc).isoformat()
                    ),
                }
            )

        return result

    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        raise HTTPException(status_code=500, detail="Failed to list projects")


@router.post("/projects", response_model=ProjectDetailResponse)
def create_project(
    project_data: ProjectCreate,
    db: DbDep,
    current_user: User | None = Depends(get_optional_current_user),
) -> ProjectDetailResponse:
    """Create a project.

    Works without auth for dev/testing. If a valid Bearer token is present we
    attribute ownership to that user.
    """

    try:
        owner_user_id = (
            current_user.id if current_user else _get_default_owner_user_id(db)
        )

        project_code = (project_data.project_code or "").strip()
        if not project_code:
            project_code = f"PROJ-{uuid.uuid4().hex[:8].upper()}"

        workspace_uuid: uuid.UUID | None = None
        if project_data.workspace_id:
            try:
                workspace_uuid = uuid.UUID(str(project_data.workspace_id))
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail="Invalid workspace_id"
                ) from exc

            workspace = (
                db.query(Workspace.id).filter(Workspace.id == workspace_uuid).first()
            )
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")

        project = Project(
            id=uuid.uuid4(),
            project_name=project_data.project_name,
            project_code=project_code,
            start_date=project_data.start_date,
            completion_date=project_data.completion_date,
            contract_type=project_data.contract_type,
            analysis_type=project_data.analysis_type or "project",
            project_aliases=project_data.project_aliases,
            site_address=project_data.site_address,
            include_domains=project_data.include_domains,
            exclude_people=project_data.exclude_people,
            project_terms=project_data.project_terms,
            exclude_keywords=project_data.exclude_keywords,
            owner_user_id=owner_user_id,
            workspace_id=workspace_uuid,
            meta={},
        )
        db.add(project)

        # Create stakeholders for the project
        for stakeholder_data in project_data.stakeholders:
            email_domain = None
            if stakeholder_data.email and "@" in stakeholder_data.email:
                email_domain = stakeholder_data.email.split("@")[-1].lower()

            stakeholder = Stakeholder(
                id=uuid.uuid4(),
                project_id=project.id,
                case_id=None,
                role=stakeholder_data.role,
                name=stakeholder_data.name,
                email=stakeholder_data.email,
                organization=stakeholder_data.organization,
                email_domain=email_domain,
            )
            db.add(stakeholder)

        # Create keywords for the project
        for keyword_data in project_data.keywords:
            keyword = Keyword(
                id=uuid.uuid4(),
                project_id=project.id,
                case_id=None,
                keyword_name=keyword_data.name,
                definition=keyword_data.definition,
                variations=keyword_data.variations,
            )
            db.add(keyword)

        db.commit()
        db.refresh(project)

        return ProjectDetailResponse(
            id=str(project.id),
            project_name=project.project_name,
            project_code=project.project_code,
            start_date=project.start_date.isoformat() if project.start_date else None,
            completion_date=(
                project.completion_date.isoformat() if project.completion_date else None
            ),
            contract_type=project.contract_type,
            analysis_type=project.analysis_type or "project",
            meta=project.meta or {},
            created_at=project.created_at.isoformat() if project.created_at else None,
            updated_at=project.updated_at.isoformat() if project.updated_at else None,
        )

    except IntegrityError as e:
        db.rollback()
        logger.exception(f"Integrity error creating project: {e}")
        raise HTTPException(
            status_code=400,
            detail="Failed to create project (likely duplicate project code or missing required fields)",
        )
    except Exception as e:
        db.rollback()
        logger.exception(f"Error creating project: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create project: {str(e)}"
        )


@router.post("/projects/default", response_model=ProjectStateResponse)
def get_or_create_default_project(db: DbDep) -> ProjectStateResponse:
    """Get or create a default project.

    The UI's state manager relies on this to ensure pages always have a valid
    project context after login.
    """

    default_code = "DEFAULT-PROJECT"
    default_name = "Evidence Uploads"

    project = db.query(Project).filter(Project.project_code == default_code).first()
    if not project:
        owner_user_id = _get_default_owner_user_id(db)
        project = Project(
            id=uuid.uuid4(),
            project_name=default_name,
            project_code=default_code,
            analysis_type="project",
            owner_user_id=owner_user_id,
            meta={},
        )
        db.add(project)
        db.commit()
        db.refresh(project)

    return ProjectStateResponse(
        id=str(project.id),
        project_name=project.project_name,
        project_code=project.project_code,
        meta=project.meta or {},
        analysis_type=project.analysis_type or "project",
    )


@router.get("/projects/default", response_model=ProjectStateResponse)
def get_or_create_default_project_get(db: DbDep) -> ProjectStateResponse:
    """GET alias for /projects/default."""

    return get_or_create_default_project(db)


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: str, db: DbDep) -> ProjectDetailResponse:
    """Fetch a single project by UUID.

    Required by the UI state manager when `?projectId=<uuid>` is present.
    """

    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectDetailResponse(
        id=str(project.id),
        project_name=project.project_name,
        project_code=project.project_code,
        start_date=project.start_date.isoformat() if project.start_date else None,
        completion_date=(
            project.completion_date.isoformat() if project.completion_date else None
        ),
        contract_type=project.contract_type,
        analysis_type=project.analysis_type or "project",
        meta=project.meta or {},
        created_at=project.created_at.isoformat() if project.created_at else None,
        updated_at=project.updated_at.isoformat() if project.updated_at else None,
    )


@router.get("/stakeholder-suggestions")
def get_stakeholder_suggestions(
    db: DbDep, search: str | None = None
) -> list[dict[str, str]]:
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
                        Stakeholder.organization.ilike(f"%{safe_search}%"),
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
            {"value": "NHBC", "type": "organization"},
        ]


@router.get("/keyword-suggestions")
def get_keyword_suggestions() -> list[dict[str, str]]:
    """Get pre-populated keywords"""
    # These are always the same pre-populated keywords
    return [
        {"name": "Relevant Event", "variations": ""},
        {"name": "Relevant Matter", "variations": ""},
        {
            "name": "Section 278",
            "variations": "Section 278, Highways Agreement, Section 106",
        },
        {"name": "Delay", "variations": "delays, delayed, postpone, postponement"},
    ]


class ProjectUpdate(BaseModel):
    project_name: str = Field(..., min_length=2, max_length=200)
    project_code: str | None = None
    description: str | None = None
    contract_type: str | None = None
    start_date: datetime | None = None
    completion_date: datetime | None = None


class CaseFromProjectRequest(BaseModel):
    case_name: str | None = None
    case_number: str | None = None
    description: str | None = None
    include_stakeholders: bool = True
    include_keywords: bool = True
    include_heads_of_claim: bool = True
    include_contentious_matters: bool = True


@router.put("/projects/{project_id}")
def update_project(
    project_id: str, project_data: ProjectUpdate, db: DbDep
) -> dict[str, str]:
    """Update a project's details"""
    try:
        # Find the project
        project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Check if new project code conflicts with another project
        if (
            project_data.project_code
            and project_data.project_code != project.project_code
        ):
            existing = (
                db.query(Project)
                .filter(
                    Project.project_code == project_data.project_code,
                    Project.id != uuid.UUID(project_id),
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=400, detail="Project code already exists"
                )

        # Update fields
        project.project_name = project_data.project_name
        if project_data.project_code:
            project.project_code = project_data.project_code
        if project_data.description is not None:
            project.description = project_data.description
        if project_data.contract_type is not None:
            project.contract_type = project_data.contract_type
        if project_data.start_date is not None:
            project.start_date = project_data.start_date
        if project_data.completion_date is not None:
            project.completion_date = project_data.completion_date

        db.commit()
        db.refresh(project)

        return {
            "id": str(project.id),
            "project_name": project.project_name,
            "project_code": project.project_code,
            "status": "success",
            "message": "Project updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Error updating project: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update project: {str(e)}"
        )


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: DbDep) -> dict[str, str]:
    """Delete a project and all associated data"""
    try:
        project_uuid = uuid.UUID(project_id)

        # Find the project
        project = db.query(Project).filter(Project.id == project_uuid).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Delete all related records in order (children first to respect FK constraints)

        # Get IDs needed for cascading deletes
        email_ids = [
            e.id
            for e in db.query(EmailMessage)
            .filter(EmailMessage.project_id == project_uuid)
            .all()
        ]
        evidence_item_ids = [
            e.id
            for e in db.query(EvidenceItem)
            .filter(EvidenceItem.project_id == project_uuid)
            .all()
        ]
        evidence_collection_ids = [
            e.id
            for e in db.query(EvidenceCollection)
            .filter(EvidenceCollection.project_id == project_uuid)
            .all()
        ]

        # Delete ItemClaimLinks for correspondence (email_messages) in this project
        if email_ids:
            db.query(ItemClaimLink).filter(
                ItemClaimLink.item_type == "correspondence",
                ItemClaimLink.item_id.in_(email_ids),
            ).delete(synchronize_session=False)

        # Delete ItemClaimLinks for evidence items in this project
        if evidence_item_ids:
            db.query(ItemClaimLink).filter(
                ItemClaimLink.item_type == "evidence",
                ItemClaimLink.item_id.in_(evidence_item_ids),
            ).delete(synchronize_session=False)

        # Delete EvidenceCorrespondenceLinks (references evidence_items and email_messages)
        if evidence_item_ids:
            db.query(EvidenceCorrespondenceLink).filter(
                EvidenceCorrespondenceLink.evidence_item_id.in_(evidence_item_ids)
            ).delete(synchronize_session=False)
        if email_ids:
            db.query(EvidenceCorrespondenceLink).filter(
                EvidenceCorrespondenceLink.email_message_id.in_(email_ids)
            ).delete(synchronize_session=False)

        # Delete EvidenceRelations (references evidence_items)
        if evidence_item_ids:
            db.query(EvidenceRelation).filter(
                EvidenceRelation.source_evidence_id.in_(evidence_item_ids)
            ).delete(synchronize_session=False)
            db.query(EvidenceRelation).filter(
                EvidenceRelation.target_evidence_id.in_(evidence_item_ids)
            ).delete(synchronize_session=False)

        # Delete EvidenceCollectionItems (references evidence_collections and evidence_items)
        if evidence_collection_ids:
            db.query(EvidenceCollectionItem).filter(
                EvidenceCollectionItem.collection_id.in_(evidence_collection_ids)
            ).delete(synchronize_session=False)
        if evidence_item_ids:
            db.query(EvidenceCollectionItem).filter(
                EvidenceCollectionItem.evidence_item_id.in_(evidence_item_ids)
            ).delete(synchronize_session=False)

        # Delete EvidenceActivityLog (references evidence_items and evidence_collections)
        if evidence_item_ids:
            db.query(EvidenceActivityLog).filter(
                EvidenceActivityLog.evidence_item_id.in_(evidence_item_ids)
            ).delete(synchronize_session=False)
        if evidence_collection_ids:
            db.query(EvidenceActivityLog).filter(
                EvidenceActivityLog.collection_id.in_(evidence_collection_ids)
            ).delete(synchronize_session=False)

        # Delete RefinementSessions for this project
        db.query(RefinementSessionDB).filter(
            RefinementSessionDB.project_id == str(project_uuid)
        ).delete(synchronize_session=False)

        # Delete email attachments (references email_messages)
        if email_ids:
            db.query(EmailAttachment).filter(
                EmailAttachment.email_message_id.in_(email_ids)
            ).delete(synchronize_session=False)

        # Delete email messages
        db.query(EmailMessage).filter(EmailMessage.project_id == project_uuid).delete(
            synchronize_session=False
        )

        # Delete PST files
        db.query(PSTFile).filter(PSTFile.project_id == project_uuid).delete(
            synchronize_session=False
        )

        # Delete evidence items
        db.query(EvidenceItem).filter(EvidenceItem.project_id == project_uuid).delete(
            synchronize_session=False
        )

        # Delete evidence collections
        db.query(EvidenceCollection).filter(
            EvidenceCollection.project_id == project_uuid
        ).delete(synchronize_session=False)

        # Delete evidence sources
        db.query(EvidenceSource).filter(
            EvidenceSource.project_id == project_uuid
        ).delete(synchronize_session=False)

        # Delete programmes
        db.query(Programme).filter(Programme.project_id == project_uuid).delete(
            synchronize_session=False
        )

        # Delete associated stakeholders
        db.query(Stakeholder).filter(Stakeholder.project_id == project_uuid).delete(
            synchronize_session=False
        )

        # Delete associated keywords
        db.query(Keyword).filter(Keyword.project_id == project_uuid).delete(
            synchronize_session=False
        )

        # Delete heads of claim (has CASCADE but be explicit)
        # Note: project_id column may not exist in older schemas, so wrap in try/except
        try:
            db.query(HeadOfClaim).filter(HeadOfClaim.project_id == project_uuid).delete(
                synchronize_session=False
            )
        except Exception:
            pass  # Column may not exist yet

        # Delete contentious matters (has CASCADE but be explicit)
        try:
            db.query(ContentiousMatter).filter(
                ContentiousMatter.project_id == project_uuid
            ).delete(synchronize_session=False)
        except Exception:
            pass  # Column may not exist yet

        # Delete the project
        db.delete(project)
        db.commit()

        return {
            "id": str(project_id),
            "status": "success",
            "message": "Project deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Error deleting project: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete project: {str(e)}"
        )


@router.post("/projects/{project_id}/cases")
def create_case_from_project(
    project_id: str,
    payload: CaseFromProjectRequest,
    db: DbDep,
    current_user: User | None = Depends(get_optional_current_user),
) -> dict[str, str]:
    """Create a case from an existing project, optionally copying configuration."""
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID format")

    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    owner_user_id = current_user.id if current_user else _get_default_owner_user_id(db)
    company_id = _get_or_create_company_id_for_user(db, owner_user_id)

    case_number = (payload.case_number or "").strip()
    if not case_number:
        case_number = f"CASE-{uuid.uuid4().hex[:8].upper()}"

    existing_case = db.query(Case).filter(Case.case_number == case_number).first()
    if existing_case:
        raise HTTPException(status_code=400, detail="Case number already exists")

    case_name = (payload.case_name or "").strip()
    if not case_name:
        case_name = f"{project.project_name} Case"

    case = Case(
        id=uuid.uuid4(),
        name=case_name,
        case_number=case_number,
        description=payload.description or f"Case derived from {project.project_name}",
        status="active",
        owner_id=owner_user_id,
        company_id=company_id,
        project_id=project.id,
        project_name=project.project_name,
        contract_type=project.contract_type,
        workspace_id=project.workspace_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(case)
    db.flush()

    if payload.include_stakeholders:
        stakeholders = (
            db.query(Stakeholder).filter(Stakeholder.project_id == project.id).all()
        )
        for s in stakeholders:
            db.add(
                Stakeholder(
                    id=uuid.uuid4(),
                    project_id=None,
                    case_id=case.id,
                    role=s.role,
                    name=s.name,
                    email=s.email,
                    organization=s.organization,
                    email_domain=s.email_domain,
                )
            )

    if payload.include_keywords:
        keywords = db.query(Keyword).filter(Keyword.project_id == project.id).all()
        for k in keywords:
            db.add(
                Keyword(
                    id=uuid.uuid4(),
                    project_id=None,
                    case_id=case.id,
                    keyword_name=k.keyword_name,
                    variations=k.variations,
                    is_regex=k.is_regex,
                )
            )

    if payload.include_heads_of_claim:
        matter_map: dict[uuid.UUID, uuid.UUID] = {}
        if payload.include_contentious_matters:
            matters = (
                db.query(ContentiousMatter)
                .filter(ContentiousMatter.project_id == project.id)
                .all()
            )
            for matter in matters:
                new_matter = ContentiousMatter(
                    id=uuid.uuid4(),
                    project_id=None,
                    case_id=case.id,
                    name=matter.name,
                    description=matter.description,
                    status=matter.status,
                    priority=matter.priority,
                    estimated_value=matter.estimated_value,
                    currency=matter.currency,
                    date_identified=matter.date_identified,
                    resolution_date=matter.resolution_date,
                    created_by=matter.created_by or owner_user_id,
                )
                db.add(new_matter)
                db.flush()
                matter_map[matter.id] = new_matter.id

        claims = (
            db.query(HeadOfClaim).filter(HeadOfClaim.project_id == project.id).all()
        )
        for claim in claims:
            db.add(
                HeadOfClaim(
                    id=uuid.uuid4(),
                    project_id=None,
                    case_id=case.id,
                    contentious_matter_id=matter_map.get(claim.contentious_matter_id),
                    reference_number=claim.reference_number,
                    name=claim.name,
                    description=claim.description,
                    claim_type=claim.claim_type,
                    claimed_amount=claim.claimed_amount,
                    awarded_amount=claim.awarded_amount,
                    currency=claim.currency,
                    status=claim.status,
                    submission_date=claim.submission_date,
                    response_due_date=claim.response_due_date,
                    determination_date=claim.determination_date,
                    supporting_contract_clause=claim.supporting_contract_clause,
                    created_by=claim.created_by or owner_user_id,
                )
            )

    db.commit()
    db.refresh(case)

    return {
        "id": str(case.id),
        "case_name": case.name,
        "case_number": case.case_number,
        "project_id": str(project.id),
        "status": case.status,
        "created_at": (
            case.created_at.isoformat()
            if case.created_at
            else datetime.now(timezone.utc).isoformat()
        ),
    }


@router.post("/cases")
def create_case(
    case_data: CaseCreate,
    db: DbDep,
    current_user: User | None = Depends(get_optional_current_user),
) -> dict[str, str]:
    """Create a case.

    This endpoint intentionally works without auth (for dev/testing), but if a
    valid Bearer token is present we attribute ownership to that user so
    logged-in UI flows behave correctly.
    """
    # #region agent log
    try:
        from .debug_logger import log_debug

        log_debug(
            "simple_cases.py:create_case",
            "Creating case via simple_cases router",
            {"case_data": case_data.model_dump()},
            "H1",
        )
    except Exception:
        pass
    # #endregion

    try:
        owner_user_id = (
            current_user.id if current_user else _get_default_owner_user_id(db)
        )
        company_id = _get_or_create_company_id_for_user(db, owner_user_id)

        workspace_uuid: uuid.UUID | None = None
        if case_data.workspace_id:
            try:
                workspace_uuid = uuid.UUID(str(case_data.workspace_id))
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail="Invalid workspace_id"
                ) from exc

            workspace = (
                db.query(Workspace.id).filter(Workspace.id == workspace_uuid).first()
            )
            if not workspace:
                raise HTTPException(status_code=404, detail="Workspace not found")

        project_uuid: uuid.UUID | None = None
        project_name: str | None = None
        if case_data.project_id:
            try:
                project_uuid = uuid.UUID(str(case_data.project_id))
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail="Invalid project_id"
                ) from exc

            project = db.query(Project).filter(Project.id == project_uuid).first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
            project_name = project.project_name
            if project.workspace_id:
                if workspace_uuid and project.workspace_id != workspace_uuid:
                    raise HTTPException(
                        status_code=400, detail="Project does not belong to workspace"
                    )
                workspace_uuid = project.workspace_id

        case_number_value = (case_data.case_number or case_data.case_id or "").strip()
        if not case_number_value:
            case_number_value = f"CASE-{uuid.uuid4().hex[:8].upper()}"

        def _dump_list(items: list[BaseModel] | None) -> list[dict[str, Any]] | None:
            if not items:
                return None
            return [item.model_dump() for item in items]

        case = Case(
            id=uuid.uuid4(),
            name=case_data.case_name,
            case_number=case_number_value,
            description=case_data.description or f"Dispute case: {case_data.case_name}",
            status="active",
            owner_id=owner_user_id,
            company_id=company_id,
            project_id=project_uuid,
            project_name=project_name,
            contract_type=case_data.contract_type,
            workspace_id=workspace_uuid,
            legal_team=_dump_list(case_data.legal_team),
            heads_of_claim=_dump_list(case_data.heads_of_claim),
            deadlines=_dump_list(case_data.deadlines),
            created_at=datetime.now(timezone.utc),
        )

        if hasattr(Case, "case_status"):
            case.case_status = case_data.case_status
        if hasattr(Case, "resolution_route"):
            case.resolution_route = case_data.resolution_route
        if hasattr(Case, "claimant"):
            case.claimant = case_data.claimant
        if hasattr(Case, "defendant"):
            case.defendant = case_data.defendant
        if hasattr(Case, "client"):
            case.client = case_data.client

        db.add(case)

        # Create stakeholders for the case
        for stakeholder_data in case_data.stakeholders:
            email_domain = None
            if stakeholder_data.email and "@" in stakeholder_data.email:
                email_domain = stakeholder_data.email.split("@")[-1].lower()

            stakeholder = Stakeholder(
                id=uuid.uuid4(),
                project_id=None,
                case_id=case.id,
                role=stakeholder_data.role,
                name=stakeholder_data.name,
                email=stakeholder_data.email,
                organization=stakeholder_data.organization,
                email_domain=email_domain,
            )
            db.add(stakeholder)

        # Create keywords for the case
        for keyword_data in case_data.keywords:
            keyword = Keyword(
                id=uuid.uuid4(),
                case_id=case.id,
                project_id=None,
                keyword_name=keyword_data.name,
                definition=keyword_data.definition,
                variations=keyword_data.variations,
            )
            db.add(keyword)

        db.commit()
        db.refresh(case)

        return {
            "id": str(case.id),
            "case_name": case.name,
            "case_number": case.case_number,
            "status": "active",
            "created_at": (
                case.created_at.isoformat()
                if case.created_at
                else datetime.now(timezone.utc).isoformat()
            ),
        }

    except IntegrityError as e:
        db.rollback()
        logger.exception(f"Integrity error creating case: {e}")
        raise HTTPException(
            status_code=400,
            detail="Failed to create case (likely duplicate case number or missing required fields)",
        )
    except Exception as e:
        db.rollback()
        logger.exception(f"Error creating case: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create case: {str(e)}")


@router.delete("/cases/{case_id}")
def delete_case(
    case_id: str,
    db: DbDep,
    current_user: User | None = Depends(get_optional_current_user),
) -> dict[str, str]:
    """Delete a case and all associated data"""
    try:
        # Find the case
        case = db.query(Case).filter(Case.id == uuid.UUID(case_id)).first()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        if current_user:
            role_val = (
                current_user.role.value
                if hasattr(current_user.role, "value")
                else str(current_user.role)
            )
            is_admin = str(role_val).upper() == "ADMIN"
            if not is_admin and getattr(case, "owner_id", None) != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")

        # Delete associated keywords
        _ = db.query(Keyword).filter(Keyword.case_id == uuid.UUID(case_id)).delete()

        # Delete the case
        db.delete(case)
        db.commit()

        return {
            "id": str(case_id),
            "status": "success",
            "message": "Case deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Error deleting case: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete case: {str(e)}")
