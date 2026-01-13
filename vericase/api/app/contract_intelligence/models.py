from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    JSON,
    DateTime,
    ForeignKey,
    Boolean,
    Index,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class ContractType(Base):
    __tablename__ = "contract_types"

    id = Column(Integer, primary_key=True)
    name = Column(
        String(100), unique=True, nullable=False
    )  # e.g., "JCT Design and Build 2016"
    description = Column(Text)
    version = Column(String(50))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to clauses
    clauses = relationship(
        "ContractClause", back_populates="contract_type", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ContractType(name='{self.name}', version='{self.version}')>"


class ContractClause(Base):
    __tablename__ = "contract_clauses"

    id = Column(Integer, primary_key=True)
    contract_type_id = Column(Integer, ForeignKey("contract_types.id"), nullable=False)
    clause_number = Column(String(50), nullable=False)  # e.g., "2.26.8"
    title = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(
        String(100)
    )  # e.g., "Relevant Event", "Compensation Event", "Risk"
    risk_level = Column(String(20))  # e.g., "High", "Medium", "Low"
    keywords = Column(JSON)  # List of keywords and phrases
    semantic_patterns = Column(JSON)  # Semantic patterns for NLP matching
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to contract type
    contract_type = relationship("ContractType", back_populates="clauses")

    def __repr__(self):
        return f"<ContractClause(clause_number='{self.clause_number}', title='{self.title}')>"


class CaseLawLearning(Base):
    __tablename__ = "case_law_learnings"

    id = Column(Integer, primary_key=True)
    contract_type_id = Column(Integer, ForeignKey("contract_types.id"), nullable=False)
    clause_number = Column(String(50), nullable=False)
    case_reference = Column(String(200))
    summary = Column(Text)
    key_findings = Column(JSON)  # Key legal principles and interpretations
    risk_implications = Column(Text)
    entitlement_guidance = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return (
            f"<CaseLawLearning(clause_number='{self.clause_number}', "
            f"case_reference='{self.case_reference}')>"
        )


class ContractAnalysisResult(Base):
    __tablename__ = "contract_analysis_results"

    id = Column(Integer, primary_key=True)
    correspondence_id = Column(Integer, ForeignKey("correspondence.id"), nullable=False)
    contract_type_id = Column(Integer, ForeignKey("contract_types.id"), nullable=False)
    matched_clauses = Column(JSON)  # List of matched clauses with confidence scores
    risk_assessment = Column(JSON)  # Risk analysis results
    entitlement_analysis = Column(JSON)  # Entitlement analysis results
    confidence_score = Column(Integer)  # Overall confidence in analysis
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ContractAnalysisResult(correspondence_id={self.correspondence_id}, confidence={self.confidence_score})>"


# Create indexes for better query performance
Index("ix_contract_clauses_contract_type_id", ContractClause.contract_type_id)
Index("ix_contract_clauses_clause_number", ContractClause.clause_number)
Index(
    "ix_case_law_learnings_contract_type_clause",
    CaseLawLearning.contract_type_id,
    CaseLawLearning.clause_number,
)
Index("ix_contract_analysis_correspondence", ContractAnalysisResult.correspondence_id)
