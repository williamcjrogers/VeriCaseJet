"""
VeriCase Smart Suggestions Engine
==================================
Phase 3: Generate context-rich suggestions with LLM explanations.

This module generates human-readable explanations for why items
were flagged, providing clear reasoning rather than just raw data.

Features:
1. LLM-generated explanations for each detection
2. Rich context showing evidence and reasoning
3. Confidence-based recommendations
4. Cluster visualizations for UI
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .corpus_learning import CorpusProfile
from .intelligent_detection import (
    OtherProjectCandidate,
    SpamCandidate,
    DetectionResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Smart Suggestions Engine
# =============================================================================


class SmartSuggestionEngine:
    """
    Generate intelligent suggestions with rich context.

    Uses LLM to explain WHY something is an outlier, not just THAT it is.
    """

    def __init__(self, db: Session, corpus_profile: CorpusProfile):
        self.db = db
        self.profile = corpus_profile

    async def enhance_detection_result(
        self,
        detection: DetectionResult,
    ) -> DetectionResult:
        """
        Enhance detection results with LLM-generated explanations.

        Adds human-readable reasoning to each candidate.
        """
        # Generate explanations for other project candidates
        for candidate in detection.other_project_candidates:
            explanation = await self.generate_other_project_explanation(candidate)
            candidate.cluster_label = explanation.get("label", candidate.cluster_label)
            # Store full explanation in a new attribute (extend dataclass if needed)

        # Generate explanations for spam candidates
        for candidate in detection.spam_candidates:
            explanation = await self.generate_spam_explanation(candidate)
            # Update candidate with explanation

        return detection

    async def generate_other_project_explanation(
        self,
        candidate: OtherProjectCandidate,
    ) -> dict[str, Any]:
        """
        Generate explanation for why a cluster is flagged as another project.

        Returns dict with:
        - label: Short descriptive label
        - explanation: 2-3 sentence explanation
        - evidence: Bullet points of evidence
        - recommendation: What to do
        """
        from .ai_runtime import complete_chat
        from .ai_settings import get_ai_api_key, get_ai_model, is_bedrock_enabled

        # Get project context
        project_name = "Unknown Project"
        if self.profile.project_id:
            from .models import Project

            project = (
                self.db.query(Project).filter_by(id=self.profile.project_id).first()
            )
            if project:
                project_name = project.project_name or "Unknown"

        # Build context for LLM
        prompt = f"""Analyze this email cluster and explain why it appears to be a different project.

MAIN PROJECT: {project_name}

DETECTED CLUSTER:
- Label: {candidate.cluster_label}
- Email count: {candidate.email_count}
- Top senders: {', '.join(candidate.top_senders[:5])}
- Sample subjects: {'; '.join(candidate.sample_subjects[:5])}
- Unique organizations found: {', '.join(candidate.unique_organizations[:5])}
- Distance from main corpus (z-score): {candidate.z_score:.2f}

Provide a concise response with:
1. LABEL: A 3-5 word label describing this cluster (e.g., "Thames Water Infrastructure Project")
2. EXPLANATION: 2-3 sentences explaining why this appears to be a different project
3. EVIDENCE: 3 bullet points of key evidence
4. CONFIDENCE: Your confidence this is a separate project (high/medium/low)
5. RECOMMENDATION: exclude, review, or keep

