"""
Contract Intelligence Database Models

This module defines the database schema for storing contract intelligence,
case law learnings, and semantic understanding of contract clauses.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Float,
    Boolean,
    JSON,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class ContractType(Base):
    """Model for different contract types (JCT, NEC, FIDIC, etc.)"""

    __tablename__ = "contract_types"

    id = Column(Integer, primary_key=True)
    name = Column(
        String(100), nullable=False, unique=True
    )  # e.g., "JCT Design and Build 2016"
    version = Column(String(50), nullable=False)  # e.g., "2016"
    description = Column(Text)
    config = Column(JSON)  # Contract-specific configuration
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    clauses = relationship("CIContractClause", back_populates="contract_type")
    projects = relationship("ProjectContract", back_populates="contract_type")


class CIContractClause(Base):
    """Model for individual contract clauses with semantic understanding"""

    __tablename__ = "ci_contract_clauses_v2"

    id = Column(Integer, primary_key=True)
    contract_type_id = Column(Integer, ForeignKey("contract_types.id"), nullable=False)
    clause_number = Column(String(20), nullable=False)  # e.g., "2.26.3"
    title = Column(String(200), nullable=False)
    description = Column(Text)
    keywords = Column(JSON)  # List of keywords and phrases
    risk_level = Column(String(20))  # low, medium, high, critical
    entitlement_type = Column(String(50))  # extension_of_time, variation, payment, etc.
    relevance_score = Column(Float, default=0.0)  # 0.0 to 1.0
    vector_embedding = Column(JSON)  # Stored vector embedding for semantic search
    metadata = Column(JSON)  # Additional metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    contract_type = relationship("ContractType", back_populates="clauses")
    case_law_references = relationship("CICase LawReference", back_populates="clause")
    correspondence_matches = relationship(
        "CorrespondenceMatch", back_populates="clause"
    )


class CICaseLawReference(Base):
    """Model for case law references and legal precedents"""

    __tablename__ = "ci_case_law_references_v2"

    id = Column(Integer, primary_key=True)
    clause_id = Column(Integer, ForeignKey("ci_contract_clauses_v2.id"), nullable=False)
    case_name = Column(String(200), nullable=False)
    citation = Column(String(100))  # Legal citation
    court = Column(String(100))  # Court name
    year = Column(Integer)
    summary = Column(Text)
    key_points = Column(JSON)  # List of key legal principles
    relevance_score = Column(Float, default=0.0)
    vector_embedding = Column(JSON)  # Semantic embedding
    source_url = Column(String(500))  # Original source URL
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    clause = relationship("CIContractClause", back_populates="case_law_references")


class ProjectContract(Base):
    """Model linking projects to specific contract types"""

    __tablename__ = "project_contracts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    contract_type_id = Column(Integer, ForeignKey("contract_types.id"), nullable=False)
    contract_reference = Column(String(100))  # Project-specific contract reference
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    contract_value = Column(Float)
    metadata = Column(JSON)  # Project-specific contract modifications
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    contract_type = relationship("ContractType", back_populates="projects")
    project = relationship("Project", back_populates="contracts")


class CorrespondenceMatch(Base):
    """Model for storing matches between correspondence and contract clauses"""

    __tablename__ = "correspondence_matches"

    id = Column(Integer, primary_key=True)
    correspondence_id = Column(Integer, ForeignKey("correspondence.id"), nullable=False)
    clause_id = Column(Integer, ForeignKey("contract_clauses.id"), nullable=False)
    confidence_score = Column(Float, nullable=False)  # 0.0 to 1.0
    match_type = Column(String(50))  # keyword, semantic, pattern, etc.
    matched_text = Column(Text)  # The text that triggered the match
    context = Column(Text)  # Surrounding context
    risk_assessment = Column(JSON)  # Risk analysis results
    entitlement_analysis = Column(JSON)  # Entitlement analysis
    is_reviewed = Column(Boolean, default=False)
    reviewed_by = Column(String(100))
    review_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    clause = relationship("CIContractClause", back_populates="correspondence_matches")
    correspondence = relationship("Correspondence", back_populates="contract_matches")


class ContractIntelligenceConfig(Base):
    """Model for system-wide contract intelligence configuration"""

    __tablename__ = "contract_intelligence_config"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    value = Column(JSON, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ModelTrainingRun(Base):
    """Model for tracking contract model training runs"""

    __tablename__ = "model_training_runs"

    id = Column(Integer, primary_key=True)
    contract_type_id = Column(Integer, ForeignKey("contract_types.id"))
    model_type = Column(String(50), nullable=False)  # semantic, classifier, etc.
    training_data_size = Column(Integer)
    accuracy_score = Column(Float)
    precision_score = Column(Float)
    recall_score = Column(Float)
    f1_score = Column(Float)
    training_duration = Column(Float)  # in seconds
    model_path = Column(String(500))  # Path to trained model
    metadata = Column(JSON)  # Training parameters and metrics
    status = Column(
        String(20), default="completed"
    )  # pending, running, completed, failed
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


# Import existing models to establish relationships
# Note: These imports assume the existing models are in the same package
from .correspondence import Correspondence  # noqa
from .project import Project  # noqa
