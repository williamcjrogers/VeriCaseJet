from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    String,
    DateTime,
    Text,
    JSON,
    Enum,
    Integer,
    BigInteger,
    ForeignKey,
    Boolean,
    Index,
    ARRAY,
    Float,
)
import sqlalchemy as sa
from sqlalchemy.sql import func, expression
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column
from enum import Enum as PyEnum
from .db import Base


class DocStatus(str, PyEnum):
    NEW = "NEW"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class UserRole(str, PyEnum):
    """
    Role hierarchy (highest to lowest):
    - ADMIN: VeriCase platform owners - AI configs, intelligence layer, system settings
    - POWER_USER: Full workspace/case control, all features within their scope
    - MANAGEMENT_USER: Team management, deadlines, workspace settings
    - USER: Standard access - view, basic editing
    """

    ADMIN = "ADMIN"
    POWER_USER = "POWER_USER"
    MANAGEMENT_USER = "MANAGEMENT_USER"
    USER = "USER"


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), nullable=False, default=UserRole.USER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Enhanced security fields
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failed_attempt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    sessions: Mapped[list[UserSession]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    password_history: Mapped[list[PasswordHistory]] = relationship(
        "PasswordHistory", back_populates="user", cascade="all, delete-orphan"
    )
    login_attempts: Mapped[list[LoginAttempt]] = relationship(
        "LoginAttempt", back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_jti: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45), nullable=True
    )  # Supports both IPv4 and IPv6
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sessions")


class PasswordHistory(Base):
    __tablename__ = "password_history"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="password_history")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped[User | None] = relationship("User", back_populates="login_attempts")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[DocStatus] = mapped_column(
        Enum(DocStatus), nullable=False, default=DocStatus.NEW
    )
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_accessed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    is_private: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )
    workspace_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="shared"
    )
    owner: Mapped[User | None] = relationship("User", foreign_keys=[owner_user_id])
    last_accessed_user: Mapped[User | None] = relationship(
        "User", foreign_keys=[last_accessed_by]
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    comments: Mapped[list["DocumentComment"]] = relationship(
        "DocumentComment",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    annotations: Mapped[list["DocumentAnnotation"]] = relationship(
        "DocumentAnnotation",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    owner: Mapped[User] = relationship("User")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class ShareLink(Base):
    __tablename__ = "share_links"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    document: Mapped[Document] = relationship("Document")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)


class UserInvitation(Base):
    __tablename__ = "user_invitations"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    inviter: Mapped[User] = relationship("User", foreign_keys=[invited_by])
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), nullable=False, default=UserRole.USER
    )
    token: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentShare(Base):
    __tablename__ = "document_shares"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    document: Mapped[Document] = relationship("Document")
    shared_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    sharer: Mapped[User] = relationship("User", foreign_keys=[shared_by])
    shared_with: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    recipient: Mapped[User] = relationship("User", foreign_keys=[shared_with])
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default="view")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentComment(Base):
    """Threaded comments for documents (moved out of document.metadata)."""

    __tablename__ = "document_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    document: Mapped[Document] = relationship("Document", back_populates="comments")
    author: Mapped[User] = relationship("User")
    parent_comment: Mapped["DocumentComment | None"] = relationship(
        "DocumentComment", remote_side=[id], backref="replies"
    )

    __table_args__ = (
        Index("idx_doc_comments_document", "document_id"),
        Index("idx_doc_comments_parent", "parent_comment_id"),
        Index("idx_doc_comments_created", "created_at"),
    )


class DocumentAnnotation(Base):
    """Structured annotations for documents (moved out of document.metadata)."""

    __tablename__ = "document_annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#FFD700")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    document: Mapped[Document] = relationship("Document", back_populates="annotations")
    author: Mapped[User] = relationship("User")

    __table_args__ = (
        Index("idx_doc_annotations_document", "document_id"),
        Index("idx_doc_annotations_page", "document_id", "page_number"),
        Index("idx_doc_annotations_created", "created_at"),
    )


class CollaborationActivity(Base):
    """Audit trail for collaboration actions (comments/annotations)."""

    __tablename__ = "collaboration_activity"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User | None] = relationship("User")

    __table_args__ = (
        Index("idx_collab_activity_resource", "resource_type", "resource_id"),
        Index("idx_collab_activity_user", "user_id"),
        Index("idx_collab_activity_created", "created_at"),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FolderShare(Base):
    __tablename__ = "folder_shares"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    folder_path: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    shared_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    sharer: Mapped[User] = relationship("User", foreign_keys=[shared_by])
    shared_with: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    recipient: Mapped[User] = relationship("User", foreign_keys=[shared_with])
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default="view")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Favorite(Base):
    __tablename__ = "favorites"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    user: Mapped[User] = relationship("User")
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    document: Mapped[Document] = relationship("Document")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    document: Mapped[Document] = relationship("Document")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    s3_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    creator: Mapped[User | None] = relationship("User")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


# ============================================================================
# LEGAL DOMAIN MODELS - Case Management
# ============================================================================


class Company(Base):
    """Multi-tenant company workspace"""

    __tablename__ = "companies"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    subscription_tier: Mapped[str] = mapped_column(String(50), default="professional")
    storage_limit_gb: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class UserCompany(Base):
    """Many-to-many: Users can belong to multiple companies"""

    __tablename__ = "user_companies"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(50), default="user"
    )  # admin, manager, user, viewer
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    user: Mapped[User] = relationship("User")
    company: Mapped[Company] = relationship("Company")


