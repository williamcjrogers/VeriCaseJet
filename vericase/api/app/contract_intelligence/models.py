"""
Database models for Contract Intelligence Layer
Stores case law learnings, contract configurations, and semantic knowledge
"""

from datetime import datetime
from typing import List, Optional, Any
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    JSON,
    Boolean,
    ForeignKey,
    Float,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from vericase.api.app.db import Base


class ContractType(Base):
    """Stores different contract types (JCT, NEC, FIDIC, etc.)"""

    __tablename__ = "ci_contract_types"

    id = Column(Integer, primary_key=True)
    name = Column(
        String(100), nullable=False, unique=True
    )  # e.g., "JCT Design and Build 2016"
    version = Column(String(50), nullable=False)  # e.g., "2016"
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    clauses = relationship("ContractClause", back_populates="contract_type")
    projects = relationship("ProjectContract", back_populates="contract_type")
    case_law_references = relationship(
        "CaseLawReference", back_populates="contract_type"
    )


class ContractClause(Base):
    """Stores detailed information about contract clauses"""

    __tablename__ = "ci_contract_clauses"

    id = Column(Integer, primary_key=True)
    contract_type_id = Column(
        Integer, ForeignKey("ci_contract_types.id"), nullable=False
    )
    clause_number = Column(String(50), nullable=False)  # e.g., "2.26.3"
    title = Column(String(200), nullable=False)
    description = Column(Text)
    risk_level = Column(String(20))  # low, medium, high, critical
    keywords = Column(ARRAY(String))  # Search keywords for this clause
    semantic_patterns = Column(ARRAY(String))  # NLP patterns for detection
    related_clauses = Column(ARRAY(String))  # Related clause numbers
    entitlement_types = Column(ARRAY(String))  # time_extension, cost_recovery, etc.
    mitigation_strategies = Column(ARRAY(String))
    time_implications = Column(Text)
    cost_implications = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    contract_type = relationship("ContractType", back_populates="clauses")
    case_law_references = relationship("CaseLawReference", back_populates="clause")
    correspondence_matches = relationship(
        "CorrespondenceClauseMatch", back_populates="clause"
    )


class CaseLawReference(Base):
    """Stores case law references and learnings for contract clauses"""

    __tablename__ = "ci_case_law_references"

    id = Column(Integer, primary_key=True)
    contract_type_id = Column(
        Integer, ForeignKey("ci_contract_types.id"), nullable=False
    )
    clause_id = Column(Integer, ForeignKey("ci_contract_clauses.id"))
    case_name = Column(String(200), nullable=False)  # e.g., "Walter Lilly v Mackay"
    citation = Column(String(100))  # e.g., "[2012] EWHC 1773 (TCC)"
    summary = Column(Text)
    key_principles = Column(ARRAY(String))  # Key legal principles from the case
    implications = Column(Text)  # Practical implications for contract administration
    relevance_score = Column(Float)  # 0-1 score of relevance to clause
    tags = Column(
        ARRAY(String)
    )  # e.g., ["time_extension", "concurrent_delay", "notice"]
    source_url = Column(String(500))  # Link to full case text
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    contract_type = relationship("ContractType", back_populates="case_law_references")
    clause = relationship("ContractClause", back_populates="case_law_references")


class ProjectContract(Base):
    """Links projects to specific contract types and configurations"""

    __tablename__ = "ci_project_contracts"

    id = Column(Integer, primary_key=True)
    project_id = Column(
        UUID(as_uuid=True), nullable=False
    )  # References projects table in main DB
    contract_type_id = Column(
        Integer, ForeignKey("ci_contract_types.id"), nullable=False
    )
    contract_reference = Column(String(100))  # Project-specific contract reference
    start_date = Column(DateTime)
    completion_date = Column(DateTime)
    contract_value = Column(Float)
    special_provisions = Column(JSON)  # Project-specific amendments
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    contract_type = relationship("ContractType", back_populates="projects")
    correspondence_analyses = relationship(
        "CorrespondenceAnalysis", back_populates="project_contract"
    )


class CorrespondenceAnalysis(Base):
    """Stores analysis results for correspondence items"""

    __tablename__ = "ci_correspondence_analyses"

    id = Column(Integer, primary_key=True)
    project_contract_id = Column(
        Integer, ForeignKey("ci_project_contracts.id"), nullable=False
    )
    correspondence_id = Column(
        UUID(as_uuid=True), nullable=False
    )  # References correspondence table in main DB
    raw_text = Column(Text)  # Original text content
    analysis_result = Column(JSON)  # Full analysis results
    risk_score = Column(Float)  # Overall risk score 0-1
    entitlement_score = Column(Float)  # Overall entitlement score 0-1
    primary_clauses = Column(ARRAY(String))  # Main clauses detected
    tags = Column(ARRAY(String))  # Auto-generated tags
    confidence_score = Column(Float)  # Analysis confidence 0-1
    analyzed_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    project_contract = relationship(
        "ProjectContract", back_populates="correspondence_analyses"
    )
    clause_matches = relationship(
        "CorrespondenceClauseMatch", back_populates="analysis"
    )


