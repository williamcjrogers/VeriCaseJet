import uuid
from sqlalchemy import Column, String, DateTime, Text, JSON, Enum, Integer, ForeignKey, Boolean, Index, ARRAY
from sqlalchemy.sql import func, expression
from sqlalchemy.dialects.postgresql import UUID, JSONB
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
    
    # Enhanced security fields
    email_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String(255), nullable=True)
    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_failed_attempt = Column(DateTime(timezone=True), nullable=True)
    password_changed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    password_history = relationship("PasswordHistory", back_populates="user", cascade="all, delete-orphan")
    login_attempts = relationship("LoginAttempt", back_populates="user", cascade="all, delete-orphan")

class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_jti = Column(String(255), nullable=False, unique=True, index=True)
    ip_address = Column(String(45), nullable=True)  # Supports both IPv4 and IPv6
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_activity = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="sessions")

class PasswordHistory(Base):
    __tablename__ = "password_history"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="password_history")

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    failure_reason = Column(String(100), nullable=True)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="login_attempts")
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
    company_name = Column(String(255), nullable=False)
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
    case_id_custom = Column(String(100), nullable=True, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text)
    project_name = Column(String(500))
    contract_type = Column(String(100))  # JCT, NEC, FIDIC
    dispute_type = Column(String(100))   # Delay, Defects, Variation
    status = Column(String(50), default="active")  # active, closed, archived
    case_status = Column(String(50), nullable=True)
    resolution_route = Column(String(100), nullable=True)
    claimant = Column(String(255), nullable=True)
    defendant = Column(String(255), nullable=True)
    client = Column(String(255), nullable=True)
    legal_team = Column(JSON, nullable=True)
    heads_of_claim = Column(JSON, nullable=True)
    deadlines = Column(JSON, nullable=True)
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
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
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
    attachments = Column(JSONB, nullable=True)  # Array of attachment info
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


# ========================================
# PST ANALYSIS SPECIFIC MODELS
# ========================================

