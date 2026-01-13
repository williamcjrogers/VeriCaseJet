"""
Vector Store for Contract Intelligence
Handles interaction with Qdrant for storing and retrieving semantic vectors
"""

import logging
import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from ..config import settings

logger = logging.getLogger(__name__)


class ContractVectorStore:
    """Interface for Qdrant vector database"""

    COLLECTION_NAME = "contract_intelligence"
    VECTOR_SIZE = 1024  # Default for Cohere embed-english-v3

    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize Qdrant client"""
        try:
            if settings.QDRANT_URL:
                self.client = QdrantClient(
                    url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY
                )
                logger.info(f"Connected to Qdrant at {settings.QDRANT_URL}")
            else:
                logger.warning("QDRANT_URL not set, vector store disabled")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")

    def ensure_collection(self):
        """Ensure the contract intelligence collection exists"""
        if not self.client:
            return

        try:
            collections = self.client.get_collections()
            exists = any(
                c.name == self.COLLECTION_NAME for c in collections.collections
            )

            if not exists:
                logger.info(f"Creating collection {self.COLLECTION_NAME}")
                self.client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=rest.VectorParams(
                        size=self.VECTOR_SIZE, distance=rest.Distance.COSINE
                    ),
                )
        except Exception as e:
            logger.error(f"Error checking/creating collection: {e}")

    async def upsert_vectors(
        self,
        vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
    ):
        """Upsert vectors with metadata"""
        if not self.client:
            return

        if not ids:
            ids = [str(uuid.uuid4()) for _ in vectors]

        points = [
            rest.PointStruct(id=id, vector=vector, payload=payload)
            for id, vector, payload in zip(ids, vectors, payloads)
        ]

        try:
            self.client.upsert(collection_name=self.COLLECTION_NAME, points=points)
            logger.info(f"Upserted {len(points)} vectors")
        except Exception as e:
            logger.error(f"Error upserting vectors: {e}")

    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: float = 0.7,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors"""
        if not self.client:
            return []

        search_filter = None
        if filter_conditions:
            # Simple equality filter implementation
            conditions = []
            for key, value in filter_conditions.items():
                conditions.append(
                    rest.FieldCondition(key=key, match=rest.MatchValue(value=value))
                )
            if conditions:
                search_filter = rest.Filter(must=conditions)

        try:
            results = self.client.search(
                collection_name=self.COLLECTION_NAME,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=search_filter,
            )

            return [
                {"id": hit.id, "score": hit.score, "payload": hit.payload}
                for hit in results
            ]
        except Exception as e:
            logger.error(f"Error searching vectors: {e}")
            return []


vector_store = ContractVectorStore()
