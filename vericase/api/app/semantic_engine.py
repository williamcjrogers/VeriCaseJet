"""
VeriCase Semantic Engine
=========================
Multi-vector semantic processing for deep research acceleration.

Implements:
- 4-Vector Semantic Threading:
  * content_vec: Semantic meaning of text content
  * participant_vec: Who's involved (sender, recipients, mentioned people)
  * temporal_vec: When things happened (cyclical month + linear year encoding)
  * attachment_vec: What's attached (file types, document categories)
- Semantic chunking (paragraph/section-aware splitting)
- Dense embedding generation (Amazon Bedrock Cohere Embed v3)
- OpenSearch k-NN vector indexing with multi-vector fusion
- Named entity extraction (spaCy)
- Pre-computed document summaries

Architecture based on Egnyte Deep Research Agent patterns:
https://www.egnyte.com/blog/post/inside-the-architecture-of-a-deep-research-agent
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypedDict


from .config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Embedding provider: "bedrock" (recommended) or "sentence-transformers" (fallback)
EMBEDDING_PROVIDER = getattr(settings, "EMBEDDING_PROVIDER", "bedrock")

# Bedrock embedding models (Cohere Embed English v3 - 1024 dimensions)
BEDROCK_EMBEDDING_MODEL = getattr(
    settings, "BEDROCK_EMBEDDING_MODEL", "cohere.embed-english-v3"
)
BEDROCK_EMBEDDING_DIMENSION = 1024  # Cohere v3 output dimension
BEDROCK_REGION = getattr(settings, "BEDROCK_REGION", "us-east-1")

# Fallback: sentence-transformers (384 dimensions)
SENTENCE_TRANSFORMER_MODEL = "all-MiniLM-L6-v2"  # 384 dimensions, ~23M params
SENTENCE_TRANSFORMER_DIMENSION = 384

# Active embedding dimension (depends on provider)
EMBEDDING_MODEL = (
    BEDROCK_EMBEDDING_MODEL
    if EMBEDDING_PROVIDER == "bedrock"
    else SENTENCE_TRANSFORMER_MODEL
)
EMBEDDING_DIMENSION = (
    BEDROCK_EMBEDDING_DIMENSION
    if EMBEDDING_PROVIDER == "bedrock"
    else SENTENCE_TRANSFORMER_DIMENSION
)

# Cross-encoder for reranking (already used in deep_research.py)
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Chunking settings
DEFAULT_CHUNK_SIZE = 512  # tokens (~400 words)
DEFAULT_CHUNK_OVERLAP = 64  # tokens overlap for context continuity
MAX_CHUNK_SIZE = 1024  # absolute max

# OpenSearch k-NN index settings
VECTOR_INDEX_NAME = "vericase_vectors"
MULTI_VECTOR_INDEX_NAME = "vericase_vectors_v3"  # 4-vector index
KNN_ALGORITHM = "hnsw"  # Hierarchical Navigable Small World - fast ANN
KNN_EF_CONSTRUCTION = 256  # Higher = better quality, slower indexing
KNN_M = 16  # Number of bi-directional links - good balance

# Multi-vector configuration
MULTI_VECTOR_ENABLED = getattr(settings, "MULTI_VECTOR_ENABLED", True)

# Default fusion weights for multi-vector search
DEFAULT_FUSION_WEIGHTS = {
    "content": 0.5,  # Semantic content is primary
    "participant": 0.25,  # Who's involved
    "temporal": 0.15,  # When it happened
    "attachment": 0.10,  # What's attached
}

# Temporal encoding reference year (for linear year distance)
TEMPORAL_REFERENCE_YEAR = 2020


# =============================================================================
# Data Types
# =============================================================================


class ChunkMetadata(TypedDict, total=False):
    """Metadata for a semantic chunk"""

    chunk_index: int
    total_chunks: int
    char_start: int
    char_end: int
    source_type: str  # email, attachment, evidence
    source_id: str
    parent_id: str | None
    section_type: str | None  # header, body, signature, quote
    entities: list[dict[str, str]]
    embedding_model: str


class MultiVectorEmbeddings(TypedDict, total=False):
    """
    4-vector semantic representation for multi-faceted search.

    Each vector captures a different aspect of the document:
    - content_vec: What the text is about (semantic meaning)
    - participant_vec: Who's involved (people, organizations)
    - temporal_vec: When it happened (encoded date/time)
    - attachment_vec: What's attached (file types, categories)
    """

    content_vec: list[float]  # 1024 dims - semantic content
    participant_vec: list[float]  # 1024 dims - people/orgs involved
    temporal_vec: list[float]  # 1024 dims - time encoding
    attachment_vec: list[float]  # 1024 dims - attachment context


class EmailContext(TypedDict, total=False):
    """Context extracted from an email for multi-vector encoding"""

    # Content
    subject: str
    body_text: str

    # Participants
    sender: str
    sender_name: str
    recipients_to: list[str]
    recipients_cc: list[str]
    mentioned_people: list[str]
    mentioned_orgs: list[str]

    # Temporal
    sent_date: datetime | None
    thread_dates: list[datetime]

    # Attachments
    attachment_names: list[str]
    attachment_types: list[str]  # e.g., ["pdf", "xlsx", "jpg"]
    attachment_categories: list[str]  # e.g., ["invoice", "drawing", "contract"]


@dataclass
class SemanticChunk:
    """A semantically coherent piece of text with embedding"""

    text: str
    embedding: list[float] | None = None
    metadata: ChunkMetadata = field(default_factory=dict)  # type: ignore[assignment]
    chunk_hash: str = ""

    def __post_init__(self):
        if not self.chunk_hash:
            self.chunk_hash = hashlib.sha256(self.text.encode()).hexdigest()[:16]


@dataclass
class EntityExtraction:
    """Extracted named entities from text"""

    persons: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    money: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    custom: dict[str, list[str]] = field(default_factory=dict)  # domain-specific


# =============================================================================
# Bedrock Embedding Client
# =============================================================================


class BedrockEmbeddingClient:
    """
    Amazon Bedrock embedding client using Cohere Embed English v3.

    Supports:
    - cohere.embed-english-v3: 1024 dimensions, best quality
    - amazon.titan-embed-text-v1: 1536 dimensions, alternative
    """

    def __init__(
        self, region: str = BEDROCK_REGION, model_id: str = BEDROCK_EMBEDDING_MODEL
    ):
        self.region = region
        self.model_id = model_id
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )
            logger.info(f"Initialized Bedrock client in {self.region}")
        return self._client

    def embed_text(self, text: str, input_type: str = "search_document") -> list[float]:
        """
        Generate embedding for a single text using Bedrock.

        Args:
            text: Text to embed
            input_type: "search_document" for indexing, "search_query" for queries

        Returns:
            List of floats (embedding vector)
        """
        import json

        if not text or not text.strip():
            return [0.0] * BEDROCK_EMBEDDING_DIMENSION

        # Cohere Embed v3 request format
        if "cohere" in self.model_id:
            request_body = {
                "texts": [text[:2048]],  # Cohere max input is 2048 tokens
                "input_type": input_type,
                "truncate": "END",
            }
        # Titan Embed request format
        elif "titan" in self.model_id:
            request_body = {
                "inputText": text[:8000],  # Titan supports longer input
            }
        else:
            raise ValueError(f"Unsupported embedding model: {self.model_id}")

        try:
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())

            # Extract embedding based on model type
            if "cohere" in self.model_id:
                return response_body["embeddings"][0]
            elif "titan" in self.model_id:
                return response_body["embedding"]
            else:
                return response_body.get(
                    "embedding", response_body.get("embeddings", [[]])[0]
                )

        except Exception as e:
            logger.error(f"Bedrock embedding failed: {e}")
            raise

    def embed_texts(
        self,
        texts: list[str],
        input_type: str = "search_document",
        batch_size: int = 96,
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts using Bedrock.

        Cohere supports batch requests of up to 96 texts.
        """
        import json

        if not texts:
            return []

        # Filter empty texts but track indices
        valid_texts: list[tuple[int, str]] = [
            (i, t[:2048]) for i, t in enumerate(texts) if t and t.strip()
        ]

        if not valid_texts:
            return [[0.0] * BEDROCK_EMBEDDING_DIMENSION] * len(texts)

        # Initialize result with zeros
        result: list[list[float]] = [[0.0] * BEDROCK_EMBEDDING_DIMENSION] * len(texts)

        # Process in batches
        for batch_start in range(0, len(valid_texts), batch_size):
            batch = valid_texts[batch_start : batch_start + batch_size]
            batch_texts = [t for _, t in batch]

            if "cohere" in self.model_id:
                request_body = {
                    "texts": batch_texts,
                    "input_type": input_type,
                    "truncate": "END",
                }

                try:
                    response = self.client.invoke_model(
                        modelId=self.model_id,
                        body=json.dumps(request_body),
                        contentType="application/json",
                        accept="application/json",
                    )

                    response_body = json.loads(response["body"].read())
                    embeddings = response_body["embeddings"]

                    # Map embeddings back to original indices
                    for (orig_idx, _), embedding in zip(batch, embeddings):
                        result[orig_idx] = embedding

                except Exception as e:
                    logger.error(f"Bedrock batch embedding failed: {e}")
                    # Fall back to individual requests
                    for orig_idx, text in batch:
                        try:
                            result[orig_idx] = self.embed_text(text, input_type)
                        except Exception:
                            pass  # Keep zeros for failed embeddings

            else:
                # Titan doesn't support batch - process individually
                for orig_idx, text in batch:
                    try:
                        result[orig_idx] = self.embed_text(text, input_type)
                    except Exception:
                        pass

        return result