class Case(Base):
    """Legal case with construction-specific fields"""

    __tablename__ = "cases"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_number: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    case_id_custom: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    project_name: Mapped[str | None] = mapped_column(String(500))
    contract_type: Mapped[str | None] = mapped_column(String(100))  # JCT, NEC, FIDIC
    dispute_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # Delay, Defects, Variation
    status: Mapped[str] = mapped_column(
        String(50), default="active"
    )  # active, closed, archived
    case_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolution_route: Mapped[str | None] = mapped_column(String(100), nullable=True)
    position: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Upstream/Downstream
    claimant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    defendant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client: Mapped[str | None] = mapped_column(String(255), nullable=True)
    legal_team: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    heads_of_claim: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    deadlines: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    # Optional link to the underlying data project (emails/evidence live primarily under Project![1766462800990](image/models/1766462800990.png)![1766462809319](image/models/1766462809319.png)![1766462821425](image/models/1766462821425.png)).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    owner: Mapped[User] = relationship("User")
    company: Mapped[Company] = relationship("Company")
    project: Mapped["Project | None"] = relationship("Project")
    workspace: Mapped["Workspace | None"] = relationship(
        "Workspace", back_populates="cases"
    )


class CaseUser(Base):
    """Case team members with roles"""

    __tablename__ = "case_users"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(50), default="viewer"
    )  # admin, editor, viewer
    added_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    case: Mapped[Case | None] = relationship("Case")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])


class Issue(Base):
    """Legal issues within a case"""

    __tablename__ = "issues"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    issue_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # Liability, Causation, Quantum
    status: Mapped[str] = mapped_column(
        String(50), default="open"
    )  # open, resolved, disputed
    relevant_contract_clauses: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    case: Mapped[Case] = relationship("Case")


class Evidence(Base):
    """Evidence linking documents to cases and issues"""

    __tablename__ = "evidence"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issues.id"), nullable=True
    )
    evidence_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # email, contract, photo, expert_report
    exhibit_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    date_of_evidence: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_cc: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_message_id: Mapped[str | None] = mapped_column(
        String(500), nullable=True, index=True
    )  # For threading
    email_in_reply_to: Mapped[str | None] = mapped_column(
        String(500), nullable=True, index=True
    )  # For threading
    email_thread_topic: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email_conversation_index: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )  # Computed thread ID
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Email body stored directly
    content_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # html or text
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )  # Array of attachment info
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    as_planned_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    as_planned_activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    as_built_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    as_built_activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delay_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, server_default="0"
    )
    is_critical_path: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )
    added_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    case: Mapped[Case] = relationship("Case")
    document: Mapped[Document] = relationship("Document")
    issue: Mapped[Issue | None] = relationship("Issue")


class ClaimType(str, PyEnum):
    DELAY = "delay"
    DEFECT = "defect"
    VARIATION = "variation"
    EOT = "extension_of_time"
    LOSS_EXPENSE = "loss_and_expense"
    OTHER = "other"


class Claim(Base):
    """Construction claims (delay, defects, variations)"""

    __tablename__ = "claims"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    claim_type: Mapped[ClaimType] = mapped_column(Enum(ClaimType), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    claimed_amount: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Store in cents
    currency: Mapped[str] = mapped_column(String(10), default="GBP")
    claim_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), default="draft"
    )  # draft, submitted, under_review, accepted, rejected
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    case: Mapped[Case] = relationship("Case")


class ChronologyItem(Base):
    """Timeline events for cases"""

    __tablename__ = "chronology_items"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("claims.id"), nullable=True
    )
    event_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    event_type: Mapped[str | None] = mapped_column(
        String(100)
    )  # notice, meeting, correspondence, site_event
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    evidence_ids: Mapped[list[str] | None] = mapped_column(JSON)  # List of evidence IDs
    parties_involved: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    case: Mapped[Case] = relationship("Case")
    claim: Mapped[Claim | None] = relationship("Claim")


class Rebuttal(Base):
    """Arguments and counter-arguments for issues"""

    __tablename__ = "rebuttals"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    issue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issues.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    argument: Mapped[str] = mapped_column(Text, nullable=False)
    counter_argument: Mapped[str | None] = mapped_column(Text)
    supporting_evidence_ids: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    issue: Mapped[Issue] = relationship("Issue")


class ParsedContractClause(Base):
    """Parsed contract clauses with unique IDs"""

    __tablename__ = "contract_clauses"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    clause_id: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "4.2.1"
    clause_text: Mapped[str] = mapped_column(Text, nullable=False)
    clause_title: Mapped[str | None] = mapped_column(String(500))
    parent_clause_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    case: Mapped[Case] = relationship("Case")
    document: Mapped[Document] = relationship("Document")


class SearchQuery(Base):
    """Search analytics"""

    __tablename__ = "search_queries"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id")
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    query_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    query_type: Mapped[str | None] = mapped_column(
        String(50)
    )  # keyword, semantic, hybrid
    filters_applied: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    results_count: Mapped[int | None] = mapped_column(Integer)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    user: Mapped[User | None] = relationship("User")
    company: Mapped[Company | None] = relationship("Company")
    case: Mapped[Case | None] = relationship("Case")


class DelayEvent(Base):
    """Identified delay/slippage between as-planned and as-built"""

    __tablename__ = "delay_events"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False
    )
    as_planned_programme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programmes.id")
    )
    as_built_programme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programmes.id")
    )
    activity_id: Mapped[str | None] = mapped_column(String(100))
    activity_name: Mapped[str | None] = mapped_column(String(500))
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_finish: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_finish: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delay_days: Mapped[int | None] = mapped_column(Integer)
    delay_type: Mapped[str | None] = mapped_column(
        String(50)
    )  # critical, non_critical, concurrent
    is_on_critical_path: Mapped[bool] = mapped_column(Boolean, default=False)
    delay_cause: Mapped[str | None] = mapped_column(
        String(100)
    )  # employer, contractor, neutral, concurrent
    description: Mapped[str | None] = mapped_column(Text)
    linked_correspondence_ids: Mapped[list[str] | None] = mapped_column(
        JSON
    )  # Document IDs of related emails
    linked_issue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("issues.id"), nullable=True
    )
    eot_entitlement_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    case: Mapped[Case] = relationship("Case")
    issue: Mapped[Issue | None] = relationship("Issue")


