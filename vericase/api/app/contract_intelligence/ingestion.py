"""
Ingestion Service for Contract Intelligence
Ingests case law and contract documents into the vector store
"""

import logging
from sqlalchemy.orm import Session
from .models import CaseLawReference, CIContractClause
from .vector_store import vector_store
from .embeddings import embedding_service

logger = logging.getLogger(__name__)


class IngestionService:
    """Service for ingesting knowledge into the vector store"""

    async def ingest_clauses(self, db: Session):
        """Ingest all contract clauses into vector store"""
        clauses = db.query(CIContractClause).all()

        texts = []
        payloads = []
        ids = []

        for clause in clauses:
            # Create a rich text representation
            text = f"{clause.title}\n{clause.description}\nKeywords: {', '.join(clause.keywords or [])}"
            texts.append(text)

            payloads.append(
                {
                    "entity_type": "clause",
                    "entity_id": clause.id,
                    "clause_number": clause.clause_number,
                    "contract_type_id": clause.contract_type_id,
                    "risk_level": clause.risk_level,
                }
            )
            ids.append(f"clause_{clause.id}")

        if not texts:
            return

        embeddings = await embedding_service.generate_embeddings(texts)

        await vector_store.upsert_vectors(embeddings, payloads, ids)

        # Store in DB as well (optional, for backup/audit)
        # ...

    async def ingest_case_law(self, db: Session):
        """Ingest case law references"""
        cases = db.query(CaseLawReference).all()

        texts = []
        payloads = []
        ids = []

        for case in cases:
            text = f"{case.case_name}\n{case.summary}\nPrinciples: {', '.join(case.key_principles or [])}"
            texts.append(text)

            payloads.append(
                {
                    "entity_type": "case_law",
                    "entity_id": case.id,
                    "citation": case.citation,
                    "contract_type_id": case.contract_type_id,
                }
            )
            ids.append(f"case_{case.id}")

        if not texts:
            return

        embeddings = await embedding_service.generate_embeddings(texts)

        await vector_store.upsert_vectors(embeddings, payloads, ids)


ingestion_service = IngestionService()