Format as:
LABEL: [your label]
EXPLANATION: [your explanation]
EVIDENCE:
- [point 1]
- [point 2]
- [point 3]
CONFIDENCE: [high/medium/low]
RECOMMENDATION: [exclude/review/keep]
"""

        try:
            if is_bedrock_enabled(self.db):
                provider = "bedrock"
                model = get_ai_model("bedrock", self.db)
                api_key = None
            else:
                provider = "anthropic"
                model = get_ai_model("anthropic", self.db)
                api_key = get_ai_api_key("anthropic", self.db)

            response = await complete_chat(
                provider=provider,
                model_id=model,
                prompt=prompt,
                api_key=api_key,
                max_tokens=500,
                temperature=0.3,
            )

            # Parse response
            result = self._parse_explanation_response(response)
            return result

        except Exception as e:
            logger.warning(f"Failed to generate explanation: {e}")
            return {
                "label": candidate.cluster_label,
                "explanation": f"Cluster of {candidate.email_count} emails that appears distinct from main project.",
                "evidence": [
                    f"Z-score of {candidate.z_score:.2f} indicates statistical outlier",
                    f"Contains {len(candidate.unique_organizations)} unique organizations",
                    f"Top sender: {candidate.top_senders[0] if candidate.top_senders else 'Unknown'}",
                ],
                "confidence": "medium" if candidate.confidence >= 0.7 else "low",
                "recommendation": candidate.recommended_action,
            }

    async def generate_spam_explanation(
        self,
        candidate: SpamCandidate,
    ) -> dict[str, Any]:
        """Generate explanation for why a sender is flagged as spam."""
        evidence: list[str] = []

        if candidate.is_peripheral:
            evidence.append(
                "Sender is peripheral in communication graph (low PageRank)"
            )

        if candidate.has_no_replies:
            evidence.append(
                "One-way communication: no replies received from recipients"
            )

        if candidate.indicators_found:
            evidence.append(
                f"Traditional spam indicators: {', '.join(candidate.indicators_found[:3])}"
            )

        confidence = "high" if candidate.confidence >= 0.9 else "medium"

        return {
            "label": f"Potential spam from {candidate.sender_domain}",
            "explanation": (
                f"This sender ({candidate.sender_email}) appears to be sending "
                f"bulk or automated emails. They have sent {candidate.email_count} emails "
                f"but are not part of the main communication flow."
            ),
            "evidence": evidence,
            "confidence": confidence,
            "recommendation": candidate.recommended_action,
        }

    def _parse_explanation_response(self, response: str) -> dict[str, Any]:
        """Parse LLM response into structured format."""
        result: dict[str, Any] = {
            "label": "",
            "explanation": "",
            "evidence": [],
            "confidence": "medium",
            "recommendation": "review",
        }

        lines = response.strip().split("\n")
        current_section = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("LABEL:"):
                result["label"] = line.replace("LABEL:", "").strip()
            elif line.startswith("EXPLANATION:"):
                result["explanation"] = line.replace("EXPLANATION:", "").strip()
                current_section = "explanation"
            elif line.startswith("EVIDENCE:"):
                current_section = "evidence"
            elif line.startswith("CONFIDENCE:"):
                conf = line.replace("CONFIDENCE:", "").strip().lower()
                result["confidence"] = (
                    conf if conf in ["high", "medium", "low"] else "medium"
                )
            elif line.startswith("RECOMMENDATION:"):
                rec = line.replace("RECOMMENDATION:", "").strip().lower()
                result["recommendation"] = (
                    rec if rec in ["exclude", "review", "keep"] else "review"
                )
            elif line.startswith("- ") and current_section == "evidence":
                result["evidence"].append(line[2:])
            elif current_section == "explanation" and not line.startswith(
                ("EVIDENCE", "CONFIDENCE", "RECOMMENDATION")
            ):
                result["explanation"] += " " + line

        return result

    def generate_summary(self, detection: DetectionResult) -> dict[str, Any]:
        """
        Generate a high-level summary of detection results.

        For display in the UI as an overview before details.
        """
        summary = {
            "total_emails_analyzed": detection.total_emails_analyzed,
            "outliers_found": detection.outliers_found,
            "outlier_percentage": (
                round(
                    detection.outliers_found / detection.total_emails_analyzed * 100, 1
                )
                if detection.total_emails_analyzed > 0
                else 0
            ),
            "categories": [],
        }

        # Other projects summary
        if detection.other_project_candidates:
            total_emails = sum(
                c.email_count for c in detection.other_project_candidates
            )
            summary["categories"].append(
                {
                    "type": "other_projects",
                    "label": "Other Projects",
                    "description": f"Found {len(detection.other_project_candidates)} cluster(s) that appear to be different projects",
                    "email_count": total_emails,
                    "candidates_count": len(detection.other_project_candidates),
                    "confidence": self._avg_confidence(
                        detection.other_project_candidates
                    ),
                }
            )

        # Spam summary
        if detection.spam_candidates:
            total_emails = sum(c.email_count for c in detection.spam_candidates)
            summary["categories"].append(
                {
                    "type": "spam",
                    "label": "Spam & Newsletters",
                    "description": f"Found {len(detection.spam_candidates)} sender(s) sending bulk/automated content",
                    "email_count": total_emails,
                    "candidates_count": len(detection.spam_candidates),
                    "confidence": self._avg_confidence(detection.spam_candidates),
                }
            )

        # Duplicates summary
        if detection.duplicate_groups:
            total_duplicates = sum(
                g.duplicate_count for g in detection.duplicate_groups
            )
            summary["categories"].append(
                {
                    "type": "duplicates",
                    "label": "Duplicates",
                    "description": f"Found {total_duplicates} duplicate emails in {len(detection.duplicate_groups)} groups",
                    "email_count": total_duplicates,
                    "candidates_count": len(detection.duplicate_groups),
                    "confidence": "high",  # Duplicates are deterministic
                }
            )

        # Peripheral senders summary
        if detection.peripheral_senders:
            total_emails = sum(s.email_count for s in detection.peripheral_senders)
            summary["categories"].append(
                {
                    "type": "peripheral_senders",
                    "label": "Peripheral Senders",
                    "description": f"Found {len(detection.peripheral_senders)} sender(s) outside main communication",
                    "email_count": total_emails,
                    "candidates_count": len(detection.peripheral_senders),
                    "confidence": self._avg_confidence(detection.peripheral_senders),
                }
            )

        return summary

    def _avg_confidence(self, candidates: list) -> str:
        """Calculate average confidence level from candidates."""
        if not candidates:
            return "low"

        avg = sum(getattr(c, "confidence", 0.5) for c in candidates) / len(candidates)

        if avg >= 0.85:
            return "high"
        elif avg >= 0.65:
            return "medium"
        else:
            return "low"

    def generate_cluster_visualization_data(self) -> dict[str, Any]:
        """
        Generate data for cluster visualization in UI.

        Returns 2D projection of clusters for scatter plot visualization.
        """
        from sklearn.manifold import TSNE
        import numpy as np

        clusters = self.profile.clusters
        if not clusters or len(clusters) < 2:
            return {"clusters": [], "projection": "none"}

        # Get cluster centroids
        centroids = [c.centroid for c in clusters if c.centroid]
        if len(centroids) < 2:
            return {"clusters": [], "projection": "none"}

        # Apply t-SNE for 2D projection
        try:
            centroid_matrix = np.array(centroids)

            # t-SNE requires n_samples > perplexity
            perplexity = min(30, len(centroids) - 1)
            if perplexity < 2:
                perplexity = 2

            tsne = TSNE(
                n_components=2,
                perplexity=perplexity,
                random_state=42,
                n_iter=500,
            )
            projection = tsne.fit_transform(centroid_matrix)

            # Build visualization data
            viz_clusters = []
            for i, cluster in enumerate(clusters):
                if i < len(projection):
                    is_outlier = cluster.distance_from_corpus_center > 2.5
                    viz_clusters.append(
                        {
                            "id": cluster.id,
                            "label": cluster.label,
                            "size": cluster.size,
                            "x": float(projection[i][0]),
                            "y": float(projection[i][1]),
                            "is_outlier": is_outlier,
                            "z_score": cluster.distance_from_corpus_center,
                        }
                    )

            return {
                "clusters": viz_clusters,
                "projection": "t-SNE",
                "total_clusters": len(clusters),
                "outlier_count": sum(1 for c in viz_clusters if c["is_outlier"]),
            }

        except Exception as e:
            logger.warning(f"Failed to generate cluster visualization: {e}")
            return {"clusters": [], "projection": "failed", "error": str(e)}

    def generate_communication_graph_data(self) -> dict[str, Any]:
        """
        Generate data for communication graph visualization.

        Returns nodes and edges for network graph display.
        """
        graph = self.profile.communication_graph

        if not graph.node_pagerank:
            return {"nodes": [], "edges": []}

        # Get top nodes by PageRank for visualization (limit to prevent clutter)
        top_nodes = sorted(
            graph.node_pagerank.items(),
            key=lambda x: -x[1],
        )[:50]

        top_node_set = set(n for n, _ in top_nodes)

        # Build nodes
        nodes = []
        for email, score in top_nodes:
            is_central = email in graph.central_nodes
            is_peripheral = email in graph.peripheral_nodes
            email_count = graph.node_email_counts.get(email, 0)

            nodes.append(
                {
                    "id": email,
                    "label": email.split("@")[0],  # Use username part
                    "domain": email.split("@")[-1] if "@" in email else "",
                    "pagerank": round(score, 4),
                    "email_count": email_count,
                    "is_central": is_central,
                    "is_peripheral": is_peripheral,
                    "size": min(
                        30, max(5, email_count / 2)
                    ),  # Node size based on activity
                }
            )

        # Build edges (only between top nodes)
        edges = []
        edge_id = 0
        for sender, recipients in graph.edges.items():
            if sender not in top_node_set:
                continue

            for recipient, count in recipients.items():
                if recipient not in top_node_set:
                    continue

                if count >= 2:  # Only show meaningful connections
                    edges.append(
                        {
                            "id": f"edge_{edge_id}",
                            "source": sender,
                            "target": recipient,
                            "weight": count,
                        }
                    )
                    edge_id += 1

        return {
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(graph.node_pagerank),
            "displayed_nodes": len(nodes),
        }