# =============================================================================
# Singleton Model Loaders (Lazy Loading)
# =============================================================================


class ModelRegistry:
    """Centralized model loading with lazy initialization"""

    _embedding_model: Any = None
    _bedrock_client: BedrockEmbeddingClient | None = None
    _cross_encoder: Any = None
    _ner_model: Any = None
    _tokenizer: Any = None

    @classmethod
    def get_bedrock_client(cls) -> BedrockEmbeddingClient:
        """Get or create Bedrock embedding client"""
        if cls._bedrock_client is None:
            logger.info(
                f"Initializing Bedrock embedding client: {BEDROCK_EMBEDDING_MODEL}"
            )
            cls._bedrock_client = BedrockEmbeddingClient(
                region=BEDROCK_REGION,
                model_id=BEDROCK_EMBEDDING_MODEL,
            )
            logger.info("Bedrock client initialized successfully")
        return cls._bedrock_client

    @classmethod
    def get_embedding_model(cls) -> Any:
        """Load sentence-transformer embedding model (fallback)"""
        if cls._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info(
                    f"Loading sentence-transformer model: {SENTENCE_TRANSFORMER_MODEL}"
                )
                cls._embedding_model = SentenceTransformer(SENTENCE_TRANSFORMER_MODEL)
                logger.info("Sentence-transformer model loaded successfully")
            except ImportError:
                logger.error(
                    "sentence-transformers not installed. Run: pip install sentence-transformers"
                )
                raise
            except Exception as e:
                logger.error(f"Failed to load embedding model: {e}")
                raise
        return cls._embedding_model

    @classmethod
    def get_cross_encoder(cls) -> Any:
        """Load cross-encoder for reranking"""
        if cls._cross_encoder is None:
            try:
                from sentence_transformers import CrossEncoder

                logger.info(f"Loading cross-encoder: {CROSS_ENCODER_MODEL}")
                cls._cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
                logger.info("Cross-encoder loaded successfully")
            except ImportError:
                logger.warning("sentence-transformers not installed for cross-encoder")
                return None
            except Exception as e:
                logger.warning(f"Failed to load cross-encoder: {e}")
                return None
        return cls._cross_encoder

    @classmethod
    def get_ner_model(cls) -> Any:
        """Load spaCy NER model"""
        if cls._ner_model is None:
            try:
                import spacy

                # Try to load the medium English model (better NER)
                try:
                    cls._ner_model = spacy.load("en_core_web_md")
                except OSError:
                    # Fall back to small model
                    try:
                        cls._ner_model = spacy.load("en_core_web_sm")
                    except OSError:
                        logger.warning(
                            "No spaCy model found. Run: python -m spacy download en_core_web_md"
                        )
                        return None
                logger.info("spaCy NER model loaded successfully")
            except ImportError:
                logger.warning("spaCy not installed. Run: pip install spacy")
                return None
        return cls._ner_model


# =============================================================================
# Semantic Chunking
# =============================================================================