class CorrespondenceClauseMatch(Base):
    """Links correspondence analyses to specific contract clauses"""

    __tablename__ = "ci_correspondence_clause_matches"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(
        Integer, ForeignKey("ci_correspondence_analyses.id"), nullable=False
    )
    clause_id = Column(Integer, ForeignKey("ci_contract_clauses.id"), nullable=False)
    match_score = Column(Float)  # 0-1 confidence in match
    keyword_matches = Column(ARRAY(String))  # Specific keywords matched
    pattern_matches = Column(ARRAY(String))  # Semantic patterns matched
    context_snippet = Column(Text)  # Relevant text snippet
    risk_level = Column(String(20))  # Inherited from clause
    entitlement_types = Column(ARRAY(String))  # Potential entitlements
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    analysis = relationship("CorrespondenceAnalysis", back_populates="clause_matches")
    clause = relationship("ContractClause", back_populates="correspondence_matches")


class ContractKnowledgeVector(Base):
    """Stores vector embeddings for semantic search and AI understanding"""

    __tablename__ = "ci_contract_knowledge_vectors"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(50), nullable=False)  # clause, case_law, correspondence
    entity_id = Column(
        String(50), nullable=False
    )  # ID of the related entity (String to support UUIDs and Ints)
    embedding_model = Column(
        String(100), nullable=False
    )  # e.g., "text-embedding-ada-002"
    embedding_vector = Column(ARRAY(Float))  # The actual vector embedding
    text_content = Column(Text)  # Original text that was embedded
    metadata = Column(JSON)  # Additional metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    # Index for efficient similarity search
    __table_args__ = (
        Index("ix_ci_contract_knowledge_vectors_entity", "entity_type", "entity_id"),
        Index("ix_ci_contract_knowledge_vectors_model", "embedding_model"),
    )


class AITrainingExample(Base):
    """Stores training examples for contract AI model"""

    __tablename__ = "ci_ai_training_examples"

    id = Column(Integer, primary_key=True)
    contract_type_id = Column(
        Integer, ForeignKey("ci_contract_types.id"), nullable=False
    )
    input_text = Column(Text, nullable=False)
    expected_output = Column(JSON, nullable=False)  # Expected analysis results
    source_type = Column(String(50))  # manual, case_law, historical, generated
    confidence_score = Column(Float)  # Quality score 0-1
    tags = Column(ARRAY(String))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    contract_type = relationship("ContractType")


class PluginConfiguration(Base):
    """Stores configuration for contract intelligence plugins"""

    __tablename__ = "ci_plugin_configurations"

    id = Column(Integer, primary_key=True)
    plugin_name = Column(
        String(100), nullable=False, unique=True
    )  # e.g., "jct_analyzer"
    contract_type = Column(String(100), nullable=False)  # e.g., "JCT"
    version = Column(String(50), nullable=False)
    configuration = Column(JSON)  # Plugin-specific settings
    is_enabled = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # Processing priority
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Utility functions
class ContractIntelligenceModels:
    """Utility class for contract intelligence model operations"""

    @staticmethod
    def get_all_models() -> List[Any]:
        """Get all model classes for database creation"""
        return [
            ContractType,
            ContractClause,
            CaseLawReference,
            ProjectContract,
            CorrespondenceAnalysis,
            CorrespondenceClauseMatch,
            ContractKnowledgeVector,
            AITrainingExample,
            PluginConfiguration,
        ]

    @staticmethod
    def get_model_by_table_name(table_name: str) -> Optional[Any]:
        """Get model class by table name"""
        models = {
            "ci_contract_types": ContractType,
            "ci_contract_clauses": ContractClause,
            "ci_case_law_references": CaseLawReference,
            "ci_project_contracts": ProjectContract,
            "ci_correspondence_analyses": CorrespondenceAnalysis,
            "ci_correspondence_clause_matches": CorrespondenceClauseMatch,
            "ci_contract_knowledge_vectors": ContractKnowledgeVector,
            "ci_ai_training_examples": AITrainingExample,
            "ci_plugin_configurations": PluginConfiguration,
        }
        return models.get(table_name)


# Example data for initialization
DEFAULT_CONTRACT_TYPES = [
    {
        "name": "JCT Design and Build 2016",
        "version": "2016",
        "description": "Joint Contracts Tribunal Design and Build Contract 2016",
    },
    {
        "name": "NEC4 Engineering and Construction Contract",
        "version": "4",
        "description": "New Engineering Contract 4th Edition",
    },
    {
        "name": "FIDIC Red Book 2017",
        "version": "2017",
        "description": "FIDIC Conditions of Contract for Construction",
    },
]
