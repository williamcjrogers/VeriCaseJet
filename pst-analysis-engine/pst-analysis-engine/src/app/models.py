import uuid
from sqlalchemy import Column, String, DateTime, Text, JSON, Enum, Integer, ForeignKey, Boolean
from sqlalchemy.sql import func, expression
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum
from .db import Base

class DocStatus(str, PyEnum):
    NEW="NEW"; PROCESSING="PROCESSING"; READY="READY"; FAILED="FAILED"

class UserRole(str, PyEnum):
    ADMIN="ADMIN"; EDITOR="EDITOR"; VIEWER="VIEWER"

class User(Base):
    __tablename__="users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.EDITOR)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    display_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
class Document(Base):
    __tablename__="documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(512), nullable=False)
    path = Column(String(1024), nullable=True)
    content_type = Column(String(128), nullable=True)
    size = Column(Integer, nullable=True)
    bucket = Column(String(128), nullable=False)
    s3_key = Column(String(2048), nullable=False)
    status = Column(Enum(DocStatus), nullable=False, default=DocStatus.NEW)
    title = Column(String(512), nullable=True)
    meta = Column("metadata", JSON, nullable=True)
    text_excerpt = Column(Text, nullable=True)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    last_accessed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_private = Column(Boolean, nullable=False, server_default=expression.false())
    workspace_type = Column(String(20), nullable=False, server_default="shared")
    owner = relationship("User", foreign_keys=[owner_user_id])
    last_accessed_user = relationship("User", foreign_keys=[last_accessed_by])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
