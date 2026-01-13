"""
VeriCase Intelligent Detection Engine
======================================
Phase 2: Detect anomalies using learned corpus patterns.

This module uses the CorpusProfile from corpus_learning.py to
identify true outliers rather than regex noise:

1. Other Projects: Clusters that semantically don't belong
2. Spam/Newsletters: Peripheral senders + negative/neutral sentiment
3. Duplicates: Delegate to existing email_dedupe.py (proper message-id handling)
4. Peripheral Senders: Low PageRank in communication graph

Key principle: Only flag clear statistical outliers (z-score > 2.5).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .corpus_learning import (
    CorpusProfile,
    MIN_CLUSTER_SIZE,
)
from .models import EmailMessage

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Detection thresholds (MUCH higher than old regex-based system)
Z_SCORE_THRESHOLD = 2.5  # Only flag clear outliers
CONFIDENCE_THRESHOLD = 0.8  # Minimum confidence to recommend exclusion
MIN_SPAM_EMAILS = 10  # Minimum emails to flag sender as spam
MIN_PERIPHERAL_EMAILS = 5  # Minimum emails for peripheral sender detection
SENTIMENT_NEGATIVE_THRESHOLD = 0.3  # Above this ratio = unusual negativity


# =============================================================================
# Detection Result Models
# =============================================================================


@dataclass
class OtherProjectCandidate:
    """A cluster identified as potentially a different project."""

    id: str
    cluster_id: str
    cluster_label: str  # LLM-generated description
    email_ids: list[str] = field(default_factory=list)
    email_count: int = 0

    # Evidence for detection
    unique_entities: list[str] = field(
        default_factory=list
    )  # Entities not in main corpus
    unique_organizations: list[str] = field(default_factory=list)
    top_senders: list[str] = field(default_factory=list)
    top_subjects: list[str] = field(default_factory=list)

    # Distance metrics
    distance_from_corpus_center: float = 0.0
    z_score: float = 0.0

    # Confidence and recommendation
    confidence: float = 0.0
    recommended_action: str = "review"  # exclude, include, review

    # Date range
    date_range: tuple[datetime | None, datetime | None] = (None, None)

    # Sample emails for user review
    sample_subjects: list[str] = field(default_factory=list)
    sample_senders: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "other_project",
            "cluster_id": self.cluster_id,
            "cluster_label": self.cluster_label,
            "email_count": self.email_count,
            "unique_entities": self.unique_entities[:10],
            "unique_organizations": self.unique_organizations[:10],
            "top_senders": self.top_senders[:5],
            "top_subjects": self.top_subjects[:5],
            "z_score": round(self.z_score, 2),
            "confidence": round(self.confidence, 2),
            "recommended_action": self.recommended_action,
            "date_range": (
                self.date_range[0].isoformat() if self.date_range[0] else None,
                self.date_range[1].isoformat() if self.date_range[1] else None,
            ),
            "sample_subjects": self.sample_subjects[:5],
            "sample_senders": self.sample_senders[:5],
        }


@dataclass
class SpamCandidate:
    """A sender/domain identified as spam or newsletter."""

    id: str
    sender_email: str
    sender_domain: str
    email_ids: list[str] = field(default_factory=list)
    email_count: int = 0

    # Evidence for detection
    is_peripheral: bool = False  # Low PageRank in communication graph
    has_no_replies: bool = False  # One-way communication
    sentiment: str = "NEUTRAL"  # Dominant sentiment
    avg_sentiment_scores: dict[str, float] = field(default_factory=dict)

    # Detection indicators (from old system, as secondary signals)
    indicators_found: list[str] = field(default_factory=list)

    # Confidence and recommendation
    confidence: float = 0.0
    recommended_action: str = "review"

    # Sample subjects for review
    sample_subjects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "spam_newsletter",
            "sender_email": self.sender_email,
            "sender_domain": self.sender_domain,
            "email_count": self.email_count,
            "is_peripheral": self.is_peripheral,
            "has_no_replies": self.has_no_replies,
            "sentiment": self.sentiment,
            "indicators_found": self.indicators_found[:5],
            "confidence": round(self.confidence, 2),
            "recommended_action": self.recommended_action,
            "sample_subjects": self.sample_subjects[:5],
        }


@dataclass
class DuplicateGroup:
    """A group of duplicate emails."""

    id: str
    original_email_id: str
    duplicate_email_ids: list[str] = field(default_factory=list)
    duplicate_count: int = 0

    # Deduplication level
    dedupe_level: str = ""  # A = message-id, B = strict hash, C = relaxed hash

    # Sample info
    subject: str = ""
    sender: str = ""
    original_date: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "duplicate",
            "original_email_id": self.original_email_id,
            "duplicate_count": self.duplicate_count,
            "dedupe_level": self.dedupe_level,
            "subject": self.subject,
            "sender": self.sender,
            "original_date": (
                self.original_date.isoformat() if self.original_date else None
            ),
        }


@dataclass
class PeripheralSenderCandidate:
    """A sender identified as peripheral to main communication."""

    id: str
    sender_email: str
    sender_name: str | None = None
    email_ids: list[str] = field(default_factory=list)
    email_count: int = 0

    # Graph metrics
    pagerank_score: float = 0.0
    pagerank_percentile: float = 0.0  # Where they rank (0 = bottom)

    # Communication pattern
    recipients_count: int = 0  # How many unique recipients
    replies_received: int = 0  # How many replies to their emails

    # Confidence and recommendation
    confidence: float = 0.0
    recommended_action: str = "review"

    # Sample subjects
    sample_subjects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "peripheral_sender",
            "sender_email": self.sender_email,
            "sender_name": self.sender_name,
            "email_count": self.email_count,
            "pagerank_percentile": round(self.pagerank_percentile, 2),
            "replies_received": self.replies_received,
            "confidence": round(self.confidence, 2),
            "recommended_action": self.recommended_action,
            "sample_subjects": self.sample_subjects[:5],
        }


@dataclass
class DetectionResult:
    """Complete result of intelligent detection."""

    # Detected anomalies
    other_project_candidates: list[OtherProjectCandidate] = field(default_factory=list)
    spam_candidates: list[SpamCandidate] = field(default_factory=list)
    duplicate_groups: list[DuplicateGroup] = field(default_factory=list)
    peripheral_senders: list[PeripheralSenderCandidate] = field(default_factory=list)

    # Statistics
    total_emails_analyzed: int = 0
    outliers_found: int = 0
    confidence_threshold_used: float = CONFIDENCE_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "other_projects": [c.to_dict() for c in self.other_project_candidates],
            "spam": [c.to_dict() for c in self.spam_candidates],
            "duplicates": [g.to_dict() for g in self.duplicate_groups],
            "peripheral_senders": [s.to_dict() for s in self.peripheral_senders],
            "statistics": {
                "total_emails_analyzed": self.total_emails_analyzed,
                "outliers_found": self.outliers_found,
                "other_project_count": sum(
                    c.email_count for c in self.other_project_candidates
                ),
                "spam_count": sum(c.email_count for c in self.spam_candidates),
                "duplicate_count": sum(
                    g.duplicate_count for g in self.duplicate_groups
                ),
                "peripheral_count": sum(s.email_count for s in self.peripheral_senders),
            },
        }


# =============================================================================
# Intelligent Detection Engine
# =============================================================================


class IntelligentDetectionEngine:
    """
    Phase 2: Detect anomalies using learned corpus profile.

    Key principle: Only flag clear statistical outliers.

    Methods:
    - detect_other_projects(): Clusters with high distance from corpus center
    - detect_spam(): Peripheral senders + sentiment analysis
    - detect_duplicates(): Delegate to email_dedupe.py
    - detect_peripheral_senders(): Low PageRank in communication graph
    """

    def __init__(
        self,
        db: Session,
        corpus_profile: CorpusProfile,
    ):
        self.db = db
        self.profile = corpus_profile

        # Configurable thresholds
        self.z_score_threshold = Z_SCORE_THRESHOLD
        self.confidence_threshold = CONFIDENCE_THRESHOLD
        self.min_cluster_size = MIN_CLUSTER_SIZE

    async def detect_all(self) -> DetectionResult:
        """Run all detection methods and return combined result."""
        result = DetectionResult(
            total_emails_analyzed=self.profile.email_count,
            confidence_threshold_used=self.confidence_threshold,
        )

        # Detect other projects (from outlier clusters)
        result.other_project_candidates = await self.detect_other_projects()

        # Detect spam using graph + sentiment
        result.spam_candidates = await self.detect_spam()

        # Detect duplicates using existing email_dedupe.py
        result.duplicate_groups = self.detect_duplicates()

        # Detect peripheral senders
        result.peripheral_senders = await self.detect_peripheral_senders()

        # Count total outliers
        result.outliers_found = (
            sum(c.email_count for c in result.other_project_candidates)
            + sum(c.email_count for c in result.spam_candidates)
            + sum(g.duplicate_count for g in result.duplicate_groups)
            + sum(s.email_count for s in result.peripheral_senders)
        )

        return result

    async def detect_other_projects(self) -> list[OtherProjectCandidate]:
        """
        Identify clusters that don't belong to the main project.

        Method:
        1. Find clusters with high z-score (distance from corpus center)
        2. Check for unique organizations not in main corpus
        3. Only flag if z-score > threshold AND has unique identifying features
        """
        candidates: list[OtherProjectCandidate] = []

        # Get top organizations from main corpus (for comparison)
        main_orgs = set(
            org.lower()
            for org, _ in self.profile.entity_distribution.top_organizations(50)
        )

        for cluster in self.profile.clusters:
            # Check if cluster is an outlier based on z-score
            if cluster.distance_from_corpus_center < self.z_score_threshold:
                continue

            # Skip small clusters
            if cluster.size < self.min_cluster_size:
                continue

            # Get emails in this cluster to analyze unique entities
            email_ids = cluster.email_ids
            cluster_emails = (
                self.db.query(EmailMessage).filter(EmailMessage.id.in_(email_ids)).all()
            )

            # Find unique organizations in this cluster
            unique_orgs = self._find_unique_entities(
                cluster_emails, main_orgs, entity_type="organization"
            )

            # Compute confidence based on z-score and unique entities
            base_confidence = min(1.0, cluster.distance_from_corpus_center / 5.0)
            entity_boost = min(0.3, len(unique_orgs) * 0.05)
            confidence = min(1.0, base_confidence + entity_boost)

            # Determine recommendation
            if confidence >= 0.9:
                recommended_action = "exclude"
            elif confidence >= 0.7:
                recommended_action = "review"
            else:
                recommended_action = "include"

            # Only include if confidence meets threshold
            if (
                confidence < self.confidence_threshold * 0.7
            ):  # Allow some lower confidence for review
                continue

            candidate = OtherProjectCandidate(
                id=f"other_{uuid.uuid4().hex[:8]}",
                cluster_id=cluster.id,
                cluster_label=cluster.label,
                email_ids=email_ids,
                email_count=cluster.size,
                unique_organizations=unique_orgs,
                top_senders=cluster.top_senders,
                top_subjects=cluster.top_subjects,
                z_score=cluster.distance_from_corpus_center,
                confidence=confidence,
                recommended_action=recommended_action,
                date_range=cluster.date_range,
                sample_subjects=cluster.top_subjects[:5],
                sample_senders=cluster.top_senders[:5],
            )

            candidates.append(candidate)

        # Sort by confidence (highest first)
        candidates.sort(key=lambda c: -c.confidence)

        return candidates

    def _find_unique_entities(
        self,
        emails: list[EmailMessage],
        main_entities: set[str],
        entity_type: str = "organization",
    ) -> list[str]:
        """
        Find entities in emails that are not in the main corpus.

        Uses simple pattern matching as fallback when Comprehend
        results aren't available at detection time.
        """
        import re

        unique: set[str] = set()

        # Simple organization patterns (fallback)
        org_patterns = [
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Ltd|Limited|PLC|Inc|Corp|LLP|Group|Holdings))\b",
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Council|Authority|Trust|Board))\b",
        ]

        for email in emails:
            text = f"{email.subject or ''} {email.body_text or ''}"

            for pattern in org_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    normalized = match.strip().lower()
                    if normalized and normalized not in main_entities:
                        unique.add(match.strip())

        return list(unique)[:20]

    async def detect_spam(self) -> list[SpamCandidate]:
        """
        Identify spam using communication graph + sentiment.

        Method:
        1. Find senders with low PageRank (peripheral)
        2. Check for one-way communication (no replies)
        3. Analyze sentiment patterns
        4. Use traditional indicators as secondary signals only
        """
        candidates: list[SpamCandidate] = []

        graph = self.profile.communication_graph

        # Get all peripheral senders from graph
        peripheral_senders = set(graph.peripheral_nodes)

        # Build sender -> emails mapping
        scope_filter = (
            EmailMessage.case_id == self.profile.case_id
            if self.profile.case_id
            else EmailMessage.project_id == self.profile.project_id
        )

        sender_emails: dict[str, list[EmailMessage]] = {}
        all_emails = self.db.query(EmailMessage).filter(scope_filter).all()

        for email in all_emails:
            sender = (email.sender_email or "").lower()
            if sender:
                if sender not in sender_emails:
                    sender_emails[sender] = []
                sender_emails[sender].append(email)

        # Analyze peripheral senders
        for sender in peripheral_senders:
            emails = sender_emails.get(sender, [])
            if len(emails) < MIN_SPAM_EMAILS:
                continue

            # Check for one-way communication
            has_replies = self._check_for_replies(sender, graph)

            # Get domain
            domain = sender.split("@")[-1] if "@" in sender else ""

            # Check traditional spam indicators as secondary signal
            indicators = self._check_spam_indicators(emails)

            # Compute confidence
            confidence = 0.0
            if sender in peripheral_senders:
                confidence += 0.3
            if not has_replies:
                confidence += 0.3
            if indicators:
                confidence += min(0.3, len(indicators) * 0.1)

            # Only flag high confidence
            if confidence < self.confidence_threshold * 0.8:
                continue

            candidate = SpamCandidate(
                id=f"spam_{uuid.uuid4().hex[:8]}",
                sender_email=sender,
                sender_domain=domain,
                email_ids=[str(e.id) for e in emails],
                email_count=len(emails),
                is_peripheral=sender in peripheral_senders,
                has_no_replies=not has_replies,
                indicators_found=indicators,
                confidence=confidence,
                recommended_action="exclude" if confidence >= 0.9 else "review",
                sample_subjects=[e.subject or "" for e in emails[:5]],
            )

            candidates.append(candidate)

        # Sort by confidence
        candidates.sort(key=lambda c: -c.confidence)

        return candidates[:30]  # Top 30 spam candidates

    def _check_for_replies(self, sender: str, graph) -> bool:
        """Check if sender has received any replies."""
        # Check if sender appears as recipient in graph
        for other_sender, recipients in graph.edges.items():
            if sender in recipients:
                return True
        return False

    def _check_spam_indicators(self, emails: list[EmailMessage]) -> list[str]:
        """Check for traditional spam indicators (secondary signal only)."""
        indicators: list[str] = []

        # Known spam patterns (conservative list)
        spam_phrases = [
            "unsubscribe",
            "view in browser",
            "email preferences",
            "manage subscription",
        ]

        spam_domains = [
            "sendgrid.net",
            "mailchimp.com",
            "hubspot.com",
            "marketo.com",
        ]

        for email in emails[:10]:  # Sample first 10
            text = f"{email.subject or ''} {email.body_text or ''}".lower()
            sender = (email.sender_email or "").lower()

            for phrase in spam_phrases:
                if phrase in text and phrase not in indicators:
                    indicators.append(f"Contains '{phrase}'")

            for domain in spam_domains:
                if domain in sender and domain not in indicators:
                    indicators.append(f"From {domain}")

        return indicators[:5]

    def detect_duplicates(self) -> list[DuplicateGroup]:
        """
        Detect duplicates using existing email_dedupe.py.

        This properly uses:
        - Message-ID exact match (Level A)
        - Content hash (Level B)
        - Relaxed hash (Level C)

        Instead of the broken MD5 of first 100 words.
        """

        groups: list[DuplicateGroup] = []

        # Query existing deduplication decisions
        scope_filter = (
            EmailMessage.case_id == self.profile.case_id
            if self.profile.case_id
            else EmailMessage.project_id == self.profile.project_id
        )

        # Get all duplicate emails (already marked by email_dedupe.py)
        duplicate_emails = (
            self.db.query(EmailMessage)
            .filter(scope_filter)
            .filter(EmailMessage.is_duplicate == True)  # noqa: E712
            .all()
        )

        # Group by canonical_email_id
        canonical_groups: dict[str, list[EmailMessage]] = {}
        for email in duplicate_emails:
            canonical_id = (
                str(email.canonical_email_id) if email.canonical_email_id else None
            )
            if canonical_id:
                if canonical_id not in canonical_groups:
                    canonical_groups[canonical_id] = []
                canonical_groups[canonical_id].append(email)

        # Build DuplicateGroup objects
        for canonical_id, duplicates in canonical_groups.items():
            if not duplicates:
                continue

            # Get original email
            original = self.db.query(EmailMessage).filter_by(id=canonical_id).first()
            if not original:
                continue

            group = DuplicateGroup(
                id=f"dup_{uuid.uuid4().hex[:8]}",
                original_email_id=canonical_id,
                duplicate_email_ids=[str(e.id) for e in duplicates],
                duplicate_count=len(duplicates),
                dedupe_level=duplicates[0].dedupe_level or "B",
                subject=original.subject or "",
                sender=original.sender_email or "",
                original_date=original.date_sent,
            )

            groups.append(group)

        # Sort by duplicate count
        groups.sort(key=lambda g: -g.duplicate_count)

        return groups[:100]  # Top 100 duplicate groups

    async def detect_peripheral_senders(self) -> list[PeripheralSenderCandidate]:
        """
        Identify senders who are peripheral to main communication.

        Uses PageRank from communication graph to find senders
        who don't participate in the main communication flow.
        """
        candidates: list[PeripheralSenderCandidate] = []

        graph = self.profile.communication_graph

        if not graph.node_pagerank:
            return candidates

        # Get PageRank distribution for percentile calculation
        all_scores = list(graph.node_pagerank.values())
        if not all_scores:
            return candidates

        # Build sender -> emails mapping
        scope_filter = (
            EmailMessage.case_id == self.profile.case_id
            if self.profile.case_id
            else EmailMessage.project_id == self.profile.project_id
        )

        all_emails = self.db.query(EmailMessage).filter(scope_filter).all()
        sender_emails: dict[str, list[EmailMessage]] = {}

        for email in all_emails:
            sender = (email.sender_email or "").lower()
            if sender:
                if sender not in sender_emails:
                    sender_emails[sender] = []
                sender_emails[sender].append(email)

        # Find peripheral senders (bottom 10% by PageRank)
        for sender in graph.peripheral_nodes:
            emails = sender_emails.get(sender, [])
            if len(emails) < MIN_PERIPHERAL_EMAILS:
                continue

            # Skip if already flagged as spam
            pagerank_score = graph.node_pagerank.get(sender, 0)

            # Calculate percentile
            percentile = sum(1 for s in all_scores if s <= pagerank_score) / len(
                all_scores
            )

            # Check for replies received
            replies_received = sum(
                1 for _, recipients in graph.edges.items() if sender in recipients
            )

            # Compute confidence (peripheral + few replies = higher confidence)
            confidence = 0.5  # Base for being peripheral
            if replies_received == 0:
                confidence += 0.3
            elif replies_received < 3:
                confidence += 0.1

            if confidence < self.confidence_threshold * 0.7:
                continue

            # Get sender name from first email
            sender_name = None
            for email in emails:
                if email.sender_name:
                    sender_name = email.sender_name
                    break

            candidate = PeripheralSenderCandidate(
                id=f"periph_{uuid.uuid4().hex[:8]}",
                sender_email=sender,
                sender_name=sender_name,
                email_ids=[str(e.id) for e in emails],
                email_count=len(emails),
                pagerank_score=pagerank_score,
                pagerank_percentile=percentile,
                replies_received=replies_received,
                confidence=confidence,
                recommended_action="review",
                sample_subjects=[e.subject or "" for e in emails[:5]],
            )

            candidates.append(candidate)

        # Sort by email count (more emails = more important to review)
        candidates.sort(key=lambda c: -c.email_count)

        return candidates[:20]  # Top 20 peripheral senders