# ========================================
# PST ANALYSIS SPECIFIC MODELS
# ========================================


class Project(Base):
    """Project management for construction/engineering projects"""

    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completion_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contract_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_form: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_form_custom: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Retrospective analysis fields
    analysis_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default="project"
    )  # 'retrospective' or 'project'
    project_aliases: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Comma-separated alternative names
    site_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    include_domains: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Comma-separated domains
    exclude_people: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Comma-separated names/emails
    project_terms: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Project-specific terms
    exclude_keywords: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Keywords to exclude
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True, default=dict
    )  # Flexible storage for refinements etc
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True, index=True
    )
    owner: Mapped[User] = relationship("User")
    workspace: Mapped["Workspace | None"] = relationship(
        "Workspace", back_populates="projects"
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class Workspace(Base):
    """Workspace entity that groups Projects and Cases together"""

    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # JCT, NEC, FIDIC
    status: Mapped[str] = mapped_column(
        String(50), default="active"
    )  # active, archived
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    owner: Mapped[User] = relationship("User")
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="workspace"
    )
    cases: Mapped[list["Case"]] = relationship("Case", back_populates="workspace")


class WorkspaceKeyword(Base):
    """Keywords and variants for a workspace"""

    __tablename__ = "workspace_keywords"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    keyword_name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    variations: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Comma-separated variations
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)

    workspace: Mapped[Workspace] = relationship("Workspace")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkspaceTeamMember(Base):
    """Project team members for a workspace"""

    __tablename__ = "workspace_team_members"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    role: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # Project Manager, QS, etc.
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    email: Mapped[str | None] = mapped_column(String(512), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(512), nullable=True)

    workspace: Mapped[Workspace] = relationship("Workspace")
    user: Mapped[User | None] = relationship("User")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkspaceKeyDate(Base):
    """Key dates and milestones for a workspace"""

    __tablename__ = "workspace_key_dates"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # contract_start, contract_end, milestone, etc.
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    date_value: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace: Mapped[Workspace] = relationship("Workspace")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OcrCorrection(Base):
    """Manual OCR corrections for feedback loop"""

    __tablename__ = "ocr_corrections"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # document, email_attachment
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    field_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    ocr_engine: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(
        sa.Float, nullable=True
    )  # Using sa.Float directly as Float isn't imported from sqlalchemy in lines 7-19
    scope: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="project"
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PSTFile(Base):
    """Uploaded PST files for email forensics"""

    __tablename__ = "pst_files"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )  # Fixed: DB allows NULL
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    s3_bucket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    s3_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(
        "file_size_bytes", BigInteger, nullable=True
    )  # Fixed: Match DB column name
    total_emails: Mapped[int] = mapped_column(Integer, default=0)
    processed_emails: Mapped[int] = mapped_column(Integer, default=0)
    processing_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # Fixed: Match DB default
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )  # Fixed: DB has no timezone
    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )  # Fixed: DB has no timezone
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    uploader: Mapped[User | None] = relationship("User")
    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    uploaded_at: Mapped[datetime | None] = mapped_column(
        "uploaded_at", DateTime(timezone=False), server_default=func.now()
    )  # Fixed: Match DB column name

    @property
    def file_size(self) -> int | None:
        """Alias for file_size_bytes for backward compatibility"""
        return self.file_size_bytes


class EmailMessage(Base):
    """Extracted email messages from PST files with forensic metadata"""

    __tablename__ = "email_messages"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pst_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pst_files.id"), nullable=False
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )  # Now nullable
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )  # New field

    # Email metadata
    message_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )  # RFC message-id
    in_reply_to: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email_references: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # For threading (renamed from references)
    conversation_index: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )  # Computed thread ID for grouping
    thread_group_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )  # Stable thread grouping identifier
    thread_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    thread_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_inclusive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.true()
    )

    # PST forensic data
    pst_message_offset: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Position in PST file
    pst_message_path: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Folder path in PST

    # Email content
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_email: Mapped[str | None] = mapped_column(
        String(512), nullable=True, index=True
    )
    sender_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recipients_to: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )  # Array of recipients
    recipients_cc: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    recipients_bcc: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    date_sent: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    date_received: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Canonical body and deduplication
    body_text_clean: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Top-message canonical text (quotes stripped, normalised)
    body_text_clean_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Layer-2 hash of normalized canonical body
    content_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Hash of canonical body + key metadata
    canonical_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True
    )
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    dedupe_level: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # Programme linking
    as_planned_activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    as_planned_finish_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    as_built_activity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    as_built_finish_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delay_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_critical_path: Mapped[bool | None] = mapped_column(Boolean, default=False)

    # Flags
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    importance: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # high, normal, low

    # Tagging (populated during processing)
    matched_stakeholders: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )  # Array of stakeholder IDs
    matched_keywords: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )  # Array of keyword IDs

    # Storage optimization: Store only preview if body is too large
    body_preview: Mapped[str | None] = mapped_column(Text, nullable=True)  # First 10KB
    body_full_s3_key: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )  # S3 key if body > 10KB

    # Flexible metadata storage
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True, default=dict
    )

    pst_file: Mapped[PSTFile] = relationship("PSTFile")
    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    attachments: Mapped[list["EmailAttachment"]] = relationship(
        "EmailAttachment", back_populates="email_message", lazy="selectin"
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Add indexes for performance
    __table_args__ = (
        Index("idx_email_case_date", "case_id", "date_sent"),
        Index("idx_email_project_date", "project_id", "date_sent"),
        Index("idx_email_stakeholders", "matched_stakeholders", postgresql_using="gin"),
        Index("idx_email_keywords", "matched_keywords", postgresql_using="gin"),
        Index("idx_email_has_attachments", "case_id", "has_attachments"),
        Index("idx_email_project_has_attachments", "project_id", "has_attachments"),
        Index("idx_email_conversation", "case_id", "conversation_index"),
        Index("idx_email_project_conversation", "project_id", "conversation_index"),
        Index("idx_email_case_content_hash", "case_id", "content_hash"),
        Index("idx_email_project_content_hash", "project_id", "content_hash"),
        Index("idx_email_thread_group", "thread_group_id"),
        Index("idx_email_thread_path", "thread_group_id", "thread_path"),
        Index("idx_email_canonical", "canonical_email_id"),
        Index("idx_email_is_duplicate", "is_duplicate"),
    )


class EmailThreadLink(Base):
    """Deterministic parent-child threading evidence for emails."""

    __tablename__ = "email_thread_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    child_email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=False
    )
    parent_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True
    )

    methods: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    alternatives: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    child_email: Mapped[EmailMessage] = relationship(
        "EmailMessage", foreign_keys=[child_email_id]
    )
    parent_email: Mapped[EmailMessage | None] = relationship(
        "EmailMessage", foreign_keys=[parent_email_id]
    )

    __table_args__ = (
        Index("idx_email_thread_links_child", "child_email_id"),
        Index("idx_email_thread_links_parent", "parent_email_id"),
    )