class SemanticChunker:
    """
    Intelligent text chunking that preserves semantic coherence.

    Unlike naive character/word splitting, this:
    1. Respects paragraph boundaries
    2. Keeps sentences intact
    3. Identifies email structure (headers, quotes, signatures)
    4. Maintains context with configurable overlap
    """

    # Email structure patterns
    QUOTE_PATTERNS = [
        r"^>+\s*",  # > quoted text
        r"^On .+ wrote:",  # On [date] [name] wrote:
        r"^From:\s",  # Forwarded headers
        r"^-{3,}\s*Original Message",  # --- Original Message ---
        r"^_{3,}\s*",  # ___ separators
    ]

    SIGNATURE_PATTERNS = [
        r"^--\s*$",  # Standard -- signature delimiter
        r"^Best regards",
        r"^Kind regards",
        r"^Regards,",
        r"^Thanks,",
        r"^Cheers,",
        r"^Sent from my iPhone",
        r"^Sent from my Android",
        r"^\*{3,}",  # *** confidentiality notice
    ]

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
        respect_sentences: bool = True,
    ):
        self.chunk_size = min(chunk_size, MAX_CHUNK_SIZE)
        self.chunk_overlap = chunk_overlap
        self.respect_sentences = respect_sentences

    def chunk_text(
        self,
        text: str,
        source_type: str = "unknown",
        source_id: str = "",
        parent_id: str | None = None,
    ) -> list[SemanticChunk]:
        """
        Split text into semantic chunks.

        For emails, identifies and tags:
        - Headers (To, From, Subject, Date)
        - Body content (primary information)
        - Quoted replies (context)
        - Signatures (usually noise)
        """
        if not text or not text.strip():
            return []

        # Clean and normalize text
        text = self._normalize_text(text)

        # For emails, use structure-aware chunking
        if source_type == "email":
            return self._chunk_email(text, source_id, parent_id)

        # For documents, use paragraph-aware chunking
        return self._chunk_document(text, source_type, source_id, parent_id)

    def _normalize_text(self, text: str) -> str:
        """Normalize whitespace and remove control characters"""
        # Remove zero-width characters
        text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Remove excessive blank lines
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    def _chunk_email(
        self, text: str, source_id: str, parent_id: str | None
    ) -> list[SemanticChunk]:
        """Structure-aware email chunking"""
        chunks: list[SemanticChunk] = []
        lines = text.split("\n")

        current_section = "body"
        current_text: list[str] = []
        char_pos = 0

        for line in lines:
            line_with_newline = line + "\n"

            # Detect section changes
            new_section = self._detect_email_section(line, current_section)

            if new_section != current_section and current_text:
                # Emit current chunk
                chunk_text = "\n".join(current_text)
                if chunk_text.strip():
                    chunks.extend(
                        self._split_if_needed(
                            chunk_text,
                            section_type=current_section,
                            source_type="email",
                            source_id=source_id,
                            parent_id=parent_id,
                            char_start=char_pos - len(chunk_text),
                        )
                    )
                current_text = []

            current_section = new_section
            current_text.append(line)
            char_pos += len(line_with_newline)

        # Don't forget last section
        if current_text:
            chunk_text = "\n".join(current_text)
            if chunk_text.strip():
                chunks.extend(
                    self._split_if_needed(
                        chunk_text,
                        section_type=current_section,
                        source_type="email",
                        source_id=source_id,
                        parent_id=parent_id,
                        char_start=char_pos - len(chunk_text),
                    )
                )

        # Add chunk indexing
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i
            chunk.metadata["total_chunks"] = len(chunks)

        return chunks

    def _detect_email_section(self, line: str, current_section: str) -> str:
        """Detect what section of an email this line belongs to"""
        line_stripped = line.strip()

        # Check for quoted content
        for pattern in self.QUOTE_PATTERNS:
            if re.match(pattern, line_stripped, re.IGNORECASE):
                return "quote"

        # Check for signature
        for pattern in self.SIGNATURE_PATTERNS:
            if re.match(pattern, line_stripped, re.IGNORECASE):
                return "signature"

        # If we're in quote/signature, stay there unless clear body content
        if current_section in ("quote", "signature"):
            # Only exit if we see clear new content
            if len(line_stripped) > 50 and not line_stripped.startswith(">"):
                return "body"
            return current_section

        return "body"

    def _chunk_document(
        self, text: str, source_type: str, source_id: str, parent_id: str | None
    ) -> list[SemanticChunk]:
        """Paragraph-aware document chunking"""
        # Split by double newlines (paragraphs)
        paragraphs = re.split(r"\n\n+", text)

        chunks: list[SemanticChunk] = []
        current_chunk: list[str] = []
        current_length = 0
        char_pos = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_length = len(para.split())  # Word count approximation

            # If adding this paragraph exceeds chunk size, emit current
            if current_length + para_length > self.chunk_size and current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                chunks.append(
                    SemanticChunk(
                        text=chunk_text,
                        metadata={
                            "source_type": source_type,
                            "source_id": source_id,
                            "parent_id": parent_id,
                            "section_type": "body",
                            "char_start": char_pos - len(chunk_text),
                            "char_end": char_pos,
                            "embedding_model": EMBEDDING_MODEL,
                        },
                    )
                )

                # Keep overlap
                if self.chunk_overlap > 0 and current_chunk:
                    # Keep last paragraph for overlap
                    overlap_text = current_chunk[-1]
                    current_chunk = [overlap_text]
                    current_length = len(overlap_text.split())
                else:
                    current_chunk = []
                    current_length = 0

            current_chunk.append(para)
            current_length += para_length
            char_pos += len(para) + 2  # +2 for \n\n

        # Emit final chunk
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunks.append(
                SemanticChunk(
                    text=chunk_text,
                    metadata={
                        "source_type": source_type,
                        "source_id": source_id,
                        "parent_id": parent_id,
                        "section_type": "body",
                        "char_start": char_pos - len(chunk_text),
                        "char_end": char_pos,
                        "embedding_model": EMBEDDING_MODEL,
                    },
                )
            )

        # Add indexing
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i
            chunk.metadata["total_chunks"] = len(chunks)

        return chunks

    def _split_if_needed(
        self,
        text: str,
        section_type: str,
        source_type: str,
        source_id: str,
        parent_id: str | None,
        char_start: int,
    ) -> list[SemanticChunk]:
        """Split text further if it exceeds chunk size"""
        word_count = len(text.split())

        if word_count <= self.chunk_size:
            return [
                SemanticChunk(
                    text=text,
                    metadata={
                        "source_type": source_type,
                        "source_id": source_id,
                        "parent_id": parent_id,
                        "section_type": section_type,
                        "char_start": char_start,
                        "char_end": char_start + len(text),
                        "embedding_model": EMBEDDING_MODEL,
                    },
                )
            ]

        # Split by sentences if too long
        if self.respect_sentences:
            return self._split_by_sentences(
                text, section_type, source_type, source_id, parent_id, char_start
            )

        # Fallback: split by words
        words = text.split()
        chunks: list[SemanticChunk] = []

        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i : i + self.chunk_size]
            chunk_text = " ".join(chunk_words)
            chunks.append(
                SemanticChunk(
                    text=chunk_text,
                    metadata={
                        "source_type": source_type,
                        "source_id": source_id,
                        "parent_id": parent_id,
                        "section_type": section_type,
                        "char_start": char_start,
                        "char_end": char_start + len(chunk_text),
                        "embedding_model": EMBEDDING_MODEL,
                    },
                )
            )

        return chunks

    def _split_by_sentences(
        self,
        text: str,
        section_type: str,
        source_type: str,
        source_id: str,
        parent_id: str | None,
        char_start: int,
    ) -> list[SemanticChunk]:
        """Split text by sentence boundaries"""
        # Simple sentence splitting (handles common cases)
        sentence_endings = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
        sentences = sentence_endings.split(text)

        chunks: list[SemanticChunk] = []
        current_chunk: list[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence.split())

            if current_length + sentence_length > self.chunk_size and current_chunk:
                chunk_text = " ".join(current_chunk)
                chunks.append(
                    SemanticChunk(
                        text=chunk_text,
                        metadata={
                            "source_type": source_type,
                            "source_id": source_id,
                            "parent_id": parent_id,
                            "section_type": section_type,
                            "char_start": char_start,
                            "char_end": char_start + len(chunk_text),
                            "embedding_model": EMBEDDING_MODEL,
                        },
                    )
                )
                current_chunk = []
                current_length = 0

            current_chunk.append(sentence)
            current_length += sentence_length

        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append(
                SemanticChunk(
                    text=chunk_text,
                    metadata={
                        "source_type": source_type,
                        "source_id": source_id,
                        "parent_id": parent_id,
                        "section_type": section_type,
                        "char_start": char_start,
                        "char_end": char_start + len(chunk_text),
                        "embedding_model": EMBEDDING_MODEL,
                    },
                )
            )

        return chunks


# =============================================================================
# Embedding Generation
# =============================================================================


