"""
Workspaces API
Manages workspace entities that group Projects and Cases together
"""

from __future__ import annotations

import logging
import uuid
import json
import re
from datetime import timezone
from datetime import datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    BackgroundTasks,
    Form,
    Query,
)
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc

from .db import get_db
from .db import SessionLocal
from .config import settings
from .aws_services import get_aws_services
from .storage import put_object, presign_get, delete_object
from .evidence.utils import compute_file_hash, get_file_type, log_activity
from .ai_runtime import complete_chat
from .ai_settings import get_tool_config
from .models import (
    Workspace,
    WorkspaceAbout,
    WorkspacePurpose,
    WorkspaceKeyword,
    WorkspaceTeamMember,
    WorkspaceKeyDate,
    Project,
    Case,
    User,
    UserRole,
    Stakeholder,
    EvidenceItem,
    Folder,
)
from .security import current_user

try:
    from .enhanced_evidence_processor import enhanced_processor
except Exception:  # pragma: no cover
    enhanced_processor = None  # type: ignore

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


def _is_admin(user: User) -> bool:
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    return str(role_val).upper() == UserRole.ADMIN.value


def _require_workspace(db: Session, workspace_id: str, user: User) -> Workspace:
    workspace_uuid = _parse_uuid(workspace_id, "workspace_id")
    workspace = db.query(Workspace).filter(Workspace.id == workspace_uuid).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace.owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Access denied")
    return workspace


def _require_project(db: Session, project_id: str, user: User) -> Project:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    owner_id = getattr(project, "owner_user_id", None)
    if owner_id is not None and owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Access denied")
    if owner_id is None and not _is_admin(user):
        # Legacy data without owner tracking: allow admin only.
        raise HTTPException(status_code=403, detail="Access denied")

    return project


# Pydantic models
class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    contract_type: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    contract_type: str | None = None
    status: str | None = None


class KeywordCreate(BaseModel):
    keyword_name: str = Field(..., min_length=1, max_length=255)
    definition: str | None = None
    variations: str | None = None
    is_regex: bool | None = False


class TeamMemberCreate(BaseModel):
    user_id: str | None = None
    role: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=512)
    email: str | None = None
    organization: str | None = None


class TeamMemberAddRequest(BaseModel):
    """Add an existing system user to a workspace's team list.

    Note: This does not create/invite users; the email must already exist.
    """

    email: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="member", min_length=1, max_length=255)


class KeyDateCreate(BaseModel):
    date_type: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=255)
    date_value: datetime
    description: str | None = None


class AboutRefreshRequest(BaseModel):
    force: bool = False


class AboutAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class AboutNotesRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=10000)


class PurposeConfigRequest(BaseModel):
    purpose_text: str | None = Field(default=None, max_length=12000)
    instructions_evidence_id: str | None = Field(default=None)


class PurposeRefreshRequest(BaseModel):
    force: bool = False
    deep: bool = False


class PurposeAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class WorkspaceDocumentFolderCreate(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)


class WorkspaceDocumentMoveRequest(BaseModel):
    folder_path: str | None = Field(default=None, max_length=512)


class WorkspaceDocumentAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


def _workspace_docs_query(db: Session, workspace_uuid: uuid.UUID):
    # Workspace documents are stored as EvidenceItems with a scoped meta marker.
    return db.query(EvidenceItem).filter(
        EvidenceItem.meta.op("->>")("workspace_id") == str(workspace_uuid)
    )


