"""
VeriCase Corpus Learning Engine
================================
Phase 1: Learn from the email corpus BEFORE making any suggestions.

This module implements a data-first approach to email refinement:
1. Extract entities using AWS Comprehend (people, orgs, locations, dates)
2. Generate embeddings using Bedrock Cohere for semantic clustering
3. Build communication graph from sender/recipient patterns
4. Compute statistical baselines for outlier detection

The CorpusProfile captures "what's normal" for THIS specific dataset,
enabling intelligent detection of true anomalies rather than regex noise.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
from sqlalchemy.orm import Session

from .models import EmailMessage

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Comprehend batch limits
COMPREHEND_BATCH_SIZE = 25  # Max 25 documents per batch_detect_* call
COMPREHEND_MAX_BYTES = 5000  # Max 5KB UTF-8 per document

# Clustering configuration
MIN_CLUSTER_SIZE = 10  # Minimum emails to form a meaningful cluster
MAX_CLUSTERS = 30  # Maximum clusters to identify
CLUSTER_OUTLIER_THRESHOLD = 2.5  # Z-score for outlier detection

# Communication graph
MIN_EMAILS_FOR_GRAPH_NODE = 3  # Minimum emails to include sender in graph
PAGERANK_DAMPING = 0.85  # Standard PageRank damping factor
PERIPHERAL_PERCENTILE = 10  # Bottom 10% by PageRank are peripheral

# Embedding batch size
EMBEDDING_BATCH_SIZE = 96  # Cohere supports up to 96 texts per batch


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class EntityDistribution:
    """Distribution of entities extracted from corpus."""

    persons: dict[str, int] = field(default_factory=dict)  # name -> count
    organizations: dict[str, int] = field(default_factory=dict)
    locations: dict[str, int] = field(default_factory=dict)
    dates: dict[str, int] = field(default_factory=dict)
    key_phrases: dict[str, int] = field(default_factory=dict)

    def top_persons(self, n: int = 50) -> list[tuple[str, int]]:
        return sorted(self.persons.items(), key=lambda x: -x[1])[:n]

    def top_organizations(self, n: int = 50) -> list[tuple[str, int]]:
        return sorted(self.organizations.items(), key=lambda x: -x[1])[:n]

    def top_locations(self, n: int = 50) -> list[tuple[str, int]]:
        return sorted(self.locations.items(), key=lambda x: -x[1])[:n]

    def to_dict(self) -> dict[str, Any]:
        return {
            "persons": self.top_persons(100),
            "organizations": self.top_organizations(100),
            "locations": self.top_locations(100),
            "dates": list(self.dates.items())[:100],
            "key_phrases": sorted(self.key_phrases.items(), key=lambda x: -x[1])[:100],
        }


@dataclass
class EmailCluster:
    """A semantic cluster of related emails."""

    id: str
    label: str  # LLM-generated label describing cluster content
    email_ids: list[str] = field(default_factory=list)
    size: int = 0

    # Centroid vector (1024 dims for Cohere)
    centroid: list[float] = field(default_factory=list)

    # Cluster characteristics
    top_entities: list[str] = field(default_factory=list)
    top_senders: list[str] = field(default_factory=list)
    top_subjects: list[str] = field(default_factory=list)
    date_range: tuple[datetime | None, datetime | None] = (None, None)
    sentiment_distribution: dict[str, float] = field(default_factory=dict)

    # Distance metrics for outlier detection
    distance_from_corpus_center: float = 0.0
    intra_cluster_variance: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "email_count": self.size,
            "top_entities": self.top_entities[:10],
            "top_senders": self.top_senders[:10],
            "top_subjects": self.top_subjects[:5],
            "date_range": (
                self.date_range[0].isoformat() if self.date_range[0] else None,
                self.date_range[1].isoformat() if self.date_range[1] else None,
            ),
            "sentiment_distribution": self.sentiment_distribution,
            "distance_from_center": self.distance_from_corpus_center,
            "is_outlier": self.distance_from_corpus_center > CLUSTER_OUTLIER_THRESHOLD,
        }


@dataclass
class CommunicationGraph:
    """Graph representing email communication patterns."""

    # Adjacency: sender_email -> recipient_email -> count
    edges: dict[str, dict[str, int]] = field(default_factory=dict)

    # Node statistics
    node_email_counts: dict[str, int] = field(
        default_factory=dict
    )  # email -> total sent
    node_pagerank: dict[str, float] = field(
        default_factory=dict
    )  # email -> PageRank score

    # Computed categories
    central_nodes: list[str] = field(default_factory=list)  # Top by PageRank
    peripheral_nodes: list[str] = field(default_factory=list)  # Bottom by PageRank

    def add_edge(self, sender: str, recipient: str) -> None:
        """Add an email edge to the graph."""
        sender_lower = sender.lower().strip()
        recipient_lower = recipient.lower().strip()

        if not sender_lower or not recipient_lower:
            return

        if sender_lower not in self.edges:
            self.edges[sender_lower] = {}
        self.edges[sender_lower][recipient_lower] = (
            self.edges[sender_lower].get(recipient_lower, 0) + 1
        )

        self.node_email_counts[sender_lower] = (
            self.node_email_counts.get(sender_lower, 0) + 1
        )

    def compute_pagerank(
        self, damping: float = PAGERANK_DAMPING, iterations: int = 100
    ) -> None:
        """Compute PageRank scores for all nodes."""
        # Get all unique nodes
        all_nodes: set[str] = set(self.edges.keys())
        for recipients in self.edges.values():
            all_nodes.update(recipients.keys())

        if not all_nodes:
            return

        n = len(all_nodes)
        node_list = list(all_nodes)
        node_index = {node: i for i, node in enumerate(node_list)}

        # Initialize PageRank
        pr = np.ones(n) / n

        # Build transition matrix
        for _ in range(iterations):
            new_pr = np.ones(n) * (1 - damping) / n

            for sender, recipients in self.edges.items():
                sender_idx = node_index.get(sender)
                if sender_idx is None:
                    continue

                total_out = sum(recipients.values())
                if total_out == 0:
                    continue

                for recipient, count in recipients.items():
                    recipient_idx = node_index.get(recipient)
                    if recipient_idx is not None:
                        new_pr[recipient_idx] += (
                            damping * pr[sender_idx] * count / total_out
                        )

            pr = new_pr

        # Store PageRank scores
        self.node_pagerank = {node_list[i]: float(pr[i]) for i in range(n)}

        # Identify central and peripheral nodes
        sorted_nodes = sorted(self.node_pagerank.items(), key=lambda x: -x[1])
        total_nodes = len(sorted_nodes)

        # Top 20% are central
        central_cutoff = max(1, int(total_nodes * 0.2))
        self.central_nodes = [node for node, _ in sorted_nodes[:central_cutoff]]

        # Bottom 10% are peripheral
        peripheral_cutoff = max(1, int(total_nodes * PERIPHERAL_PERCENTILE / 100))
        self.peripheral_nodes = [node for node, _ in sorted_nodes[-peripheral_cutoff:]]

    def is_peripheral(self, email: str) -> bool:
        """Check if an email address is peripheral in the communication graph."""
        return email.lower().strip() in self.peripheral_nodes

    def is_central(self, email: str) -> bool:
        """Check if an email address is central in the communication graph."""
        return email.lower().strip() in self.central_nodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_nodes": len(self.node_pagerank),
            "total_edges": sum(len(r) for r in self.edges.values()),
            "central_nodes": self.central_nodes[:20],
            "peripheral_nodes": self.peripheral_nodes[:20],
            "top_senders": sorted(self.node_email_counts.items(), key=lambda x: -x[1])[
                :20
            ],
        }


@dataclass
class SentimentBaseline:
    """Baseline sentiment distribution for the corpus."""

    positive_ratio: float = 0.0
    negative_ratio: float = 0.0
    neutral_ratio: float = 0.0
    mixed_ratio: float = 0.0
    total_analyzed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "positive": self.positive_ratio,
            "negative": self.negative_ratio,
            "neutral": self.neutral_ratio,
            "mixed": self.mixed_ratio,
            "total_analyzed": self.total_analyzed,
        }


@dataclass
class CorpusProfile:
    """
    Complete learned profile of an email corpus.

    This captures "what's normal" for the dataset, enabling
    intelligent outlier detection rather than static regex rules.
    """

    id: str
    project_id: str | None = None
    case_id: str | None = None
    scope_type: str = "project"

    # Corpus statistics
    email_count: int = 0
    date_range: tuple[datetime | None, datetime | None] = (None, None)
    learned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Entity distributions (from Comprehend)
    entity_distribution: EntityDistribution = field(default_factory=EntityDistribution)

    # Semantic clusters (from Bedrock embeddings + k-means)
    clusters: list[EmailCluster] = field(default_factory=list)
    corpus_centroid: list[float] = field(default_factory=list)  # Mean of all embeddings

    # Communication graph
    communication_graph: CommunicationGraph = field(default_factory=CommunicationGraph)

    # Domain distribution
    domain_counts: dict[str, int] = field(default_factory=dict)
    core_domains: list[str] = field(default_factory=list)  # Top 80% of traffic

    # Sentiment baseline
    sentiment_baseline: SentimentBaseline = field(default_factory=SentimentBaseline)

    # Statistics for outlier detection
    avg_emails_per_sender: float = 0.0
    std_emails_per_sender: float = 0.0

    # Content hash for invalidation
    content_hash: str = ""

    def compute_content_hash(self, email_ids: list[str]) -> str:
        """Compute hash of email IDs for cache invalidation."""
        sorted_ids = sorted(email_ids)
        content = "|".join(sorted_ids)
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def is_outlier_cluster(self, cluster: EmailCluster) -> bool:
        """Check if a cluster is an outlier based on distance from center."""
        return cluster.distance_from_corpus_center > CLUSTER_OUTLIER_THRESHOLD

    def get_outlier_clusters(self) -> list[EmailCluster]:
        """Get all clusters identified as outliers."""
        return [c for c in self.clusters if self.is_outlier_cluster(c)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "case_id": self.case_id,
            "email_count": self.email_count,
            "date_range": (
                self.date_range[0].isoformat() if self.date_range[0] else None,
                self.date_range[1].isoformat() if self.date_range[1] else None,
            ),
            "learned_at": self.learned_at.isoformat(),
            "entity_distribution": self.entity_distribution.to_dict(),
            "clusters": [c.to_dict() for c in self.clusters],
            "communication_graph": self.communication_graph.to_dict(),
            "domain_counts": dict(
                sorted(self.domain_counts.items(), key=lambda x: -x[1])[:30]
            ),
            "core_domains": self.core_domains[:20],
            "sentiment_baseline": self.sentiment_baseline.to_dict(),
            "statistics": {
                "avg_emails_per_sender": self.avg_emails_per_sender,
                "std_emails_per_sender": self.std_emails_per_sender,
            },
        }


# =============================================================================
# Corpus Learning Engine
# =============================================================================


class CorpusLearningEngine:
    """
    Phase 1: Learn from the email corpus before making suggestions.

    This engine:
    1. Extracts entities using AWS Comprehend (batch mode for efficiency)
    2. Generates embeddings using Bedrock Cohere for semantic clustering
    3. Builds communication graph from sender/recipient patterns
    4. Computes statistical baselines for outlier detection
    """

    def __init__(self, db: Session):
        self.db = db
        self._comprehend_client: Any = None
        self._embedding_client: Any = None

    @property
    def comprehend(self) -> Any:
        """Lazy-load Comprehend client."""
        if self._comprehend_client is None:
            import boto3
            from .config import settings

            region = getattr(settings, "AWS_REGION", "us-east-1")
            self._comprehend_client = boto3.client("comprehend", region_name=region)
            logger.info(f"Initialized Comprehend client in {region}")
        return self._comprehend_client

    @property
    def embedding_client(self) -> Any:
        """Lazy-load Bedrock embedding client."""
        if self._embedding_client is None:
            from .semantic_engine import BedrockEmbeddingClient

            self._embedding_client = BedrockEmbeddingClient()
            logger.info("Initialized Bedrock embedding client")
        return self._embedding_client

    async def learn_corpus(
        self,
        project_id: str | None = None,
        case_id: str | None = None,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> CorpusProfile:
        """
        Full corpus learning pipeline.

        Steps:
        1. Load all emails from project/case
        2. Extract entities using Comprehend (batch)
        3. Generate embeddings using Bedrock
        4. Cluster emails semantically (k-means)
        5. Build communication graph
        6. Compute statistical baselines

        Args:
            project_id: Project to analyze (mutually exclusive with case_id)
            case_id: Case to analyze (mutually exclusive with project_id)
            progress_callback: Optional callback for progress updates (phase, progress 0-1)

        Returns:
            CorpusProfile with learned patterns
        """
        # Initialize profile
        profile = CorpusProfile(
            id=str(uuid.uuid4()),
            project_id=project_id,
            case_id=case_id,
            scope_type="case" if case_id else "project",
        )

        def report_progress(phase: str, progress: float) -> None:
            if progress_callback:
                progress_callback(phase, progress)
            logger.info(f"Corpus learning: {phase} ({progress * 100:.1f}%)")

        report_progress("loading_emails", 0.0)

        # Step 1: Load all emails
        emails = await self._load_emails(project_id, case_id)
        profile.email_count = len(emails)

        if not emails:
            logger.warning("No emails found for corpus learning")
            return profile

        # Compute content hash for cache invalidation
        email_ids = [str(e.id) for e in emails]
        profile.content_hash = profile.compute_content_hash(email_ids)

        # Compute date range
        dates = [e.date_sent for e in emails if e.date_sent]
        if dates:
            profile.date_range = (min(dates), max(dates))

        report_progress("loading_emails", 1.0)

        # Step 2: Extract entities using Comprehend
        report_progress("extracting_entities", 0.0)
        profile.entity_distribution = await self._extract_entities_batch(
            emails,
            progress_callback=lambda p: report_progress("extracting_entities", p),
        )

        # Step 3: Analyze sentiment
        report_progress("analyzing_sentiment", 0.0)
        profile.sentiment_baseline = await self._analyze_sentiment_batch(
            emails,
            progress_callback=lambda p: report_progress("analyzing_sentiment", p),
        )

        # Step 4: Generate embeddings and cluster
        report_progress("clustering_emails", 0.0)
        profile.clusters, profile.corpus_centroid = await self._cluster_emails(
            emails,
            progress_callback=lambda p: report_progress("clustering_emails", p),
        )

        # Step 5: Build communication graph
        report_progress("building_graph", 0.0)
        profile.communication_graph = self._build_communication_graph(emails)
        profile.communication_graph.compute_pagerank()
        report_progress("building_graph", 1.0)

        # Step 6: Compute domain distribution
        report_progress("analyzing_domains", 0.0)
        profile.domain_counts, profile.core_domains = self._analyze_domains(emails)
        report_progress("analyzing_domains", 1.0)

        # Step 7: Compute sender statistics
        report_progress("computing_statistics", 0.0)
        (
            profile.avg_emails_per_sender,
            profile.std_emails_per_sender,
        ) = self._compute_sender_statistics(emails)
        report_progress("computing_statistics", 1.0)

        report_progress("complete", 1.0)
        logger.info(
            f"Corpus learning complete: {profile.email_count} emails, "
            f"{len(profile.clusters)} clusters, "
            f"{len(profile.communication_graph.node_pagerank)} graph nodes"
        )

        return profile

    async def _load_emails(
        self,
        project_id: str | None,
        case_id: str | None,
    ) -> list[EmailMessage]:
        """Load all relevant emails from the database."""
        from .correspondence.utils import build_correspondence_hard_exclusion_filter
        from .visibility import build_email_visibility_filter
        from sqlalchemy import and_

        query = self.db.query(EmailMessage)

        if case_id:
            query = query.filter(EmailMessage.case_id == case_id)
        elif project_id:
            query = query.filter(EmailMessage.project_id == project_id)
        else:
            raise ValueError("Either project_id or case_id must be provided")

        # Apply visibility filters (exclude already-hidden spam, duplicates, etc.)
        query = query.filter(
            and_(
                build_correspondence_hard_exclusion_filter(),
                build_email_visibility_filter(EmailMessage),
            )
        )

        return query.all()

    async def _extract_entities_batch(
        self,
        emails: list[EmailMessage],
        progress_callback: Callable[[float], None] | None = None,
    ) -> EntityDistribution:
        """
        Extract entities using Comprehend batch_detect_entities.

        Uses batch processing (25 docs per call) for efficiency.
        Extracts: PERSON, ORGANIZATION, LOCATION, DATE + key phrases.
        """
        distribution = EntityDistribution()

        # Prepare texts for batch processing
        texts: list[tuple[int, str]] = []
        for i, email in enumerate(emails):
            text = f"{email.subject or ''}\n{email.body_text or ''}"
            # Truncate for Comprehend limit
            truncated = text[:COMPREHEND_MAX_BYTES].strip()
            if truncated:
                texts.append((i, truncated))

        if not texts:
            return distribution

        total_batches = (
            len(texts) + COMPREHEND_BATCH_SIZE - 1
        ) // COMPREHEND_BATCH_SIZE
        processed_batches = 0

        # Process in batches
        for batch_start in range(0, len(texts), COMPREHEND_BATCH_SIZE):
            batch = texts[batch_start : batch_start + COMPREHEND_BATCH_SIZE]
            batch_texts = [t for _, t in batch]

            try:
                # Batch entity detection
                entities_response = await asyncio.to_thread(
                    self.comprehend.batch_detect_entities,
                    TextList=batch_texts,
                    LanguageCode="en",
                )

                # Batch key phrase detection
                phrases_response = await asyncio.to_thread(
                    self.comprehend.batch_detect_key_phrases,
                    TextList=batch_texts,
                    LanguageCode="en",
                )

                # Process entity results
                for result in entities_response.get("ResultList", []):
                    for entity in result.get("Entities", []):
                        entity_type = entity.get("Type", "")
                        text = entity.get("Text", "").strip()

                        if not text or len(text) < 2:
                            continue

                        # Normalize entity text
                        normalized = text.title() if entity_type == "PERSON" else text

                        if entity_type == "PERSON":
                            distribution.persons[normalized] = (
                                distribution.persons.get(normalized, 0) + 1
                            )
                        elif entity_type == "ORGANIZATION":
                            distribution.organizations[normalized] = (
                                distribution.organizations.get(normalized, 0) + 1
                            )
                        elif entity_type == "LOCATION":
                            distribution.locations[normalized] = (
                                distribution.locations.get(normalized, 0) + 1
                            )
                        elif entity_type == "DATE":
                            distribution.dates[normalized] = (
                                distribution.dates.get(normalized, 0) + 1
                            )

                # Process key phrase results
                for result in phrases_response.get("ResultList", []):
                    for phrase in result.get("KeyPhrases", []):
                        text = phrase.get("Text", "").strip().lower()
                        score = phrase.get("Score", 0)

                        if text and len(text) > 3 and score > 0.7:
                            distribution.key_phrases[text] = (
                                distribution.key_phrases.get(text, 0) + 1
                            )

            except Exception as e:
                logger.warning(f"Comprehend batch failed: {e}")

            processed_batches += 1
            if progress_callback:
                progress_callback(processed_batches / total_batches)

        return distribution

    async def _analyze_sentiment_batch(
        self,
        emails: list[EmailMessage],
        progress_callback: Callable[[float], None] | None = None,
        sample_size: int = 500,
    ) -> SentimentBaseline:
        """
        Analyze sentiment using Comprehend batch_detect_sentiment.

        Uses sampling for large corpora to balance speed vs accuracy.
        """
        baseline = SentimentBaseline()

        # Sample emails if corpus is large
        if len(emails) > sample_size:
            import random

            sampled_emails = random.sample(emails, sample_size)
        else:
            sampled_emails = emails

        # Prepare texts
        texts: list[str] = []
        for email in sampled_emails:
            text = f"{email.subject or ''}\n{(email.body_text or '')[:2000]}"
            truncated = text[:COMPREHEND_MAX_BYTES].strip()
            if truncated:
                texts.append(truncated)

        if not texts:
            return baseline

        sentiment_counts: dict[str, int] = defaultdict(int)
        total_batches = (
            len(texts) + COMPREHEND_BATCH_SIZE - 1
        ) // COMPREHEND_BATCH_SIZE
        processed_batches = 0

        for batch_start in range(0, len(texts), COMPREHEND_BATCH_SIZE):
            batch_texts = texts[batch_start : batch_start + COMPREHEND_BATCH_SIZE]

            try:
                response = await asyncio.to_thread(
                    self.comprehend.batch_detect_sentiment,
                    TextList=batch_texts,
                    LanguageCode="en",
                )

                for result in response.get("ResultList", []):
                    sentiment = result.get("Sentiment", "NEUTRAL")
                    sentiment_counts[sentiment] += 1

            except Exception as e:
                logger.warning(f"Comprehend sentiment batch failed: {e}")

            processed_batches += 1
            if progress_callback:
                progress_callback(processed_batches / total_batches)

        # Compute ratios
        total = sum(sentiment_counts.values())
        if total > 0:
            baseline.positive_ratio = sentiment_counts.get("POSITIVE", 0) / total
            baseline.negative_ratio = sentiment_counts.get("NEGATIVE", 0) / total
            baseline.neutral_ratio = sentiment_counts.get("NEUTRAL", 0) / total
            baseline.mixed_ratio = sentiment_counts.get("MIXED", 0) / total
            baseline.total_analyzed = total

        return baseline

    async def _cluster_emails(
        self,
        emails: list[EmailMessage],
        progress_callback: Callable[[float], None] | None = None,
    ) -> tuple[list[EmailCluster], list[float]]:
        """
        Cluster emails using Bedrock embeddings + k-means.

        1. Generate embeddings for all emails
        2. Apply k-means clustering
        3. Label clusters using LLM
        4. Compute distance metrics
        """
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score

        if len(emails) < MIN_CLUSTER_SIZE:
            return [], []

        # Step 1: Generate embeddings
        if progress_callback:
            progress_callback(0.1)

        texts = [f"{e.subject or ''}\n{(e.body_text or '')[:1500]}" for e in emails]

        try:
            embeddings = self.embedding_client.embed_texts(
                texts,
                input_type="search_document",
                batch_size=EMBEDDING_BATCH_SIZE,
            )
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return [], []

        if progress_callback:
            progress_callback(0.5)

        # Convert to numpy
        embedding_matrix = np.array(embeddings)

        # Compute corpus centroid
        corpus_centroid = np.mean(embedding_matrix, axis=0).tolist()

        # Step 2: Determine optimal k using elbow method
        max_k = min(MAX_CLUSTERS, len(emails) // MIN_CLUSTER_SIZE)
        if max_k < 2:
            return [], corpus_centroid

        # Try different k values
        best_k = 5  # Default
        best_score = -1

        for k in range(2, min(max_k + 1, 15)):
            try:
                kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = kmeans.fit_predict(embedding_matrix)
                score = silhouette_score(embedding_matrix, labels)

                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception:
                pass

        if progress_callback:
            progress_callback(0.7)

        # Step 3: Final clustering with best k
        kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embedding_matrix)

        # Step 4: Build cluster objects
        clusters: list[EmailCluster] = []
        corpus_centroid_np = np.array(corpus_centroid)

        for cluster_idx in range(best_k):
            # Get emails in this cluster
            cluster_mask = labels == cluster_idx
            cluster_emails = [e for e, m in zip(emails, cluster_mask) if m]
            cluster_embeddings = embedding_matrix[cluster_mask]

            if len(cluster_emails) < MIN_CLUSTER_SIZE:
                continue

            # Compute cluster centroid
            centroid = np.mean(cluster_embeddings, axis=0)

            # Compute distance from corpus center
            distance_from_center = float(np.linalg.norm(centroid - corpus_centroid_np))

            # Compute z-score (how many std devs from center)
            all_distances = np.linalg.norm(
                embedding_matrix - corpus_centroid_np, axis=1
            )
            mean_dist = np.mean(all_distances)
            std_dist = np.std(all_distances)
            z_score = (
                (distance_from_center - mean_dist) / std_dist if std_dist > 0 else 0
            )

            # Compute intra-cluster variance
            intra_variance = float(
                np.mean(np.linalg.norm(cluster_embeddings - centroid, axis=1))
            )

            # Collect cluster metadata
            cluster_senders = defaultdict(int)
            cluster_subjects: list[str] = []
            cluster_dates: list[datetime] = []

            for email in cluster_emails:
                if email.sender_email:
                    cluster_senders[email.sender_email.lower()] += 1
                if email.subject:
                    cluster_subjects.append(email.subject)
                if email.date_sent:
                    cluster_dates.append(email.date_sent)

            # Create cluster object
            cluster = EmailCluster(
                id=f"cluster_{cluster_idx}",
                label=f"Cluster {cluster_idx + 1}",  # Will be labeled by LLM later
                email_ids=[str(e.id) for e in cluster_emails],
                size=len(cluster_emails),
                centroid=centroid.tolist(),
                top_senders=sorted(
                    cluster_senders.keys(),
                    key=lambda x: -cluster_senders[x],
                )[:10],
                top_subjects=cluster_subjects[:10],
                date_range=(
                    min(cluster_dates) if cluster_dates else None,
                    max(cluster_dates) if cluster_dates else None,
                ),
                distance_from_corpus_center=z_score,  # Use z-score, not raw distance
                intra_cluster_variance=intra_variance,
            )

            clusters.append(cluster)

        if progress_callback:
            progress_callback(0.9)

        # Step 5: Label clusters using LLM (async)
        await self._label_clusters(clusters)

        if progress_callback:
            progress_callback(1.0)

        # Sort clusters by size (largest first)
        clusters.sort(key=lambda c: -c.size)

        return clusters, corpus_centroid

    async def _label_clusters(self, clusters: list[EmailCluster]) -> None:
        """Generate human-readable labels for clusters using LLM."""
        from .ai_runtime import complete_chat
        from .ai_settings import get_ai_api_key, get_ai_model, is_bedrock_enabled

        try:
            # Use Bedrock if available
            if is_bedrock_enabled(self.db):
                provider = "bedrock"
                model = get_ai_model("bedrock", self.db)
                api_key = None
            else:
                provider = "anthropic"
                model = get_ai_model("anthropic", self.db)
                api_key = get_ai_api_key("anthropic", self.db)

            for cluster in clusters:
                # Build prompt with cluster samples
                subjects_sample = "\n".join(f"- {s}" for s in cluster.top_subjects[:5])
                senders_sample = ", ".join(cluster.top_senders[:5])

                prompt = f"""Analyze this cluster of {cluster.size} emails and provide a short label (3-5 words) describing what they're about.