class EmbeddingService:
    """
    Generate dense vector embeddings for text.

    Supports two providers:
    - "bedrock": Amazon Bedrock with Cohere Embed English v3 (1024 dims, recommended)
    - "sentence-transformers": Local all-MiniLM-L6-v2 (384 dims, fallback)

    Provider is selected via EMBEDDING_PROVIDER setting.
    """

    def __init__(self, provider: str | None = None):
        self._provider = provider or EMBEDDING_PROVIDER
        self._model = None
        self._bedrock_client: BedrockEmbeddingClient | None = None
        logger.info(f"EmbeddingService initialized with provider: {self._provider}")

    @property
    def dimension(self) -> int:
        """Return the embedding dimension for the current provider"""
        if self._provider == "bedrock":
            return BEDROCK_EMBEDDING_DIMENSION
        return SENTENCE_TRANSFORMER_DIMENSION

    @property
    def bedrock_client(self) -> BedrockEmbeddingClient:
        if self._bedrock_client is None:
            self._bedrock_client = ModelRegistry.get_bedrock_client()
        return self._bedrock_client

    @property
    def model(self) -> Any:
        """Get sentence-transformer model (fallback only)"""
        if self._model is None:
            self._model = ModelRegistry.get_embedding_model()
        return self._model

    def embed_text(self, text: str, input_type: str = "search_document") -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed
            input_type: For Bedrock - "search_document" for indexing, "search_query" for queries

        Returns:
            List of floats (embedding vector)
        """
        if not text or not text.strip():
            return [0.0] * self.dimension

        if self._provider == "bedrock":
            try:
                return self.bedrock_client.embed_text(text, input_type)
            except Exception as e:
                logger.warning(
                    f"Bedrock embedding failed, falling back to sentence-transformers: {e}"
                )
                # Fall back to sentence-transformers
                embedding = self.model.encode(text, convert_to_numpy=True)
                return embedding.tolist()
        else:
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()

    def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a search query.

        Uses input_type="search_query" for Bedrock (optimized for queries).
        """
        return self.embed_text(query, input_type="search_query")

    def embed_texts(
        self,
        texts: list[str],
        batch_size: int = 32,
        input_type: str = "search_document",
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts (batched for efficiency).

        Args:
            texts: List of texts to embed
            batch_size: Batch size (96 for Bedrock Cohere, 32 for sentence-transformers)
            input_type: For Bedrock - "search_document" for indexing

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        if self._provider == "bedrock":
            try:
                # Bedrock Cohere supports batches of 96
                return self.bedrock_client.embed_texts(texts, input_type, batch_size=96)
            except Exception as e:
                logger.warning(f"Bedrock batch embedding failed, falling back: {e}")
                # Fall through to sentence-transformers

        # Sentence-transformers fallback
        valid_texts: list[tuple[int, str]] = [
            (i, t) for i, t in enumerate(texts) if t and t.strip()
        ]

        if not valid_texts:
            return [[0.0] * SENTENCE_TRANSFORMER_DIMENSION] * len(texts)

        # Batch encode
        valid_embeddings = self.model.encode(
            [t for _, t in valid_texts],
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=len(valid_texts) > 100,
        )

        # Reconstruct full list with zeros for empty texts
        result: list[list[float]] = [[0.0] * SENTENCE_TRANSFORMER_DIMENSION] * len(
            texts
        )
        for (orig_idx, _), embedding in zip(valid_texts, valid_embeddings):
            result[orig_idx] = embedding.tolist()

        return result

    def embed_chunks(
        self, chunks: list[SemanticChunk], batch_size: int = 32
    ) -> list[SemanticChunk]:
        """Add embeddings to chunks"""
        texts = [c.text for c in chunks]
        embeddings = self.embed_texts(texts, batch_size)

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding
            # Update metadata with actual model used
            chunk.metadata["embedding_model"] = EMBEDDING_MODEL

        return chunks


# =============================================================================
# Multi-Vector Embedding Service
# =============================================================================


class MultiVectorEmbeddingService:
    """
    Generate 4-vector semantic embeddings for multi-faceted search.

    Each email/document produces 4 vectors:
    1. content_vec: Semantic embedding of text content
    2. participant_vec: Embedding of who's involved (sender, recipients, mentioned)
    3. temporal_vec: Encoded date/time with cyclical month + linear year
    4. attachment_vec: Embedding of attachment context (types, names, categories)

    This enables queries like:
    "Emails between Keith and Mark about payment delays in Q1 2024 with invoices"
    - "payment delays" → content_vec
    - "Keith and Mark" → participant_vec
    - "Q1 2024" → temporal_vec
    - "invoices" → attachment_vec
    """

    # Common attachment type categories
    ATTACHMENT_CATEGORIES = {
        # Documents
        "pdf": "document",
        "doc": "document",
        "docx": "document",
        "txt": "document",
        "rtf": "document",
        # Spreadsheets
        "xls": "spreadsheet",
        "xlsx": "spreadsheet",
        "csv": "spreadsheet",
        # Images
        "jpg": "image",
        "jpeg": "image",
        "png": "image",
        "gif": "image",
        "bmp": "image",
        "tiff": "image",
        # Drawings/CAD
        "dwg": "drawing",
        "dxf": "drawing",
        "dwf": "drawing",
        # Presentations
        "ppt": "presentation",
        "pptx": "presentation",
        # Archives
        "zip": "archive",
        "rar": "archive",
        "7z": "archive",
        # Email
        "msg": "email",
        "eml": "email",
    }

    def __init__(self, embedding_service: EmbeddingService | None = None):
        self._embedder = embedding_service or EmbeddingService()

    @property
    def dimension(self) -> int:
        """All 4 vectors have same dimension"""
        return self._embedder.dimension

    def generate_multi_vectors(self, context: EmailContext) -> MultiVectorEmbeddings:
        """
        Generate all 4 vectors for an email.

        Args:
            context: EmailContext with all extracted information

        Returns:
            MultiVectorEmbeddings with all 4 vectors
        """
        return {
            "content_vec": self._generate_content_vector(context),
            "participant_vec": self._generate_participant_vector(context),
            "temporal_vec": self._generate_temporal_vector(context),
            "attachment_vec": self._generate_attachment_vector(context),
        }

    def _generate_content_vector(self, context: EmailContext) -> list[float]:
        """
        Generate semantic content embedding.

        Combines subject and body for full semantic representation.
        """
        subject = context.get("subject", "") or ""
        body = context.get("body_text", "") or ""

        # Combine with subject emphasis
        full_text = f"Subject: {subject}\n\n{body}" if subject else body

        if not full_text.strip():
            return [0.0] * self.dimension

        return self._embedder.embed_text(full_text, input_type="search_document")

    def _generate_participant_vector(self, context: EmailContext) -> list[float]:
        """
        Generate participant embedding.

        Creates a text representation of all people/orgs involved,
        then embeds it to enable semantic matching.

        E.g., "Keith Wood, Mark Emery, Bobby Kher from Welbourne Construction"
        """
        participants: list[str] = []

        # Sender
        sender = context.get("sender", "")
        sender_name = context.get("sender_name", "")
        if sender_name:
            participants.append(sender_name)
        elif sender:
            # Extract name from email
            name = self._extract_name_from_email(sender)
            if name:
                participants.append(name)

        # Recipients
        for recipient in context.get("recipients_to", []):
            name = self._extract_name_from_email(recipient)
            if name and name not in participants:
                participants.append(name)

        for recipient in context.get("recipients_cc", []):
            name = self._extract_name_from_email(recipient)
            if name and name not in participants:
                participants.append(name)

        # Mentioned people/orgs
        for person in context.get("mentioned_people", []):
            if person and person not in participants:
                participants.append(person)

        for org in context.get("mentioned_orgs", []):
            if org and org not in participants:
                participants.append(org)

        if not participants:
            return [0.0] * self.dimension

        # Create participant text and embed
        participant_text = ", ".join(participants[:20])  # Limit to 20
        return self._embedder.embed_text(participant_text, input_type="search_document")

    def _generate_temporal_vector(self, context: EmailContext) -> list[float]:
        """
        Generate temporal encoding vector.

        Uses hybrid encoding:
        - Cyclical encoding for month (sin/cos for circular continuity)
        - Linear encoding for year (distance from reference)
        - Day-of-week encoding

        Then pads to full embedding dimension for compatibility.
        """
        sent_date = context.get("sent_date")

        if not sent_date:
            return [0.0] * self.dimension

        # Extract components
        year = sent_date.year
        month = sent_date.month
        day = sent_date.day
        weekday = sent_date.weekday()  # 0=Monday, 6=Sunday

        # Cyclical month encoding (January close to December)
        month_sin = math.sin(2 * math.pi * month / 12)
        month_cos = math.cos(2 * math.pi * month / 12)

        # Cyclical day-of-month encoding
        day_sin = math.sin(2 * math.pi * day / 31)
        day_cos = math.cos(2 * math.pi * day / 31)

        # Cyclical weekday encoding
        weekday_sin = math.sin(2 * math.pi * weekday / 7)
        weekday_cos = math.cos(2 * math.pi * weekday / 7)

        # Linear year encoding (normalized distance from reference)
        year_linear = (year - TEMPORAL_REFERENCE_YEAR) / 10.0  # Scale to ~[-1, 1]

        # Quarter encoding
        quarter = (month - 1) // 3 + 1
        quarter_sin = math.sin(2 * math.pi * quarter / 4)
        quarter_cos = math.cos(2 * math.pi * quarter / 4)

        # Create base temporal features (9 values)
        temporal_features = [
            month_sin,
            month_cos,
            day_sin,
            day_cos,
            weekday_sin,
            weekday_cos,
            year_linear,
            quarter_sin,
            quarter_cos,
        ]

        # For k-NN to work, we need same dimension as other vectors
        # Approach: Create temporal description and embed it
        temporal_text = self._format_temporal_description(sent_date)
        temporal_embedding = self._embedder.embed_text(
            temporal_text, input_type="search_document"
        )

        # Inject raw temporal features into first positions (they're more precise)
        for i, val in enumerate(temporal_features):
            if i < len(temporal_embedding):
                temporal_embedding[i] = val

        return temporal_embedding

    def _generate_attachment_vector(self, context: EmailContext) -> list[float]:
        """
        Generate attachment context embedding.

        Creates text description of attachments and embeds it.
        E.g., "3 PDF documents, 2 Excel spreadsheets, 1 CAD drawing"
        """
        attachment_names = context.get("attachment_names", [])
        attachment_types = context.get("attachment_types", [])
        attachment_categories = context.get("attachment_categories", [])

        if not attachment_names and not attachment_types:
            return [0.0] * self.dimension

        # Build attachment description
        parts: list[str] = []

        # Count by category
        category_counts: dict[str, int] = {}
        for ext in attachment_types:
            category = self.ATTACHMENT_CATEGORIES.get(ext.lower(), "file")
            category_counts[category] = category_counts.get(category, 0) + 1

        for category, count in category_counts.items():
            if count == 1:
                parts.append(f"1 {category}")
            else:
                parts.append(f"{count} {category}s")

        # Add specific names that might be meaningful
        meaningful_names = []
        for name in attachment_names[:5]:
            # Skip generic names
            if name and not name.lower().startswith(("image", "attachment", "file")):
                meaningful_names.append(name)

        # Add manual categories if provided
        for cat in attachment_categories[:5]:
            if cat and cat not in parts:
                parts.append(cat)

        attachment_text = ", ".join(parts)
        if meaningful_names:
            attachment_text += f" named: {', '.join(meaningful_names)}"

        if not attachment_text.strip():
            return [0.0] * self.dimension

        return self._embedder.embed_text(attachment_text, input_type="search_document")

    def _extract_name_from_email(self, email: str) -> str:
        """Extract person name from email address"""
        if not email:
            return ""

        # Try "Name <email>" format
        match = re.match(r'"?([^"<]+)"?\s*<', email)
        if match:
            return match.group(1).strip()

        # Try extracting from email local part
        local = email.split("@")[0] if "@" in email else email

        # Convert separators to spaces
        name = re.sub(r"[._-]", " ", local)

        # Title case
        name = name.title()

        return name if len(name) > 2 else ""

    def _format_temporal_description(self, dt: datetime) -> str:
        """Create natural language temporal description for embedding"""
        month_names = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        weekday_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]

        month_name = month_names[dt.month - 1]
        weekday_name = weekday_names[dt.weekday()]
        quarter = (dt.month - 1) // 3 + 1

        return (
            f"{weekday_name}, {month_name} {dt.day}, {dt.year}. "
            f"Q{quarter} {dt.year}. "
            f"{month_name} {dt.year}."
        )

    def generate_query_vectors(
        self,
        content_query: str | None = None,
        participant_query: str | None = None,
        temporal_query: str | None = None,
        attachment_query: str | None = None,
    ) -> MultiVectorEmbeddings:
        """
        Generate query vectors for multi-vector search.

        Only generates vectors for non-None queries.
        Uses input_type="search_query" for better retrieval.
        """
        result: MultiVectorEmbeddings = {}

        if content_query:
            result["content_vec"] = self._embedder.embed_query(content_query)

        if participant_query:
            result["participant_vec"] = self._embedder.embed_query(participant_query)

        if temporal_query:
            # Parse temporal query and generate appropriate vector
            # For now, just embed the text
            result["temporal_vec"] = self._embedder.embed_query(temporal_query)

        if attachment_query:
            result["attachment_vec"] = self._embedder.embed_query(attachment_query)

        return result