def _get_workspace_scoped_evidence(
    db: Session,
    *,
    workspace: Workspace,
    evidence_id: str | None,
    project_ids: list[uuid.UUID] | None = None,
    case_ids: list[uuid.UUID] | None = None,
) -> EvidenceItem | None:
    if not evidence_id:
        return None
    ev_uuid = _parse_uuid(evidence_id, "instructions_evidence_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == ev_uuid).first()
    if not item:
        return None
    if (item.meta or {}).get("workspace_id") == str(workspace.id):  # type: ignore[union-attr]
        return item
    if project_ids and item.project_id in project_ids:
        return item
    if case_ids and item.case_id in case_ids:
        return item
    return None


def _normalize_workspace_doc_folder_path(value: str | None) -> str | None:
    """Normalize and validate a workspace document folder path.

    Folder paths are stored relative to the workspace root, e.g.:
    - "Contracts"
    - "Contracts/JCT"
    - "Expert Reports/Quantum"
    """

    if value is None:
        return None
    path = str(value).strip()
    if not path:
        return None

    # Normalize separators and strip leading/trailing slashes
    path = path.strip().strip("/")
    if not path:
        return None

    # Block traversal / oddities
    if ".." in path or path.startswith("/") or "\\" in path:
        raise HTTPException(status_code=400, detail="Invalid folder_path")

    # Disallow obvious filesystem-forbidden chars (Windows-safe)
    invalid_chars = ["<", ">", ":", '"', "|", "?", "*"]
    if any(ch in path for ch in invalid_chars):
        raise HTTPException(status_code=400, detail="Invalid folder_path")

    parts = [p.strip() for p in path.split("/") if p.strip()]
    if not parts:
        return None
    if len(parts) > 20:
        raise HTTPException(status_code=400, detail="Invalid folder_path (too deep)")

    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
    for part in parts:
        if part.upper() in reserved:
            raise HTTPException(status_code=400, detail="Invalid folder_path")

    normalized = "/".join(parts)
    if len(normalized) > 512:
        raise HTTPException(status_code=400, detail="Invalid folder_path (too long)")
    return normalized


def _workspace_doc_folder_db_prefix(workspace: Workspace) -> str:
    # Namespace workspace folders in the shared Folder table to allow empty folders.
    # Do NOT use slashes at the ends; caller appends "/<relative_path>".
    return f"workspace-docs/{workspace.id}"


def _ensure_workspace_doc_folders(db: Session, workspace: Workspace, folder_path: str) -> None:
    """Ensure Folder rows exist for each segment of folder_path for this workspace.

    This lets the UI show empty folders and not only folders implied by docs.
    """

    folder_path = _normalize_workspace_doc_folder_path(folder_path) or ""
    if not folder_path:
        return

    prefix = _workspace_doc_folder_db_prefix(workspace)
    owner_id = workspace.owner_id

    parts = folder_path.split("/")
    for i in range(1, len(parts) + 1):
        rel = "/".join(parts[:i])
        db_path = f"{prefix}/{rel}"
        parent_rel = "/".join(parts[: i - 1]) if i > 1 else ""
        parent_db_path = f"{prefix}/{parent_rel}" if parent_rel else None

        existing = (
            db.query(Folder)
            .filter(Folder.owner_user_id == owner_id, Folder.path == db_path)
            .first()
        )
        if existing:
            continue
        folder = Folder(
            path=db_path,
            name=parts[i - 1],
            parent_path=parent_db_path,
            owner_user_id=owner_id,
        )
        db.add(folder)


def _safe_excerpt(text: str | None, limit: int = 1800) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= limit:
        return t
    return t[:limit].rstrip() + "…"


def _hint_tokens(text: str | None, max_tokens: int = 18) -> list[str]:
    if not text:
        return []
    tokens = re.findall(r"[a-zA-Z0-9]{4,}", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_tokens:
            break
    return out


def _select_best_excerpt(
    text: str | None, limit: int = 1800, hints: list[str] | None = None
) -> str:
    """Pick the most relevant chunk rather than a naive prefix."""
    t = (text or "").strip()
    if not t:
        return ""
    if len(t) <= limit:
        return t

    chunk_size = min(max(800, limit), 1600)
    overlap = 200
    lower_hints = [h.lower() for h in (hints or []) if h]

    def score_chunk(chunk: str) -> int:
        if not lower_hints:
            return 0
        hay = chunk.lower()
        score = 0
        for h in lower_hints:
            if h in hay:
                score += 2
                score += min(hay.count(h), 3)
        return score

    chunks: list[tuple[int, str]] = []
    start = 0
    while start < len(t):
        end = min(len(t), start + chunk_size)
        chunk = t[start:end]
        chunks.append((score_chunk(chunk), chunk))
        if end == len(t):
            break
        start = max(0, end - overlap)

    chunks.sort(key=lambda x: x[0], reverse=True)
    best = chunks[0][1] if chunks else t[:limit]
    return _safe_excerpt(best, limit)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # Prefer fenced json blocks
    m = re.search(r"```json\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    candidate = m.group(1).strip() if m else ""
    if not candidate:
        # Best-effort: first { ... last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1].strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


async def _complete_with_tool_fallback(
    *,
    tool_name: str,
    prompt: str,
    system_prompt: str,
    db: Session,
    task_type: str = "workspace_about",
    max_tokens: int = 2200,
    temperature: float = 0.2,
) -> str:
    cfg = get_tool_config(tool_name, db) or get_tool_config("basic_chat", db) or {}
    provider = str(cfg.get("provider", "gemini"))
    model = str(cfg.get("model") or "")
    fallback_chain = cfg.get("fallback_chain") or []

    async def _try(p: str, m: str) -> str:
        return await complete_chat(
            provider=p,
            model_id=m,
            prompt=prompt,
            system_prompt=system_prompt,
            db=db,
            max_tokens=max_tokens,
            temperature=temperature,
            function_name=tool_name,
            task_type=task_type,
        )

    # First attempt: configured provider/model
    if model:
        try:
            return await _try(provider, model)
        except Exception:
            pass

    # Fallback chain: list of tuples like ("bedrock", "amazon.nova-lite-v1:0")
    for entry in fallback_chain:
        try:
            p = str(entry[0])
            m = str(entry[1])
            if not m:
                continue
            return await _try(p, m)
        except Exception:
            continue

    # Final: deterministic fallback (no external AI)
    return ""


async def _build_workspace_about_snapshot(
    *,
    db: Session,
    workspace: Workspace,
    force: bool = False,
    deep: bool = False,
) -> WorkspaceAbout:
    about = (
        db.query(WorkspaceAbout)
        .filter(WorkspaceAbout.workspace_id == workspace.id)
        .first()
    )
    if not about:
        about = WorkspaceAbout(workspace_id=workspace.id, status="empty")
        db.add(about)
        db.commit()
        db.refresh(about)

    # If not forcing and we already have a ready summary, keep it unless new docs exist.
    latest_doc = (
        _workspace_docs_query(db, workspace.id)
        .order_by(desc(EvidenceItem.created_at))
        .first()
    )
    latest_doc_at = getattr(latest_doc, "created_at", None)
    if (
        not force
        and (about.status or "").lower() == "ready"
        and about.updated_at
        and latest_doc_at
        and about.updated_at >= latest_doc_at
    ):
        return about

    about.status = "building"
    about.last_error = None
    db.commit()

    # Aggregate core workspace context
    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()
    cases = db.query(Case).filter(Case.workspace_id == workspace.id).all()

    # Pull workspace-scoped evidence, plus related project/case evidence (bounded).
    project_ids = [p.id for p in projects]
    case_ids = [c.id for c in cases]

    # Purpose baseline (if configured) to prioritize instruction PDFs in About.
    purpose = (
        db.query(WorkspacePurpose)
        .filter(WorkspacePurpose.workspace_id == workspace.id)
        .first()
    )
    purpose_text = (purpose.purpose_text or "") if purpose else ""
    instruction_item = _get_workspace_scoped_evidence(
        db,
        workspace=workspace,
        evidence_id=str(purpose.instructions_evidence_id)
        if purpose and purpose.instructions_evidence_id
        else None,
        project_ids=project_ids,
        case_ids=case_ids,
    )

    evidence_conds = [
        EvidenceItem.meta.op("->>")("workspace_id") == str(workspace.id),
    ]
    if project_ids:
        evidence_conds.append(EvidenceItem.project_id.in_(project_ids))
    if case_ids:
        evidence_conds.append(EvidenceItem.case_id.in_(case_ids))

    evidence_query = db.query(EvidenceItem).filter(or_(*evidence_conds))
    # Pull a bounded pool, then rank for "read-in" usefulness (not just recency).
    evidence_pool = (
        evidence_query.order_by(desc(EvidenceItem.created_at))
        .limit(240 if deep else 160)
        .all()
    )
    if instruction_item and all(it.id != instruction_item.id for it in evidence_pool):
        evidence_pool.insert(0, instruction_item)

    # Identify contract documents uploaded at workspace scope (pivotal for counsel read-in).
    workspace_docs = (
        _workspace_docs_query(db, workspace.id)
        .order_by(desc(EvidenceItem.created_at))
        .limit(200)
        .all()
    )

    def _looks_like_contract(it: EvidenceItem) -> bool:
        try:
            if (it.evidence_type or "").lower() == "contract":
                return True
        except Exception:
            pass
        # Strong signal: Textract queries returned commercial/contract fields
        try:
            md = (
                it.extracted_metadata if isinstance(it.extracted_metadata, dict) else {}
            )
            tex = md.get("textract_data") if isinstance(md, dict) else None
            if isinstance(tex, dict):
                q = tex.get("queries")
                if isinstance(q, dict):

                    def _ans(key: str) -> str:
                        v = q.get(key)
                        if isinstance(v, dict):
                            return str(v.get("answer") or "").strip()
                        if isinstance(v, str):
                            return v.strip()
                        return ""

                    hits = 0
                    for k in (
                        "contract_value",
                        "contract_form",
                        "contract_date",
                        "parties",
                        "employer",
                        "contractor",
                        "payment_terms",
                        "retention",
                        "liquidated_damages",
                    ):
                        if _ans(k):
                            hits += 1
                    if hits >= 2:
                        return True
        except Exception:
            pass
        fn = (it.filename or "").lower()
        if any(
            k in fn
            for k in (
                "contract",
                "agreement",
                "jct",
                "nec",
                "subcontract",
                "sub-contract",
                "terms",
                "conditions",
                "scope of works",
                "appointment",
                "consultancy",
                "consultant",
                "professional",
                "warranty",
                "collateral",
                "deed",
                "novation",
                "side letter",
                "letter of intent",
                "loi",
                "purchase order",
                "po ",
            )
        ):
            return True
        # Best-effort: peek at a small text prefix (avoid large scans).
        sample = ((it.extracted_text or "")[:8000]).lower()
        if any(
            k in sample
            for k in (
                "this contract",
                "this agreement",
                "conditions of contract",
                "jct",
                "nec",
                "schedule of amendments",
                "contract sum",
                "articles of agreement",
                "appointment of",
                "terms of engagement",
                "deed of",
                "collateral warranty",
                "letter of intent",
            )
        ):
            return True
        return False

    contract_docs = [d for d in workspace_docs if _looks_like_contract(d)]
    contract_docs = contract_docs[:6]

    about_hints = [
        "instruction",
        "instructions",
        "instruction narrative",
        "scope",
        "deliverable",
        "employer",
        "client",
        "main contractor",
        "contractor",
        "architect",
        "engineer",
        "design",
        "inspection",
        "responsibility",
        "causation",
        "water ingress",
        "defect",
        "correspondence",
        "chronology",
        "contradiction",
        "issue",
    ]
    about_hints.extend(_hint_tokens(purpose_text))
    about_hints = list(dict.fromkeys([h for h in about_hints if h]))

    def _score_for_readin(it: EvidenceItem) -> int:
        score = 0
        fn = (it.filename or "").lower()
        et = (it.evidence_type or "").lower()

        if _looks_like_contract(it):
            score += 250
        if et == "meeting_minutes":
            score += 90
        if et == "drawing":
            score += 50
        if et == "invoice":
            score += 35

        # Filename hints for high-signal documents
        for k, w in (
            ("expert", 90),
            ("report", 60),
            ("letter of claim", 120),
            ("claim", 70),
            ("particulars", 80),
            ("notice", 60),
            ("valuation", 50),
            ("schedule", 40),
            ("programme", 40),
            ("chronology", 40),
            ("whatsapp", 30),
            ("meeting", 35),
            ("minutes", 35),
        ):
            if k in fn:
                score += w

        # Tag boosts (when enhanced processing has run)
        tags = it.auto_tags if isinstance(it.auto_tags, list) else []
        for t in tags:
            if t in ("delay", "defect", "variation", "payment", "quality"):
                score += 25

        # Recency boost (lightweight)
        try:
            if it.created_at:
                now = datetime.now(timezone.utc)
                age_days = max(0, int((now - it.created_at).total_seconds() // 86400))
                score += max(0, 40 - age_days)
        except Exception:
            pass

        # Reward if we have extracted text
        if (it.extracted_text or "").strip():
            score += 10
        return score

    ranked_pool = sorted(evidence_pool, key=_score_for_readin, reverse=True)

    target_docs = 26 if deep else 20
    candidate_limit = 90 if deep else 55

    # Candidates for reranking: force-in contracts, then best-of rest.
    candidate_items: list[EvidenceItem] = []
    seen_ids: set[str] = set()
    for it in contract_docs + ranked_pool[:candidate_limit]:
        sid = str(it.id)
        if sid not in seen_ids:
            candidate_items.append(it)
            seen_ids.add(sid)

    ordered_items = candidate_items

    # Deep mode: rerank candidates using Bedrock Cohere Rerank 3.5 (best-effort).
    if deep and getattr(settings, "BEDROCK_RERANK_ENABLED", False) and len(candidate_items) > 3:
        try:
            aws = get_aws_services()
            snippets: list[str] = []
            for it in candidate_items:
                excerpt = _select_best_excerpt(it.extracted_text, 1200, hints=about_hints) or (
                    (it.extracted_text or "")[:1200]
                )
                meta = []
                if it.document_date:
                    meta.append(f"date={it.document_date.isoformat()}")
                if (it.evidence_type or "").strip():
                    meta.append(f"type={(it.evidence_type or '').strip()}")
                header = f"{it.filename or 'Untitled'}" + (f" ({', '.join(meta)})" if meta else "")
                snippets.append(f"{header}\n{excerpt}")

            rerank_query = (
                "Select the most relevant sources for a counsel-ready construction dispute read-in. "
                "Prioritize contracts and key terms, notices/claims, pleadings, expert reports, key correspondence, "
                "programme/delay material, defects/inspections, payment/valuation, and decisive admissions/positions."
            )
            reranked = await aws.rerank_texts(rerank_query, snippets, top_n=min(target_docs, len(snippets)))
            order = [int(r.get("index", -1)) for r in reranked if isinstance(r, dict)]
            picked: list[EvidenceItem] = []
            picked_ids: set[str] = set()
            for idx in order:
                if 0 <= idx < len(candidate_items):
                    it = candidate_items[idx]
                    sid = str(it.id)
                    if sid not in picked_ids:
                        picked.append(it)
                        picked_ids.add(sid)

            # Ensure contract docs remain represented even if reranker is noisy.
            for it in contract_docs:
                sid = str(it.id)
                if sid not in picked_ids:
                    picked.insert(0, it)
                    picked_ids.add(sid)

            ordered_items = picked[:target_docs]
        except Exception:
            ordered_items = candidate_items[:target_docs]
    else:
        ordered_items = candidate_items[:target_docs]

    sources: list[dict[str, Any]] = []
    source_blocks: list[str] = []
    contract_source_labels: dict[str, str] = {}
    for idx, item in enumerate(ordered_items, start=1):
        label = f"S{idx}"
        filename = item.filename or "Untitled"
        doc_date = item.document_date.isoformat() if item.document_date else None

        # Pull high-signal structured fields when available (Textract queries, etc.)
        signals: list[str] = []
        md = (
            item.extracted_metadata if isinstance(item.extracted_metadata, dict) else {}
        )
        tex = md.get("textract_data") if isinstance(md, dict) else None
        if isinstance(tex, dict):
            q = tex.get("queries")
            if isinstance(q, dict):
                for alias in (
                    "project_name",
                    "parties",
                    "contract_value",
                    "completion_date",
                    "payment_terms",
                    "retention",
                    "liquidated_damages",
                    "delay_clauses",
                    "contract_form",
                    "contract_date",
                    "employer",
                    "contractor",
                ):
                    entry = q.get(alias)
                    ans = None
                    if isinstance(entry, dict):
                        ans = entry.get("answer")
                    elif isinstance(entry, str):
                        ans = entry
                    if ans and str(ans).strip():
                        signals.append(f"{alias}={str(ans).strip()[:160]}")
        # Give more room to contract documents.
        excerpt_limit = 3200 if _looks_like_contract(item) else 1600
        excerpt = _select_best_excerpt(
            item.extracted_text, excerpt_limit, hints=about_hints
        ) or _select_best_excerpt(
            (
                (item.extracted_metadata or {}).get("text_preview")  # type: ignore[union-attr]
                if isinstance(item.extracted_metadata, dict)
                else ""
            ),
            excerpt_limit,
            hints=about_hints,
        )
        sources.append(
            {
                "label": label,
                "evidence_id": str(item.id),
                "filename": filename,
                "document_date": doc_date,
                "evidence_type": getattr(item, "evidence_type", None),
            }
        )
        if excerpt:
            header = (
                f"[{label}] {filename} (id={item.id}, date={doc_date or 'unknown'})"
            )
            if signals:
                header += "\nSignals: " + "; ".join(signals[:10])
            source_blocks.append(f"{header}\n{excerpt}")
        if _looks_like_contract(item):
            contract_source_labels[str(item.id)] = label

    # Pull a bounded slice of correspondence (emails) from projects/cases in this workspace.
    # This gives the read-in access to the "Correspondence" tab content, not just documents.
    try:
        from .models import EmailMessage

        email_conds = []
        if project_ids:
            email_conds.append(EmailMessage.project_id.in_(project_ids))
        if case_ids:
            email_conds.append(EmailMessage.case_id.in_(case_ids))

        emails: list[EmailMessage] = []
        if email_conds:
            emails = (
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

        def _score_email_for_readin(em: EmailMessage) -> int:
            score = 0
            subj = (em.subject or "").lower()

            if em.has_attachments:
                score += 70
            if (em.importance or "").lower() == "high":
                score += 25

            for k, w in (
                ("letter of claim", 120),
                ("without prejudice", 90),
                ("claim", 70),
                ("notice", 55),
                ("delay", 45),
                ("eot", 45),
                ("extension of time", 45),
                ("payment", 40),
                ("pay less", 55),
                ("invoice", 30),
                ("valuation", 35),
                ("variation", 35),
                ("defect", 35),
                ("snag", 20),
                ("termination", 60),
                ("adjudication", 60),
                ("expert", 45),
                ("programme", 25),
                ("program", 25),
            ):
                if k in subj:
                    score += w

            # Lightweight recency boost
            try:
                dt = em.date_sent or em.created_at
                if dt:
                    now = datetime.now(timezone.utc)
                    age_days = max(0, int((now - dt).total_seconds() // 86400))
                    score += max(0, 28 - age_days)
            except Exception:
                pass

            # Reward if we have canonical body text
            if (em.body_text_clean or "").strip():
                score += 10
            return score

        ranked_emails = sorted(emails, key=_score_email_for_readin, reverse=True)
        selected_emails = ranked_emails[: (10 if deep else 6)]

        # Deep mode: rerank email candidates for read-in relevance (best-effort).
        if (
            deep
            and getattr(settings, "BEDROCK_RERANK_ENABLED", False)
            and len(ranked_emails) > 6
        ):
            try:
                aws = get_aws_services()
                cand = ranked_emails[:50]
                em_snippets: list[str] = []
                for em in cand:
                    subject = (em.subject or "(no subject)").strip()
                    dt = em.date_sent.isoformat() if em.date_sent else None
                    frm = (em.sender_email or em.sender_name or "Unknown").strip()
                    body = em.body_text_clean or em.body_preview or em.body_text or ""
                    excerpt = _select_best_excerpt(body, 900, hints=about_hints) or (body[:900])
                    header = f"Email: {subject}" + (f" (date={dt})" if dt else "")
                    em_snippets.append(f"{header}\nFrom: {frm}\n{excerpt}")

                rerank_query = (
                    "Select the most relevant correspondence for a counsel-ready construction dispute read-in. "
                    "Prioritize notices/claims, admissions/positions, key delay/payment/defect communications, "
                    "expert-related exchanges, programme/EOT threads, and emails with attachments."
                )
                reranked = await aws.rerank_texts(
                    rerank_query,
                    em_snippets,
                    top_n=min((10 if deep else 6), len(em_snippets)),
                )
                order = [int(r.get("index", -1)) for r in reranked if isinstance(r, dict)]
                picked = []
                seen = set()
                for idx in order:
                    if 0 <= idx < len(cand):
                        em = cand[idx]
                        sid = str(getattr(em, "id", "")) or f"idx:{idx}"
                        if sid not in seen:
                            picked.append(em)
                            seen.add(sid)
                if picked:
                    selected_emails = picked
            except Exception:
                pass

        start_idx = len(sources) + 1
        for i, em in enumerate(selected_emails, start=start_idx):
            label = f"S{i}"
            subject = (em.subject or "(no subject)").strip()
            dt = em.date_sent.isoformat() if em.date_sent else None
            frm = (em.sender_email or em.sender_name or "Unknown").strip()
            to = ", ".join((em.recipients_to or [])[:6]) if em.recipients_to else ""
            if len(to) > 220:
                to = to[:220].rstrip() + "…"

            body = em.body_text_clean or em.body_preview or em.body_text or ""
            excerpt = _select_best_excerpt(body, 1400, hints=about_hints)

            sources.append(
                {
                    "label": label,
                    "evidence_id": str(em.id),
                    "filename": f"Email: {subject[:180]}",
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
                source_blocks.append(f"{header}\n{excerpt}")
    except Exception:
        # best-effort; never block read-in generation
        pass

    user_notes = (about.user_notes or "").strip()
    evidence_excerpt_text = "\n\n".join(source_blocks) if source_blocks else "None"
    contract_list_text = (
        "\n".join(
            [
                f"- [{contract_source_labels.get(str(d.id), '?')}] {d.filename} (id={d.id})"
                for d in contract_docs
            ]
        )
        if contract_docs
        else "None"
    )
    instruction_context = ""
    if instruction_item:
        instruction_context = f"{instruction_item.filename} (id={instruction_item.id})"

    system_prompt = (
        "You are a senior construction disputes barrister's assistant. "
        "Only use the facts provided. Do NOT invent. "
        "If information is missing, say 'Unknown' and add an open question."
    )

    prompt = f"""
Build a counsel-ready Workspace Read-In that reduces read-in time to minutes.

Return ONE JSON object with keys:
- read_in: string (plain text; use headings + bullets; be comprehensive but factual)
- structured: object with:
  - at_a_glance: object {{headline, dispute_type, location, contract_form, contract_value, key_dates, current_position, quantum}}
  - parties_roles: array of objects {{name, role, organisation, notes, sources}}
  - issues: array of objects {{issue, what_happened, why_it_matters, sources}}
  - evidence_map: object with arrays for {{contracts, pleadings, expert_reports, correspondence, programmes, photos}} each item {{filename, evidence_id, why_relevant, sources}}
  - next_actions: array of objects {{action, why, owner_hint, sources}}
- contracts: object with:
  - documents: array of objects {{evidence_id, filename, contract_form, contract_date, parties, contract_value, key_terms, risks, source_labels}}
  - key_terms_overview: array of strings (most important clauses/terms, each with citation)
  - gaps: array of strings (missing contract documents/clauses/appendices)
- open_questions: array of strings (8-20 items; prioritized; each should be answerable by a missing document or fact)
- sources: array of objects {{label, evidence_id, filename, document_date}}

Workspace:
- name: {workspace.name}
- code: {workspace.code}
- contract_type: {workspace.contract_type or "Unknown"}
- description: {workspace.description or "None"}

Projects (count={len(projects)}): {", ".join([p.project_name for p in projects if p.project_name]) or "None"}
Cases (count={len(cases)}): {", ".join([c.name for c in cases if c.name]) or "None"}

Authoritative user notes (treat as ground truth if present):
{user_notes or "None"}

Purpose baseline:
{purpose_text or "None"}

Instruction baseline document:
{instruction_context or "None"}

Contract documents uploaded in this workspace (if any):
{contract_list_text}

Evidence + correspondence excerpts (cite sources like [S1], [S2] where relevant):
{evidence_excerpt_text}
""".strip()

    # Always use the workspace tool so Bedrock Guardrails apply consistently.
    tool_name = "workspace_about"
    max_tokens = 7000 if deep else 3200
    ai_text = await _complete_with_tool_fallback(
        tool_name=tool_name,
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        max_tokens=max_tokens,
        temperature=0.2,
    )

    payload = _extract_json_object(ai_text) if ai_text else None
    if not payload:
        # Deterministic fallback: build a minimal summary without external AI.
        summary_lines = [
            f"Workspace: {workspace.name} ({workspace.code})",
            f"Contract type: {workspace.contract_type or 'Unknown'}",
        ]
        if workspace.description:
            summary_lines.append(f"Description: {workspace.description}")
        if projects:
            summary_lines.append(
                "Projects: "
                + ", ".join([p.project_name for p in projects if p.project_name][:10])
            )
        if cases:
            summary_lines.append(
                "Cases: " + ", ".join([c.name for c in cases if c.name][:10])
            )
        if contract_docs:
            summary_lines.append(
                "Contract documents uploaded: "
                + ", ".join([d.filename for d in contract_docs if d.filename][:8])
            )
        if ordered_items:
            summary_lines.append(
                "Recent evidence: "
                + ", ".join([e.filename for e in ordered_items if e.filename][:8])
            )

        payload = {
            "read_in": "\n".join(summary_lines),
            "structured": {},
            "contracts": {
                "documents": [
                    {
                        "evidence_id": str(d.id),
                        "filename": d.filename,
                        "source_labels": [contract_source_labels.get(str(d.id), "")],
                    }
                    for d in contract_docs
                ],
                "key_terms_overview": [],
                "gaps": [],
            },
            "open_questions": [
                "What is the dispute headline / claim narrative?",
                "Who are the key parties and roles (Employer, Contractor, PM, QS, Engineer)?",
                "What is the contract form, scope, and key dates (start/completion/EOT)?",
                "What are the pleaded issues (delay, variations, payment, defects, termination)?",
                "Which documents are missing and need collecting?",
            ],
            "sources": sources,
        }

    # Normalize payload keys for UI
    summary = str(payload.get("read_in") or payload.get("summary") or "").strip()
    open_questions = (
        payload.get("open_questions")
        if isinstance(payload.get("open_questions"), list)
        else []
    )
    payload["open_questions"] = [str(q) for q in open_questions if str(q).strip()][:20]
    payload["sources"] = sources
    structured_obj = (
        payload.get("structured") if isinstance(payload.get("structured"), dict) else {}
    )
    if not isinstance(structured_obj, dict):
        structured_obj = {}
    payload["structured"] = structured_obj
    contracts_obj = (
        payload.get("contracts") if isinstance(payload.get("contracts"), dict) else {}
    )
    # Ensure stable contract payload shape for the UI, even if the model omits it.
    if not isinstance(contracts_obj, dict):
        contracts_obj = {}
    if not isinstance(contracts_obj.get("documents"), list):
        contracts_obj["documents"] = []
    if not isinstance(contracts_obj.get("key_terms_overview"), list):
        contracts_obj["key_terms_overview"] = []
    if not isinstance(contracts_obj.get("gaps"), list):
        contracts_obj["gaps"] = []

    def _q_answer(it: EvidenceItem, alias: str) -> str:
        md = it.extracted_metadata if isinstance(it.extracted_metadata, dict) else {}
        tex = md.get("textract_data") if isinstance(md, dict) else None
        if not isinstance(tex, dict):
            return ""
        q = tex.get("queries")
        if not isinstance(q, dict):
            return ""
        entry = q.get(alias)
        if isinstance(entry, dict):
            return str(entry.get("answer") or "").strip()
        if isinstance(entry, str):
            return entry.strip()
        return ""

    # If the model didn't return contract documents but we detected them, populate from detected set.
    if not contracts_obj.get("documents") and contract_docs:
        docs_payload: list[dict[str, Any]] = []
        key_terms_overview: list[str] = []
        for d in contract_docs[:8]:
            key_terms: dict[str, str] = {}
            for alias in (
                "payment_terms",
                "retention",
                "liquidated_damages",
                "completion_date",
                "delay_clauses",
            ):
                ans = _q_answer(d, alias)
                if ans:
                    key_terms[alias] = ans
                    key_terms_overview.append(
                        f"{alias}: {ans} [{contract_source_labels.get(str(d.id), '?')}]"
                    )

            docs_payload.append(
                {
                    "evidence_id": str(d.id),
                    "filename": d.filename,
                    "contract_form": _q_answer(d, "contract_form")
                    or (workspace.contract_type or ""),
                    "contract_date": _q_answer(d, "contract_date")
                    or (d.document_date.isoformat() if d.document_date else ""),
                    "parties": _q_answer(d, "parties")
                    or ", ".join((d.extracted_parties or [])[:6]),
                    "contract_value": _q_answer(d, "contract_value"),
                    "key_terms": key_terms,
                    "source_labels": [contract_source_labels.get(str(d.id), "")],
                }
            )
        contracts_obj["documents"] = docs_payload
        if not contracts_obj.get("key_terms_overview"):
            contracts_obj["key_terms_overview"] = key_terms_overview[:20]

    payload["contracts"] = contracts_obj

    about.summary_md = summary
    about.data = payload
    about.status = "ready"
    about.last_error = None
    about.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(about)
    return about


async def _workspace_doc_postprocess_job(
    evidence_id: str,
    workspace_id: str,
) -> None:
    # Run after upload: AWS digestion + refresh About snapshot.
    db = SessionLocal()
    try:
        try:
            if enhanced_processor is not None:
                await enhanced_processor.process_evidence_item(evidence_id, db)
        except Exception as e:
            logger.info("Workspace evidence postprocess skipped/failed: %s", e)
        try:
            ws_uuid = _parse_uuid(workspace_id, "workspace_id")
            ws = db.query(Workspace).filter(Workspace.id == ws_uuid).first()
            if ws:
                # Rebuild using newly extracted AWS metadata (quick mode).
                await _build_workspace_about_snapshot(
                    db=db, workspace=ws, force=False, deep=False
                )
        except Exception as e:
            logger.info("Workspace About refresh failed: %s", e)
    finally:
        db.close()


# CRUD Endpoints
@router.get("")
def list_workspaces(
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """List all workspaces accessible to the user"""
    if _is_admin(user):
        workspaces = db.query(Workspace).all()
    else:
        workspaces = db.query(Workspace).filter(Workspace.owner_id == user.id).all()

    result = []
    for ws in workspaces:
        # Count projects and cases
        project_count = (
            db.query(func.count(Project.id))
            .filter(Project.workspace_id == ws.id)
            .scalar()
            or 0
        )
        case_count = (
            db.query(func.count(Case.id)).filter(Case.workspace_id == ws.id).scalar()
            or 0
        )

        # Get projects and cases for this workspace
        projects = db.query(Project).filter(Project.workspace_id == ws.id).all()
        cases = db.query(Case).filter(Case.workspace_id == ws.id).all()

        project_ids = [p.id for p in projects]
        case_ids = [c.id for c in cases]

        from .models import EmailMessage, EvidenceItem

        email_count = 0
        evidence_count = 0
        if project_ids:
            email_count += (
                db.query(func.count(EmailMessage.id))
                .filter(EmailMessage.project_id.in_(project_ids))
                .scalar()
                or 0
            )
        if case_ids:
            email_count += (
                db.query(func.count(EmailMessage.id))
                .filter(EmailMessage.case_id.in_(case_ids))
                .scalar()
                or 0
            )
        if project_ids:
            evidence_count += (
                db.query(func.count(EvidenceItem.id))
                .filter(EvidenceItem.project_id.in_(project_ids))
                .scalar()
                or 0
            )
        if case_ids:
            evidence_count += (
                db.query(func.count(EvidenceItem.id))
                .filter(EvidenceItem.case_id.in_(case_ids))
                .scalar()
                or 0
            )

        result.append(
            {
                "id": str(ws.id),
                "name": ws.name,
                "code": ws.code,
                "description": ws.description,
                "contract_type": ws.contract_type,
                "status": ws.status,
                "project_count": project_count,
                "case_count": case_count,
                "email_count": email_count,
                "evidence_count": evidence_count,
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
                "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
                # Include nested projects and cases for frontend navigation
                "projects": [
                    {
                        "id": str(p.id),
                        "name": p.project_name,
                        "code": p.project_code,
                    }
                    for p in projects
                ],
                "cases": [
                    {
                        "id": str(c.id),
                        "name": c.name,
                        "case_number": c.case_number,
                    }
                    for c in cases
                ],
            }
        )

    return result


@router.post("")
def create_workspace(
    payload: WorkspaceCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Create a new workspace"""
    # Check if code already exists
    existing = db.query(Workspace).filter(Workspace.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Workspace code already exists")

    workspace = Workspace(
        name=payload.name,
        code=payload.code,
        description=payload.description,
        contract_type=payload.contract_type,
        owner_id=user.id,
        status="active",
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "code": workspace.code,
        "description": workspace.description,
        "contract_type": workspace.contract_type,
        "status": workspace.status,
        "created_at": (
            workspace.created_at.isoformat() if workspace.created_at else None
        ),
        "updated_at": (
            workspace.updated_at.isoformat() if workspace.updated_at else None
        ),
    }


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Get workspace details with nested projects and cases"""
    try:
        workspace = _require_workspace(db, workspace_id, user)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Error in _require_workspace for workspace_id=%s", workspace_id
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to load workspace: {e}"
        ) from e

    try:
        # Get projects
        projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()
        project_list = []
        for p in projects:
            from .models import EmailMessage, EvidenceItem

            email_count = (
                db.query(func.count(EmailMessage.id))
                .filter(EmailMessage.project_id == p.id)
                .scalar()
                or 0
            )
            evidence_count = (
                db.query(func.count(EvidenceItem.id))
                .filter(EvidenceItem.project_id == p.id)
                .scalar()
                or 0
            )
            project_list.append(
                {
                    "id": str(p.id),
                    "name": p.project_name,
                    "code": p.project_code,
                    "description": None,  # Projects don't have description in current model
                    "email_count": email_count,
                    "evidence_count": evidence_count,
                }
            )

        # Get cases
        cases = db.query(Case).filter(Case.workspace_id == workspace.id).all()
        case_list = []
        for c in cases:
            from .models import EmailMessage, EvidenceItem

            email_count = (
                db.query(func.count(EmailMessage.id))
                .filter(EmailMessage.case_id == c.id)
                .scalar()
                or 0
            )
            evidence_count = (
                db.query(func.count(EvidenceItem.id))
                .filter(EvidenceItem.case_id == c.id)
                .scalar()
                or 0
            )
            case_list.append(
                {
                    "id": str(c.id),
                    "name": c.name,
                    "code": c.case_number,
                    "description": c.description,
                    "project_id": str(c.project_id) if c.project_id else None,
                    "project_name": c.project_name,
                    "email_count": email_count,
                    "evidence_count": evidence_count,
                }
            )

        # Get keywords
        keywords = (
            db.query(WorkspaceKeyword)
            .filter(WorkspaceKeyword.workspace_id == workspace.id)
            .all()
        )
        keyword_list = [
            {
                "id": str(k.id),
                "keyword_name": k.keyword_name,
                "definition": k.definition,
                "variations": k.variations,
                "is_regex": k.is_regex,
            }
            for k in keywords
        ]

        # Get team members
        team = (
            db.query(WorkspaceTeamMember)
            .filter(WorkspaceTeamMember.workspace_id == workspace.id)
            .all()
        )
        team_list = [
            {
                "id": str(t.id),
                "user_id": str(t.user_id) if t.user_id else None,
                "role": t.role,
                "name": t.name,
                "email": t.email,
                "organization": t.organization,
            }
            for t in team
        ]

        # Get key dates
        dates = (
            db.query(WorkspaceKeyDate)
            .filter(WorkspaceKeyDate.workspace_id == workspace.id)
            .all()
        )
        date_list = [
            {
                "id": str(d.id),
                "date_type": d.date_type,
                "label": d.label,
                "date_value": d.date_value.isoformat() if d.date_value else None,
                "description": d.description,
            }
            for d in dates
        ]

        # Get stakeholders (JCT categories)
        stakeholders = (
            db.query(Stakeholder)
            .filter(Stakeholder.project_id.in_([p.id for p in projects]))
            .all()
        )
        stakeholder_list = [
            {
                "id": str(s.id),
                "role": s.role,
                "name": s.name,
                "email": s.email,
                "organization": s.organization,
            }
            for s in stakeholders
        ]

        # Workspace-scoped documents (context uploads)
        docs = (
            _workspace_docs_query(db, workspace.id)
            .order_by(desc(EvidenceItem.created_at))
            .limit(250)
            .all()
        )
        doc_list = [
            {
                "id": str(d.id),
                "filename": d.filename,
                "size": int(d.file_size or 0),
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "processing_status": d.processing_status or "pending",
                "folder_path": (
                    (d.meta or {}).get("folder_path")  # type: ignore[union-attr]
                    if isinstance(d.meta, dict) or d.meta is None
                    else None
                ),
            }
            for d in docs
        ]

        about = (
            db.query(WorkspaceAbout)
            .filter(WorkspaceAbout.workspace_id == workspace.id)
            .first()
        )

        return {
            "id": str(workspace.id),
            "name": workspace.name,
            "code": workspace.code,
            "description": workspace.description,
            "contract_type": workspace.contract_type,
            "status": workspace.status,
            "projects": project_list,
            "cases": case_list,
            "keywords": keyword_list,
            "team_members": team_list,
            "key_dates": date_list,
            "stakeholders": stakeholder_list,
            "documents": doc_list,
            "about_status": (about.status if about else "empty"),
            "created_at": (
                workspace.created_at.isoformat() if workspace.created_at else None
            ),
            "updated_at": (
                workspace.updated_at.isoformat() if workspace.updated_at else None
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Error fetching workspace details for workspace_id=%s", workspace_id
        )
        raise HTTPException(
            status_code=500, detail=f"Error fetching workspace details: {e}"
        ) from e


@router.put("/{workspace_id}")
def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Update workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    if payload.code is not None and payload.code != workspace.code:
        # Check if new code already exists
        existing = db.query(Workspace).filter(Workspace.code == payload.code).first()
        if existing:
            raise HTTPException(status_code=400, detail="Workspace code already exists")
        workspace.code = payload.code

    if payload.name is not None:
        workspace.name = payload.name
    if payload.description is not None:
        workspace.description = payload.description
    if payload.contract_type is not None:
        workspace.contract_type = payload.contract_type
    if payload.status is not None:
        workspace.status = payload.status

    db.commit()
    db.refresh(workspace)

    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "code": workspace.code,
        "description": workspace.description,
        "contract_type": workspace.contract_type,
        "status": workspace.status,
        "updated_at": (
            workspace.updated_at.isoformat() if workspace.updated_at else None
        ),
    }


@router.put("/{workspace_id}/projects/{project_id}")
def move_project_to_workspace(
    workspace_id: str,
    project_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Move/link an existing project into a workspace.

    Emails/evidence remain attached to the project; the workspace just groups projects/cases.
    """
    workspace = _require_workspace(db, workspace_id, user)
    project = _require_project(db, project_id, user)

    from_workspace_id = str(project.workspace_id) if project.workspace_id else None
    project.workspace_id = workspace.id
    db.commit()
    db.refresh(project)

    return {
        "status": "success",
        "project_id": str(project.id),
        "from_workspace_id": from_workspace_id,
        "to_workspace_id": str(workspace.id),
    }


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    """Delete workspace (cascade deletes related config items)"""
    workspace = _require_workspace(db, workspace_id, user)
    db.delete(workspace)
    db.commit()
    return {"status": "success"}


# Keywords endpoints
@router.put("/{workspace_id}/keywords")
def update_workspace_keywords(
    workspace_id: str,
    keywords: list[KeywordCreate],
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Replace all keywords for a workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    # Delete existing keywords
    db.query(WorkspaceKeyword).filter(
        WorkspaceKeyword.workspace_id == workspace.id
    ).delete()

    # Create new keywords
    result = []
    for kw in keywords:
        keyword = WorkspaceKeyword(
            workspace_id=workspace.id,
            keyword_name=kw.keyword_name,
            definition=kw.definition,
            variations=kw.variations,
            is_regex=kw.is_regex or False,
        )
        db.add(keyword)
        result.append(
            {
                "id": str(keyword.id),
                "keyword_name": keyword.keyword_name,
                "definition": keyword.definition,
                "variations": keyword.variations,
                "is_regex": keyword.is_regex,
            }
        )

    db.commit()
    return result


# Team members endpoints
@router.put("/{workspace_id}/team")
def update_workspace_team(
    workspace_id: str,
    team: list[TeamMemberCreate],
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Replace all team members for a workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    # Delete existing team members
    db.query(WorkspaceTeamMember).filter(
        WorkspaceTeamMember.workspace_id == workspace.id
    ).delete()

    # Create new team members
    result = []
    for tm in team:
        user_id = _parse_uuid(tm.user_id, "user_id") if tm.user_id else None
        member = WorkspaceTeamMember(
            workspace_id=workspace.id,
            user_id=user_id,
            role=tm.role,
            name=tm.name,
            email=tm.email,
            organization=tm.organization,
        )
        db.add(member)
        result.append(
            {
                "id": str(member.id),
                "user_id": str(member.user_id) if member.user_id else None,
                "role": member.role,
                "name": member.name,
                "email": member.email,
                "organization": member.organization,
            }
        )

    db.commit()
    return result


@router.post("/{workspace_id}/team")
def add_workspace_team_member(
    workspace_id: str,
    payload: TeamMemberAddRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Add an existing system user to the workspace team list."""

    workspace = _require_workspace(db, workspace_id, user)

    email = (payload.email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    existing_user = (
        db.query(User).filter(func.lower(User.email) == email).first()  # type: ignore[arg-type]
    )
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing_member = (
        db.query(WorkspaceTeamMember)
        .filter(
            WorkspaceTeamMember.workspace_id == workspace.id,
            WorkspaceTeamMember.user_id == existing_user.id,
        )
        .first()
    )
    if existing_member:
        return {
            "id": str(existing_member.id),
            "user_id": (
                str(existing_member.user_id) if existing_member.user_id else None
            ),
            "role": existing_member.role,
            "name": existing_member.name,
            "email": existing_member.email,
            "organization": existing_member.organization,
        }

    role = (payload.role or "member").strip() or "member"
    display_name = (existing_user.display_name or existing_user.email or email).strip()

    member = WorkspaceTeamMember(
        workspace_id=workspace.id,
        user_id=existing_user.id,
        role=role,
        name=display_name,
        email=existing_user.email,
        organization=None,
    )
    db.add(member)
    db.commit()
    db.refresh(member)

    return {
        "id": str(member.id),
        "user_id": str(member.user_id) if member.user_id else None,
        "role": member.role,
        "name": member.name,
        "email": member.email,
        "organization": member.organization,
    }


@router.delete("/{workspace_id}/team/{member_id}")
def delete_workspace_team_member(
    workspace_id: str,
    member_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    """Remove a team member entry from a workspace."""

    workspace = _require_workspace(db, workspace_id, user)
    member_uuid = _parse_uuid(member_id, "member_id")

    member = (
        db.query(WorkspaceTeamMember)
        .filter(
            WorkspaceTeamMember.id == member_uuid,
            WorkspaceTeamMember.workspace_id == workspace.id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")

    db.delete(member)
    db.commit()

    return {"status": "success", "id": member_id}


# Key dates endpoints
@router.put("/{workspace_id}/dates")
def update_workspace_dates(
    workspace_id: str,
    dates: list[KeyDateCreate],
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Replace all key dates for a workspace"""
    workspace = _require_workspace(db, workspace_id, user)

    # Delete existing dates
    db.query(WorkspaceKeyDate).filter(
        WorkspaceKeyDate.workspace_id == workspace.id
    ).delete()

    # Create new dates
    result = []
    for d in dates:
        key_date = WorkspaceKeyDate(
            workspace_id=workspace.id,
            date_type=d.date_type,
            label=d.label,
            date_value=d.date_value,
            description=d.description,
        )
        db.add(key_date)
        result.append(
            {
                "id": str(key_date.id),
                "date_type": key_date.date_type,
                "label": key_date.label,
                "date_value": (
                    key_date.date_value.isoformat() if key_date.date_value else None
                ),
                "description": key_date.description,
            }
        )

    db.commit()
    return result


# Stakeholders endpoints - for JCT categories
@router.get("/{workspace_id}/stakeholders")
def get_workspace_stakeholders(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    """Get stakeholders for a workspace (aggregated from projects)"""
    workspace = _require_workspace(db, workspace_id, user)
    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()

    if not projects:
        return []

    project_ids = [p.id for p in projects]
    stakeholders = (
        db.query(Stakeholder).filter(Stakeholder.project_id.in_(project_ids)).all()
    )

    return [
        {
            "id": str(s.id),
            "role": s.role,
            "name": s.name,
            "email": s.email,
            "organization": s.organization,
        }
        for s in stakeholders
    ]


# ============================================================================
# Workspace Documents (context uploads, dispute read-in)
# ============================================================================


@router.get("/{workspace_id}/documents")
def list_workspace_documents(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict[str, Any]]:
    workspace = _require_workspace(db, workspace_id, user)
    items = (
        _workspace_docs_query(db, workspace.id)
        .order_by(desc(EvidenceItem.created_at))
        .limit(1000)
        .all()
    )
    return [
        {
            "id": str(i.id),
            "filename": i.filename,
            "size": int(i.file_size or 0),
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "processing_status": i.processing_status or "pending",
            "folder_path": (
                (i.meta or {}).get("folder_path")  # type: ignore[union-attr]
                if isinstance(i.meta, dict) or i.meta is None
                else None
            ),
        }
        for i in items
    ]


@router.get("/{workspace_id}/documents/folders")
def list_workspace_document_folders(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)

    prefix = _workspace_doc_folder_db_prefix(workspace)

    folder_paths: set[str] = set()
    try:
        rows = (
            db.query(Folder)
            .filter(
                Folder.owner_user_id == workspace.owner_id,
                Folder.path.startswith(prefix + "/"),
            )
            .all()
        )
        for f in rows:
            p = str(f.path or "")
            if not p.startswith(prefix + "/"):
                continue
            rel = p[len(prefix) + 1 :]
            rel = rel.strip().strip("/")
            if rel:
                folder_paths.add(rel)
    except Exception:
        # best-effort; still derive folders from docs
        pass

    docs = _workspace_docs_query(db, workspace.id).limit(5000).all()
    unfiled_count = 0
    direct_counts: dict[str, int] = {}
    recursive_counts: dict[str, int] = {}

    for d in docs:
        meta = d.meta if isinstance(d.meta, dict) else {}
        raw_fp = meta.get("folder_path") if isinstance(meta, dict) else None
        try:
            fp = _normalize_workspace_doc_folder_path(raw_fp)
        except HTTPException:
            fp = None

        if not fp:
            unfiled_count += 1
            continue

        direct_counts[fp] = direct_counts.get(fp, 0) + 1
        parts = fp.split("/")
        for i in range(1, len(parts) + 1):
            p = "/".join(parts[:i])
            folder_paths.add(p)
            recursive_counts[p] = recursive_counts.get(p, 0) + 1

    folders: list[dict[str, Any]] = []
    for path in sorted(folder_paths, key=lambda s: (s.count("/"), s.lower())):
        parts = path.split("/")
        name = parts[-1]
        parent = "/".join(parts[:-1]) or None
        folders.append(
            {
                "path": path,
                "name": name,
                "parent_path": parent,
                "doc_count": direct_counts.get(path, 0),
                "doc_count_recursive": recursive_counts.get(path, 0),
            }
        )

    return {
        "folders": folders,
        "unfiled_count": unfiled_count,
        "total_documents": len(docs),
    }


@router.post("/{workspace_id}/documents/folders")
def create_workspace_document_folder(
    workspace_id: str,
    payload: WorkspaceDocumentFolderCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    folder_path = _normalize_workspace_doc_folder_path(payload.path)
    if not folder_path:
        raise HTTPException(status_code=400, detail="Invalid folder path")

    _ensure_workspace_doc_folders(db, workspace, folder_path)
    db.commit()
    return {"status": "success", "path": folder_path}


@router.post("/{workspace_id}/documents")
async def upload_workspace_document(
    workspace_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    folder_path: str | None = Form(default=None),
    relative_path: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    content = await file.read()
    file_size = len(content)
    if file_size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    file_hash = compute_file_hash(content)
    existing = (
        db.query(EvidenceItem).filter(EvidenceItem.file_hash == file_hash).first()
    )
    is_duplicate = existing is not None
    duplicate_of_id = existing.id if existing else None

    evidence_id = uuid.uuid4()
    date_prefix = datetime.now().strftime("%Y/%m")
    safe_filename = file.filename.replace(" ", "_")
    bucket = settings.S3_BUCKET or settings.MINIO_BUCKET
    s3_key = f"workspace/{workspace.id}/{date_prefix}/{evidence_id}/{safe_filename}"

    try:
        put_object(
            key=s3_key,
            data=content,
            content_type=file.content_type or "application/octet-stream",
            bucket=bucket,
        )
    except Exception as exc:
        logger.error("Workspace document upload failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="Failed to upload document to storage"
        ) from exc

    # Best-effort initial classification from filename (helps contract detection before OCR finishes)
    initial_type = None
    try:
        fn = (file.filename or "").lower()
        if any(
            k in fn
            for k in (
                "contract",
                "agreement",
                "appointment",
                "terms",
                "conditions",
                "warranty",
                "collateral",
                "deed",
                "novation",
                "letter of intent",
                "loi",
                "jct",
                "nec",
            )
        ):
            initial_type = "contract"
        elif any(k in fn for k in ("programme", "program", "schedule")):
            initial_type = "programme"
        elif any(k in fn for k in ("minutes", "meeting")):
            initial_type = "meeting_minutes"
        elif any(k in fn for k in ("invoice", "valuation", "pay less", "payment")):
            initial_type = "invoice"
        elif any(k in fn for k in ("drawing", "plan", "elevation", "section")):
            initial_type = "drawing"
    except Exception:
        initial_type = None

    normalized_folder_path = _normalize_workspace_doc_folder_path(folder_path)
    normalized_relative_path = (str(relative_path).strip() if relative_path else "") or None
    if normalized_relative_path and len(normalized_relative_path) > 1024:
        normalized_relative_path = normalized_relative_path[:1024]

    item = EvidenceItem(
        id=evidence_id,
        filename=file.filename,
        file_type=get_file_type(file.filename),
        mime_type=file.content_type,
        file_size=file_size,
        file_hash=file_hash,
        s3_bucket=bucket,
        s3_key=s3_key,
        title=file.filename,
        evidence_type=initial_type,
        processing_status="pending",
        source_type="workspace_document",
        case_id=None,
        project_id=None,
        is_duplicate=is_duplicate,
        duplicate_of_id=duplicate_of_id,
        uploaded_by=user.id,
        meta={
            "workspace_id": str(workspace.id),
            "scope": "workspace_document",
            "origin": "workspace-hub",
            **({"folder_path": normalized_folder_path} if normalized_folder_path else {}),
            **({"relative_path": normalized_relative_path} if normalized_relative_path else {}),
        },
    )

    db.add(item)
    if normalized_folder_path:
        # Create folder rows for empty-folder UI representation (best-effort)
        try:
            _ensure_workspace_doc_folders(db, workspace, normalized_folder_path)
        except HTTPException:
            # Ignore invalid folder_path for upload; the file still uploads successfully.
            pass
    try:
        log_activity(
            db,
            "upload",
            user.id,
            evidence_item_id=item.id,
            details={
                "filename": file.filename,
                "size": file_size,
                "scope": "workspace_document",
                "workspace_id": str(workspace.id),
            },
        )
    except Exception:
        # best effort
        pass

    db.commit()
    db.refresh(item)

    # Background: deep AWS digestion + About snapshot refresh
    try:
        background_tasks.add_task(
            _workspace_doc_postprocess_job, str(item.id), str(workspace.id)
        )
    except Exception:
        pass

    return {
        "id": str(item.id),
        "filename": item.filename,
        "size": int(item.file_size or 0),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "processing_status": item.processing_status or "pending",
        "folder_path": normalized_folder_path,
        "is_duplicate": is_duplicate,
        "duplicate_of_id": str(duplicate_of_id) if duplicate_of_id else None,
    }


@router.post("/{workspace_id}/documents/{doc_id}/move")
def move_workspace_document(
    workspace_id: str,
    doc_id: str,
    payload: WorkspaceDocumentMoveRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    doc_uuid = _parse_uuid(doc_id, "doc_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == doc_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")
    if (item.meta or {}).get("workspace_id") != str(workspace.id):  # type: ignore[union-attr]
        raise HTTPException(status_code=403, detail="Access denied")

    dest = _normalize_workspace_doc_folder_path(payload.folder_path)
    meta = item.meta if isinstance(item.meta, dict) else {}
    if not isinstance(meta, dict):
        meta = {}

    if dest:
        meta["folder_path"] = dest
        try:
            _ensure_workspace_doc_folders(db, workspace, dest)
        except Exception:
            pass
    else:
        meta.pop("folder_path", None)

    item.meta = meta
    db.commit()
    db.refresh(item)

    return {
        "id": str(item.id),
        "filename": item.filename,
        "size": int(item.file_size or 0),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "processing_status": item.processing_status or "pending",
        "folder_path": dest,
    }


@router.get("/{workspace_id}/documents/{doc_id}/preview")
async def preview_workspace_document(
    workspace_id: str,
    doc_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    doc_uuid = _parse_uuid(doc_id, "doc_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == doc_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")
    if (item.meta or {}).get("workspace_id") != str(workspace.id):  # type: ignore[union-attr]
        raise HTTPException(status_code=403, detail="Access denied")

    from .evidence.services import get_evidence_preview_service

    return await get_evidence_preview_service(doc_id, db, user)


@router.get("/{workspace_id}/documents/{doc_id}/text-content")
async def get_workspace_document_text_content(
    workspace_id: str,
    doc_id: str,
    db: DbSession,
    user: CurrentUser,
    max_length: Annotated[int, Query(description="Max chars", ge=1, le=200000)] = 50000,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    doc_uuid = _parse_uuid(doc_id, "doc_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == doc_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")
    if (item.meta or {}).get("workspace_id") != str(workspace.id):  # type: ignore[union-attr]
        raise HTTPException(status_code=403, detail="Access denied")

    from .evidence.services import get_evidence_text_content_service

    return await get_evidence_text_content_service(doc_id, db, user, max_length)


@router.post("/{workspace_id}/documents/{doc_id}/ask")
async def ask_workspace_document(
    workspace_id: str,
    doc_id: str,
    payload: WorkspaceDocumentAskRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    doc_uuid = _parse_uuid(doc_id, "doc_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == doc_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")
    if (item.meta or {}).get("workspace_id") != str(workspace.id):  # type: ignore[union-attr]
        raise HTTPException(status_code=403, detail="Access denied")

    # Ensure we have text to work with (falls back to extraction if needed).
    from .evidence.services import get_evidence_text_content_service

    text_payload = await get_evidence_text_content_service(doc_id, db, user, 120000)
    full_text = str(text_payload.get("text") or "").strip()
    if not full_text:
        return {
            "answer": "I can’t answer yet: this document doesn’t have extracted text available. Try again in a moment (processing may still be running), or upload a text/PDF version.",
            "sources": [],
        }

    tokens = re.findall(r"[a-zA-Z0-9]{3,}", question.lower())[:18]

    def _score(chunk: str) -> int:
        if not tokens:
            return 0
        hay = chunk.lower()
        score = 0
        for t in tokens:
            if t in hay:
                score += 2
                score += min(hay.count(t), 5)
        return score

    # Build lightweight, question-focused excerpts.
    chunk_size = 2200
    chunks: list[tuple[int, int, str]] = []
    for start in range(0, len(full_text), chunk_size):
        end = min(len(full_text), start + chunk_size)
        chunks.append((start, end, full_text[start:end]))

    ranked = sorted(
        [(s, e, c, _score(c)) for (s, e, c) in chunks],
        key=lambda x: x[3],
        reverse=True,
    )

    selected: list[tuple[str, int, int, str]] = []
    used_spans: set[tuple[int, int]] = set()

    # Always include the opening chunk for context.
    if chunks:
        s0, e0, c0 = chunks[0]
        selected.append(("E1", s0, e0, c0))
        used_spans.add((s0, e0))

    label_idx = 2
    for s, e, c, sc in ranked:
        if sc <= 0:
            continue
        if (s, e) in used_spans:
            continue
        selected.append((f"E{label_idx}", s, e, c))
        used_spans.add((s, e))
        label_idx += 1
        if len(selected) >= 7:
            break

    excerpt_blocks = "\n\n".join(
        [f"[{lbl}] (chars {s}-{e})\n{txt.strip()}" for (lbl, s, e, txt) in selected]
    )

    system_prompt = (
        "You are a disputes/legal assistant. Answer using ONLY the supplied excerpts from this one document. "
        "Cite the excerpt labels like [E2]. If the answer is not in the excerpts, say 'Not found in this document excerpts' "
        "and suggest what to search for or which section is likely relevant."
    )
    prompt = f"""
Document: {item.filename} (id={item.id})
Workspace: {workspace.name} ({workspace.code})

Question: {question}

Excerpts:
{excerpt_blocks}

Answer concisely, with citations like [E2].
""".strip()

    ai_text = await _complete_with_tool_fallback(
        tool_name="workspace_document",
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        task_type="workspace_document",
        max_tokens=1400,
        temperature=0.2,
    )
    answer = (ai_text or "").strip()
    if not answer:
        answer = "AI provider unavailable. I can’t answer reliably right now."

    sources = [
        {"label": lbl, "start": s, "end": e} for (lbl, s, e, _txt) in selected
    ]
    return {"answer": answer, "sources": sources}


@router.get("/{workspace_id}/documents/{doc_id}/download")
def download_workspace_document(
    workspace_id: str,
    doc_id: str,
    db: DbSession,
    user: CurrentUser,
):
    workspace = _require_workspace(db, workspace_id, user)
    doc_uuid = _parse_uuid(doc_id, "doc_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == doc_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")

    # Enforce workspace scope
    if (item.meta or {}).get("workspace_id") != str(workspace.id):  # type: ignore[union-attr]
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        url = presign_get(item.s3_key, bucket=item.s3_bucket, expires=3600)
    except Exception as exc:
        logger.error("Failed to presign download: %s", exc)
        raise HTTPException(
            status_code=500, detail="Failed to generate download URL"
        ) from exc

    return RedirectResponse(url=url)


@router.delete("/{workspace_id}/documents/{doc_id}")
def delete_workspace_document(
    workspace_id: str,
    doc_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    doc_uuid = _parse_uuid(doc_id, "doc_id")
    item = db.query(EvidenceItem).filter(EvidenceItem.id == doc_uuid).first()
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")

    if (item.meta or {}).get("workspace_id") != str(workspace.id):  # type: ignore[union-attr]
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        delete_object(item.s3_key, bucket=item.s3_bucket)
    except Exception:
        # best effort; still remove DB record
        pass

    db.delete(item)
    db.commit()

    return {"status": "success", "id": doc_id}


# ============================================================================
# Workspace About (AI context + Q&A + user notes)
# ============================================================================


@router.get("/{workspace_id}/about")
def get_workspace_about(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    about = (
        db.query(WorkspaceAbout)
        .filter(WorkspaceAbout.workspace_id == workspace.id)
        .first()
    )
    if not about:
        return {
            "workspace_id": str(workspace.id),
            "status": "empty",
            "summary": "",
            "open_questions": [],
            "user_notes": "",
            "updated_at": None,
        }

    data = about.data or {}
    open_questions = data.get("open_questions") if isinstance(data, dict) else None
    contracts = data.get("contracts") if isinstance(data, dict) else None
    structured = data.get("structured") if isinstance(data, dict) else None
    return {
        "workspace_id": str(workspace.id),
        "status": about.status,
        "summary": about.summary_md or "",
        "open_questions": open_questions if isinstance(open_questions, list) else [],
        "contracts": (
            contracts
            if isinstance(contracts, dict)
            else {"documents": [], "key_terms_overview": [], "gaps": []}
        ),
        "structured": structured if isinstance(structured, dict) else {},
        "user_notes": about.user_notes or "",
        "updated_at": about.updated_at.isoformat() if about.updated_at else None,
        "last_error": about.last_error,
    }


@router.post("/{workspace_id}/about/notes")
def save_workspace_about_notes(
    workspace_id: str,
    payload: AboutNotesRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    about = (
        db.query(WorkspaceAbout)
        .filter(WorkspaceAbout.workspace_id == workspace.id)
        .first()
    )
    if not about:
        about = WorkspaceAbout(workspace_id=workspace.id, status="empty")
        db.add(about)
        db.commit()
        db.refresh(about)

    about.user_notes = (payload.notes or "").strip() or None
    about.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(about)

    return {
        "workspace_id": str(workspace.id),
        "status": about.status,
        "user_notes": about.user_notes or "",
        "updated_at": about.updated_at.isoformat() if about.updated_at else None,
    }


async def _workspace_about_refresh_job(
    workspace_id: str, force: bool, deep: bool
) -> None:
    db = SessionLocal()
    try:
        ws_uuid = _parse_uuid(workspace_id, "workspace_id")
        ws = db.query(Workspace).filter(Workspace.id == ws_uuid).first()
        if not ws:
            return
        # Deep refresh: (re)process key workspace documents to ensure text/metadata exist
        # before generating the structured read-in. This is where we "max out" AWS services.
        if deep and enhanced_processor is not None:
            try:
                docs = (
                    _workspace_docs_query(db, ws.id)
                    .order_by(desc(EvidenceItem.created_at))
                    .limit(60)
                    .all()
                )
                to_process: list[EvidenceItem] = []
                for d in docs:
                    status = (d.processing_status or "").lower()
                    has_text = bool((d.extracted_text or "").strip())
                    md = (
                        d.extracted_metadata
                        if isinstance(d.extracted_metadata, dict)
                        else {}
                    )
                    has_tex = isinstance(md.get("textract_data"), dict)
                    if (
                        status not in ("ready", "completed")
                        or not has_text
                        or not has_tex
                    ):
                        to_process.append(d)
                # Cap to avoid runaway jobs; deep refresh can still be invoked again.
                for d in to_process[:12]:
                    try:
                        await enhanced_processor.process_evidence_item(str(d.id), db)
                    except Exception as e:
                        logger.info(
                            "Deep refresh doc processing failed for %s: %s", d.id, e
                        )
            except Exception as e:
                logger.info("Deep refresh pre-processing skipped: %s", e)
        await _build_workspace_about_snapshot(
            db=db, workspace=ws, force=force, deep=deep
        )
    finally:
        db.close()


@router.post("/{workspace_id}/about/refresh")
async def refresh_workspace_about(
    workspace_id: str,
    payload: AboutRefreshRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    about = (
        db.query(WorkspaceAbout)
        .filter(WorkspaceAbout.workspace_id == workspace.id)
        .first()
    )
    if not about:
        about = WorkspaceAbout(workspace_id=workspace.id, status="empty")
        db.add(about)
        db.commit()
        db.refresh(about)

    about.status = "building"
    about.last_error = None
    about.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(about)

    background_tasks.add_task(
        _workspace_about_refresh_job,
        str(workspace.id),
        bool(payload.force),
        bool(payload.force),
    )

    return {
        "workspace_id": str(workspace.id),
        "status": about.status,
        "summary": about.summary_md or "",
        "open_questions": (about.data or {}).get("open_questions", []),
        "contracts": (about.data or {}).get(
            "contracts", {"documents": [], "key_terms_overview": [], "gaps": []}
        ),
        "structured": (about.data or {}).get("structured", {}),
        "user_notes": about.user_notes or "",
        "updated_at": about.updated_at.isoformat() if about.updated_at else None,
    }


@router.post("/{workspace_id}/about/ask")
async def ask_workspace_about(
    workspace_id: str,
    payload: AboutAskRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    about = (
        db.query(WorkspaceAbout)
        .filter(WorkspaceAbout.workspace_id == workspace.id)
        .first()
    )
    user_notes = (about.user_notes if about else None) or ""
    about_summary = (about.summary_md if about else None) or ""
    about_contracts = (
        (about.data or {}).get("contracts", {})
        if about and isinstance(about.data, dict)
        else {}
    )
    purpose = (
        db.query(WorkspacePurpose)
        .filter(WorkspacePurpose.workspace_id == workspace.id)
        .first()
    )
    purpose_text = (purpose.purpose_text or "") if purpose else ""

    # Build evidence pool: workspace docs + related project/case evidence (bounded).
    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()
    cases = db.query(Case).filter(Case.workspace_id == workspace.id).all()
    project_ids = [p.id for p in projects]
    case_ids = [c.id for c in cases]
    instruction_item = _get_workspace_scoped_evidence(
        db,
        workspace=workspace,
        evidence_id=str(purpose.instructions_evidence_id)
        if purpose and purpose.instructions_evidence_id
        else None,
        project_ids=project_ids,
        case_ids=case_ids,
    )

    pool_conds = [
        EvidenceItem.meta.op("->>")("workspace_id") == str(workspace.id),
    ]
    if project_ids:
        pool_conds.append(EvidenceItem.project_id.in_(project_ids))
    if case_ids:
        pool_conds.append(EvidenceItem.case_id.in_(case_ids))

    pool = (
        db.query(EvidenceItem)
        .filter(or_(*pool_conds))
        .order_by(desc(EvidenceItem.created_at))
        .limit(200)
        .all()
    )
    if instruction_item and all(it.id != instruction_item.id for it in pool):
        pool.insert(0, instruction_item)

    # Pull correspondence (emails) from projects/cases in this workspace (bounded).
    email_pool = []
    try:
        from .models import EmailMessage

        email_conds = []
        if project_ids:
            email_conds.append(EmailMessage.project_id.in_(project_ids))
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
                .limit(260)
                .all()
            )
    except Exception:
        email_pool = []

    tokens = re.findall(r"[a-zA-Z0-9]{3,}", question.lower())[:14]
    purpose_hints = [
        "instruction",
        "instructions",
        "scope",
        "deliverable",
        "chronology",
        "contradiction",
        "responsibility",
        "causation",
        "inspection",
        "design",
        "water ingress",
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
                # reward multiple occurrences lightly
                score += min(hay.count(t), 4)
        return score

    ranked = sorted(pool, key=score_item, reverse=True)
    contract_ranked = [
        it for it in ranked if (it.evidence_type or "").lower() == "contract"
    ][:2]
    topical = [it for it in ranked if score_item(it) > 0][:4]
    top = []
    seen: set[str] = set()
    for it in contract_ranked + topical:
        sid = str(it.id)
        if sid in seen:
            continue
        top.append(it)
        seen.add(sid)
    top = top[:6] or ranked[:4]

    def score_email(em) -> int:
        try:
            subj = (em.subject or "")
            body = em.body_text_clean or em.body_preview or em.body_text or ""
            to = " ".join((em.recipients_to or [])[:8]) if em.recipients_to else ""
            hay = f"{subj} {em.sender_email or ''} {em.sender_name or ''} {to} {_safe_excerpt(body, 6000)}".lower()
            score = 0
            for t in tokens:
                if t in hay:
                    score += 2
                    score += min(hay.count(t), 4)
            if getattr(em, "has_attachments", False):
                score += 1
            return score
        except Exception:
            return 0

    ranked_emails = sorted(email_pool, key=score_email, reverse=True)
    top_emails = [em for em in ranked_emails if score_email(em) > 0][:3]
    if not top_emails and email_pool:
        # If the question is broad, still include a small slice of recent correspondence.
        top_emails = email_pool[:2]

    sources: list[dict[str, Any]] = []
    blocks: list[str] = []
    start_idx = 1
    if instruction_item:
        label = f"S{start_idx}"
        excerpt = _select_best_excerpt(
            instruction_item.extracted_text,
            1500,
            hints=excerpt_hints,
        ) or _select_best_excerpt(
            (
                (instruction_item.extracted_metadata or {}).get("text_preview")  # type: ignore[union-attr]
                if isinstance(instruction_item.extracted_metadata, dict)
                else ""
            ),
            1500,
            hints=excerpt_hints,
        )
        sources.append(
            {
                "label": label,
                "id": str(instruction_item.id),
                "filename": instruction_item.filename,
            }
        )
        if excerpt:
            blocks.append(
                f"[{label}] {instruction_item.filename} (id={instruction_item.id})\n{excerpt}"
            )
        start_idx += 1

    for idx, it in enumerate(top, start=start_idx):
        label = f"S{idx}"
        excerpt = _select_best_excerpt(it.extracted_text, 1400, hints=excerpt_hints)
        sources.append({"label": label, "id": str(it.id), "filename": it.filename})
        if excerpt:
            blocks.append(f"[{label}] {it.filename} (id={it.id})\n{excerpt}")

    start_idx = len(sources) + 1
    for i, em in enumerate(top_emails, start=start_idx):
        label = f"S{i}"
        subject = (getattr(em, "subject", None) or "(no subject)").strip()
        dt = em.date_sent.isoformat() if getattr(em, "date_sent", None) else None
        frm = (getattr(em, "sender_email", None) or getattr(em, "sender_name", None) or "Unknown").strip()
        to = ", ".join((getattr(em, "recipients_to", None) or [])[:6]) if getattr(em, "recipients_to", None) else ""
        if len(to) > 220:
            to = to[:220].rstrip() + "…"

        body = getattr(em, "body_text_clean", None) or getattr(em, "body_preview", None) or getattr(em, "body_text", None) or ""
        excerpt = _select_best_excerpt(body, 1200, hints=excerpt_hints)

        sources.append({"label": label, "id": str(em.id), "filename": f"Email: {subject}"})
        if excerpt:
            header = f"[{label}] Email: {subject} (id={em.id}, date={dt or 'unknown'})\nFrom: {frm}\nTo: {to or 'Unknown'}"
            if getattr(em, "has_attachments", False):
                header += "\nHas attachments: yes"
            blocks.append(f"{header}\n{excerpt}")

    system_prompt = (
        "You answer questions for lawyers/barristers about a workspace dispute. "
        "Use ONLY the supplied context (evidence + correspondence). Cite sources as [S#]. "
        "If unsure, say what is missing and propose the next document to request."
    )
    evidence_blocks_text = "\n\n".join(blocks) if blocks else "None"
    instruction_context = ""
    if instruction_item:
        instruction_context = f"{instruction_item.filename} (id={instruction_item.id})"

    prompt = f"""
Question: {question}

Authoritative user notes (ground truth):
{user_notes or "None"}

Purpose baseline:
{purpose_text or "None"}

Instruction baseline document:
{instruction_context or "None"}

Cached workspace summary:
{about_summary or "None"}

Contracts & key terms (cached):
{json.dumps(about_contracts, ensure_ascii=False)[:6000] if about_contracts else "None"}

Evidence + correspondence excerpts:
{evidence_blocks_text}

Answer concisely, with citations like [S1].
""".strip()

    ai_text = await _complete_with_tool_fallback(
        tool_name="workspace_about",
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        max_tokens=1400,
        temperature=0.2,
    )

    answer = (ai_text or "").strip()
    if not answer:
        answer = "AI provider unavailable. I can’t answer reliably yet; please upload key documents (contract, key correspondence, notices, schedules, valuations)."

    return {"answer": answer, "sources": sources}


# ============================================================================
# Workspace Purpose (baseline instructions + tracking)
# ============================================================================


async def _build_workspace_purpose_snapshot(
    *,
    db: Session,
    workspace: Workspace,
    force: bool = False,
    deep: bool = False,
) -> WorkspacePurpose:
    purpose = (
        db.query(WorkspacePurpose)
        .filter(WorkspacePurpose.workspace_id == workspace.id)
        .first()
    )
    if not purpose:
        purpose = WorkspacePurpose(workspace_id=workspace.id, status="empty")
        db.add(purpose)
        db.commit()
        db.refresh(purpose)

    latest_doc = (
        _workspace_docs_query(db, workspace.id)
        .order_by(desc(EvidenceItem.created_at))
        .first()
    )
    latest_doc_at = getattr(latest_doc, "created_at", None)
    if (
        not force
        and (purpose.status or "").lower() == "ready"
        and purpose.updated_at
        and latest_doc_at
        and purpose.updated_at >= latest_doc_at
    ):
        return purpose

    purpose.status = "building"
    purpose.last_error = None
    db.commit()

    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()
    cases = db.query(Case).filter(Case.workspace_id == workspace.id).all()
    project_ids = [p.id for p in projects]
    case_ids = [c.id for c in cases]

    purpose_text = (purpose.purpose_text or "").strip()
    instruction_item = _get_workspace_scoped_evidence(
        db,
        workspace=workspace,
        evidence_id=str(purpose.instructions_evidence_id)
        if purpose.instructions_evidence_id
        else None,
        project_ids=project_ids,
        case_ids=case_ids,
    )

    evidence_conds = [
        EvidenceItem.meta.op("->>")("workspace_id") == str(workspace.id),
    ]
    if project_ids:
        evidence_conds.append(EvidenceItem.project_id.in_(project_ids))
    if case_ids:
        evidence_conds.append(EvidenceItem.case_id.in_(case_ids))
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
    try:
        from .models import EmailMessage

        email_conds = []
        if project_ids:
            email_conds.append(EmailMessage.project_id.in_(project_ids))
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
    except Exception:
        email_pool = []

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
        "water ingress",
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

    def score_email_for_purpose(em) -> int:
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
        ):
            if k in subj:
                score += 20
        return score

    ranked_emails = sorted(email_pool, key=score_email_for_purpose, reverse=True)
    target_emails = 8 if deep else 5
    email_candidate_limit = 50 if deep else 25
    top_emails = ranked_emails[:target_emails]

    # Deep mode: rerank evidence/email candidates for purpose extraction (best-effort).
    if deep and getattr(settings, "BEDROCK_RERANK_ENABLED", False):
        try:
            aws = get_aws_services()
            rerank_query = (
                "Select the most relevant sources for building a purpose baseline from an instruction narrative. "
                "Prioritize instruction/scope, deliverables, chronology, responsibility/causation, inspections/defects, "
                "key notices, and any contradictions between parties' positions."
            )

            # Evidence rerank
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
                    header = f"{it.filename or 'Untitled'}" + (f" ({', '.join(meta)})" if meta else "")
                    ev_snippets.append(f"{header}\n{excerpt}")
                reranked = await aws.rerank_texts(
                    rerank_query, ev_snippets, top_n=min(target_evidence, len(ev_snippets))
                )
                ev_order = [int(r.get("index", -1)) for r in reranked if isinstance(r, dict)]
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

            # Email rerank
            cand_emails = ranked_emails[:email_candidate_limit]
            if len(cand_emails) > 3:
                em_snippets: list[str] = []
                for em in cand_emails:
                    subject = (em.subject or "(no subject)").strip()
                    dt = em.date_sent.isoformat() if em.date_sent else None
                    frm = (em.sender_email or em.sender_name or "Unknown").strip()
                    body = em.body_text_clean or em.body_preview or em.body_text or ""
                    excerpt = _select_best_excerpt(body, 800, hints=purpose_hints) or (body[:800])
                    header = f"Email: {subject}" + (f" (date={dt})" if dt else "")
                    em_snippets.append(f"{header}\nFrom: {frm}\n{excerpt}")
                reranked = await aws.rerank_texts(
                    rerank_query, em_snippets, top_n=min(target_emails, len(em_snippets))
                )
                em_order = [int(r.get("index", -1)) for r in reranked if isinstance(r, dict)]
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
                (instruction_item.extracted_metadata or {}).get("text_preview")  # type: ignore[union-attr]
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
                "document_date": instruction_item.document_date.isoformat()
                if instruction_item.document_date
                else None,
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

    system_prompt = (
        "You are a senior construction disputes barrister's assistant. "
        "Use ONLY the facts provided. Do NOT invent. "
        "If information is missing, say 'Unknown' and add an open question."
    )
    prompt = f"""
Build a baseline “Purpose” plan and tracking pack for this workspace.

Return ONE JSON object with keys:
- summary_md: string (plain text; use headings + bullets; reference the purpose baseline)
- baseline: object with fields {{goal_statement, deliverables, issue_groupings, keywords, sources}}
- tracking: array of objects {{deliverable, status, evidence, gaps, sources}}
- chronology: array {{date, party, issue_tags, quote, source}}
- contradictions: array {{statement_a, statement_b, explanation, sources}}
- evidence_organisation: object {{issue_groupings, keyword_map}}
- open_questions: array of strings
- sources: array of objects {{label, evidence_id, filename, document_date, evidence_type}}

Workspace:
- name: {workspace.name}
- code: {workspace.code}
- contract_type: {workspace.contract_type or "Unknown"}
- description: {workspace.description or "None"}

Purpose statement (authoritative if present):
{purpose_text or "None"}

Instruction baseline document:
{instruction_label}

Evidence + correspondence excerpts (cite sources like [S1], [S2]):
{evidence_blocks_text}
""".strip()

    # Always use the workspace tool so Bedrock Guardrails apply consistently.
    tool_name = "workspace_purpose"
    ai_text = await _complete_with_tool_fallback(
        tool_name=tool_name,
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        max_tokens=7000 if deep else 3200,
        temperature=0.2,
    )

    payload = _extract_json_object(ai_text) if ai_text else None
    if not payload:
        summary_lines = [
            f"Workspace: {workspace.name} ({workspace.code})",
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
            "evidence_organisation": {},
            "open_questions": [],
            "sources": sources,
        }

    purpose.summary_md = str(payload.get("summary_md") or payload.get("summary") or "")
    purpose.data = payload
    purpose.status = "ready"
    purpose.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(purpose)
    return purpose


async def _workspace_purpose_refresh_job(
    workspace_id: str, force: bool, deep: bool
) -> None:
    db = SessionLocal()
    try:
        ws_uuid = _parse_uuid(workspace_id, "workspace_id")
        ws = db.query(Workspace).filter(Workspace.id == ws_uuid).first()
        if not ws:
            return
        await _build_workspace_purpose_snapshot(
            db=db, workspace=ws, force=force, deep=deep
        )
    finally:
        db.close()


@router.get("/{workspace_id}/purpose")
def get_workspace_purpose(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    purpose = (
        db.query(WorkspacePurpose)
        .filter(WorkspacePurpose.workspace_id == workspace.id)
        .first()
    )
    if not purpose:
        return {
            "workspace_id": str(workspace.id),
            "status": "empty",
            "purpose_text": "",
            "instructions_evidence_id": None,
            "instructions_filename": None,
            "summary": "",
            "data": {},
            "updated_at": None,
        }

    instructions_filename = None
    if purpose.instructions_evidence_id:
        item = db.query(EvidenceItem).filter(
            EvidenceItem.id == purpose.instructions_evidence_id
        ).first()
        if item:
            instructions_filename = item.filename

    return {
        "workspace_id": str(workspace.id),
        "status": purpose.status,
        "purpose_text": purpose.purpose_text or "",
        "instructions_evidence_id": str(purpose.instructions_evidence_id)
        if purpose.instructions_evidence_id
        else None,
        "instructions_filename": instructions_filename,
        "summary": purpose.summary_md or "",
        "data": purpose.data or {},
        "updated_at": purpose.updated_at.isoformat() if purpose.updated_at else None,
        "last_error": purpose.last_error,
    }


@router.post("/{workspace_id}/purpose/config")
def save_workspace_purpose_config(
    workspace_id: str,
    payload: PurposeConfigRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    purpose = (
        db.query(WorkspacePurpose)
        .filter(WorkspacePurpose.workspace_id == workspace.id)
        .first()
    )
    if not purpose:
        purpose = WorkspacePurpose(workspace_id=workspace.id, status="empty")
        db.add(purpose)
        db.commit()
        db.refresh(purpose)

    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()
    cases = db.query(Case).filter(Case.workspace_id == workspace.id).all()
    project_ids = [p.id for p in projects]
    case_ids = [c.id for c in cases]

    instruction_item = _get_workspace_scoped_evidence(
        db,
        workspace=workspace,
        evidence_id=payload.instructions_evidence_id,
        project_ids=project_ids,
        case_ids=case_ids,
    )
    if payload.instructions_evidence_id and not instruction_item:
        raise HTTPException(status_code=404, detail="Instruction document not found")

    purpose.purpose_text = (payload.purpose_text or "").strip() or None
    purpose.instructions_evidence_id = (
        instruction_item.id if instruction_item else None
    )
    purpose.status = "empty"
    purpose.last_error = None
    purpose.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(purpose)

    return {
        "workspace_id": str(workspace.id),
        "status": purpose.status,
        "purpose_text": purpose.purpose_text or "",
        "instructions_evidence_id": str(purpose.instructions_evidence_id)
        if purpose.instructions_evidence_id
        else None,
        "updated_at": purpose.updated_at.isoformat() if purpose.updated_at else None,
    }


@router.post("/{workspace_id}/purpose/refresh")
def refresh_workspace_purpose(
    workspace_id: str,
    payload: PurposeRefreshRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    purpose = (
        db.query(WorkspacePurpose)
        .filter(WorkspacePurpose.workspace_id == workspace.id)
        .first()
    )
    if not purpose:
        purpose = WorkspacePurpose(workspace_id=workspace.id, status="empty")
        db.add(purpose)
        db.commit()
        db.refresh(purpose)

    purpose.status = "building"
    purpose.last_error = None
    purpose.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(purpose)

    background_tasks.add_task(
        _workspace_purpose_refresh_job,
        str(workspace.id),
        bool(payload.force),
        bool(payload.deep),
    )

    return {
        "workspace_id": str(workspace.id),
        "status": purpose.status,
        "summary": purpose.summary_md or "",
        "purpose_text": purpose.purpose_text or "",
        "updated_at": purpose.updated_at.isoformat() if purpose.updated_at else None,
    }


@router.post("/{workspace_id}/purpose/ask")
async def ask_workspace_purpose(
    workspace_id: str,
    payload: PurposeAskRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    workspace = _require_workspace(db, workspace_id, user)
    question = (payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    purpose = (
        db.query(WorkspacePurpose)
        .filter(WorkspacePurpose.workspace_id == workspace.id)
        .first()
    )
    purpose_text = (purpose.purpose_text if purpose else None) or ""
    purpose_summary = (purpose.summary_md if purpose else None) or ""

    projects = db.query(Project).filter(Project.workspace_id == workspace.id).all()
    cases = db.query(Case).filter(Case.workspace_id == workspace.id).all()
    project_ids = [p.id for p in projects]
    case_ids = [c.id for c in cases]

    instruction_item = _get_workspace_scoped_evidence(
        db,
        workspace=workspace,
        evidence_id=str(purpose.instructions_evidence_id)
        if purpose and purpose.instructions_evidence_id
        else None,
        project_ids=project_ids,
        case_ids=case_ids,
    )

    pool_conds = [
        EvidenceItem.meta.op("->>")("workspace_id") == str(workspace.id),
    ]
    if project_ids:
        pool_conds.append(EvidenceItem.project_id.in_(project_ids))
    if case_ids:
        pool_conds.append(EvidenceItem.case_id.in_(case_ids))

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
    try:
        from .models import EmailMessage

        email_conds = []
        if project_ids:
            email_conds.append(EmailMessage.project_id.in_(project_ids))
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
    except Exception:
        email_pool = []

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
        "water ingress",
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

    def score_email(em) -> int:
        subj = (em.subject or "")
        body = em.body_text_clean or em.body_preview or em.body_text or ""
        hay = f"{subj} {em.sender_email or ''} {em.sender_name or ''} {_safe_excerpt(body, 6000)}".lower()
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
                (instruction_item.extracted_metadata or {}).get("text_preview")  # type: ignore[union-attr]
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
        excerpt = _select_best_excerpt(it.extracted_text, 1200, hints=excerpt_hints)
        sources.append({"label": label, "id": str(it.id), "filename": it.filename})
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
        excerpt = _select_best_excerpt(body, 1200, hints=excerpt_hints)
        sources.append({"label": label, "id": str(em.id), "filename": f"Email: {subject}"})
        if excerpt:
            header = f"[{label}] Email: {subject} (id={em.id}, date={dt or 'unknown'})\nFrom: {frm}\nTo: {to or 'Unknown'}"
            if em.has_attachments:
                header += "\nHas attachments: yes"
            blocks.append(f"{header}\n{excerpt}")
        label_idx += 1

    evidence_blocks_text = "\n\n".join(blocks) if blocks else "None"
    instruction_context = ""
    if instruction_item:
        instruction_context = f"{instruction_item.filename} (id={instruction_item.id})"

    system_prompt = (
        "You answer questions for lawyers/barristers about a workspace purpose baseline. "
        "Use ONLY the supplied context. Cite sources as [S#]. "
        "If unsure, say what is missing and propose the next document to request."
    )
    prompt = f"""
Question: {question}

Purpose baseline:
{purpose_text or "None"}

Instruction baseline document:
{instruction_context or "None"}

Purpose snapshot summary:
{purpose_summary or "None"}

Evidence + correspondence excerpts:
{evidence_blocks_text}

Answer concisely, with citations like [S1].
""".strip()

    ai_text = await _complete_with_tool_fallback(
        tool_name="workspace_purpose",
        prompt=prompt,
        system_prompt=system_prompt,
        db=db,
        max_tokens=1400,
        temperature=0.2,
    )

    answer = (ai_text or "").strip()
    if not answer:
        answer = "AI provider unavailable. I can’t answer reliably yet; please upload key documents and the instruction baseline."

    return {"answer": answer, "sources": sources}
