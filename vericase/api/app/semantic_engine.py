"""
VeriCase Semantic Engine
=========================
Ingestion-time semantic processing for deep research acceleration.

Implements:
- Semantic chunking (paragraph/section-aware splitting)
- Dense embedding generation (sentence-transformers)
- OpenSearch k-NN vector indexing
- Named entity extraction (spaCy)
- Pre-computed document summaries

Architecture based on Egnyte Deep Research Agent patterns:
https://www.egnyte.com/blog/post/inside-the-architecture-of-a-deep-research-agent
"""

from __future__ import annotations

import hashlib
import logging
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
KNN_ALGORITHM = "hnsw"  # Hierarchical Navigable Small World - fast ANN
KNN_EF_CONSTRUCTION = 256  # Higher = better quality, slower indexing
KNN_M = 16  # Number of bi-directional links - good balance


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

    def __init__(self, region: str = BEDROCK_REGION, model_id: str = BEDROCK_EMBEDDING_MODEL):
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
                return response_body.get("embedding", response_body.get("embeddings", [[]])[0])

        except Exception as e:
            logger.error(f"Bedrock embedding failed: {e}")
            raise

    def embed_texts(
        self, texts: list[str], input_type: str = "search_document", batch_size: int = 96
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
            logger.info(f"Initializing Bedrock embedding client: {BEDROCK_EMBEDDING_MODEL}")
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

                logger.info(f"Loading sentence-transformer model: {SENTENCE_TRANSFORMER_MODEL}")
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
                logger.warning(f"Bedrock embedding failed, falling back to sentence-transformers: {e}")
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
        self, texts: list[str], batch_size: int = 32, input_type: str = "search_document"
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
        result: list[list[float]] = [[0.0] * SENTENCE_TRANSFORMER_DIMENSION] * len(texts)
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
                logger.info(f"Vector index {index_name} already exists (dim={EMBEDDING_DIMENSION})")
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
                "embedding_model": chunk.metadata.get("embedding_model", EMBEDDING_MODEL),
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
# High-Level Semantic Ingestion Service
# =============================================================================


class SemanticIngestionService:
    """
    Orchestrates the full semantic ingestion pipeline.

    Call this during email/document ingestion to enable fast deep research.
    """

    def __init__(self, opensearch_client: Any = None):
        self.chunker = SemanticChunker()
        self.embedder = EmbeddingService()
        self.entity_extractor = EntityExtractor()
        self.vector_index = VectorIndexService(opensearch_client)
        self._index_ready = False

    def ensure_ready(self) -> bool:
        """Ensure vector index is ready"""
        if not self._index_ready:
            self._index_ready = self.vector_index.ensure_index()
        return self._index_ready

    def process_email(
        self,
        email_id: str,
        subject: str | None,
        body_text: str | None,
        sender: str | None = None,
        recipients: list[str] | None = None,
        case_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """
        Process an email for semantic indexing.

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

        # Index chunks
        entities_list = [entities] * len(chunks)  # Same entities for all chunks
        indexed = self.vector_index.index_chunks_bulk(
            chunks, entities_list, case_id, project_id
        )

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