# =============================================================================
# Entity Extraction
# =============================================================================


class EntityExtractor:
    """Extract named entities from text using spaCy"""

    # Construction/legal domain patterns
    MONEY_PATTERN = re.compile(
        r"(?:[$\u00a3\u20ac])\s*[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|m|bn|k))?|"
        r"[\d,]+(?:\.\d{2})?\s*(?:dollars|pounds|euros|USD|GBP|EUR)",
        re.IGNORECASE,
    )

    DATE_PATTERN = re.compile(
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|"
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b|"
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
        re.IGNORECASE,
    )

    def __init__(self):
        self._nlp = None

    @property
    def nlp(self) -> Any:
        if self._nlp is None:
            self._nlp = ModelRegistry.get_ner_model()
        return self._nlp

    def extract(self, text: str, use_spacy: bool = True) -> EntityExtraction:
        """Extract named entities from text"""
        if not text:
            return EntityExtraction()

        # Limit text length for performance
        text = text[:50000]

        extraction = EntityExtraction()

        # Regex-based extraction (always works)
        extraction.money = self.MONEY_PATTERN.findall(text)
        extraction.dates = self.DATE_PATTERN.findall(text)

        # spaCy NER (if available)
        if use_spacy and self.nlp:
            try:
                doc = self.nlp(text)

                for ent in doc.ents:
                    if ent.label_ == "PERSON":
                        if ent.text not in extraction.persons:
                            extraction.persons.append(ent.text)
                    elif ent.label_ == "ORG":
                        if ent.text not in extraction.organizations:
                            extraction.organizations.append(ent.text)
                    elif ent.label_ == "GPE" or ent.label_ == "LOC":
                        if ent.text not in extraction.locations:
                            extraction.locations.append(ent.text)
                    elif ent.label_ == "DATE" and ent.text not in extraction.dates:
                        extraction.dates.append(ent.text)
                    elif ent.label_ == "MONEY" and ent.text not in extraction.money:
                        extraction.money.append(ent.text)
            except Exception as e:
                logger.warning(f"spaCy NER failed: {e}")

        return extraction


# =============================================================================
# OpenSearch Vector Index
# =============================================================================