class EmailDedupeDecision(Base):
    """Dedupe decisions for emails (winner/loser with evidence)."""

    __tablename__ = "email_dedupe_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    winner_email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=False
    )
    loser_email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(2), nullable=False)
    match_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strict_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    relaxed_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quoted_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    alternatives: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    winner_email: Mapped[EmailMessage] = relationship(
        "EmailMessage", foreign_keys=[winner_email_id]
    )
    loser_email: Mapped[EmailMessage] = relationship(
        "EmailMessage", foreign_keys=[loser_email_id]
    )

    __table_args__ = (
        Index("idx_email_dedupe_winner", "winner_email_id"),
        Index("idx_email_dedupe_loser", "loser_email_id"),
        Index("idx_email_dedupe_level", "level"),
    )


class EmailAttachment(Base):
    """Email attachments extracted from PST files"""

    __tablename__ = "email_attachments"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True
    )
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    s3_bucket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    s3_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Deduplication and inline metadata
    attachment_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_inline: Mapped[bool] = mapped_column(Boolean, default=False)
    content_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)

    # OCR/extraction status
    has_been_ocred: Mapped[bool] = mapped_column(Boolean, default=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    email_message: Mapped[EmailMessage | None] = relationship(
        "EmailMessage", back_populates="attachments"
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("idx_email_attachment_hash", "attachment_hash"),)

    @property
    def file_size(self) -> int | None:
        """Alias for file_size_bytes for backward compatibility"""
        return self.file_size_bytes


class MessageRaw(Base):
    """Immutable raw message artefact with provenance data."""

    __tablename__ = "message_raw"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_tool_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    occurrences: Mapped[list["MessageOccurrence"]] = relationship(
        "MessageOccurrence", back_populates="raw", lazy="selectin"
    )
    derived: Mapped[list["MessageDerived"]] = relationship(
        "MessageDerived", back_populates="raw", lazy="selectin"
    )
    attachments: Mapped[list["AttachmentRaw"]] = relationship(
        "AttachmentRaw", back_populates="raw", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_message_raw_source_hash", "source_hash"),
        Index("idx_message_raw_source_type", "source_type"),
        Index("idx_message_raw_extracted_at", "extracted_at"),
    )


class MessageOccurrence(Base):
    """Occurrence of a raw message within an ingest run."""

    __tablename__ = "message_occurrences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_raw.id"), nullable=False
    )
    ingest_run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )

    raw: Mapped[MessageRaw] = relationship("MessageRaw", back_populates="occurrences")
    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")

    __table_args__ = (
        Index("idx_message_occurrences_raw_id", "raw_id"),
        Index("idx_message_occurrences_ingest_run", "ingest_run_id"),
        Index("idx_message_occurrences_case", "case_id"),
        Index("idx_message_occurrences_project", "project_id"),
    )


class MessageDerived(Base):
    """Derived, versioned canonical representation of a message."""

    __tablename__ = "message_derived"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_raw.id"), nullable=False
    )
    normalizer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_ruleset_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_participants: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )
    canonical_body_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_body_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    banner_stripped_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote_blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    user_blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    content_hash_phase1: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash_phase2: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dep_uri: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)

    derived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    raw: Mapped[MessageRaw] = relationship("MessageRaw", back_populates="derived")
    artefacts: Mapped[list["EnrichmentArtefact"]] = relationship(
        "EnrichmentArtefact", back_populates="derived", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_message_derived_raw_id", "raw_id"),
        Index("idx_message_derived_hash_p1", "content_hash_phase1"),
        Index("idx_message_derived_hash_p2", "content_hash_phase2"),
        Index("idx_message_derived_dep_uri", "dep_uri"),
    )