class Project(Base):
    """Project management for construction/engineering projects"""
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_name = Column(String(255), nullable=False)
    project_code = Column(String(100), unique=True, nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=True)
    completion_date = Column(DateTime(timezone=True), nullable=True)
    contract_type = Column(String(100), nullable=True)
    # Retrospective analysis fields
    analysis_type = Column(String(50), nullable=True, default='project')  # 'retrospective' or 'project'
    project_aliases = Column(Text, nullable=True)  # Comma-separated alternative names
    site_address = Column(Text, nullable=True)
    include_domains = Column(Text, nullable=True)  # Comma-separated domains
    exclude_people = Column(Text, nullable=True)  # Comma-separated names/emails
    project_terms = Column(Text, nullable=True)  # Project-specific terms
    exclude_keywords = Column(Text, nullable=True)  # Keywords to exclude
    meta = Column("metadata", JSON, nullable=True, default=lambda: {})  # Flexible storage for refinements etc
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    owner = relationship("User")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PSTFile(Base):
    """Uploaded PST files for email forensics"""
    __tablename__ = "pst_files"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(512), nullable=False)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)  # Fixed: DB allows NULL
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    s3_bucket = Column(String(128), nullable=True)  # Fixed: DB allows NULL
    s3_key = Column(String(2048), nullable=False)
    file_size_bytes = Column("file_size_bytes", Integer, nullable=True)  # Fixed: Match DB column name
    total_emails = Column(Integer, default=0)
    processed_emails = Column(Integer, default=0)
    processing_status = Column(String(50), default='pending')  # Fixed: Match DB default
    processing_started_at = Column(DateTime(timezone=False), nullable=True)  # Fixed: DB has no timezone
    processing_completed_at = Column(DateTime(timezone=False), nullable=True)  # Fixed: DB has no timezone
    error_message = Column(Text, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    uploader = relationship("User")
    case = relationship("Case")
    project = relationship("Project")
    uploaded_at = Column("uploaded_at", DateTime(timezone=False), server_default=func.now())  # Fixed: Match DB column name


class EmailMessage(Base):
    """Extracted email messages from PST files with forensic metadata"""
    __tablename__ = "email_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pst_file_id = Column(UUID(as_uuid=True), ForeignKey("pst_files.id"), nullable=False)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)  # Now nullable
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)  # New field
    
    # Email metadata
    message_id = Column(String(512), nullable=True, index=True)  # RFC message-id
    in_reply_to = Column(String(512), nullable=True)
    email_references = Column(Text, nullable=True)  # For threading (renamed from references)
    conversation_index = Column(String(1024), nullable=True)
    thread_id = Column(String(100), nullable=True, index=True)  # Computed thread ID for grouping
    
    # PST forensic data
    pst_message_offset = Column(Integer, nullable=True)  # Position in PST file
    pst_message_path = Column(Text, nullable=True)  # Folder path in PST
    
    # Email content
    subject = Column(Text, nullable=True)
    sender_email = Column(String(512), nullable=True, index=True)
    sender_name = Column(String(512), nullable=True)
    recipients_to = Column(ARRAY(Text), nullable=True)  # Array of recipients
    recipients_cc = Column(ARRAY(Text), nullable=True)
    recipients_bcc = Column(ARRAY(Text), nullable=True)
    date_sent = Column(DateTime(timezone=True), nullable=True, index=True)
    date_received = Column(DateTime(timezone=True), nullable=True)
    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)

    # Canonical body and deduplication
    body_text_clean = Column(Text, nullable=True)  # Top-message canonical text (quotes stripped, normalised)
    content_hash = Column(String(128), nullable=True)  # Hash of canonical body + key metadata
    
    # Flags
    has_attachments = Column(Boolean, default=False)
    is_read = Column(Boolean, default=False)
    importance = Column(String(20), nullable=True)  # high, normal, low
    
    # Tagging (populated during processing)
    matched_stakeholders = Column(JSONB, nullable=True)  # Array of stakeholder IDs
    matched_keywords = Column(JSONB, nullable=True)  # Array of keyword IDs
    
    # Storage optimization: Store only preview if body is too large
    body_preview = Column(Text, nullable=True)  # First 10KB
    body_full_s3_key = Column(String(512), nullable=True)  # S3 key if body > 10KB
    
    # Flexible metadata storage
    meta = Column("metadata", JSON, nullable=True, default=lambda: {})
    
    pst_file = relationship("PSTFile")
    case = relationship("Case")
    project = relationship("Project")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Add indexes for performance
    __table_args__ = (
        Index('idx_email_case_date', 'case_id', 'date_sent'),
        Index('idx_email_project_date', 'project_id', 'date_sent'),
        Index('idx_email_stakeholders', 'matched_stakeholders', postgresql_using='gin'),
        Index('idx_email_keywords', 'matched_keywords', postgresql_using='gin'),
        Index('idx_email_has_attachments', 'case_id', 'has_attachments'),
        Index('idx_email_project_has_attachments', 'project_id', 'has_attachments'),
        Index('idx_email_conversation', 'case_id', 'conversation_index'),
        Index('idx_email_project_conversation', 'project_id', 'conversation_index'),
        Index('idx_email_case_content_hash', 'case_id', 'content_hash'),
        Index('idx_email_project_content_hash', 'project_id', 'content_hash'),
    )


class EmailAttachment(Base):
    """Email attachments extracted from PST files"""
    __tablename__ = "email_attachments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_message_id = Column(UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True)
    filename = Column(String(512), nullable=True)
    content_type = Column(String(128), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    s3_bucket = Column(String(128), nullable=True)
    s3_key = Column(String(2048), nullable=True)

    # Deduplication and inline metadata
    attachment_hash = Column(String(128), nullable=True)
    is_inline = Column(Boolean, default=False)
    content_id = Column(String(512), nullable=True)
    is_duplicate = Column(Boolean, default=False)
    
    # OCR/extraction status
    has_been_ocred = Column(Boolean, default=False)
    extracted_text = Column(Text, nullable=True)
    
    email_message = relationship("EmailMessage")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_email_attachment_hash', 'attachment_hash'),
    )