class VectorIndexService:
    """Manage OpenSearch k-NN vector index"""

    # Use versioned index name to handle dimension changes
    # When switching from 384 to 1024 dimensions, existing data must be re-indexed
    VECTOR_INDEX_V2 = "vericase_vectors_v2"  # 1024 dimensions (Bedrock)

    def __init__(self, opensearch_client: Any = None):
        self._client = opensearch_client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from opensearchpy import OpenSearch

                self._client = OpenSearch(
                    hosts=[
                        {
                            "host": getattr(settings, "OPENSEARCH_HOST", "localhost"),
                            "port": int(getattr(settings, "OPENSEARCH_PORT", 9200)),
                        }
                    ],
                    http_compress=True,
                    use_ssl=False,
                    verify_certs=False,
                    timeout=30,
                )
            except ImportError:
                logger.error("opensearch-py not installed")
                raise
        return self._client

    def get_index_name(self) -> str:
        """
        Get the appropriate index name based on embedding dimension.

        v1 (vericase_vectors): 384 dimensions (sentence-transformers)
        v2 (vericase_vectors_v2): 1024 dimensions (Bedrock Cohere)
        """
        if EMBEDDING_PROVIDER == "bedrock":
            return self.VECTOR_INDEX_V2
        return VECTOR_INDEX_NAME

    def ensure_index(self) -> bool:
        """Create the vector index if it doesn't exist"""
        index_name = self.get_index_name()

        try:
            if self.client.indices.exists(index=index_name):
                logger.info(
                    f"Vector index {index_name} already exists (dim={EMBEDDING_DIMENSION})"
                )
                return True

            # Create index with k-NN settings
            index_body = {
                "settings": {
                    "index": {
                        "knn": True,
                        "knn.algo_param.ef_search": 100,
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                    }
                },
                "mappings": {
                    "properties": {
                        # Vector field for k-NN search
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": EMBEDDING_DIMENSION,
                            "method": {
                                "name": KNN_ALGORITHM,
                                "space_type": "cosinesimil",
                                "engine": "nmslib",
                                "parameters": {
                                    "ef_construction": KNN_EF_CONSTRUCTION,
                                    "m": KNN_M,
                                },
                            },
                        },
                        # Chunk content
                        "text": {"type": "text", "analyzer": "english"},
                        "chunk_hash": {"type": "keyword"},
                        # Source identification
                        "source_type": {"type": "keyword"},
                        "source_id": {"type": "keyword"},
                        "parent_id": {"type": "keyword"},
                        # Metadata
                        "section_type": {"type": "keyword"},
                        "chunk_index": {"type": "integer"},
                        "total_chunks": {"type": "integer"},
                        # Embedding metadata
                        "embedding_model": {"type": "keyword"},
                        "embedding_provider": {"type": "keyword"},
                        # Entities (for filtering)
                        "entities_persons": {"type": "keyword"},
                        "entities_organizations": {"type": "keyword"},
                        "entities_dates": {"type": "keyword"},
                        "entities_money": {"type": "keyword"},
                        # Organizational
                        "case_id": {"type": "keyword"},
                        "project_id": {"type": "keyword"},
                        "indexed_at": {"type": "date"},
                    }
                },
            }

            self.client.indices.create(index_name, body=index_body)
            logger.info(
                f"Created vector index: {index_name} "
                f"(provider={EMBEDDING_PROVIDER}, dim={EMBEDDING_DIMENSION})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to create vector index: {e}")
            return False

    def index_chunk(
        self,
        chunk: SemanticChunk,
        entities: EntityExtraction | None = None,
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> str | None:
        """Index a single chunk with its embedding"""
        if not chunk.embedding:
            logger.warning("Chunk has no embedding, skipping")
            return None

        index_name = self.get_index_name()
        doc_id = f"{chunk.metadata.get('source_type', 'unknown')}_{chunk.metadata.get('source_id', 'unknown')}_{chunk.chunk_hash}"

        doc = {
            "embedding": chunk.embedding,
            "text": chunk.text,
            "chunk_hash": chunk.chunk_hash,
            "source_type": chunk.metadata.get("source_type"),
            "source_id": chunk.metadata.get("source_id"),
            "parent_id": chunk.metadata.get("parent_id"),
            "section_type": chunk.metadata.get("section_type"),
            "chunk_index": chunk.metadata.get("chunk_index"),
            "total_chunks": chunk.metadata.get("total_chunks"),
            "embedding_model": chunk.metadata.get("embedding_model", EMBEDDING_MODEL),
            "embedding_provider": EMBEDDING_PROVIDER,
            "case_id": case_id,
            "project_id": project_id,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

        if entities:
            doc["entities_persons"] = entities.persons[:20]  # Limit for performance
            doc["entities_organizations"] = entities.organizations[:20]
            doc["entities_dates"] = entities.dates[:20]
            doc["entities_money"] = entities.money[:20]

        try:
            self.client.index(
                index=index_name,
                body=doc,
                id=doc_id,
                refresh=False,  # Don't refresh on every insert
            )
            return doc_id
        except Exception as e:
            logger.error(f"Failed to index chunk: {e}")
            return None

    def index_chunks_bulk(
        self,
        chunks: list[SemanticChunk],
        entities_list: list[EntityExtraction | None] | None = None,
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Bulk index multiple chunks"""
        if not chunks:
            return 0

        from opensearchpy.helpers import bulk

        index_name = self.get_index_name()
        actions = []
        for i, chunk in enumerate(chunks):
            if not chunk.embedding:
                continue

            doc_id = f"{chunk.metadata.get('source_type', 'unknown')}_{chunk.metadata.get('source_id', 'unknown')}_{chunk.chunk_hash}"

            doc = {
                "_index": index_name,
                "_id": doc_id,
                "embedding": chunk.embedding,
                "text": chunk.text,
                "chunk_hash": chunk.chunk_hash,
                "source_type": chunk.metadata.get("source_type"),
                "source_id": chunk.metadata.get("source_id"),
                "parent_id": chunk.metadata.get("parent_id"),
                "section_type": chunk.metadata.get("section_type"),
                "chunk_index": chunk.metadata.get("chunk_index"),
                "total_chunks": chunk.metadata.get("total_chunks"),
                "embedding_model": chunk.metadata.get(
                    "embedding_model", EMBEDDING_MODEL
                ),
                "embedding_provider": EMBEDDING_PROVIDER,
                "case_id": case_id,
                "project_id": project_id,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

            if entities_list and i < len(entities_list) and entities_list[i]:
                entities = entities_list[i]
                doc["entities_persons"] = entities.persons[:20]
                doc["entities_organizations"] = entities.organizations[:20]
                doc["entities_dates"] = entities.dates[:20]
                doc["entities_money"] = entities.money[:20]

            actions.append(doc)

        if not actions:
            return 0

        try:
            success, errors = bulk(self.client, actions, refresh=False)
            if errors:
                logger.warning(f"Bulk indexing had {len(errors)} errors")
            return success
        except Exception as e:
            logger.error(f"Bulk indexing failed: {e}")
            return 0

    def search_similar(
        self,
        query_embedding: list[float],
        k: int = 20,
        case_id: str | None = None,
        project_id: str | None = None,
        source_types: list[str] | None = None,
        section_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fast k-NN search for similar chunks.

        This is the fast initial retrieval step before cross-encoder reranking.
        Returns top-k candidates in ~10-50ms even with millions of vectors.
        """
        index_name = self.get_index_name()

        # Build filter
        filter_clauses = []
        if case_id:
            filter_clauses.append({"term": {"case_id": case_id}})
        if project_id:
            filter_clauses.append({"term": {"project_id": project_id}})
        if source_types:
            filter_clauses.append({"terms": {"source_type": source_types}})
        if section_types:
            filter_clauses.append({"terms": {"section_type": section_types}})

        # Build k-NN query
        query: dict[str, Any] = {
            "size": k,
            "query": {"knn": {"embedding": {"vector": query_embedding, "k": k}}},
        }

        # Add filter if any
        if filter_clauses:
            query["query"] = {
                "bool": {"must": [query["query"]], "filter": filter_clauses}
            }

        try:
            response = self.client.search(index=index_name, body=query)

            results = []
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                results.append(
                    {
                        "id": hit["_id"],
                        "score": hit["_score"],
                        "text": source.get("text"),
                        "content": source.get("text"),  # Alias for compatibility
                        "source_type": source.get("source_type"),
                        "source_id": source.get("source_id"),
                        "section_type": source.get("section_type"),
                        "chunk_index": source.get("chunk_index"),
                        "embedding_model": source.get("embedding_model"),
                        "entities_persons": source.get("entities_persons", []),
                        "entities_organizations": source.get(
                            "entities_organizations", []
                        ),
                    }
                )

            return results

        except Exception as e:
            logger.error(f"k-NN search failed: {e}")
            return []

    def refresh_index(self) -> None:
        """Force refresh the index (call after bulk operations)"""
        index_name = self.get_index_name()
        try:
            self.client.indices.refresh(index=index_name)
        except Exception as e:
            logger.warning(f"Index refresh failed: {e}")


# =============================================================================
# Multi-Vector Index Service
# =============================================================================


class MultiVectorIndexService:
    """
    Manage OpenSearch k-NN index with 4 vector fields for multi-faceted search.

    Index schema (vericase_vectors_v3):
    - content_vec: 1024 dims - semantic content embedding
    - participant_vec: 1024 dims - people/orgs involved
    - temporal_vec: 1024 dims - time encoding
    - attachment_vec: 1024 dims - attachment context
    """

    def __init__(self, opensearch_client: Any = None):
        self._client = opensearch_client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from opensearchpy import OpenSearch

                self._client = OpenSearch(
                    hosts=[
                        {
                            "host": getattr(settings, "OPENSEARCH_HOST", "localhost"),
                            "port": int(getattr(settings, "OPENSEARCH_PORT", 9200)),
                        }
                    ],
                    http_compress=True,
                    use_ssl=False,
                    verify_certs=False,
                    timeout=30,
                )
            except ImportError:
                logger.error("opensearch-py not installed")
                raise
        return self._client

    def ensure_index(self) -> bool:
        """Create the multi-vector index if it doesn't exist"""
        try:
            if self.client.indices.exists(index=MULTI_VECTOR_INDEX_NAME):
                logger.info(
                    f"Multi-vector index {MULTI_VECTOR_INDEX_NAME} already exists"
                )
                return True

            # k-NN vector field template
            def knn_vector_field(dim: int) -> dict[str, Any]:
                return {
                    "type": "knn_vector",
                    "dimension": dim,
                    "method": {
                        "name": KNN_ALGORITHM,
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {
                            "ef_construction": KNN_EF_CONSTRUCTION,
                            "m": KNN_M,
                        },
                    },
                }

            # Create index with 4 vector fields
            index_body = {
                "settings": {
                    "index": {
                        "knn": True,
                        "knn.algo_param.ef_search": 100,
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                    }
                },
                "mappings": {
                    "properties": {
                        # 4 Vector fields for multi-faceted search
                        "content_vec": knn_vector_field(EMBEDDING_DIMENSION),
                        "participant_vec": knn_vector_field(EMBEDDING_DIMENSION),
                        "temporal_vec": knn_vector_field(EMBEDDING_DIMENSION),
                        "attachment_vec": knn_vector_field(EMBEDDING_DIMENSION),
                        # Text content
                        "text": {"type": "text", "analyzer": "english"},
                        "subject": {"type": "text", "analyzer": "english"},
                        # Source identification
                        "source_type": {"type": "keyword"},
                        "source_id": {"type": "keyword"},
                        "email_id": {"type": "keyword"},
                        "thread_id": {"type": "keyword"},
                        # Participants (for filtering)
                        "sender": {"type": "keyword"},
                        "sender_name": {"type": "text"},
                        "recipients": {"type": "keyword"},
                        "mentioned_people": {"type": "keyword"},
                        "mentioned_orgs": {"type": "keyword"},
                        # Temporal (for filtering)
                        "sent_date": {"type": "date"},
                        "year": {"type": "integer"},
                        "month": {"type": "integer"},
                        "quarter": {"type": "integer"},
                        # Attachments (for filtering)
                        "attachment_count": {"type": "integer"},
                        "attachment_types": {"type": "keyword"},
                        "attachment_names": {"type": "text"},
                        "has_attachments": {"type": "boolean"},
                        # Organizational
                        "case_id": {"type": "keyword"},
                        "project_id": {"type": "keyword"},
                        # Metadata
                        "embedding_model": {"type": "keyword"},
                        "indexed_at": {"type": "date"},
                    }
                },
            }

            self.client.indices.create(MULTI_VECTOR_INDEX_NAME, body=index_body)
            logger.info(
                f"Created multi-vector index: {MULTI_VECTOR_INDEX_NAME} "
                f"(4 x {EMBEDDING_DIMENSION} dims)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to create multi-vector index: {e}")
            return False

    def index_email(
        self,
        email_id: str,
        vectors: MultiVectorEmbeddings,
        context: EmailContext,
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> str | None:
        """Index an email with its 4 vectors"""
        doc = {
            # Vectors
            "content_vec": vectors.get("content_vec", [0.0] * EMBEDDING_DIMENSION),
            "participant_vec": vectors.get(
                "participant_vec", [0.0] * EMBEDDING_DIMENSION
            ),
            "temporal_vec": vectors.get("temporal_vec", [0.0] * EMBEDDING_DIMENSION),
            "attachment_vec": vectors.get(
                "attachment_vec", [0.0] * EMBEDDING_DIMENSION
            ),
            # Content
            "text": context.get("body_text", ""),
            "subject": context.get("subject", ""),
            "source_type": "email",
            "source_id": email_id,
            "email_id": email_id,
            # Participants
            "sender": context.get("sender", ""),
            "sender_name": context.get("sender_name", ""),
            "recipients": (context.get("recipients_to", []) or [])
            + (context.get("recipients_cc", []) or []),
            "mentioned_people": context.get("mentioned_people", []),
            "mentioned_orgs": context.get("mentioned_orgs", []),
            # Temporal
            "sent_date": (
                context.get("sent_date").isoformat()
                if context.get("sent_date")
                else None
            ),
            "year": context.get("sent_date").year if context.get("sent_date") else None,
            "month": (
                context.get("sent_date").month if context.get("sent_date") else None
            ),
            "quarter": (
                ((context.get("sent_date").month - 1) // 3 + 1)
                if context.get("sent_date")
                else None
            ),
            # Attachments
            "attachment_count": len(context.get("attachment_names", [])),
            "attachment_types": context.get("attachment_types", []),
            "attachment_names": " ".join(context.get("attachment_names", [])),
            "has_attachments": len(context.get("attachment_names", [])) > 0,
            # Organizational
            "case_id": case_id,
            "project_id": project_id,
            # Metadata
            "embedding_model": EMBEDDING_MODEL,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self.client.index(
                index=MULTI_VECTOR_INDEX_NAME,
                body=doc,
                id=f"email_{email_id}",
                refresh=False,
            )
            return f"email_{email_id}"
        except Exception as e:
            logger.error(f"Failed to index email {email_id}: {e}")
            return None

    def search_multi_vector(
        self,
        query_vectors: MultiVectorEmbeddings,
        k: int = 20,
        weights: dict[str, float] | None = None,
        case_id: str | None = None,
        project_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Multi-vector search with weighted score fusion.

        Searches each vector field separately, then fuses scores using RRF
        (Reciprocal Rank Fusion) or weighted combination.

        Args:
            query_vectors: MultiVectorEmbeddings with vectors to search
            k: Number of results to return
            weights: Optional custom weights for each vector type
            case_id: Filter by case
            project_id: Filter by project
            filters: Additional filters (e.g., {"year": 2024, "has_attachments": True})

        Returns:
            List of results with fused scores
        """
        weights = weights or DEFAULT_FUSION_WEIGHTS

        # Build filter clause
        filter_clauses = []
        if case_id:
            filter_clauses.append({"term": {"case_id": case_id}})
        if project_id:
            filter_clauses.append({"term": {"project_id": project_id}})
        if filters:
            for field, value in filters.items():
                if isinstance(value, list):
                    filter_clauses.append({"terms": {field: value}})
                else:
                    filter_clauses.append({"term": {field: value}})

        # Collect results from each vector search
        all_results: dict[str, dict[str, Any]] = {}  # doc_id -> {scores, data}

        vector_fields = [
            ("content_vec", "content"),
            ("participant_vec", "participant"),
            ("temporal_vec", "temporal"),
            ("attachment_vec", "attachment"),
        ]

        for field_name, weight_key in vector_fields:
            vec = query_vectors.get(field_name)  # type: ignore
            if not vec or all(v == 0.0 for v in vec):
                continue

            weight = weights.get(weight_key, 0.0)
            if weight <= 0:
                continue

            # Build k-NN query for this vector
            query: dict[str, Any] = {
                "size": k * 2,  # Get more for fusion
                "query": {"knn": {field_name: {"vector": vec, "k": k * 2}}},
                "_source": [
                    "email_id",
                    "subject",
                    "text",
                    "sender",
                    "sent_date",
                    "recipients",
                    "attachment_types",
                    "has_attachments",
                    "case_id",
                    "project_id",
                ],
            }

            if filter_clauses:
                query["query"] = {
                    "bool": {"must": [query["query"]], "filter": filter_clauses}
                }

            try:
                response = self.client.search(index=MULTI_VECTOR_INDEX_NAME, body=query)

                for rank, hit in enumerate(response["hits"]["hits"]):
                    doc_id = hit["_id"]
                    score = hit["_score"] * weight

                    if doc_id not in all_results:
                        all_results[doc_id] = {
                            "scores": {},
                            "rrf_ranks": {},
                            "data": hit["_source"],
                        }

                    all_results[doc_id]["scores"][weight_key] = hit["_score"]
                    all_results[doc_id]["rrf_ranks"][weight_key] = rank + 1

            except Exception as e:
                logger.warning(f"k-NN search failed for {field_name}: {e}")

        if not all_results:
            return []

        # Fuse scores using RRF (Reciprocal Rank Fusion)
        # RRF score = sum(1 / (k + rank)) across all queries
        RRF_K = 60  # Standard RRF constant

        final_results = []
        for doc_id, result in all_results.items():
            # Calculate weighted RRF score
            rrf_score = 0.0
            for weight_key, rank in result["rrf_ranks"].items():
                weight = weights.get(weight_key, 0.0)
                rrf_score += weight * (1.0 / (RRF_K + rank))

            # Also calculate weighted sum of raw scores
            weighted_score = sum(
                result["scores"].get(wk, 0.0) * weights.get(wk, 0.0)
                for wk in ["content", "participant", "temporal", "attachment"]
            )

            final_results.append(
                {
                    "id": doc_id,
                    "email_id": result["data"].get("email_id"),
                    "score": rrf_score,
                    "weighted_score": weighted_score,
                    "component_scores": result["scores"],
                    "subject": result["data"].get("subject"),
                    "text": result["data"].get("text", "")[:500],  # Truncate
                    "sender": result["data"].get("sender"),
                    "sent_date": result["data"].get("sent_date"),
                    "recipients": result["data"].get("recipients", []),
                    "has_attachments": result["data"].get("has_attachments"),
                    "attachment_types": result["data"].get("attachment_types", []),
                }
            )

        # Sort by RRF score
        final_results.sort(key=lambda x: x["score"], reverse=True)

        return final_results[:k]

    def refresh_index(self) -> None:
        """Force refresh the index"""
        try:
            self.client.indices.refresh(index=MULTI_VECTOR_INDEX_NAME)
        except Exception as e:
            logger.warning(f"Multi-vector index refresh failed: {e}")


# =============================================================================
# High-Level Semantic Ingestion Service
# =============================================================================


class SemanticIngestionService:
    """
    Orchestrates the full semantic ingestion pipeline.

    Call this during email/document ingestion to enable fast deep research.

    Supports two modes:
    - Single-vector (legacy): One embedding per chunk
    - Multi-vector (v3): 4 embeddings per email (content, participant, temporal, attachment)

    Multi-vector mode is enabled when MULTI_VECTOR_ENABLED=True (default).
    """

    def __init__(self, opensearch_client: Any = None):
        self.chunker = SemanticChunker()
        self.embedder = EmbeddingService()
        self.entity_extractor = EntityExtractor()
        self.vector_index = VectorIndexService(opensearch_client)

        # Multi-vector services (only initialized if enabled)
        self._multi_vector_embedder: MultiVectorEmbeddingService | None = None
        self._multi_vector_index: MultiVectorIndexService | None = None

        self._index_ready = False
        self._multi_index_ready = False

    @property
    def multi_vector_embedder(self) -> MultiVectorEmbeddingService:
        """Lazy-load multi-vector embedding service"""
        if self._multi_vector_embedder is None:
            self._multi_vector_embedder = MultiVectorEmbeddingService(self.embedder)
        return self._multi_vector_embedder

    @property
    def multi_vector_index(self) -> MultiVectorIndexService:
        """Lazy-load multi-vector index service"""
        if self._multi_vector_index is None:
            self._multi_vector_index = MultiVectorIndexService(
                self.vector_index._client
            )
        return self._multi_vector_index

    def ensure_ready(self) -> bool:
        """Ensure vector index is ready"""
        if not self._index_ready:
            self._index_ready = self.vector_index.ensure_index()
        return self._index_ready

    def ensure_multi_vector_ready(self) -> bool:
        """Ensure multi-vector index is ready"""
        if not self._multi_index_ready and MULTI_VECTOR_ENABLED:
            self._multi_index_ready = self.multi_vector_index.ensure_index()
        return self._multi_index_ready

    def process_email(
        self,
        email_id: str,
        subject: str | None,
        body_text: str | None,
        sender: str | None = None,
        recipients: list[str] | None = None,
        case_id: str | None = None,
        project_id: str | None = None,
        sent_date: datetime | None = None,
        attachment_names: list[str] | None = None,
        attachment_types: list[str] | None = None,
    ) -> int:
        """
        Process an email for semantic indexing.

        When MULTI_VECTOR_ENABLED=True, indexes both:
        - Chunk-based single-vector index (for document-level search)
        - Multi-vector index (for faceted email search)

        Returns number of chunks indexed.
        """
        if not self.ensure_ready():
            logger.warning("Vector index not ready, skipping semantic indexing")
            return 0

        # Combine subject and body
        full_text = ""
        if subject:
            full_text = f"Subject: {subject}\n\n"
        if body_text:
            full_text += body_text

        if not full_text.strip():
            return 0

        # Chunk the email
        chunks = self.chunker.chunk_text(
            text=full_text, source_type="email", source_id=email_id
        )

        if not chunks:
            return 0

        # Generate embeddings
        chunks = self.embedder.embed_chunks(chunks)

        # Extract entities from full text
        entities = self.entity_extractor.extract(full_text)

        # Add sender/recipients to entities
        if sender:
            entities.persons.insert(0, sender)
        if recipients:
            entities.persons.extend(recipients[:5])

        # Index chunks (single-vector)
        entities_list = [entities] * len(chunks)  # Same entities for all chunks
        indexed = self.vector_index.index_chunks_bulk(
            chunks, entities_list, case_id, project_id
        )

        # Multi-vector indexing (if enabled)
        if MULTI_VECTOR_ENABLED and self.ensure_multi_vector_ready():
            try:
                # Build email context for multi-vector embedding
                context: EmailContext = {
                    "subject": subject or "",
                    "body_text": body_text or "",
                    "sender": sender or "",
                    "recipients_to": recipients or [],
                    "recipients_cc": [],
                    "mentioned_people": entities.persons[:10],
                    "mentioned_orgs": entities.organizations[:10],
                    "sent_date": sent_date,
                    "attachment_names": attachment_names or [],
                    "attachment_types": attachment_types or [],
                }

                # Generate 4 vectors
                vectors = self.multi_vector_embedder.generate_multi_vectors(context)

                # Index in multi-vector index
                self.multi_vector_index.index_email(
                    email_id=email_id,
                    vectors=vectors,
                    context=context,
                    case_id=case_id,
                    project_id=project_id,
                )
                logger.debug(f"Multi-vector indexed email {email_id}")

            except Exception as e:
                logger.warning(f"Multi-vector indexing failed for {email_id}: {e}")

        logger.debug(f"Indexed {indexed} chunks for email {email_id}")
        return indexed

    def process_document(
        self,
        document_id: str,
        text: str,
        document_type: str = "document",
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """
        Process a document (attachment, evidence item) for semantic indexing.

        Returns number of chunks indexed.
        """
        if not self.ensure_ready():
            return 0

        if not text or not text.strip():
            return 0

        # Chunk the document
        chunks = self.chunker.chunk_text(
            text=text, source_type=document_type, source_id=document_id
        )

        if not chunks:
            return 0

        # Generate embeddings
        chunks = self.embedder.embed_chunks(chunks)

        # Extract entities
        entities = self.entity_extractor.extract(text)
        entities_list = [entities] * len(chunks)

        # Index
        indexed = self.vector_index.index_chunks_bulk(
            chunks, entities_list, case_id, project_id
        )

        logger.debug(f"Indexed {indexed} chunks for document {document_id}")
        return indexed

    def refresh(self) -> None:
        """Refresh the index after bulk operations"""
        self.vector_index.refresh_index()
        if MULTI_VECTOR_ENABLED and self._multi_index_ready:
            self.multi_vector_index.refresh_index()

    def search_multi_vector(
        self,
        content_query: str | None = None,
        participant_query: str | None = None,
        temporal_query: str | None = None,
        attachment_query: str | None = None,
        k: int = 20,
        weights: dict[str, float] | None = None,
        case_id: str | None = None,
        project_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search using multi-vector faceted search.

        Args:
            content_query: What the email is about (e.g., "payment delays")
            participant_query: Who's involved (e.g., "Keith Wood")
            temporal_query: When (e.g., "Q1 2024", "January 2024")
            attachment_query: What's attached (e.g., "invoices", "PDF documents")
            k: Number of results
            weights: Custom fusion weights
            case_id: Filter by case
            project_id: Filter by project
            filters: Additional filters

        Returns:
            List of results with fused scores
        """
        if not MULTI_VECTOR_ENABLED or not self.ensure_multi_vector_ready():
            logger.warning("Multi-vector search not available")
            return []

        # Generate query vectors
        query_vectors = self.multi_vector_embedder.generate_query_vectors(
            content_query=content_query,
            participant_query=participant_query,
            temporal_query=temporal_query,
            attachment_query=attachment_query,
        )

        if not any(query_vectors.values()):
            logger.warning("No valid query vectors generated")
            return []

        return self.multi_vector_index.search_multi_vector(
            query_vectors=query_vectors,
            k=k,
            weights=weights,
            case_id=case_id,
            project_id=project_id,
            filters=filters,
        )


# =============================================================================
# Convenience Functions
# =============================================================================

# Global instance for convenience
_semantic_service: SemanticIngestionService | None = None


def get_semantic_service() -> SemanticIngestionService:
    """Get or create the global semantic service instance"""
    global _semantic_service
    if _semantic_service is None:
        _semantic_service = SemanticIngestionService()
    return _semantic_service


def process_email_semantics(
    email_id: str,
    subject: str | None,
    body_text: str | None,
    case_id: str | None = None,
    project_id: str | None = None,
) -> int:
    """Convenience function to process an email"""
    return get_semantic_service().process_email(
        email_id, subject, body_text, case_id=case_id, project_id=project_id
    )


def process_document_semantics(
    document_id: str,
    text: str,
    document_type: str = "document",
    case_id: str | None = None,
    project_id: str | None = None,
) -> int:
    """Convenience function to process a document"""
    return get_semantic_service().process_document(
        document_id, text, document_type, case_id=case_id, project_id=project_id
    )


def search_emails_multi_vector(
    content_query: str | None = None,
    participant_query: str | None = None,
    temporal_query: str | None = None,
    attachment_query: str | None = None,
    k: int = 20,
    weights: dict[str, float] | None = None,
    case_id: str | None = None,
    project_id: str | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Convenience function for multi-vector email search.

    Example usage:
    ```python
    # Find emails about payment delays from Keith with invoices
    results = search_emails_multi_vector(
        content_query="payment delays construction project",
        participant_query="Keith Wood",
        attachment_query="invoice PDF",
        project_id="69f812ac-af5f-4d9f-9e14-281879025a5a"
    )
    ```
    """
    return get_semantic_service().search_multi_vector(
        content_query=content_query,
        participant_query=participant_query,
        temporal_query=temporal_query,
        attachment_query=attachment_query,
        k=k,
        weights=weights,
        case_id=case_id,
        project_id=project_id,
        filters=filters,
    )


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    # Data types
    "ChunkMetadata",
    "MultiVectorEmbeddings",
    "EmailContext",
    "SemanticChunk",
    "EntityExtraction",
    # Configuration
    "EMBEDDING_PROVIDER",
    "EMBEDDING_DIMENSION",
    "MULTI_VECTOR_ENABLED",
    "DEFAULT_FUSION_WEIGHTS",
    # Core classes
    "BedrockEmbeddingClient",
    "ModelRegistry",
    "SemanticChunker",
    "EmbeddingService",
    "MultiVectorEmbeddingService",
    "EntityExtractor",
    "VectorIndexService",
    "MultiVectorIndexService",
    "SemanticIngestionService",
    # Convenience functions
    "get_semantic_service",
    "process_email_semantics",
    "process_document_semantics",
    "search_emails_multi_vector",
]