class Folder(Base):
    __tablename__="folders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    path = Column(String(1024), nullable=False)
    name = Column(String(255), nullable=False)
    parent_path = Column(String(1024), nullable=True)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    owner = relationship("User")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class ShareLink(Base):
    __tablename__="share_links"
    token = Column(String(64), primary_key=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document = relationship("Document")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    password_hash = Column(String(255), nullable=True)

class UserInvitation(Base):
    __tablename__="user_invitations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, index=True)
    invited_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    inviter = relationship("User", foreign_keys=[invited_by])
    role = Column(Enum(UserRole), nullable=False, default=UserRole.VIEWER)
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DocumentShare(Base):
    __tablename__="document_shares"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document = relationship("Document")
    shared_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    sharer = relationship("User", foreign_keys=[shared_by])
    shared_with = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    recipient = relationship("User", foreign_keys=[shared_with])
    permission = Column(String(20), nullable=False, default='view')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class FolderShare(Base):
    __tablename__="folder_shares"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    folder_path = Column(String(500), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    owner = relationship("User", foreign_keys=[owner_id])
    shared_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    sharer = relationship("User", foreign_keys=[shared_by])
    shared_with = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    recipient = relationship("User", foreign_keys=[shared_with])
    permission = Column(String(20), nullable=False, default='view')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Favorite(Base):
    __tablename__="favorites"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user = relationship("User")
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document = relationship("Document")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DocumentVersion(Base):
    __tablename__="document_versions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    document = relationship("Document")
    version_number = Column(Integer, nullable=False)
    s3_key = Column(String(2048), nullable=False)
    filename = Column(String(512), nullable=False)
    size = Column(Integer, nullable=True)
    content_type = Column(String(128), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    creator = relationship("User")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    comment = Column(Text, nullable=True)

# ============================================================================
# LEGAL DOMAIN MODELS - Case Management
# ============================================================================

class Company(Base):
    """Multi-tenant company workspace"""
    __tablename__="companies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), unique=True, nullable=True)
    subscription_tier = Column(String(50), default="professional")
    storage_limit_gb = Column(Integer, default=100)
    is_active = Column(Boolean, default=True)
    logo_url = Column(String(500), nullable=True)
    primary_color = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class UserCompany(Base):
    """Many-to-many: Users can belong to multiple companies"""
    __tablename__="user_companies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    role = Column(String(50), default="user")  # admin, manager, user, viewer
    is_primary = Column(Boolean, default=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User")
    company = relationship("Company")

class Case(Base):
    """Legal case with construction-specific fields"""
    __tablename__="cases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_number = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text)
    project_name = Column(String(500))
    contract_type = Column(String(100))  # JCT, NEC, FIDIC
    dispute_type = Column(String(100))   # Delay, Defects, Variation
    status = Column(String(50), default="active")  # active, closed, archived
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    owner = relationship("User")
    company = relationship("Company")

class CaseUser(Base):
    """Case team members with roles"""
    __tablename__="case_users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role = Column(String(50), default="viewer")  # admin, editor, viewer
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    added_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    case = relationship("Case")
    user = relationship("User", foreign_keys=[user_id])

class Issue(Base):
    """Legal issues within a case"""
    __tablename__="issues"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    issue_type = Column(String(100))  # Liability, Causation, Quantum
    status = Column(String(50), default="open")  # open, resolved, disputed
    relevant_contract_clauses = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    case = relationship("Case")

class Evidence(Base):
    """Evidence linking documents to cases and issues"""
    __tablename__="evidence"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    issue_id = Column(UUID(as_uuid=True), ForeignKey("issues.id"), nullable=True)
    evidence_type = Column(String(100))  # email, contract, photo, expert_report
    exhibit_number = Column(String(50), nullable=True)
    date_of_evidence = Column(DateTime(timezone=True), nullable=True)
    email_from = Column(String(255), nullable=True)
    email_to = Column(String(500), nullable=True)
    email_cc = Column(String(500), nullable=True)
    email_subject = Column(String(500), nullable=True)
    email_date = Column(DateTime(timezone=True), nullable=True)
    email_message_id = Column(String(500), nullable=True, index=True)  # For threading
    email_in_reply_to = Column(String(500), nullable=True, index=True)  # For threading
    email_thread_topic = Column(String(500), nullable=True)
    email_conversation_index = Column(String(500), nullable=True)
    thread_id = Column(String(100), nullable=True, index=True)  # Computed thread ID
    content = Column(Text, nullable=True)  # Email body stored directly
    content_type = Column(String(50), nullable=True)  # html or text
    attachments = Column(JSON, nullable=True)  # Array of attachment info
    relevance_score = Column(Integer, nullable=True)
    notes = Column(Text)
    meta = Column("metadata", JSON, nullable=True)
    as_planned_date = Column(DateTime(timezone=False), nullable=True)
    as_planned_activity = Column(String(500), nullable=True)
    as_built_date = Column(DateTime(timezone=False), nullable=True)
    as_built_activity = Column(String(500), nullable=True)
    delay_days = Column(Integer, nullable=True, server_default="0")
    is_critical_path = Column(Boolean, nullable=False, server_default=expression.false())
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    added_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    case = relationship("Case")
    document = relationship("Document")
    issue = relationship("Issue")

class ClaimType(str, PyEnum):
    DELAY = "delay"
    DEFECT = "defect"
    VARIATION = "variation"
    EOT = "extension_of_time"
    LOSS_EXPENSE = "loss_and_expense"
    OTHER = "other"

class Claim(Base):
    """Construction claims (delay, defects, variations)"""
    __tablename__="claims"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    claim_type = Column(Enum(ClaimType), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    claimed_amount = Column(Integer, nullable=True)  # Store in cents
    currency = Column(String(10), default="GBP")
    claim_date = Column(DateTime(timezone=True))
    response_due_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="draft")  # draft, submitted, under_review, accepted, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    case = relationship("Case")

class ChronologyItem(Base):
    """Timeline events for cases"""
    __tablename__="chronology_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    claim_id = Column(UUID(as_uuid=True), ForeignKey("claims.id"), nullable=True)
    event_date = Column(DateTime(timezone=True), nullable=False, index=True)
    event_type = Column(String(100))  # notice, meeting, correspondence, site_event
    title = Column(String(500), nullable=False)
    description = Column(Text)
    evidence_ids = Column(JSON)  # List of evidence IDs
    parties_involved = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    case = relationship("Case")
    claim = relationship("Claim")

class Rebuttal(Base):
    """Arguments and counter-arguments for issues"""
    __tablename__="rebuttals"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issue_id = Column(UUID(as_uuid=True), ForeignKey("issues.id"), nullable=False)
    title = Column(String(500), nullable=False)
    argument = Column(Text, nullable=False)
    counter_argument = Column(Text)
    supporting_evidence_ids = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    issue = relationship("Issue")

class ContractClause(Base):
    """Parsed contract clauses with unique IDs"""
    __tablename__="contract_clauses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    clause_id = Column(String(50), nullable=False)  # e.g., "4.2.1"
    clause_text = Column(Text, nullable=False)
    clause_title = Column(String(500))
    parent_clause_id = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    case = relationship("Case")
    document = relationship("Document")

class SearchQuery(Base):
    """Search analytics"""
    __tablename__="search_queries"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    query_text = Column(String(1000), nullable=False)
    query_type = Column(String(50))  # keyword, semantic, hybrid
    filters_applied = Column(JSON)
    results_count = Column(Integer)
    execution_time_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User")
    company = relationship("Company")
    case = relationship("Case")

class Programme(Base):
    """Construction programme/schedule (Asta Powerproject or PDF)"""
    __tablename__="programmes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    programme_type = Column(String(50), nullable=False)  # as_planned, as_built, interim
    programme_date = Column(DateTime(timezone=True), nullable=True)
    version_number = Column(String(50), nullable=True)
    file_format = Column(String(20))  # asta_pp, asta_xml, pdf, mpp, primavera
    activities = Column(JSON)  # Activity data
    critical_path = Column(JSON)  # Critical path activity IDs
    milestones = Column(JSON)
    project_start = Column(DateTime(timezone=True))
    project_finish = Column(DateTime(timezone=True))
    data_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    uploaded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    case = relationship("Case")
    document = relationship("Document")

class DelayEvent(Base):
    """Identified delay/slippage between as-planned and as-built"""
    __tablename__="delay_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    as_planned_programme_id = Column(UUID(as_uuid=True), ForeignKey("programmes.id"))
    as_built_programme_id = Column(UUID(as_uuid=True), ForeignKey("programmes.id"))
    activity_id = Column(String(100))
    activity_name = Column(String(500))
    planned_start = Column(DateTime(timezone=True))
    actual_start = Column(DateTime(timezone=True))
    planned_finish = Column(DateTime(timezone=True))
    actual_finish = Column(DateTime(timezone=True))
    delay_days = Column(Integer)
    delay_type = Column(String(50))  # critical, non_critical, concurrent
    is_on_critical_path = Column(Boolean, default=False)
    delay_cause = Column(String(100))  # employer, contractor, neutral, concurrent
    description = Column(Text)
    linked_correspondence_ids = Column(JSON)  # Document IDs of related emails
    linked_issue_id = Column(UUID(as_uuid=True), ForeignKey("issues.id"), nullable=True)
    eot_entitlement_days = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    case = relationship("Case")
    issue = relationship("Issue")