class AttachmentRaw(Base):
    """Raw attachment artefacted linked to a raw message."""

    __tablename__ = "attachment_raw"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_raw.id"), nullable=False
    )
    attachment_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename_normalized: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    raw: Mapped[MessageRaw] = relationship("MessageRaw", back_populates="attachments")

    __table_args__ = (
        Index("idx_attachment_raw_message", "raw_id"),
        Index("idx_attachment_raw_hash", "attachment_hash"),
    )


class EnrichmentArtefact(Base):
    """Derived enrichment artefact with explicit versioning."""

    __tablename__ = "enrichment_artefacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    derived_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_derived.id"), nullable=False
    )
    artefact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    artefact_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )  # Column name stays "metadata" in DB, but Python attr is "artefact_metadata"
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    derived: Mapped[MessageDerived] = relationship(
        "MessageDerived", back_populates="artefacts"
    )

    __table_args__ = (
        Index("idx_enrichment_artefacts_derived", "derived_id"),
        Index("idx_enrichment_artefacts_type", "artefact_type"),
    )


class Stakeholder(Base):
    """Stakeholders for auto-tagging emails"""

    __tablename__ = "stakeholders"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )

    role: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # e.g., "Main Contractor", "Client"
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    email: Mapped[str | None] = mapped_column(String(512), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # For fuzzy matching
    email_domain: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Extracted domain for matching

    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StakeholderRole(Base):
    """Custom stakeholder roles/categories for a project or case.

    Allows users to define their own party role categories beyond defaults.
    Each role has a name, display color, and optional description.
    """

    __tablename__ = "stakeholder_roles"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Display styling
    color_bg: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="#f3f4f6"
    )  # Background color (hex)
    color_text: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="#374151"
    )  # Text color (hex)

    # Ordering for display
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    # System vs user-defined
    is_system: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True for default roles that can't be deleted

    project: Mapped[Project | None] = relationship("Project")
    case: Mapped[Case | None] = relationship("Case")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_stakeholder_role_project", "project_id"),
        Index("idx_stakeholder_role_case", "case_id"),
    )


class Keyword(Base):
    """Keywords for auto-tagging emails"""

    __tablename__ = "keywords"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )

    keyword_name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    variations: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Comma-separated variations
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)

    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Programme(Base):
    """Construction programmes (Asta Powerproject, MS Project, etc.)"""

    __tablename__ = "programmes"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )

    programme_name: Mapped[str] = mapped_column(String(255), nullable=False)
    programme_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # baseline, actual, as-built, etc.
    programme_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # File storage
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_format: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # XML, PP, MPP

    # Parsed data (JSON)
    activities: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    critical_path: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    milestones: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # Summary dates
    project_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    project_finish: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    uploader: Mapped[User] = relationship("User")
    case: Mapped[Case] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AppSetting(Base):
    """Application settings that can be modified by admins"""

    __tablename__ = "app_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    updater: Mapped[User | None] = relationship("User")


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

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Source identification
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # For PST files (optional link)
    pst_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pst_files.id"), nullable=True
    )

    # Original file storage
    original_s3_bucket: Mapped[str | None] = mapped_column(String(128), nullable=True)
    original_s3_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    original_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    original_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Processing statistics
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_items: Mapped[int] = mapped_column(Integer, default=0)

    # Processing status
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Optional associations
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )

    # Audit
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    pst_file: Mapped[PSTFile | None] = relationship("PSTFile")
    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    uploader: Mapped[User | None] = relationship("User")


class EvidenceCollection(Base):
    """Virtual folders for organizing evidence"""

    __tablename__ = "evidence_collections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Collection info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_type: Mapped[str] = mapped_column(
        String(50), default="manual"
    )  # manual, smart, auto_date, auto_type

    # Smart collection rules
    filter_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    # Hierarchy support
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=True
    )
    path: Mapped[str | None] = mapped_column(Text, nullable=True)  # Materialized path
    depth: Mapped[int] = mapped_column(Integer, default=0)

    # Optional associations
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )

    # Display settings
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    # Statistics
    item_count: Mapped[int] = mapped_column(Integer, default=0)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    parent: Mapped[EvidenceCollection | None] = relationship(
        "EvidenceCollection", remote_side=[id], backref="children"
    )
    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    creator: Mapped[User | None] = relationship("User")


class EvidenceItem(Base):
    """Core evidence repository - NOT case-dependent"""

    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Core file metadata
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Increased from 50 for flexibility
    mime_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Increased for edge cases
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False)  # SHA-256

    # Storage
    s3_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    thumbnail_s3_key: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Classification
    evidence_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Auto-extracted metadata
    document_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    document_date_confidence: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 0-100
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Full-text content
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Layer-2 hash of normalized extracted_text
    text_language: Mapped[str] = mapped_column(String(10), default="en")

    # Entity extraction (auto-populated)
    extracted_parties: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extracted_dates: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extracted_amounts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extracted_references: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extracted_locations: Mapped[list[str]] = mapped_column(JSONB, default=list)

    # Auto-tagging
    auto_tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    manual_tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    keywords_matched: Mapped[list[str]] = mapped_column(JSONB, default=list)
    stakeholders_matched: Mapped[list[str]] = mapped_column(JSONB, default=list)

    # Comprehensive metadata (from extraction service)
    extracted_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )  # Full metadata from MetadataExtractor
    metadata_extracted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Classification confidence
    classification_confidence: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 0-100
    classification_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Processing status
    processing_status: Mapped[str] = mapped_column(String(50), default="pending")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Provenance
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_sources.id"), nullable=True
    )
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True
    )

    # Optional associations (NULL = unassigned)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=True
    )

    # Flags
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=True
    )
    is_privileged: Mapped[bool] = mapped_column(Boolean, default=False)
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # User notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata (spam classification, refinement state, etc.)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)

    # Audit
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    source: Mapped[EvidenceSource | None] = relationship("EvidenceSource")
    source_email: Mapped[EmailMessage | None] = relationship("EmailMessage")
    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    collection: Mapped[EvidenceCollection | None] = relationship("EvidenceCollection")
    duplicate_of: Mapped[EvidenceItem | None] = relationship(
        "EvidenceItem", remote_side=[id]
    )
    uploader: Mapped[User | None] = relationship("User", foreign_keys=[uploaded_by])
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])

    # Indexes defined in __table_args__
    __table_args__ = (
        Index("idx_evidence_items_hash", "file_hash"),
        Index("idx_evidence_items_type", "evidence_type"),
        Index("idx_evidence_items_date", "document_date"),
        Index("idx_evidence_items_status", "processing_status"),
        Index("idx_evidence_items_case", "case_id"),
        Index("idx_evidence_items_project", "project_id"),
        Index("idx_evidence_items_auto_tags", "auto_tags", postgresql_using="gin"),
        Index("idx_evidence_items_manual_tags", "manual_tags", postgresql_using="gin"),
    )


