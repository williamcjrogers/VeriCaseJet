"""
Simple Cases APIE for testing without authentication
"""

from typing import Annotated, Any, cast
import logging
import os
import uuid
import re
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from pydantic import BaseModel, Field, model_validator

from .db import SessionLocal, get_db
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
    ProjectIntelPack,
    ProjectIntelPackSnapshot,
    DelayEvent,
    RefinementSessionDB,
    MessageOccurrence,
)
from .workspaces import (
    _complete_with_tool_fallback,
    _extract_json_object,
    _hint_tokens,
    _is_missing_table_error,
    _raise_missing_migration,
    _safe_excerpt,
    _select_best_excerpt,
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


def _parse_uuid(value: str | None, field: str) -> uuid.UUID:
    if value in (None, ""):
        raise HTTPException(status_code=400, detail=f"Missing {field}")
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


def _split_keyword_variations(value: str | None) -> list[str]:
    """Split keyword variations into clean terms.

    Supports comma, semicolon, or newline separated values.
    """

    if not value:
        return []
    parts = re.split(r"[,;\n]+", str(value))
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        term = str(raw or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(term)
    return cleaned


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        v = str(raw or "").strip()
        if not v:
            continue
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


class _KeywordMatcher:
    """Fast-ish matcher for Keyword rules against text."""

    def __init__(self, keywords: list[Keyword]):
        self.names_by_id: dict[str, str] = {}
        self.plain_terms_by_id: dict[str, list[re.Pattern[str]]] = {}
        self.regex_terms_by_id: dict[str, list[re.Pattern[str]]] = {}

        for k in keywords:
            kw_id = str(getattr(k, "id", "") or "")
            name = (getattr(k, "keyword_name", "") or "").strip()
            if not kw_id or not name:
                continue

            self.names_by_id[kw_id] = name
            raw_terms = [name] + _split_keyword_variations(
                getattr(k, "variations", None)
            )

            is_regex = bool(getattr(k, "is_regex", False))
            if is_regex:
                patterns: list[re.Pattern[str]] = []
                for term in raw_terms:
                    t = (term or "").strip()
                    if not t:
                        continue
                    try:
                        patterns.append(re.compile(t, flags=re.IGNORECASE))
                    except re.error:
                        # Skip invalid user regex; don't fail the whole scan.
                        continue
                if patterns:
                    self.regex_terms_by_id[kw_id] = patterns
            else:
                terms: list[re.Pattern[str]] = []
                seen: set[str] = set()
                for term in raw_terms:
                    t = (term or "").strip().lower()
                    if len(t) < 3:
                        continue
                    if t in seen:
                        continue
                    seen.add(t)
                    escaped = re.escape(t)
                    pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
                    try:
                        terms.append(re.compile(pattern, flags=re.IGNORECASE))
                    except re.error:
                        continue
                if terms:
                    self.plain_terms_by_id[kw_id] = terms

    def match_keyword_ids(self, subject: str | None, body: str | None) -> list[str]:
        subj = (subject or "").strip()
        text = (body or "").strip()
        if not subj and not text:
            return []

        haystack = f"{subj}\n{text}"
        matched: list[str] = []

        for kw_id, terms in self.plain_terms_by_id.items():
            for term in terms:
                if term.search(haystack):
                    matched.append(kw_id)
                    break

        for kw_id, patterns in self.regex_terms_by_id.items():
            for pat in patterns:
                try:
                    if pat.search(haystack):
                        matched.append(kw_id)
                        break
                except re.error:
                    continue

        return matched


class KeywordRescanRequest(BaseModel):
    include_emails: bool = True
    include_evidence: bool = True
    max_emails: int | None = Field(default=5000, ge=1, le=200000)
    max_evidence: int | None = Field(default=5000, ge=1, le=200000)
    mode: str = Field(
        default="merge",
        description="merge (default) unions new matches with existing; overwrite replaces.",
    )


class ProjectStateResponse(BaseModel):
    id: str
    project_name: str
    project_code: str
    meta: dict[str, Any] = Field(default_factory=dict)
    analysis_type: str | None = None


class StakeholderOut(BaseModel):
    id: str
    role: str
    name: str
    email: str | None = None
    organization: str | None = None


class KeywordOut(BaseModel):
    id: str
    keyword_name: str
    definition: str | None = None
    variations: str | None = None


class ProjectDetailResponse(ProjectStateResponse):
    start_date: str | None = None
    completion_date: str | None = None
    contract_type: str | None = None
    contract_family: str | None = None
    contract_form: str | None = None
    contract_form_custom: str | None = None
    stakeholders: list[StakeholderOut] = Field(default_factory=list)
    keywords: list[KeywordOut] = Field(default_factory=list)
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
    contract_family: str | None = None
    contract_form: str | None = None
    contract_form_custom: str | None = None
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
    name: str | None = None
    head: str | None = None  # Backwards compatibility
    status: str = "Discovery"
    actions: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_head(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Accept either 'name' or 'head'
            if "head" in data and "name" not in data:
                data["name"] = data["head"]
            elif "name" in data and "head" not in data:
                data["head"] = data["name"]
        return data


class Deadline(BaseModel):
    task: str
    description: str | None = None
    date: datetime | None = None
    reminder: str | None = "none"


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
    position: str | None = None  # Upstream/Downstream
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
            contract_family=project_data.contract_family,
            contract_form=project_data.contract_form,
            contract_form_custom=project_data.contract_form_custom,
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

    # Get stakeholders
    stakeholders = (
        db.query(Stakeholder).filter(Stakeholder.project_id == project_uuid).all()
    )
    stakeholder_list = [
        StakeholderOut(
            id=str(s.id),
            role=s.role or "",
            name=s.name or "",
            email=s.email,
            organization=s.organization,
        )
        for s in stakeholders
    ]

    # Get keywords
    keywords = db.query(Keyword).filter(Keyword.project_id == project_uuid).all()
    keyword_list = [
        KeywordOut(
            id=str(k.id),
            keyword_name=k.keyword_name or "",
            definition=k.definition,
            variations=k.variations,
        )
        for k in keywords
    ]

    return ProjectDetailResponse(
        id=str(project.id),
        project_name=project.project_name,
        project_code=project.project_code,
        start_date=project.start_date.isoformat() if project.start_date else None,
        completion_date=(
            project.completion_date.isoformat() if project.completion_date else None
        ),
        contract_type=project.contract_type,
        contract_family=getattr(project, "contract_family", None),
        contract_form=getattr(project, "contract_form", None),
        contract_form_custom=getattr(project, "contract_form_custom", None),
        stakeholders=stakeholder_list,
        keywords=keyword_list,
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
    contract_family: str | None = None
    contract_form: str | None = None
    contract_form_custom: str | None = None
    start_date: datetime | None = None
    completion_date: datetime | None = None
    stakeholders: list[StakeholderCreate] | None = None
    keywords: list[KeywordCreate] | None = None


class ProjectIntelConfigRequest(BaseModel):
    purpose_text: str | None = Field(default=None, max_length=12000)
    instructions_evidence_id: str | None = Field(default=None)


class ProjectIntelRefreshRequest(BaseModel):
    force: bool = False
    deep: bool = False


class ProjectIntelAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class ProjectIntelBuildRequest(BaseModel):
    rescan_keywords: bool = True
    link_evidence: bool = True
    refresh_intel: bool = True
    deep: bool = False
    max_evidence: int = Field(default=300, ge=10, le=2000)


class ClaimNodeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    node_type: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None


class ClaimNodeUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    node_type: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None


class ClaimLinkCreate(BaseModel):
    node_id: str = Field(..., min_length=1)
    item_type: str = Field(..., min_length=1, max_length=50)
    item_id: str = Field(..., min_length=1)
    link_type: str = Field(default="supports", max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


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
    """Update a project's details including stakeholders and keywords"""
    try:
        project_uuid = uuid.UUID(project_id)

        # Find the project
        project = db.query(Project).filter(Project.id == project_uuid).first()
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
                    Project.id != project_uuid,
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=400, detail="Project code already exists"
                )

        # Update basic fields
        project.project_name = project_data.project_name
        if project_data.project_code:
            project.project_code = project_data.project_code
        if project_data.description is not None:
            project.description = project_data.description
        if project_data.contract_type is not None:
            project.contract_type = project_data.contract_type
        if project_data.contract_family is not None:
            project.contract_family = project_data.contract_family
        if project_data.contract_form is not None:
            project.contract_form = project_data.contract_form
        if project_data.contract_form_custom is not None:
            project.contract_form_custom = project_data.contract_form_custom
        if project_data.start_date is not None:
            project.start_date = project_data.start_date
        if project_data.completion_date is not None:
            project.completion_date = project_data.completion_date

        # Update stakeholders (replace all)
        if project_data.stakeholders is not None:
            # Delete existing stakeholders for this project
            db.query(Stakeholder).filter(
                Stakeholder.project_id == project_uuid
            ).delete()

            # Create new stakeholders
            for stakeholder_data in project_data.stakeholders:
                email_domain = None
                if stakeholder_data.email and "@" in stakeholder_data.email:
                    email_domain = stakeholder_data.email.split("@")[-1].lower()

                stakeholder = Stakeholder(
                    project_id=project_uuid,
                    role=stakeholder_data.role,
                    name=stakeholder_data.name,
                    email=stakeholder_data.email,
                    email_domain=email_domain,
                    organization=stakeholder_data.organization,
                )
                db.add(stakeholder)

        # Update keywords (replace all)
        if project_data.keywords is not None:
            # Delete existing keywords for this project
            db.query(Keyword).filter(Keyword.project_id == project_uuid).delete()

            # Create new keywords
            for keyword_data in project_data.keywords:
                keyword = Keyword(
                    project_id=project_uuid,
                    keyword_name=keyword_data.name,
                    definition=keyword_data.definition,
                    variations=keyword_data.variations,
                )
                db.add(keyword)

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


@router.post("/projects/{project_id}/keywords/rescan")
def rescan_project_keywords(
    project_id: str,
    payload: KeywordRescanRequest,
    db: DbDep,
    current_user: User | None = Depends(get_optional_current_user),
) -> dict[str, Any]:
    """Rescan correspondence + evidence and allocate keyword matches.

    Uses Keyword rules stored for the Project (keywords table).
    """

    try:
        project_uuid = uuid.UUID(str(project_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Invalid project ID format"
        ) from exc

    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mode = (payload.mode or "merge").strip().lower()
    if mode not in ("merge", "overwrite"):
        raise HTTPException(status_code=400, detail="Invalid mode (merge|overwrite)")

    keywords = (
        db.query(Keyword)
        .filter(Keyword.project_id == project_uuid, Keyword.case_id.is_(None))
        .order_by(Keyword.keyword_name.asc())
        .all()
    )
    matcher = _KeywordMatcher(keywords)
    if not matcher.names_by_id:
        return {
            "status": "success",
            "project_id": str(project_uuid),
            "keywords": 0,
            "emails_scanned": 0,
            "emails_updated": 0,
            "evidence_scanned": 0,
            "evidence_updated": 0,
            "message": "No keywords configured for this project.",
        }

    emails_scanned = 0
    emails_updated = 0
    evidence_scanned = 0
    evidence_updated = 0

    # Correspondence
    if payload.include_emails:
        q = db.query(EmailMessage).filter(EmailMessage.project_id == project_uuid)
        max_emails = int(payload.max_emails or 0)
        if max_emails > 0:
            q = q.order_by(EmailMessage.created_at.desc()).limit(max_emails)
        emails = q.all()

        for e in emails:
            emails_scanned += 1
            body = (
                e.body_text_clean
                or e.body_text
                or e.body_preview
                or (re.sub(r"<[^>]+>", " ", e.body_html or "") if e.body_html else "")
            )
            new_ids = matcher.match_keyword_ids(e.subject, body)
            if not new_ids:
                continue
            existing = (
                e.matched_keywords if isinstance(e.matched_keywords, list) else []
            )
            if mode == "overwrite":
                merged = _unique_strings(new_ids)
            else:
                merged = _unique_strings([*existing, *new_ids])
            if merged != existing:
                e.matched_keywords = merged
                emails_updated += 1

    # Evidence
    if payload.include_evidence:
        q = db.query(EvidenceItem).filter(EvidenceItem.project_id == project_uuid)
        max_evidence = int(payload.max_evidence or 0)
        if max_evidence > 0:
            q = q.order_by(EvidenceItem.created_at.desc()).limit(max_evidence)
        items = q.all()

        for it in items:
            evidence_scanned += 1
            # Keep evidence matching bounded to avoid huge allocations.
            extracted = it.extracted_text or ""
            if len(extracted) > 200000:
                extracted = extracted[:200000]
            blob = "\n".join(
                [
                    str(it.filename or ""),
                    str(it.title or ""),
                    str(it.description or ""),
                    extracted,
                ]
            )
            new_ids = matcher.match_keyword_ids(it.filename, blob)
            if not new_ids:
                continue

            existing_ids = (
                it.keywords_matched if isinstance(it.keywords_matched, list) else []
            )
            if mode == "overwrite":
                merged_ids = _unique_strings(new_ids)
            else:
                merged_ids = _unique_strings([*existing_ids, *new_ids])
            changed = merged_ids != existing_ids
            if changed:
                it.keywords_matched = merged_ids

            # Also expose keyword *names* via auto_tags so existing tag filtering works.
            auto = it.auto_tags if isinstance(it.auto_tags, list) else []
            name_tags = [matcher.names_by_id.get(kid, "") for kid in new_ids]
            name_tags = [t for t in name_tags if t]
            merged_auto = _unique_strings([*auto, *name_tags])
            if merged_auto != auto:
                it.auto_tags = merged_auto
                changed = True

            if changed:
                evidence_updated += 1

    # Persist updates
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    actor_id = str(current_user.id) if current_user else None
    logger.info(
        "Keyword rescan complete (project_id=%s actor_id=%s): emails_updated=%s evidence_updated=%s",
        project_uuid,
        actor_id,
        emails_updated,
        evidence_updated,
    )

    return {
        "status": "success",
        "project_id": str(project_uuid),
        "keywords": len(matcher.names_by_id),
        "emails_scanned": emails_scanned,
        "emails_updated": emails_updated,
        "evidence_scanned": evidence_scanned,
        "evidence_updated": evidence_updated,
        "mode": mode,
    }


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

        # Clear source_email_id references in evidence_items before deleting emails
        if email_ids:
            db.query(EvidenceItem).filter(
                EvidenceItem.source_email_id.in_(email_ids)
            ).update({EvidenceItem.source_email_id: None}, synchronize_session=False)

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

        # Delete message occurrences (references project)
        try:
            db.query(MessageOccurrence).filter(
                MessageOccurrence.project_id == project_uuid
            ).delete(synchronize_session=False)
        except Exception:
            pass  # Table may not exist yet

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


# =============================================================================
# Project Intel Pack (project-scoped purpose + tracking pack)
# =============================================================================


def _get_project_scoped_evidence(
    db: Session,
    *,
    project: Project,
    evidence_id: str | None,
    case_ids: list[uuid.UUID] | None = None,
) -> EvidenceItem | None:
    if not evidence_id:
        return None
    ev_uuid = _parse_uuid(evidence_id, "instructions_evidence_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == ev_uuid).first()
    if not item:
        return None
    if item.project_id == project.id:
        return item
    if case_ids and item.case_id in case_ids:
        return item
    if project.workspace_id and (item.meta or {}).get("workspace_id") == str(
        project.workspace_id
    ):
        return item
    return None


async def _build_project_intel_pack_snapshot(
    *,
    db: Session,
    project: Project,
    force: bool = False,
    deep: bool = False,
) -> ProjectIntelPack:
    try:
        pack = (
            db.query(ProjectIntelPack)
            .filter(ProjectIntelPack.project_id == project.id)
            .first()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_packs"):
            _raise_missing_migration("project_intel_packs")
        raise
    if not pack:
        pack = ProjectIntelPack(project_id=project.id, status="empty")
        db.add(pack)
        db.commit()
        db.refresh(pack)

    cases = db.query(Case).filter(Case.project_id == project.id).all()
    case_ids = [c.id for c in cases]

    delay_events: list[DelayEvent] = []
    if case_ids:
        delay_events = (
            db.query(DelayEvent)
            .filter(DelayEvent.case_id.in_(case_ids))
            .order_by(desc(DelayEvent.created_at))
            .limit(30)
            .all()
        )

    evidence_conds = [EvidenceItem.project_id == project.id]
    if case_ids:
        evidence_conds.append(EvidenceItem.case_id.in_(case_ids))
    if project.workspace_id:
        evidence_conds.append(
            EvidenceItem.meta.op("->>")("workspace_id") == str(project.workspace_id)
        )

    latest_doc = (
        db.query(EvidenceItem)
        .filter(or_(*evidence_conds))
        .order_by(desc(EvidenceItem.created_at))
        .first()
    )
    latest_doc_at = getattr(latest_doc, "created_at", None)
    if (
        not force
        and (pack.status or "").lower() == "ready"
        and pack.updated_at
        and latest_doc_at
        and pack.updated_at >= latest_doc_at
    ):
        return pack

    pack.status = "building"
    pack.last_error = None
    db.commit()
    run_id = uuid.uuid4()
    run_started_at = datetime.now(timezone.utc)

    purpose_text = (pack.purpose_text or "").strip()
    instruction_item = _get_project_scoped_evidence(
        db,
        project=project,
        evidence_id=(
            str(pack.instructions_evidence_id) if pack.instructions_evidence_id else None
        ),
        case_ids=case_ids,
    )

    evidence_pool = (
        db.query(EvidenceItem)
        .filter(or_(*evidence_conds))
        .order_by(desc(EvidenceItem.created_at))
        .limit(240 if deep else 160)
        .all()
    )
    if instruction_item and all(it.id != instruction_item.id for it in evidence_pool):
        evidence_pool.insert(0, instruction_item)

    email_pool = []
    email_conds = [EmailMessage.project_id == project.id]
    if case_ids:
        email_conds.append(EmailMessage.case_id.in_(case_ids))
    if email_conds:
        email_pool = (
            db.query(EmailMessage)
            .filter(or_(*email_conds))
            .filter(EmailMessage.is_duplicate.is_(False))
            .filter(EmailMessage.is_inclusive.is_(True))
            .order_by(
                desc(EmailMessage.date_sent).nullslast(),
                desc(EmailMessage.created_at),
            )
            .limit(260 if deep else 180)
            .all()
        )

    purpose_hints = [
        "instruction",
        "instructions",
        "instruction narrative",
        "deliverable",
        "chronology",
        "contradiction",
        "responsibility",
        "inspection",
        "design",
        "causation",
        "delay",
        "keyword",
        "issue grouping",
    ]
    purpose_hints.extend(_hint_tokens(purpose_text))
    purpose_hints = list(dict.fromkeys([h for h in purpose_hints if h]))

    def score_evidence(it: EvidenceItem) -> int:
        score = 0
        fn = (it.filename or "").lower()
        et = (it.evidence_type or "").lower()
        if et in ("contract", "expert_report", "pleading"):
            score += 90
        if any(k in fn for k in ("instruction", "narrative", "scope", "terms")):
            score += 70
        for k, w in (
            ("expert", 40),
            ("report", 30),
            ("notice", 30),
            ("chronology", 35),
            ("inspection", 35),
            ("drawing", 25),
            ("specification", 30),
            ("email", 15),
        ):
            if k in fn:
                score += w
        if (it.extracted_text or "").strip():
            score += 10
        return score

    ranked_evidence = sorted(evidence_pool, key=score_evidence, reverse=True)
    target_evidence = 16 if deep else 10
    evidence_candidate_limit = 80 if deep else 45
    top_evidence = ranked_evidence[:target_evidence]

    def score_email_for_purpose(em: EmailMessage) -> int:
        subj = (em.subject or "").lower()
        score = 0
        if em.has_attachments:
            score += 30
        for k in (
            "instruction",
            "scope",
            "notice",
            "inspection",
            "defect",
            "water ingress",
            "design",
            "responsibility",
            "delay",
        ):
            if k in subj:
                score += 20
        return score

    ranked_emails = sorted(email_pool, key=score_email_for_purpose, reverse=True)
    target_emails = 8 if deep else 5
    email_candidate_limit = 50 if deep else 25
    top_emails = ranked_emails[:target_emails]

    # Deep mode: rerank evidence/email candidates (best-effort).
    if deep:
        try:
            from .config import settings
            from .aws_services import get_aws_services

            if getattr(settings, "BEDROCK_RERANK_ENABLED", False):
                aws = get_aws_services()
                rerank_query = (
                    "Select the most relevant sources for building a purpose baseline from an instruction narrative. "
                    "Prioritize instruction/scope, deliverables, chronology, responsibility/causation, inspections/defects, "
                    "key notices, and any contradictions between parties' positions."
                )

                cand_evidence = ranked_evidence[:evidence_candidate_limit]
                if len(cand_evidence) > 3:
                    ev_snippets: list[str] = []
                    for it in cand_evidence:
                        excerpt = _select_best_excerpt(
                            it.extracted_text, 900, hints=purpose_hints
                        ) or ((it.extracted_text or "")[:900])
                        meta = []
                        if it.document_date:
                            meta.append(f"date={it.document_date.isoformat()}")
                        if (it.evidence_type or "").strip():
                            meta.append(f"type={(it.evidence_type or '').strip()}")
                        header = f"{it.filename or 'Untitled'}" + (
                            f" ({', '.join(meta)})" if meta else ""
                        )
                        ev_snippets.append(f"{header}\n{excerpt}")
                    reranked = await aws.rerank_texts(
                        rerank_query,
                        ev_snippets,
                        top_n=min(target_evidence, len(ev_snippets)),
                    )
                    ev_order = [
                        int(r.get("index", -1)) for r in reranked if isinstance(r, dict)
                    ]
                    picked: list[EvidenceItem] = []
                    seen: set[str] = set()
                    for idx in ev_order:
                        if 0 <= idx < len(cand_evidence):
                            it = cand_evidence[idx]
                            sid = str(it.id)
                            if sid not in seen:
                                picked.append(it)
                                seen.add(sid)
                    if picked:
                        top_evidence = picked[:target_evidence]

                cand_emails = ranked_emails[:email_candidate_limit]
                if len(cand_emails) > 3:
                    em_snippets: list[str] = []
                    for em in cand_emails:
                        subject = (em.subject or "(no subject)").strip()
                        dt = em.date_sent.isoformat() if em.date_sent else None
                        frm = (em.sender_email or em.sender_name or "Unknown").strip()
                        body = em.body_text_clean or em.body_preview or em.body_text or ""
                        excerpt = _select_best_excerpt(body, 800, hints=purpose_hints) or (
                            body[:800]
                        )
                        header = f"Email: {subject}" + (f" (date={dt})" if dt else "")
                        em_snippets.append(f"{header}\nFrom: {frm}\n{excerpt}")
                    reranked = await aws.rerank_texts(
                        rerank_query,
                        em_snippets,
                        top_n=min(target_emails, len(em_snippets)),
                    )
                    em_order = [
                        int(r.get("index", -1)) for r in reranked if isinstance(r, dict)
                    ]
                    picked_em: list[Any] = []
                    seen_em: set[str] = set()
                    for idx in em_order:
                        if 0 <= idx < len(cand_emails):
                            em = cand_emails[idx]
                            sid = str(getattr(em, "id", "")) or f"idx:{idx}"
                            if sid not in seen_em:
                                picked_em.append(em)
                                seen_em.add(sid)
                    if picked_em:
                        top_emails = picked_em[:target_emails]
        except Exception:
            pass

    sources: list[dict[str, Any]] = []
    blocks: list[str] = []
    label_idx = 1
    if instruction_item:
        excerpt = _select_best_excerpt(
            instruction_item.extracted_text,
            1600,
            hints=purpose_hints,
        ) or _select_best_excerpt(
            (
                (instruction_item.extracted_metadata or {}).get("text_preview")
                if isinstance(instruction_item.extracted_metadata, dict)
                else ""
            ),
            1600,
            hints=purpose_hints,
        )
        sources.append(
            {
                "label": f"S{label_idx}",
                "evidence_id": str(instruction_item.id),
                "filename": instruction_item.filename,
                "document_date": (
                    instruction_item.document_date.isoformat()
                    if instruction_item.document_date
                    else None
                ),
                "evidence_type": "instructions",
            }
        )
        if excerpt:
            blocks.append(
                f"[S{label_idx}] {instruction_item.filename} (id={instruction_item.id})\n{excerpt}"
            )
        label_idx += 1

    for it in top_evidence:
        label = f"S{label_idx}"
        excerpt = _select_best_excerpt(it.extracted_text, 1400, hints=purpose_hints)
        sources.append(
            {
                "label": label,
                "evidence_id": str(it.id),
                "filename": it.filename,
                "document_date": it.document_date.isoformat() if it.document_date else None,
                "evidence_type": getattr(it, "evidence_type", None),
            }
        )
        if excerpt:
            blocks.append(f"[{label}] {it.filename} (id={it.id})\n{excerpt}")
        label_idx += 1

    for em in top_emails:
        label = f"S{label_idx}"
        subject = (em.subject or "(no subject)").strip()
        dt = em.date_sent.isoformat() if em.date_sent else None
        frm = (em.sender_email or em.sender_name or "Unknown").strip()
        to = ", ".join((em.recipients_to or [])[:6]) if em.recipients_to else ""
        body = em.body_text_clean or em.body_preview or em.body_text or ""
        excerpt = _select_best_excerpt(body, 1200, hints=purpose_hints)
        sources.append(
            {
                "label": label,
                "evidence_id": str(em.id),
                "filename": f"Email: {subject}",
                "document_date": dt,
                "evidence_type": "email",
            }
        )
        if excerpt:
            header = (
                f"[{label}] Email: {subject} (id={em.id}, date={dt or 'unknown'})"
                f"\nFrom: {frm}\nTo: {to or 'Unknown'}"
            )
            if em.has_attachments:
                header += "\nHas attachments: yes"
            blocks.append(f"{header}\n{excerpt}")
        label_idx += 1

    evidence_blocks_text = "\n\n".join(blocks) if blocks else "None"
    instruction_label = (
        f"{instruction_item.filename} (id={instruction_item.id})"
        if instruction_item
        else "None"
    )
    delay_event_lines: list[str] = []
    for ev in delay_events:
        planned = ev.planned_finish or ev.planned_start
        actual = ev.actual_finish or ev.actual_start
        delay_event_lines.append(
            "- "
            + " | ".join(
                [
                    (ev.activity_name or ev.description or "Delay event").strip(),
                    f"delay_days={ev.delay_days}" if ev.delay_days is not None else "",
                    f"cause={ev.delay_cause}" if ev.delay_cause else "",
                    f"planned={planned.isoformat()}" if planned else "",
                    f"actual={actual.isoformat()}" if actual else "",
                ]
            ).strip(" |")
        )
    delay_events_text = "\n".join(delay_event_lines) if delay_event_lines else "None"

    system_prompt = (
        "You are a senior construction disputes barrister's assistant. "
        "Use ONLY the facts provided. Do NOT invent. "
        "If information is missing, say 'Unknown' and add an open question."
    )
    prompt = f"""
Build a baseline “Purpose” plan and tracking pack for this project.

Return ONE JSON object with keys:
- summary_md: string (plain text; use headings + bullets; reference the purpose baseline)
- baseline: object with fields {{goal_statement, deliverables, issue_groupings, keywords, sources}}
- tracking: array of objects {{deliverable, status, evidence, gaps, sources}}
- chronology: array {{date, party, issue_tags, quote, source}}
- contradictions: array {{statement_a, statement_b, explanation, sources}}
- causation: array of objects {{cause, effect, explanation, confidence, sources}}
- evidence_organisation: object {{issue_groupings, keyword_map}}
- open_questions: array of strings
- sources: array of objects {{label, evidence_id, filename, document_date, evidence_type}}

Project:
- name: {project.project_name}
- code: {project.project_code}
- contract_type: {project.contract_type or "Unknown"}
- analysis_type: {project.analysis_type or "project"}
- contract_form: {project.contract_form or project.contract_form_custom or "Unknown"}

Purpose statement (authoritative if present):
{purpose_text or "None"}

Instruction baseline document:
{instruction_label}

Evidence + correspondence excerpts (cite sources like [S1], [S2]):
{evidence_blocks_text}

Delay events (structured, if available):
{delay_events_text}
""".strip()

    tool_name = "project_intel_pack"
    ai_text = await _complete_with_tool_fallback(
        tool_name=tool_name,
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        max_tokens=7000 if deep else 3200,
        temperature=0.2,
        task_type="project_intel_pack",
    )

    payload = _extract_json_object(ai_text) if ai_text else None
    if not payload:
        summary_lines = [
            f"Project: {project.project_name} ({project.project_code})",
            f"Purpose: {purpose_text or 'None'}",
            f"Instructions: {instruction_label}",
        ]
        if top_evidence:
            summary_lines.append(
                "Key evidence: "
                + ", ".join([e.filename for e in top_evidence if e.filename][:8])
            )
        payload = {
            "summary_md": "\n".join(summary_lines),
            "baseline": {"goal_statement": purpose_text or "", "deliverables": []},
            "tracking": [],
            "chronology": [],
            "contradictions": [],
            "causation": [],
            "evidence_organisation": {},
            "open_questions": [],
            "sources": sources,
        }
    elif isinstance(payload, dict) and "causation" not in payload:
        payload["causation"] = []

    # Missing document detection (best-effort)
    missing_documents: list[dict[str, Any]] = []
    try:
        from .evidence_linking import REFERENCE_PATTERNS

        def extract_refs(text: str | None) -> list[tuple[str, str]]:
            if not text:
                return []
            refs: list[tuple[str, str]] = []
            for pattern, ref_type in REFERENCE_PATTERNS:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        ref = f"{match[0]}-{match[1]}".upper()
                    else:
                        ref = str(match).upper()
                    refs.append((ref, ref_type))
            return refs

        mentioned: dict[str, str] = {}
        for it in evidence_pool:
            for ref, rtype in extract_refs(it.extracted_text or ""):
                mentioned.setdefault(ref, rtype)
        for em in email_pool:
            body = em.body_text_clean or em.body_preview or em.body_text or ""
            for ref, rtype in extract_refs(f"{em.subject or ''}\n{body}"):
                mentioned.setdefault(ref, rtype)

        present_refs: set[str] = set()
        for it in evidence_pool:
            present_refs.update({ref for ref, _ in extract_refs(it.filename or "")})

        for ref, rtype in list(mentioned.items())[:40]:
            if ref in present_refs:
                continue
            candidates = (
                db.query(EvidenceItem)
                .filter(EvidenceItem.filename.ilike(f"%{ref}%"))
                .limit(3)
                .all()
            )
            missing_documents.append(
                {
                    "reference": ref,
                    "type": rtype,
                    "candidates": [
                        {"id": str(c.id), "filename": c.filename} for c in candidates
                    ],
                }
            )
    except Exception:
        missing_documents = []

    if isinstance(payload, dict):
        payload["missing_documents"] = missing_documents
        payload["run_id"] = str(run_id)
        payload["run_started_at"] = run_started_at.isoformat()
        payload["run_completed_at"] = datetime.now(timezone.utc).isoformat()

    pack.summary_md = str(payload.get("summary_md") or payload.get("summary") or "")
    pack.data = payload
    pack.status = "ready"
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pack)
    try:
        snapshot = ProjectIntelPackSnapshot(
            id=uuid.uuid4(),
            project_id=project.id,
            run_id=run_id,
            status="ready",
            summary_md=pack.summary_md,
            data=payload,
        )
        db.add(snapshot)
        db.commit()
    except (ProgrammingError, OperationalError) as exc:
        db.rollback()
        if _is_missing_table_error(exc, "project_intel_pack_snapshots"):
            logger.warning("Project intel snapshot table missing; skipping snapshot.")
        else:
            raise
    return pack


async def _project_intel_refresh_job(
    project_id: str, force: bool, deep: bool
) -> None:
    db = SessionLocal()
    try:
        project_uuid = _parse_uuid(project_id, "project_id")
        project = db.query(Project).filter(Project.id == project_uuid).first()
        if not project:
            return
        await _build_project_intel_pack_snapshot(
            db=db, project=project, force=force, deep=deep
        )
    finally:
        db.close()


def _project_intel_orchestrate_job(
    project_id: str, payload: ProjectIntelBuildRequest
) -> None:
    import asyncio

    async def run() -> None:
        task_db = SessionLocal()
        try:
            project_uuid = _parse_uuid(project_id, "project_id")
            project = (
                task_db.query(Project).filter(Project.id == project_uuid).first()
            )
            if not project:
                return

            case_ids = [
                c.id
                for c in task_db.query(Case)
                .filter(Case.project_id == project.id)
                .all()
            ]

            if payload.rescan_keywords:
                try:
                    rescan_payload = KeywordRescanRequest(
                        mode="merge",
                        include_emails=True,
                        include_evidence=True,
                        max_emails=None,
                        max_evidence=None,
                    )
                    rescan_project_keywords(
                        project_id=str(project.id),
                        payload=rescan_payload,
                        db=task_db,
                        current_user=None,
                    )
                except Exception as exc:
                    logger.warning("Project intel rescan failed: %s", exc)

            if payload.link_evidence:
                try:
                    from .evidence_linking import process_evidence_batch

                    evidence_conds = [EvidenceItem.project_id == project.id]
                    if case_ids:
                        evidence_conds.append(EvidenceItem.case_id.in_(case_ids))

                    evidence_ids = [
                        e.id
                        for e in task_db.query(EvidenceItem)
                        .filter(or_(*evidence_conds))
                        .order_by(desc(EvidenceItem.created_at))
                        .limit(payload.max_evidence)
                        .all()
                    ]
                    if evidence_ids:
                        user_id = (
                            project.owner_user_id
                            if getattr(project, "owner_user_id", None)
                            else _get_default_owner_user_id(task_db)
                        )
                        process_evidence_batch(
                            task_db, evidence_ids, user_id=user_id, auto_link=True
                        )
                except Exception as exc:
                    logger.warning("Project intel linking failed: %s", exc)

            if payload.refresh_intel:
                await _build_project_intel_pack_snapshot(
                    db=task_db,
                    project=project,
                    force=True,
                    deep=payload.deep,
                )
        finally:
            task_db.close()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


@router.get("/projects/{project_id}/intel")
def get_project_intel_pack(
    project_id: str,
    db: DbDep,
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        pack = (
            db.query(ProjectIntelPack)
            .filter(ProjectIntelPack.project_id == project.id)
            .first()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_packs"):
            _raise_missing_migration("project_intel_packs")
        raise

    if not pack:
        return {
            "project_id": str(project.id),
            "status": "empty",
            "purpose_text": "",
            "instructions_evidence_id": None,
            "instructions_filename": None,
            "summary": "",
            "data": {},
            "sources": [],
            "updated_at": None,
        }

    instructions_filename = None
    if pack.instructions_evidence_id:
        item = (
            db.query(EvidenceItem)
            .filter(EvidenceItem.id == pack.instructions_evidence_id)
            .first()
        )
        if item:
            instructions_filename = item.filename

    data = pack.data or {}
    sources = data.get("sources", []) if isinstance(data, dict) else []

    return {
        "project_id": str(project.id),
        "status": pack.status,
        "purpose_text": pack.purpose_text or "",
        "instructions_evidence_id": (
            str(pack.instructions_evidence_id) if pack.instructions_evidence_id else None
        ),
        "instructions_filename": instructions_filename,
        "summary": pack.summary_md or "",
        "data": data,
        "sources": sources if isinstance(sources, list) else [],
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else None,
        "last_error": pack.last_error,
    }


@router.post("/projects/{project_id}/intel/config")
def save_project_intel_config(
    project_id: str,
    payload: ProjectIntelConfigRequest,
    db: DbDep,
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        pack = (
            db.query(ProjectIntelPack)
            .filter(ProjectIntelPack.project_id == project.id)
            .first()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_packs"):
            _raise_missing_migration("project_intel_packs")
        raise

    if not pack:
        pack = ProjectIntelPack(project_id=project.id, status="empty")
        db.add(pack)
        db.commit()
        db.refresh(pack)

    cases = db.query(Case).filter(Case.project_id == project.id).all()
    case_ids = [c.id for c in cases]

    instruction_item = _get_project_scoped_evidence(
        db,
        project=project,
        evidence_id=payload.instructions_evidence_id,
        case_ids=case_ids,
    )
    if payload.instructions_evidence_id and not instruction_item:
        raise HTTPException(status_code=404, detail="Instruction document not found")

    pack.purpose_text = (payload.purpose_text or "").strip() or None
    pack.instructions_evidence_id = instruction_item.id if instruction_item else None
    pack.status = "empty"
    pack.last_error = None
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pack)

    return {
        "project_id": str(project.id),
        "status": pack.status,
        "purpose_text": pack.purpose_text or "",
        "instructions_evidence_id": (
            str(pack.instructions_evidence_id) if pack.instructions_evidence_id else None
        ),
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else None,
    }


@router.post("/projects/{project_id}/intel/refresh")
def refresh_project_intel_pack(
    project_id: str,
    payload: ProjectIntelRefreshRequest,
    background_tasks: BackgroundTasks,
    db: DbDep,
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        pack = (
            db.query(ProjectIntelPack)
            .filter(ProjectIntelPack.project_id == project.id)
            .first()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_packs"):
            _raise_missing_migration("project_intel_packs")
        raise

    if not pack:
        pack = ProjectIntelPack(project_id=project.id, status="empty")
        db.add(pack)
        db.commit()
        db.refresh(pack)

    pack.status = "building"
    pack.last_error = None
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pack)

    background_tasks.add_task(
        _project_intel_refresh_job,
        str(project.id),
        bool(payload.force),
        bool(payload.deep),
    )

    return {
        "project_id": str(project.id),
        "status": pack.status,
        "summary": pack.summary_md or "",
        "purpose_text": pack.purpose_text or "",
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else None,
    }


@router.post("/projects/{project_id}/intel/ask")
async def ask_project_intel_pack(
    project_id: str,
    payload: ProjectIntelAskRequest,
    db: DbDep,
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    try:
        pack = (
            db.query(ProjectIntelPack)
            .filter(ProjectIntelPack.project_id == project.id)
            .first()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_packs"):
            _raise_missing_migration("project_intel_packs")
        raise

    purpose_text = (pack.purpose_text if pack else None) or ""
    purpose_summary = (pack.summary_md if pack else None) or ""

    cases = db.query(Case).filter(Case.project_id == project.id).all()
    case_ids = [c.id for c in cases]

    instruction_item = _get_project_scoped_evidence(
        db,
        project=project,
        evidence_id=(
            str(pack.instructions_evidence_id)
            if pack and pack.instructions_evidence_id
            else None
        ),
        case_ids=case_ids,
    )

    pool_conds = [EvidenceItem.project_id == project.id]
    if case_ids:
        pool_conds.append(EvidenceItem.case_id.in_(case_ids))
    if project.workspace_id:
        pool_conds.append(
            EvidenceItem.meta.op("->>")("workspace_id") == str(project.workspace_id)
        )

    pool = (
        db.query(EvidenceItem)
        .filter(or_(*pool_conds))
        .order_by(desc(EvidenceItem.created_at))
        .limit(200)
        .all()
    )
    if instruction_item and all(it.id != instruction_item.id for it in pool):
        pool.insert(0, instruction_item)

    email_pool = []
    email_conds = [EmailMessage.project_id == project.id]
    if case_ids:
        email_conds.append(EmailMessage.case_id.in_(case_ids))
    if email_conds:
        email_pool = (
            db.query(EmailMessage)
            .filter(or_(*email_conds))
            .filter(EmailMessage.is_duplicate.is_(False))
            .filter(EmailMessage.is_inclusive.is_(True))
            .order_by(
                desc(EmailMessage.date_sent).nullslast(),
                desc(EmailMessage.created_at),
            )
            .limit(220)
            .all()
        )

    tokens = re.findall(r"[a-zA-Z0-9]{3,}", question.lower())[:14]
    purpose_hints = [
        "instruction",
        "instructions",
        "scope",
        "deliverable",
        "chronology",
        "contradiction",
        "responsibility",
        "inspection",
        "design",
        "causation",
        "delay",
    ]
    purpose_hints.extend(_hint_tokens(purpose_text))
    purpose_hints = list(dict.fromkeys([h for h in purpose_hints if h]))
    excerpt_hints = list(dict.fromkeys(tokens + purpose_hints))

    def score_item(it: EvidenceItem) -> int:
        hay = f"{it.filename} {it.title or ''} {(_safe_excerpt(it.extracted_text, 6000))}".lower()
        score = 0
        for t in tokens:
            if t in hay:
                score += 2
                score += min(hay.count(t), 4)
        return score

    ranked = sorted(pool, key=score_item, reverse=True)
    top = [it for it in ranked if score_item(it) > 0][:6]
    if not top:
        top = ranked[:4]

    def score_email(em: EmailMessage) -> int:
        subj = em.subject or ""
        body = em.body_text_clean or em.body_preview or em.body_text or ""
        hay = (
            f"{subj} {em.sender_email or ''} {em.sender_name or ''} {_safe_excerpt(body, 6000)}"
        ).lower()
        score = 0
        for t in tokens:
            if t in hay:
                score += 2
                score += min(hay.count(t), 3)
        return score

    ranked_emails = sorted(email_pool, key=score_email, reverse=True)
    top_emails = [em for em in ranked_emails if score_email(em) > 0][:3]
    if not top_emails and email_pool:
        top_emails = email_pool[:2]

    sources: list[dict[str, Any]] = []
    blocks: list[str] = []
    label_idx = 1
    if instruction_item:
        excerpt = _select_best_excerpt(
            instruction_item.extracted_text,
            1400,
            hints=excerpt_hints,
        ) or _select_best_excerpt(
            (
                (instruction_item.extracted_metadata or {}).get("text_preview")
                if isinstance(instruction_item.extracted_metadata, dict)
                else ""
            ),
            1400,
            hints=excerpt_hints,
        )
        sources.append(
            {
                "label": f"S{label_idx}",
                "id": str(instruction_item.id),
                "filename": instruction_item.filename,
            }
        )
        if excerpt:
            blocks.append(
                f"[S{label_idx}] {instruction_item.filename} (id={instruction_item.id})\n{excerpt}"
            )
        label_idx += 1

    for it in top:
        label = f"S{label_idx}"
        excerpt = _select_best_excerpt(it.extracted_text, 1000, hints=excerpt_hints)
        sources.append(
            {
                "label": label,
                "id": str(it.id),
                "filename": it.filename,
            }
        )
        if excerpt:
            blocks.append(f"[{label}] {it.filename} (id={it.id})\n{excerpt}")
        label_idx += 1

    for em in top_emails:
        label = f"S{label_idx}"
        subject = (em.subject or "(no subject)").strip()
        dt = em.date_sent.isoformat() if em.date_sent else None
        frm = (em.sender_email or em.sender_name or "Unknown").strip()
        to = ", ".join((em.recipients_to or [])[:6]) if em.recipients_to else ""
        body = em.body_text_clean or em.body_preview or em.body_text or ""
        excerpt = _select_best_excerpt(body, 900, hints=excerpt_hints)
        sources.append(
            {
                "label": label,
                "id": str(em.id),
                "filename": f"Email: {subject}",
            }
        )
        if excerpt:
            header = (
                f"[{label}] Email: {subject} (id={em.id}, date={dt or 'unknown'})"
                f"\nFrom: {frm}\nTo: {to or 'Unknown'}"
            )
            if em.has_attachments:
                header += "\nHas attachments: yes"
            blocks.append(f"{header}\n{excerpt}")
        label_idx += 1

    evidence_blocks_text = "\n\n".join(blocks) if blocks else "None"

    system_prompt = (
        "You are a senior construction disputes barrister's assistant. "
        "Use ONLY the facts provided. Do NOT invent. "
        "If information is missing, say 'Unknown' and add an open question."
    )
    prompt = f"""
Answer the question about this project.

Project:
- name: {project.project_name}
- code: {project.project_code}
- contract_type: {project.contract_type or "Unknown"}

Purpose statement (authoritative if present):
{purpose_text or "None"}

Cached project intel summary:
{purpose_summary or "None"}

Evidence + correspondence excerpts (cite sources like [S1], [S2]):
{evidence_blocks_text}

Question:
{question}
""".strip()

    ai_text = await _complete_with_tool_fallback(
        tool_name="project_intel_pack",
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        max_tokens=1600,
        temperature=0.2,
        task_type="project_intel_pack",
    )

    answer = (ai_text or "").strip()
    if not answer:
        answer = (
            "AI provider unavailable. I can’t answer reliably yet; please upload key "
            "documents (contract, key correspondence, notices, schedules, valuations)."
        )

    return {"answer": answer, "sources": sources}


@router.post("/projects/{project_id}/intel/build")
def build_project_intel_pack(
    project_id: str,
    payload: ProjectIntelBuildRequest,
    background_tasks: BackgroundTasks,
    db: DbDep,
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Mark pack as building if we're refreshing
    if payload.refresh_intel:
        pack = _ensure_project_intel_pack(db, project)
        pack.status = "building"
        pack.last_error = None
        pack.updated_at = datetime.now(timezone.utc)
        db.commit()

    background_tasks.add_task(
        _project_intel_orchestrate_job,
        str(project.id),
        payload,
    )

    return {
        "status": "queued",
        "project_id": str(project.id),
        "rescan_keywords": payload.rescan_keywords,
        "link_evidence": payload.link_evidence,
        "refresh_intel": payload.refresh_intel,
        "deep": payload.deep,
    }


@router.get("/projects/{project_id}/intel/snapshots")
def list_project_intel_snapshots(project_id: str, db: DbDep) -> list[dict[str, Any]]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        snapshots = (
            db.query(ProjectIntelPackSnapshot)
            .filter(ProjectIntelPackSnapshot.project_id == project.id)
            .order_by(desc(ProjectIntelPackSnapshot.created_at))
            .limit(50)
            .all()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_pack_snapshots"):
            _raise_missing_migration("project_intel_pack_snapshots")
        raise
    return [
        {
            "id": str(s.id),
            "run_id": str(s.run_id),
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]


@router.get("/projects/{project_id}/intel/snapshots/{snapshot_id}")
def get_project_intel_snapshot(
    project_id: str, snapshot_id: str, db: DbDep
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    snap_uuid = _parse_uuid(snapshot_id, "snapshot_id")
    try:
        snapshot = (
            db.query(ProjectIntelPackSnapshot)
            .filter(
                ProjectIntelPackSnapshot.id == snap_uuid,
                ProjectIntelPackSnapshot.project_id == project.id,
            )
            .first()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_pack_snapshots"):
            _raise_missing_migration("project_intel_pack_snapshots")
        raise
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return {
        "project_id": str(project.id),
        "snapshot_id": str(snapshot.id),
        "run_id": str(snapshot.run_id),
        "status": snapshot.status,
        "summary": snapshot.summary_md or "",
        "data": snapshot.data or {},
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


@router.get("/projects/{project_id}/intel/export")
def export_project_intel(
    project_id: str, snapshot_id: str | None = None, db: DbDep
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    snapshot = None
    try:
        if snapshot_id:
            snap_uuid = _parse_uuid(snapshot_id, "snapshot_id")
            snapshot = (
                db.query(ProjectIntelPackSnapshot)
                .filter(
                    ProjectIntelPackSnapshot.id == snap_uuid,
                    ProjectIntelPackSnapshot.project_id == project.id,
                )
                .first()
            )
        else:
            snapshot = (
                db.query(ProjectIntelPackSnapshot)
                .filter(ProjectIntelPackSnapshot.project_id == project.id)
                .order_by(desc(ProjectIntelPackSnapshot.created_at))
                .first()
            )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_pack_snapshots"):
            _raise_missing_migration("project_intel_pack_snapshots")
        raise

    if snapshot:
        return {
            "project_id": str(project.id),
            "run_id": str(snapshot.run_id),
            "snapshot_id": str(snapshot.id),
            "summary": snapshot.summary_md or "",
            "data": snapshot.data or {},
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        }

    pack = (
        db.query(ProjectIntelPack)
        .filter(ProjectIntelPack.project_id == project.id)
        .first()
    )
    if not pack:
        raise HTTPException(status_code=404, detail="No intel pack found to export")

    data = pack.data or {}
    return {
        "project_id": str(project.id),
        "run_id": data.get("run_id"),
        "snapshot_id": None,
        "summary": pack.summary_md or "",
        "data": data,
        "created_at": pack.updated_at.isoformat() if pack.updated_at else None,
    }


def _ensure_project_intel_pack(db: Session, project: Project) -> ProjectIntelPack:
    try:
        pack = (
            db.query(ProjectIntelPack)
            .filter(ProjectIntelPack.project_id == project.id)
            .first()
        )
    except (ProgrammingError, OperationalError) as exc:
        if _is_missing_table_error(exc, "project_intel_packs"):
            _raise_missing_migration("project_intel_packs")
        raise
    if not pack:
        pack = ProjectIntelPack(project_id=project.id, status="empty")
        db.add(pack)
        db.commit()
        db.refresh(pack)
    if not isinstance(pack.data, dict):
        pack.data = {}
    return pack


@router.get("/projects/{project_id}/intel/claims")
def list_claim_nodes_links(project_id: str, db: DbDep) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pack = _ensure_project_intel_pack(db, project)
    data = pack.data or {}
    nodes = data.get("claim_nodes", [])
    links = data.get("claim_links", [])
    return {"nodes": nodes if isinstance(nodes, list) else [], "links": links if isinstance(links, list) else []}


@router.post("/projects/{project_id}/intel/claims/nodes")
def create_claim_node(
    project_id: str, payload: ClaimNodeCreate, db: DbDep
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pack = _ensure_project_intel_pack(db, project)
    data = pack.data or {}
    nodes = data.get("claim_nodes", [])
    if not isinstance(nodes, list):
        nodes = []

    node = {
        "id": str(uuid.uuid4()),
        "title": payload.title.strip(),
        "description": (payload.description or "").strip() or None,
        "node_type": (payload.node_type or "").strip() or None,
        "tags": payload.tags or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    nodes.append(node)
    data["claim_nodes"] = nodes
    if "claim_links" not in data:
        data["claim_links"] = []
    pack.data = data
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()

    return node


@router.put("/projects/{project_id}/intel/claims/nodes/{node_id}")
def update_claim_node(
    project_id: str, node_id: str, payload: ClaimNodeUpdate, db: DbDep
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pack = _ensure_project_intel_pack(db, project)
    data = pack.data or {}
    nodes = data.get("claim_nodes", [])
    if not isinstance(nodes, list):
        nodes = []

    target = None
    for node in nodes:
        if node.get("id") == node_id:
            target = node
            break
    if not target:
        raise HTTPException(status_code=404, detail="Claim node not found")

    if payload.title is not None:
        target["title"] = payload.title.strip()
    if payload.description is not None:
        target["description"] = payload.description.strip() or None
    if payload.node_type is not None:
        target["node_type"] = payload.node_type.strip() or None
    if payload.tags is not None:
        target["tags"] = payload.tags
    target["updated_at"] = datetime.now(timezone.utc).isoformat()

    data["claim_nodes"] = nodes
    pack.data = data
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()

    return target


@router.delete("/projects/{project_id}/intel/claims/nodes/{node_id}")
def delete_claim_node(project_id: str, node_id: str, db: DbDep) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pack = _ensure_project_intel_pack(db, project)
    data = pack.data or {}
    nodes = data.get("claim_nodes", [])
    links = data.get("claim_links", [])
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(links, list):
        links = []

    new_nodes = [n for n in nodes if n.get("id") != node_id]
    if len(new_nodes) == len(nodes):
        raise HTTPException(status_code=404, detail="Claim node not found")
    new_links = [l for l in links if l.get("node_id") != node_id]

    data["claim_nodes"] = new_nodes
    data["claim_links"] = new_links
    pack.data = data
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"status": "deleted", "node_id": node_id}


@router.post("/projects/{project_id}/intel/claims/links")
def create_claim_link(
    project_id: str, payload: ClaimLinkCreate, db: DbDep
) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pack = _ensure_project_intel_pack(db, project)
    data = pack.data or {}
    nodes = data.get("claim_nodes", [])
    links = data.get("claim_links", [])
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(links, list):
        links = []

    if not any(n.get("id") == payload.node_id for n in nodes):
        raise HTTPException(status_code=404, detail="Claim node not found")

    link = {
        "id": str(uuid.uuid4()),
        "node_id": payload.node_id,
        "item_type": payload.item_type.strip().lower(),
        "item_id": payload.item_id.strip(),
        "link_type": (payload.link_type or "supports").strip().lower(),
        "notes": (payload.notes or "").strip() or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    links.append(link)
    data["claim_links"] = links
    data["claim_nodes"] = nodes
    pack.data = data
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()

    return link


@router.delete("/projects/{project_id}/intel/claims/links/{link_id}")
def delete_claim_link(project_id: str, link_id: str, db: DbDep) -> dict[str, Any]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pack = _ensure_project_intel_pack(db, project)
    data = pack.data or {}
    links = data.get("claim_links", [])
    if not isinstance(links, list):
        links = []

    new_links = [l for l in links if l.get("id") != link_id]
    if len(new_links) == len(links):
        raise HTTPException(status_code=404, detail="Claim link not found")

    data["claim_links"] = new_links
    pack.data = data
    pack.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"status": "deleted", "link_id": link_id}


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
        if hasattr(Case, "position"):
            case.position = case_data.position
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


@router.post("/cases/{case_id}/keywords/rescan")
def rescan_case_keywords(
    case_id: str,
    payload: KeywordRescanRequest,
    db: DbDep,
    current_user: User | None = Depends(get_optional_current_user),
) -> dict[str, Any]:
    """Rescan correspondence + evidence and allocate keyword matches.

    Uses Keyword rules stored for the Case, plus linked Project-level defaults
    (where Keyword.case_id is NULL) when the case belongs to a project.
    """

    try:
        case_uuid = uuid.UUID(str(case_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid case ID format") from exc

    case = db.query(Case).filter(Case.id == case_uuid).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    linked_project_uuid = getattr(case, "project_id", None)

    mode = (payload.mode or "merge").strip().lower()
    if mode not in ("merge", "overwrite"):
        raise HTTPException(status_code=400, detail="Invalid mode (merge|overwrite)")

    kw_query = db.query(Keyword)
    if linked_project_uuid is not None:
        kw_query = kw_query.filter(
            or_(
                Keyword.case_id == case_uuid,
                (Keyword.project_id == linked_project_uuid)
                & (Keyword.case_id.is_(None)),
            )
        )
    else:
        kw_query = kw_query.filter(Keyword.case_id == case_uuid)

    keywords = kw_query.order_by(Keyword.keyword_name.asc()).all()
    matcher = _KeywordMatcher(keywords)
    if not matcher.names_by_id:
        return {
            "status": "success",
            "case_id": str(case_uuid),
            "project_id": str(linked_project_uuid) if linked_project_uuid else None,
            "keywords": 0,
            "emails_scanned": 0,
            "emails_updated": 0,
            "evidence_scanned": 0,
            "evidence_updated": 0,
            "message": "No keywords configured for this case (or linked project).",
        }

    emails_scanned = 0
    emails_updated = 0
    evidence_scanned = 0
    evidence_updated = 0

    # Correspondence
    if payload.include_emails:
        q = db.query(EmailMessage)
        if linked_project_uuid is not None:
            q = q.filter(
                or_(
                    EmailMessage.case_id == case_uuid,
                    EmailMessage.project_id == linked_project_uuid,
                )
            )
        else:
            q = q.filter(EmailMessage.case_id == case_uuid)

        max_emails = int(payload.max_emails or 0)
        if max_emails > 0:
            q = q.order_by(EmailMessage.created_at.desc()).limit(max_emails)
        emails = q.all()

        for e in emails:
            emails_scanned += 1
            body = (
                e.body_text_clean
                or e.body_text
                or e.body_preview
                or (re.sub(r"<[^>]+>", " ", e.body_html or "") if e.body_html else "")
            )
            new_ids = matcher.match_keyword_ids(e.subject, body)
            if not new_ids:
                continue
            existing = (
                e.matched_keywords if isinstance(e.matched_keywords, list) else []
            )
            if mode == "overwrite":
                merged = _unique_strings(new_ids)
            else:
                merged = _unique_strings([*existing, *new_ids])
            if merged != existing:
                e.matched_keywords = merged
                emails_updated += 1

    # Evidence
    if payload.include_evidence:
        q = db.query(EvidenceItem)
        if linked_project_uuid is not None:
            q = q.filter(
                or_(
                    EvidenceItem.case_id == case_uuid,
                    EvidenceItem.project_id == linked_project_uuid,
                )
            )
        else:
            q = q.filter(EvidenceItem.case_id == case_uuid)

        max_evidence = int(payload.max_evidence or 0)
        if max_evidence > 0:
            q = q.order_by(EvidenceItem.created_at.desc()).limit(max_evidence)
        items = q.all()

        for it in items:
            evidence_scanned += 1
            extracted = it.extracted_text or ""
            if len(extracted) > 200000:
                extracted = extracted[:200000]
            blob = "\n".join(
                [
                    str(it.filename or ""),
                    str(it.title or ""),
                    str(it.description or ""),
                    extracted,
                ]
            )
            new_ids = matcher.match_keyword_ids(it.filename, blob)
            if not new_ids:
                continue

            existing_ids = (
                it.keywords_matched if isinstance(it.keywords_matched, list) else []
            )
            if mode == "overwrite":
                merged_ids = _unique_strings(new_ids)
            else:
                merged_ids = _unique_strings([*existing_ids, *new_ids])
            changed = merged_ids != existing_ids
            if changed:
                it.keywords_matched = merged_ids

            auto = it.auto_tags if isinstance(it.auto_tags, list) else []
            name_tags = [matcher.names_by_id.get(kid, "") for kid in new_ids]
            name_tags = [t for t in name_tags if t]
            merged_auto = _unique_strings([*auto, *name_tags])
            if merged_auto != auto:
                it.auto_tags = merged_auto
                changed = True

            if changed:
                evidence_updated += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    actor_id = str(current_user.id) if current_user else None
    logger.info(
        "Keyword rescan complete (case_id=%s project_id=%s actor_id=%s): emails_updated=%s evidence_updated=%s",
        case_uuid,
        linked_project_uuid,
        actor_id,
        emails_updated,
        evidence_updated,
    )

    return {
        "status": "success",
        "case_id": str(case_uuid),
        "project_id": str(linked_project_uuid) if linked_project_uuid else None,
        "keywords": len(matcher.names_by_id),
        "emails_scanned": emails_scanned,
        "emails_updated": emails_updated,
        "evidence_scanned": evidence_scanned,
        "evidence_updated": evidence_updated,
        "mode": mode,
    }
