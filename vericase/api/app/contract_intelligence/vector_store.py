"""
Vector Store for Contract Intelligence
Stub implementation - vector store disabled
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ContractVectorStore:
    """Stub vector store - no-op implementation"""

    def __init__(self):
        logger.info("Vector store disabled (no Qdrant configured)")

    def ensure_collection(self):
        pass

    async def upsert_vectors(
        self,
        vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
    ):
        pass

    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: float = 0.7,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return []


vector_store = ContractVectorStore()