class EvidenceSpan(Base):
    """Deterministic Evidence Pointer (DEP) span anchoring for forensic traceability."""

    __tablename__ = "evidence_spans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True
    )

    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=True, index=True
    )
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True, index=True
    )

    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)

    span_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_text_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    dep_uri: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    case: Mapped[Case | None] = relationship("Case")
    project: Mapped[Project | None] = relationship("Project")
    source_evidence: Mapped[EvidenceItem | None] = relationship(
        "EvidenceItem", foreign_keys=[source_evidence_id]
    )
    source_email: Mapped[EmailMessage | None] = relationship(
        "EmailMessage", foreign_keys=[source_email_id]
    )

    __table_args__ = (
        Index("idx_evidence_spans_case_source", "case_id", "source_type"),
        Index("idx_evidence_spans_dep_uri", "dep_uri"),
    )


class EvidenceCorrespondenceLink(Base):
    """Links evidence items to emails/correspondence"""

    __tablename__ = "evidence_correspondence_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Evidence item
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False
    )

    # Link type and confidence
    link_type: Mapped[str] = mapped_column(String(50), nullable=False)
    link_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    link_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Target: Email message
    email_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_messages.id"), nullable=True
    )

    # OR: External correspondence
    correspondence_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    correspondence_reference: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    correspondence_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    correspondence_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correspondence_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correspondence_subject: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Context
    context_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_reference: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Flags
    is_auto_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Audit
    linked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    evidence_item: Mapped[EvidenceItem] = relationship(
        "EvidenceItem", backref="correspondence_links"
    )
    email_message: Mapped[EmailMessage | None] = relationship("EmailMessage")
    linker: Mapped[User | None] = relationship("User", foreign_keys=[linked_by])
    verifier: Mapped[User | None] = relationship("User", foreign_keys=[verified_by])


class EvidenceRelation(Base):
    """Relationships between evidence items"""

    __tablename__ = "evidence_relations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Source and target
    source_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False
    )
    target_evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False
    )

    # Relation details
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    relation_direction: Mapped[str] = mapped_column(
        String(20), default="unidirectional"
    )

    # Context
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    detection_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Flags
    is_auto_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    source_evidence: Mapped[EvidenceItem] = relationship(
        "EvidenceItem", foreign_keys=[source_evidence_id], backref="outgoing_relations"
    )
    target_evidence: Mapped[EvidenceItem] = relationship(
        "EvidenceItem", foreign_keys=[target_evidence_id], backref="incoming_relations"
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    verifier: Mapped[User | None] = relationship("User", foreign_keys=[verified_by])


class EvidenceCollectionItem(Base):
    """Junction table: evidence items can be in multiple collections"""

    __tablename__ = "evidence_collection_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=False
    )
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=False
    )

    # Order within collection
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # How added
    added_method: Mapped[str] = mapped_column(String(50), default="manual")

    # Audit
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    added_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    collection: Mapped[EvidenceCollection] = relationship(
        "EvidenceCollection", backref="items"
    )
    evidence_item: Mapped[EvidenceItem] = relationship(
        "EvidenceItem", backref="collection_memberships"
    )
    adder: Mapped[User | None] = relationship("User")


class EvidenceActivityLog(Base):
    """Audit trail for evidence access and modifications"""

    __tablename__ = "evidence_activity_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Target
    evidence_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_items.id"), nullable=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_collections.id"), nullable=True
    )

    # Action
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    action_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Actor
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamp
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    evidence_item: Mapped[EvidenceItem | None] = relationship("EvidenceItem")
    collection: Mapped[EvidenceCollection | None] = relationship("EvidenceCollection")
    user: Mapped[User | None] = relationship("User")


# ==============================================================================
# Contentious Matters and Heads of Claim Module
# ==============================================================================


class MatterStatus(str, PyEnum):
    ACTIVE = "active"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class MatterPriority(str, PyEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ClaimStatus(str, PyEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SETTLED = "settled"
    WITHDRAWN = "withdrawn"


class LinkType(str, PyEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    NEUTRAL = "neutral"
    KEY = "key"


class ItemType(str, PyEnum):
    CORRESPONDENCE = "correspondence"
    EVIDENCE = "evidence"
    MATTER = "matter"
    CLAIM = "claim"


class ContentiousMatter(Base):
    """
    Groups of disputed items - overarching dispute categories.
    A contentious matter represents a significant dispute area that may
    contain multiple specific heads of claim.
    """

    __tablename__ = "contentious_matters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=True
    )

    # Matter details
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="active"
    )  # Uses MatterStatus values
    priority: Mapped[str] = mapped_column(
        String(20), default="normal"
    )  # Uses MatterPriority values

    # Financial
    estimated_value: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Store in cents/pence
    currency: Mapped[str] = mapped_column(String(10), default="GBP")

    # Dates
    date_identified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Audit
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )

    # Relationships
    project: Mapped[Project | None] = relationship("Project")
    case: Mapped[Case | None] = relationship("Case")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    heads_of_claim: Mapped[list[HeadOfClaim]] = relationship(
        "HeadOfClaim", back_populates="contentious_matter"
    )
    item_links: Mapped[list[ItemClaimLink]] = relationship(
        "ItemClaimLink", back_populates="contentious_matter"
    )

    # Indexes
    __table_args__ = (
        Index("idx_contentious_matters_project", "project_id"),
        Index("idx_contentious_matters_case", "case_id"),
        Index("idx_contentious_matters_status", "status"),
    )