class Stakeholder(Base):
    """Stakeholders for auto-tagging emails"""
    __tablename__ = "stakeholders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    
    role = Column(String(255), nullable=False)  # e.g., "Main Contractor", "Client"
    name = Column(String(512), nullable=False)
    email = Column(String(512), nullable=True)
    organization = Column(String(512), nullable=True)
    
    # For fuzzy matching
    email_domain = Column(String(255), nullable=True)  # Extracted domain for matching
    
    case = relationship("Case")
    project = relationship("Project")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Keyword(Base):
    """Keywords for auto-tagging emails"""
    __tablename__ = "keywords"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    
    keyword_name = Column(String(255), nullable=False)
    variations = Column(Text, nullable=True)  # Comma-separated variations
    is_regex = Column(Boolean, default=False)
    
    case = relationship("Case")
    project = relationship("Project")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Programme(Base):
    """Construction programmes (Asta Powerproject, MS Project, etc.)"""
    __tablename__ = "programmes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    
    programme_name = Column(String(255), nullable=False)
    programme_type = Column(String(100), nullable=False)  # baseline, actual, as-built, etc.
    programme_date = Column(DateTime(timezone=True), nullable=True)
    version_number = Column(String(50), nullable=True)
    
    # File storage
    filename = Column(String(512), nullable=False)
    s3_bucket = Column(String(128), nullable=False)
    s3_key = Column(String(2048), nullable=False)
    file_format = Column(String(50), nullable=True)  # XML, PP, MPP
    
    # Parsed data (JSON)
    activities = Column(JSON, nullable=True)
    critical_path = Column(JSON, nullable=True)
    milestones = Column(JSON, nullable=True)
    
    # Summary dates
    project_start = Column(DateTime(timezone=True), nullable=True)
    project_finish = Column(DateTime(timezone=True), nullable=True)
    
    notes = Column(Text, nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    uploader = relationship("User")
    case = relationship("Case")
    project = relationship("Project")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """Application settings that can be modified by admins"""
    __tablename__ = "app_settings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    updater = relationship("User")


# ============================================================================
# EVIDENCE REPOSITORY MODELS
# Case-independent evidence management system
# ============================================================================

class EvidenceType(str, PyEnum):
    """Classification of evidence types"""
    CONTRACT = "contract"
    VARIATION = "variation"
    DRAWING = "drawing"
    SPECIFICATION = "specification"
    PROGRAMME = "programme"
    INVOICE = "invoice"
    PAYMENT_CERTIFICATE = "payment_certificate"
    MEETING_MINUTES = "meeting_minutes"
    SITE_INSTRUCTION = "site_instruction"
    RFI = "rfi"
    NOTICE = "notice"
    LETTER = "letter"
    EMAIL = "email"
    PHOTO = "photo"
    EXPERT_REPORT = "expert_report"
    CLAIM = "claim"
    EOT_NOTICE = "eot_notice"
    DELAY_NOTICE = "delay_notice"
    PROGRESS_REPORT = "progress_report"
    QUALITY_RECORD = "quality_record"
    OTHER = "other"


class DocumentCategory(str, PyEnum):
    """Construction-specific document categories"""
    JCT_RELEVANT_EVENT = "jct_relevant_event"
    JCT_EXTENSION_TIME = "jct_extension_time"
    JCT_LOSS_EXPENSE = "jct_loss_expense"
    NEC_COMPENSATION_EVENT = "nec_compensation_event"
    NEC_EARLY_WARNING = "nec_early_warning"
    FIDIC_CLAIM = "fidic_claim"
    FIDIC_VARIATION = "fidic_variation"
    CONTEMPORANEOUS = "contemporaneous"
    RETROSPECTIVE = "retrospective"
    WITNESS_STATEMENT = "witness_statement"
    TECHNICAL = "technical"
    FINANCIAL = "financial"
    LEGAL = "legal"
    CORRESPONDENCE = "correspondence"
    OTHER = "other"


class EvidenceSourceType(str, PyEnum):
    """Source types for evidence provenance"""
    PST_ATTACHMENT = "pst_attachment"
    DIRECT_UPLOAD = "direct_upload"
    BULK_IMPORT = "bulk_import"
    EMAIL_EXPORT = "email_export"
    SCAN = "scan"
    API = "api"
    MIGRATION = "migration"


class CorrespondenceLinkType(str, PyEnum):
    """Types of links between evidence and correspondence"""
    ATTACHMENT = "attachment"
    MENTIONED = "mentioned"
    RELATED = "related"
    SAME_THREAD = "same_thread"
    REPLY_TO = "reply_to"
    FORWARDS = "forwards"
    REFERENCES = "references"


class EvidenceRelationType(str, PyEnum):
    """Types of relationships between evidence items"""
    SUPERSEDES = "supersedes"
    REFERENCES = "references"
    RESPONDS_TO = "responds_to"
    AMENDS = "amends"
    DUPLICATE = "duplicate"
    VERSION_OF = "version_of"
    RELATED = "related"
    CONTRADICTS = "contradicts"


class EvidenceProcessingStatus(str, PyEnum):
    """Processing status for evidence items"""
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class EvidenceSource(Base):
    """Track provenance of evidence (PST files, bulk imports, etc.)"""
    __tablename__ = "evidence_sources"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Source identification
    source_type = Column(String(50), nullable=False)
    source_name = Column(String(500), nullable=False)
    source_path = Column(Text, nullable=True)
    source_description = Column(Text, nullable=True)
    
    # For PST files (optional link)
    pst_file_id = Column(UUID(as_uuid=True), ForeignKey("pst_files.id"), nullable=True)
    
    # Original file storage
    original_s3_bucket = Column(String(128), nullable=True)
    original_s3_key = Column(String(2048), nullable=True)
    original_hash = Column(String(128), nullable=True)
    original_size = Column(Integer, nullable=True)
    
    # Processing statistics
    total_items = Column(Integer, default=0)
    processed_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
    duplicate_items = Column(Integer, default=0)
    
    # Processing status
    status = Column(String(50), default='pending')
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Optional associations
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    
    # Audit
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    pst_file = relationship("PSTFile")
    case = relationship("Case")
    project = relationship("Project")
    uploader = relationship("User")


class EvidenceCollection(Base):
    """Virtual folders for organizing evidence"""
    __tablename__ = "evidence_collections"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Collection info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    collection_type = Column(String(50), default='manual')  # manual, smart, auto_date, auto_type
    
    # Smart collection rules
    filter_rules = Column(JSONB, default=dict)
    
    # Hierarchy support
    parent_id = Column(UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=True)
    path = Column(Text, nullable=True)  # Materialized path
    depth = Column(Integer, default=0)
    
    # Optional associations
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    
    # Display settings
    color = Column(String(20), nullable=True)
    icon = Column(String(50), nullable=True)
    sort_order = Column(Integer, default=0)
    is_system = Column(Boolean, default=False)
    
    # Statistics
    item_count = Column(Integer, default=0)
    
    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    parent = relationship("EvidenceCollection", remote_side=[id], backref="children")
    case = relationship("Case")
    project = relationship("Project")
    creator = relationship("User")


class EvidenceItem(Base):
    """Core evidence repository - NOT case-dependent"""
    __tablename__ = "evidence_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Core file metadata
    filename = Column(String(512), nullable=False)
    original_path = Column(Text, nullable=True)
    file_type = Column(String(50), nullable=True)
    mime_type = Column(String(128), nullable=True)
    file_size = Column(Integer, nullable=True)
    file_hash = Column(String(128), nullable=False)  # SHA-256
    
    # Storage
    s3_bucket = Column(String(128), nullable=False)
    s3_key = Column(String(2048), nullable=False)
    thumbnail_s3_key = Column(String(2048), nullable=True)
    
    # Classification
    evidence_type = Column(String(100), nullable=True)
    document_category = Column(String(100), nullable=True)
    
    # Auto-extracted metadata
    document_date = Column(DateTime(timezone=False), nullable=True)
    document_date_confidence = Column(Integer, nullable=True)  # 0-100
    title = Column(String(500), nullable=True)
    author = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    
    # Full-text content
    extracted_text = Column(Text, nullable=True)
    text_language = Column(String(10), default='en')
    
    # Entity extraction (auto-populated)
    extracted_parties = Column(JSONB, default=list)
    extracted_dates = Column(JSONB, default=list)
    extracted_amounts = Column(JSONB, default=list)
    extracted_references = Column(JSONB, default=list)
    extracted_locations = Column(JSONB, default=list)
    
    # Auto-tagging
    auto_tags = Column(JSONB, default=list)
    manual_tags = Column(JSONB, default=list)
    keywords_matched = Column(JSONB, default=list)
    stakeholders_matched = Column(JSONB, default=list)
    
    # Comprehensive metadata (from extraction service)
    extracted_metadata = Column(JSONB, nullable=True)  # Full metadata from MetadataExtractor
    metadata_extracted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Classification confidence
    classification_confidence = Column(Integer, nullable=True)  # 0-100
    classification_method = Column(String(50), nullable=True)
    
    # Processing status
    processing_status = Column(String(50), default='pending')
    processing_error = Column(Text, nullable=True)
    ocr_completed = Column(Boolean, default=False)
    ai_analyzed = Column(Boolean, default=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Provenance
    source_type = Column(String(50), nullable=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("evidence_sources.id"), nullable=True)
    source_path = Column(Text, nullable=True)
    source_email_id = Column(UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True)
    
    # Optional associations (NULL = unassigned)
    case_id = Column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    collection_id = Column(UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=True)
    
    # Flags
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=True)
    is_privileged = Column(Boolean, default=False)
    is_confidential = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)
    is_reviewed = Column(Boolean, default=False)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    
    # User notes
    notes = Column(Text, nullable=True)
    
    # Audit
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    source = relationship("EvidenceSource")
    source_email = relationship("EmailMessage")
    case = relationship("Case")
    project = relationship("Project")
    collection = relationship("EvidenceCollection")
    duplicate_of = relationship("EvidenceItem", remote_side=[id])
    uploader = relationship("User", foreign_keys=[uploaded_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    
    # Indexes defined in __table_args__
    __table_args__ = (
        Index('idx_evidence_items_hash', 'file_hash'),
        Index('idx_evidence_items_type', 'evidence_type'),
        Index('idx_evidence_items_date', 'document_date'),
        Index('idx_evidence_items_status', 'processing_status'),
        Index('idx_evidence_items_case', 'case_id'),
        Index('idx_evidence_items_project', 'project_id'),
        Index('idx_evidence_items_auto_tags', 'auto_tags', postgresql_using='gin'),
        Index('idx_evidence_items_manual_tags', 'manual_tags', postgresql_using='gin'),
    )


class EvidenceCorrespondenceLink(Base):
    """Links evidence items to emails/correspondence"""
    __tablename__ = "evidence_correspondence_links"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Evidence item
    evidence_item_id = Column(UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False)
    
    # Link type and confidence
    link_type = Column(String(50), nullable=False)
    link_confidence = Column(Integer, nullable=True)  # 0-100
    link_method = Column(String(50), nullable=True)
    
    # Target: Email message
    email_message_id = Column(UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True)
    
    # OR: External correspondence
    correspondence_type = Column(String(50), nullable=True)
    correspondence_reference = Column(String(500), nullable=True)
    correspondence_date = Column(DateTime(timezone=False), nullable=True)
    correspondence_from = Column(String(255), nullable=True)
    correspondence_to = Column(String(255), nullable=True)
    correspondence_subject = Column(Text, nullable=True)
    
    # Context
    context_snippet = Column(Text, nullable=True)
    page_reference = Column(String(50), nullable=True)
    
    # Flags
    is_auto_linked = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    
    # Audit
    linked_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    verified_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    evidence_item = relationship("EvidenceItem", backref="correspondence_links")
    email_message = relationship("EmailMessage")
    linker = relationship("User", foreign_keys=[linked_by])
    verifier = relationship("User", foreign_keys=[verified_by])


class EvidenceRelation(Base):
    """Relationships between evidence items"""
    __tablename__ = "evidence_relations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Source and target
    source_evidence_id = Column(UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False)
    target_evidence_id = Column(UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False)
    
    # Relation details
    relation_type = Column(String(50), nullable=False)
    relation_direction = Column(String(20), default='unidirectional')
    
    # Context
    description = Column(Text, nullable=True)
    confidence = Column(Integer, nullable=True)  # 0-100
    detection_method = Column(String(50), nullable=True)
    
    # Flags
    is_auto_detected = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    
    # Audit
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    verified_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    source_evidence = relationship("EvidenceItem", foreign_keys=[source_evidence_id], backref="outgoing_relations")
    target_evidence = relationship("EvidenceItem", foreign_keys=[target_evidence_id], backref="incoming_relations")
    creator = relationship("User", foreign_keys=[created_by])
    verifier = relationship("User", foreign_keys=[verified_by])


class EvidenceCollectionItem(Base):
    """Junction table: evidence items can be in multiple collections"""
    __tablename__ = "evidence_collection_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    collection_id = Column(UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=False)
    evidence_item_id = Column(UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False)
    
    # Order within collection
    sort_order = Column(Integer, default=0)
    
    # How added
    added_method = Column(String(50), default='manual')
    
    # Audit
    added_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    collection = relationship("EvidenceCollection", backref="items")
    evidence_item = relationship("EvidenceItem", backref="collection_memberships")
    adder = relationship("User")


class EvidenceActivityLog(Base):
    """Audit trail for evidence access and modifications"""
    __tablename__ = "evidence_activity_log"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Target
    evidence_item_id = Column(UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=True)
    collection_id = Column(UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=True)
    
    # Action
    action = Column(String(50), nullable=False)
    action_details = Column(JSONB, nullable=True)
    
    # Actor
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    evidence_item = relationship("EvidenceItem")
    collection = relationship("EvidenceCollection")
    user = relationship("User")