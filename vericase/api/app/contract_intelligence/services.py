import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..config import CONTRACT_CONFIGS
from ...search import semantic_search
from ...database import get_db

logger = logging.getLogger(__name__)


class ContractIntelligenceService:
    """
    Service for contract intelligence and analysis
    Handles contract-specific terminology, clause detection, and risk analysis
    """

    def __init__(self, db_session: Optional[Session] = None):
        self.db_session = db_session or next(get_db())
        self.contract_configs = CONTRACT_CONFIGS

    def get_contract_config(self, contract_type: str) -> Dict[str, Any]:
        """Get configuration for a specific contract type"""
        return self.contract_configs.get(contract_type, {})

    def detect_contract_clauses(
        self, text_content: str, contract_type: str
    ) -> List[Dict[str, Any]]:
        """
        Detect contract clauses in text content for a specific contract type
        Returns list of detected clauses with confidence scores
        """
        config = self.get_contract_config(contract_type)
        if not config:
            return []

        detected_clauses = []

        # Check for exact clause references (e.g., 2.26.8, 5.1.2)
        clause_pattern = r"\b(\d+\.\d+(?:\.\d+)?)\b"
        clause_matches = re.finditer(clause_pattern, text_content)

        for match in clause_matches:
            clause_ref = match.group(1)
            if clause_ref in config.get("clauses", {}):
                clause_info = config["clauses"][clause_ref]
                detected_clauses.append(
                    {
                        "clause_reference": clause_ref,
                        "clause_title": clause_info.get("title", ""),
                        "description": clause_info.get("description", ""),
                        "risk_level": clause_info.get("risk_level", "medium"),
                        "entitlement_type": clause_info.get("entitlement_type", ""),
                        "confidence": 0.95,  # High confidence for exact matches
                        "match_type": "exact_reference",
                        "text_snippet": self._get_context_snippet(
                            text_content, match.start(), match.end()
                        ),
                    }
                )

        # Semantic search for contract terminology and keywords
        keywords = config.get("keywords", [])
        for keyword_info in keywords:
            keyword = keyword_info["term"]
            pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
            matches = pattern.finditer(text_content)

            for match in matches:
                detected_clauses.append(
                    {
                        "clause_reference": keyword_info.get("related_clause", ""),
                        "clause_title": keyword_info.get("title", ""),
                        "description": keyword_info.get("description", ""),
                        "risk_level": keyword_info.get("risk_level", "low"),
                        "entitlement_type": keyword_info.get("entitlement_type", ""),
                        "confidence": 0.85,  # Medium confidence for keyword matches
                        "match_type": "keyword",
                        "keyword": keyword,
                        "text_snippet": self._get_context_snippet(
                            text_content, match.start(), match.end()
                        ),
                    }
                )

        # Remove duplicates and sort by confidence
        unique_clauses = {}
        for clause in detected_clauses:
            key = clause["clause_reference"]
            if (
                key not in unique_clauses
                or clause["confidence"] > unique_clauses[key]["confidence"]
            ):
                unique_clauses[key] = clause

        return sorted(
            unique_clauses.values(), key=lambda x: x["confidence"], reverse=True
        )

    def analyze_correspondence_risks(
        self, text_content: str, contract_type: str
    ) -> Dict[str, Any]:
        """
        Analyze correspondence text for contract-related risks and entitlements
        """
        detected_clauses = self.detect_contract_clauses(text_content, contract_type)

        # Categorize by risk level and entitlement type
        risks = {
            "high_risk": [],
            "medium_risk": [],
            "low_risk": [],
            "entitlements": [],
            "all_clauses": detected_clauses,
        }

        for clause in detected_clauses:
            if clause["risk_level"] == "high":
                risks["high_risk"].append(clause)
            elif clause["risk_level"] == "medium":
                risks["medium_risk"].append(clause)
            else:
                risks["low_risk"].append(clause)

            if clause["entitlement_type"]:
                risks["entitlements"].append(clause)

        # Calculate overall risk score
        risk_score = self._calculate_risk_score(detected_clauses)

        return {
            "risk_score": risk_score,
            "risk_level": self._get_risk_level(risk_score),
            "detected_clauses": detected_clauses,
            "risk_categories": risks,
            "contract_type": contract_type,
            "analysis_timestamp": datetime.utcnow().isoformat(),
        }

    def _calculate_risk_score(self, clauses: List[Dict[str, Any]]) -> float:
        """Calculate overall risk score based on detected clauses"""
        if not clauses:
            return 0.0

        risk_weights = {"high": 1.0, "medium": 0.5, "low": 0.2}
        total_weight = 0.0
        weighted_sum = 0.0

        for clause in clauses:
            weight = risk_weights.get(clause["risk_level"], 0.2)
            weighted_sum += clause["confidence"] * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _get_risk_level(self, score: float) -> str:
        """Convert risk score to human-readable level"""
        if score >= 0.7:
            return "high"
        elif score >= 0.4:
            return "medium"
        else:
            return "low"

    def _get_context_snippet(
        self, text: str, start: int, end: int, context_chars: int = 100
    ) -> str:
        """Get context around a match in the text"""
        context_start = max(0, start - context_chars)
        context_end = min(len(text), end + context_chars)
        return text[context_start:context_end]

    def search_case_law(
        self, query: str, contract_type: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search case law references related to contract clauses
        """
        # First try semantic search in vector database
        try:
            semantic_results = semantic_search(
                query=query, index_name=f"case_law_{contract_type.lower()}", limit=limit
            )

            if semantic_results:
                return semantic_results
        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")

        # Fallback to database search
        return self._search_case_law_db(query, contract_type, limit)

    def _search_case_law_db(
        self, query: str, contract_type: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Search case law in database"""
        try:
            # Use full-text search if available, otherwise simple LIKE search
            results = self.db_session.execute(
                text(
                    """
                SELECT id, title, summary, citation, relevance_score, 
                       contract_clauses, key_findings, decision_date
                FROM case_law_references 
                WHERE contract_type = :contract_type 
                AND (title ILIKE :query OR summary ILIKE :query OR key_findings ILIKE :query)
                ORDER BY relevance_score DESC, decision_date DESC
                LIMIT :limit
                """
                ),
                {"contract_type": contract_type, "query": f"%{query}%", "limit": limit},
            ).fetchall()

            return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Database search failed: {e}")
            return []

    def get_contract_insights(
        self, project_id: str, contract_type: str
    ) -> Dict[str, Any]:
        """
        Get comprehensive contract insights for a project
        """
        # Get recent correspondence with contract analysis
        recent_correspondence = self._get_recent_correspondence(project_id)

        # Analyze risks across all correspondence
        all_risks = []
        for correspondence in recent_correspondence:
            analysis = self.analyze_correspondence_risks(
                correspondence.get("content", ""), contract_type
            )
            all_risks.append(analysis)

        # Calculate project-wide risk metrics
        project_risk = self._calculate_project_risk_metrics(all_risks)

        # Get top risk patterns
        risk_patterns = self._identify_risk_patterns(all_risks)

        return {
            "project_id": project_id,
            "contract_type": contract_type,
            "risk_metrics": project_risk,
            "risk_patterns": risk_patterns,
            "recent_analyses": all_risks[:5],  # Last 5 analyses
            "total_analyses": len(all_risks),
            "generated_at": datetime.utcnow().isoformat(),
        }

    def _get_recent_correspondence(
        self, project_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get recent correspondence for a project"""
        try:
            results = self.db_session.execute(
                text(
                    """
                SELECT id, subject, body, created_at, metadata
                FROM correspondence 
                WHERE project_id = :project_id 
                ORDER BY created_at DESC
                LIMIT :limit
                """
                ),
                {"project_id": project_id, "limit": limit},
            ).fetchall()

            return [
                {
                    "id": row[0],
                    "subject": row[1],
                    "content": f"{row[1]} {row[2]}",  # Combine subject and body
                    "created_at": row[3],
                    "metadata": row[4] if row[4] else {},
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"Failed to get correspondence: {e}")
            return []

    def _calculate_project_risk_metrics(
        self, analyses: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate project-wide risk metrics"""
        if not analyses:
            return {"overall_risk": 0.0, "risk_level": "low", "high_risk_count": 0}

        total_risk = sum(analysis["risk_score"] for analysis in analyses)
        avg_risk = total_risk / len(analyses)

        high_risk_count = sum(
            1 for analysis in analyses if analysis["risk_level"] == "high"
        )

        return {
            "overall_risk": avg_risk,
            "risk_level": self._get_risk_level(avg_risk),
            "high_risk_count": high_risk_count,
            "total_analyses": len(analyses),
            "entitlement_opportunities": sum(
                len(analysis["risk_categories"]["entitlements"])
                for analysis in analyses
            ),
        }

    def _identify_risk_patterns(
        self, analyses: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify recurring risk patterns across analyses"""
        clause_counts = {}

        for analysis in analyses:
            for clause in analysis.get("detected_clauses", []):
                clause_ref = clause["clause_reference"]
                clause_counts[clause_ref] = clause_counts.get(clause_ref, 0) + 1

        # Get top 5 most frequent clauses
        top_clauses = sorted(clause_counts.items(), key=lambda x: x[1], reverse=True)[
            :5
        ]

        return [
            {
                "clause_reference": clause_ref,
                "frequency": count,
                "frequency_percentage": (
                    (count / len(analyses)) * 100 if analyses else 0
                ),
            }
            for clause_ref, count in top_clauses
        ]


def get_contract_intelligence_service() -> ContractIntelligenceService:
    """Factory function to get contract intelligence service"""
    return ContractIntelligenceService()