class HeadOfClaim(Base):
    """
    Specific legal claims, can be nested under contentious matters.
    Represents individual claims such as delay damages, defect remediation costs, etc.
    """

    __tablename__ = "heads_of_claim"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=True
    )
    contentious_matter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contentious_matters.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Claim identification
    reference_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # e.g., "HOC-001", "EOT-001"
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # delay, defects, variation, loss_expense, extension_of_time

    # Financial
    claimed_amount: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Store in cents/pence
    awarded_amount: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Store in cents/pence
    currency: Mapped[str] = mapped_column(String(10), default="GBP")

    # Status and dates
    status: Mapped[str] = mapped_column(
        String(50), default="draft"
    )  # Uses ClaimStatus values
    submission_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    response_due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    determination_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Supporting information
    supporting_contract_clause: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )

    # Relationships
    project: Mapped[Project | None] = relationship("Project")
    case: Mapped[Case | None] = relationship("Case")
    contentious_matter: Mapped[ContentiousMatter | None] = relationship(
        "ContentiousMatter", back_populates="heads_of_claim"
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    item_links: Mapped[list[ItemClaimLink]] = relationship(
        "ItemClaimLink", back_populates="head_of_claim"
    )

    # Indexes
    __table_args__ = (
        Index("idx_heads_of_claim_project", "project_id"),
        Index("idx_heads_of_claim_case", "case_id"),
        Index("idx_heads_of_claim_matter", "contentious_matter_id"),
        Index("idx_heads_of_claim_status", "status"),
        Index("idx_heads_of_claim_ref", "reference_number"),
    )


class ItemClaimLink(Base):
    """
    Links correspondence and evidence items to contentious matters or heads of claim.
    This allows tagging emails and documents as supporting/contradicting evidence
    for specific disputes.
    """

    __tablename__ = "item_claim_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Linked item
    item_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 'correspondence' or 'evidence'
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Link targets (at least one must be set)
    contentious_matter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contentious_matters.id", ondelete="CASCADE"),
        nullable=True,
    )
    head_of_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("heads_of_claim.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Link details
    link_type: Mapped[str] = mapped_column(
        String(50), default="supporting"
    )  # Uses LinkType values
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="active"
    )  # active, removed, superseded

    # Audit
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )

    # Relationships
    contentious_matter: Mapped[ContentiousMatter | None] = relationship(
        "ContentiousMatter", back_populates="item_links"
    )
    head_of_claim: Mapped[HeadOfClaim | None] = relationship(
        "HeadOfClaim", back_populates="item_links"
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    comments: Mapped[list[ItemComment]] = relationship(
        "ItemComment", back_populates="item_link", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_item_claim_links_item", "item_type", "item_id"),
        Index("idx_item_claim_links_matter", "contentious_matter_id"),
        Index("idx_item_claim_links_claim", "head_of_claim_id"),
    )


class ItemComment(Base):
    """
    Comment history on linked items.
    Supports threaded comments through parent_comment_id.
    """

    __tablename__ = "item_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Link to item_claim_link (if commenting on a linked item)
    item_claim_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("item_claim_links.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Direct item reference (if commenting directly on an item without link)
    item_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # 'correspondence', 'evidence', 'matter', 'claim'
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Collaboration lane (core, counsel, expert)
    lane: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="core", default="core"
    )

    # Comment threading
    parent_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("item_comments.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Pinning
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pinned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Audit
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )

    # Relationships
    item_link: Mapped[ItemClaimLink | None] = relationship(
        "ItemClaimLink", back_populates="comments"
    )
    parent_comment: Mapped[ItemComment | None] = relationship(
        "ItemComment", remote_side=[id], backref="replies"
    )
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])

    # Indexes
    __table_args__ = (
        Index("idx_item_comments_link", "item_claim_link_id"),
        Index("idx_item_comments_item", "item_type", "item_id"),
        Index(
            "idx_item_comments_item_lane_created",
            "item_type",
            "item_id",
            "lane",
            "created_at",
        ),
        Index(
            "idx_item_comments_link_lane_created",
            "item_claim_link_id",
            "lane",
            "created_at",
        ),
        Index("idx_item_comments_parent", "parent_comment_id"),
        Index("idx_item_comments_created", "created_at"),
        Index("idx_item_comments_pinned", "is_pinned"),
    )


class CommentReaction(Base):
    """
    Emoji reactions on comments.
    Users can add one reaction per emoji type per comment.
    """

    __tablename__ = "comment_reactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("item_comments.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g., '👍', '❤️'
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    comment: Mapped[ItemComment] = relationship("ItemComment", backref="reactions")
    user: Mapped[User] = relationship("User")

    # Unique constraint: one reaction per emoji per user per comment
    __table_args__ = (
        Index("idx_comment_reactions_comment", "comment_id"),
        Index("idx_comment_reactions_user", "user_id"),
        sa.UniqueConstraint(
            "comment_id", "user_id", "emoji", name="uq_comment_reaction"
        ),
    )