Sample subjects:
{subjects_sample}

Top senders: {senders_sample}

Respond with ONLY the label, nothing else. Example labels:
- "Thames Water Infrastructure Project"
- "Internal HR Communications"
- "Marketing Newsletters"
- "Legal Contract Discussions"
"""

                try:
                    label = await complete_chat(
                        provider=provider,
                        model_id=model,
                        prompt=prompt,
                        api_key=api_key,
                        max_tokens=50,
                        temperature=0.3,
                    )
                    cluster.label = label.strip().strip('"')
                except Exception as e:
                    logger.warning(f"Failed to label cluster {cluster.id}: {e}")

        except Exception as e:
            logger.warning(f"Cluster labeling failed: {e}")

    def _build_communication_graph(
        self,
        emails: list[EmailMessage],
    ) -> CommunicationGraph:
        """Build directed communication graph from emails."""
        graph = CommunicationGraph()

        for email in emails:
            sender = email.sender_email
            if not sender:
                continue

            # Add edges to TO recipients
            for recipient in email.recipients_to or []:
                if recipient:
                    graph.add_edge(sender, recipient)

            # Add edges to CC recipients (lower weight implicit)
            for recipient in email.recipients_cc or []:
                if recipient:
                    graph.add_edge(sender, recipient)

        return graph

    def _analyze_domains(
        self,
        emails: list[EmailMessage],
    ) -> tuple[dict[str, int], list[str]]:
        """Analyze domain distribution and identify core domains."""
        domain_counts: dict[str, int] = defaultdict(int)

        for email in emails:
            sender = email.sender_email
            if sender and "@" in sender:
                domain = sender.lower().split("@")[-1]
                domain_counts[domain] += 1

        # Sort by count
        sorted_domains = sorted(domain_counts.items(), key=lambda x: -x[1])

        # Core domains = top 80% of email traffic
        total_emails = sum(domain_counts.values())
        cumulative = 0
        core_domains: list[str] = []

        for domain, count in sorted_domains:
            cumulative += count
            core_domains.append(domain)
            if cumulative >= total_emails * 0.8:
                break

        return dict(domain_counts), core_domains

    def _compute_sender_statistics(
        self,
        emails: list[EmailMessage],
    ) -> tuple[float, float]:
        """Compute statistical baseline for sender activity."""
        sender_counts: dict[str, int] = defaultdict(int)

        for email in emails:
            sender = email.sender_email
            if sender:
                sender_counts[sender.lower()] += 1

        if not sender_counts:
            return 0.0, 0.0

        counts = list(sender_counts.values())
        avg = sum(counts) / len(counts)
        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        std = math.sqrt(variance)

        return avg, std