class CommentReadStatus(Base):
    """
    Track when users last read comments on a claim.
    Used for unread badges and highlighting new comments.
    """

    __tablename__ = "comment_read_status"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("heads_of_claim.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship("User")
    claim: Mapped[HeadOfClaim] = relationship("HeadOfClaim")

    # Unique constraint: one read status per user per claim
    __table_args__ = (
        Index("idx_comment_read_user", "user_id"),
        Index("idx_comment_read_claim", "claim_id"),
        sa.UniqueConstraint("user_id", "claim_id", name="uq_comment_read_status"),
    )


class UserNotificationPreferences(Base):
    """
    User preferences for notification types.
    Controls which notifications users receive via email.
    """

    __tablename__ = "user_notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Email notification toggles
    email_mentions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_replies: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_claim_updates: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    email_daily_digest: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    user: Mapped[User] = relationship("User", backref="notification_preferences")

    __table_args__ = (Index("idx_notification_prefs_user", "user_id"),)


# ==============================================================================
# AI Refinement Session Storage
# ==============================================================================


class RefinementSessionDB(Base):
    """
    Persistent storage for AI refinement sessions.
    Sessions are stored in the database to survive server restarts.
    """

    __tablename__ = "refinement_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID as string
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(50), default="active"
    )  # active, awaiting_answers, ready_to_apply, applied, cancelled, failed
    current_stage: Mapped[str] = mapped_column(String(50), default="initial_analysis")

    # Store complex data as JSON
    questions_asked: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True, default=list
    )
    answers_received: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True, default=list
    )
    analysis_results: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )
    exclusion_rules: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Indexes
    __table_args__ = (
        Index("idx_refinement_sessions_project", "project_id"),
        Index("idx_refinement_sessions_user", "user_id"),
        Index("idx_refinement_sessions_status", "status"),
    )


# ==============================================================================
# AI Optimization Tracking
# ==============================================================================


class CorpusLearningResult(Base):
    """
    Persistent storage for corpus learning results.

    Caches learned corpus profiles to avoid re-learning on every analysis.
    Invalidated by content_hash when emails change.
    """

    __tablename__ = "corpus_learning_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Scope (either project_id OR case_id, not both)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Corpus statistics
    email_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    learned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Learned data (stored as JSONB for flexibility)
    entity_distributions: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )  # {persons: [...], organizations: [...], locations: [...]}

    cluster_data: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )  # List of cluster objects

    corpus_centroid: Mapped[list[float] | None] = mapped_column(
        JSONB, nullable=True
    )  # 1024-dim embedding vector

    communication_graph: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )  # {edges: {...}, central_nodes: [...], peripheral_nodes: [...]}

    domain_distribution: Mapped[dict[str, int] | None] = mapped_column(
        JSONB, nullable=True
    )  # domain -> email count

    core_domains: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )  # Top 80% domains

    sentiment_baseline: Mapped[dict[str, float] | None] = mapped_column(
        JSONB, nullable=True
    )  # {positive: 0.x, negative: 0.x, ...}

    # Statistics for outlier detection
    avg_emails_per_sender: Mapped[float | None] = mapped_column(Float, nullable=True)
    std_emails_per_sender: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Content hash for cache invalidation
    # If email_ids change, hash changes, cached result is invalidated
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Indexes
    __table_args__ = (
        Index("idx_corpus_learning_project", "project_id"),
        Index("idx_corpus_learning_case", "case_id"),
        Index("idx_corpus_learning_hash", "content_hash"),
    )


# ==============================================================================
# Case Law Intelligence Layer
# ==============================================================================


class CaseLaw(Base):
    """
    Repository of ingested case law judgments.
    Serves as the source of truth for the AI Knowledge Base.
    """

    __tablename__ = "case_law"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Citation & Identification
    neutral_citation: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )  # e.g., [2023] EWHC 123 (TCC)
    case_name: Mapped[str] = mapped_column(String(500), nullable=False)
    court: Mapped[str | None] = mapped_column(String(255), nullable=True)
    judgment_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    judge: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Storage references
    s3_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    s3_key_raw: Mapped[str] = mapped_column(
        String(2048), nullable=False
    )  # Original PDF/XML
    s3_key_curated: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )  # Normalized Text/JSON

    # Content
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_text_preview: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI & Processing status
    embedding_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending, embedded, failed
    extraction_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending, extracted, failed
    kb_ingestion_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Structured extraction (pattern mining)
    # Storing as JSONB for flexibility, can be mirrored to OpenSearch
    extracted_analysis: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # Schema: {
    #   "issues": [...],
    #   "outcome": "...",
    #   "factors_for": [...],
    #   "factors_against": [...],
    #   "legal_tests": [...]
    # }

    # Metadata
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)

    # Audit
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_case_law_citation", "neutral_citation"),
        Index("idx_case_law_court", "court"),
        Index("idx_case_law_date", "judgment_date"),
    )


class AIOptimizationEvent(Base):
    """Track AI API calls for optimization analysis.

    Records detailed metrics for each AI API call including:
    - Provider and model used
    - Token usage and costs
    - Response times
    - Success/failure status
    - Quality assessments
    """

    __tablename__ = "ai_optimization_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    function_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    task_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # NOTE: 'metadata' is reserved in SQLAlchemy declarative models.
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Indexes
    __table_args__ = (
        Index("idx_ai_opt_provider_model", "provider", "model_id"),
        Index("idx_ai_opt_provider_created", "provider", "created_at"),
    )


# =============================================================================
# Contract Intelligence Models
# =============================================================================
