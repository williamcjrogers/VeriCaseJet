"""
VeriCase Contract Intelligence Module (TEMP)
=====================================
Provides contract-aware categorization and keyword detection for construction disputes.

Usage:
    from contract_intelligence import ContractIntelligence
    
    ci = ContractIntelligence()  # Loads JCT D&B 2016 by default
    
    # Analyze email content
    results = ci.analyze_text("The contractor hereby gives notice of delay...")
    
    # Get relevant events mentioned
    events = ci.find_relevant_events(email_body)
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field


@dataclass
class ContractMatch:
    """Represents a matched contract term in text"""

    term: str
    term_id: str
    clause_ref: str
    category: str
    matched_keyword: str
    position: Tuple[int, int]
    confidence: float


@dataclass
class AnalysisResult:
    """Complete analysis result for a piece of text"""

    relevant_events: List[ContractMatch] = field(default_factory=list)
    relevant_matters: List[ContractMatch] = field(default_factory=list)
    notice_indicators: List[ContractMatch] = field(default_factory=list)
    parties_mentioned: List[ContractMatch] = field(default_factory=list)
    key_dates: List[ContractMatch] = field(default_factory=list)
    suggested_categories: List[str] = field(default_factory=list)
    claim_type_indicators: Dict[str, float] = field(default_factory=dict)


class ContractIntelligence:
    """
    Contract-aware intelligence for construction dispute analysis.

    Loads contract configuration and provides keyword/clause detection
    for automated categorization of correspondence.
    """

    def __init__(
        self, config_path: Optional[str] = None, contract_type: str = "JCT_DB_2016"
    ):
        """
        Initialize with contract configuration.

        Args:
            config_path: Path to JSON config file. If None, uses built-in config.
            contract_type: Contract type identifier for multi-contract support.
        """
        self.contract_type = contract_type
        self.config = self._load_config(config_path)
        self._compile_patterns()

    def _load_config(self, config_path: Optional[str]) -> Dict:
        """Load contract configuration from JSON file."""
        if config_path and Path(config_path).exists():
            with open(config_path, "r") as f:
                return json.load(f)

        # Return minimal default config if no file provided
        return self._get_default_config()

    def _get_default_config(self) -> Dict:
        """Return embedded default JCT D&B 2016 configuration."""
        return {
            "contract_type": "JCT Design and Build 2016",
            "defined_terms": {
                "relevant_events": {
                    "clause_ref": "2.26",
                    "items": [
                        {
                            "id": "RE1",
                            "term": "Variations",
                            "keywords": ["variation", "varied", "change order"],
                            "clause": "2.26.1",
                        },
                        {
                            "id": "RE2",
                            "term": "Employer's Instructions",
                            "keywords": [
                                "instruction",
                                "AI",
                                "architect's instruction",
                            ],
                            "clause": "2.26.2",
                        },
                        {
                            "id": "RE5",
                            "term": "Impediment by Employer",
                            "keywords": ["impediment", "prevention", "default"],
                            "clause": "2.26.5",
                        },
                        {
                            "id": "RE7",
                            "term": "Adverse weather",
                            "keywords": [
                                "weather",
                                "adverse weather",
                                "exceptional weather",
                            ],
                            "clause": "2.26.7",
                        },
                    ],
                },
                "relevant_matters": {
                    "clause_ref": "4.20",
                    "items": [
                        {
                            "id": "RM1",
                            "term": "Variations",
                            "keywords": ["variation", "additional work"],
                            "clause": "4.20.1",
                        },
                        {
                            "id": "RM6",
                            "term": "Late information",
                            "keywords": [
                                "late information",
                                "ER",
                                "employer's requirements",
                            ],
                            "clause": "4.20.6",
                        },
                    ],
                },
            },
        }

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficient matching."""
        self._patterns: Dict[str, List[Tuple[re.Pattern, Dict]]] = {}

        defined_terms = self.config.get("defined_terms", {})

        for category, data in defined_terms.items():
            self._patterns[category] = []
            items = data.get("items", [])

            for item in items:
                keywords = item.get("keywords", [])
                for keyword in keywords:
                    # Create case-insensitive pattern with word boundaries
                    pattern = re.compile(
                        r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE
                    )
                    self._patterns[category].append(
                        (
                            pattern,
                            {
                                "term": item.get("term"),
                                "term_id": item.get("id"),
                                "clause": item.get("clause"),
                                "keyword": keyword,
                            },
                        )
                    )

        # Compile search patterns for claim type detection
        self._claim_patterns: Dict[str, List[re.Pattern]] = {}
        search_patterns = self.config.get("search_patterns", {})

        for pattern_type, phrases in search_patterns.items():
            self._claim_patterns[pattern_type] = [
                re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
                for phrase in phrases
            ]

    def analyze_text(self, text: str) -> AnalysisResult:
        """
        Perform comprehensive contract-aware analysis on text.

        Args:
            text: The text content to analyze (email body, document content, etc.)

        Returns:
            AnalysisResult containing all detected contract references.
        """
        result = AnalysisResult()

        # Find matches in each category
        for category, patterns in self._patterns.items():
            matches = self._find_matches(text, patterns, category)

            if category == "relevant_events":
                result.relevant_events = matches
            elif category == "relevant_matters":
                result.relevant_matters = matches
            elif category == "notice_requirements":
                result.notice_indicators = matches
            elif category == "parties_and_roles":
                result.parties_mentioned = matches
            elif category == "key_dates":
                result.key_dates = matches

        # Detect claim type indicators
        result.claim_type_indicators = self._detect_claim_types(text)

        # Suggest categories based on findings
        result.suggested_categories = self._suggest_categories(result)

        return result

    def _find_matches(
        self, text: str, patterns: List[Tuple[re.Pattern, Dict]], category: str
    ) -> List[ContractMatch]:
        """Find all matches for a set of patterns in text."""
        matches = []
        seen_terms = set()  # Avoid duplicate matches for same term

        for pattern, metadata in patterns:
            for match in pattern.finditer(text):
                term_id = metadata["term_id"]

                # Only add first match per unique term
                if term_id not in seen_terms:
                    seen_terms.add(term_id)
                    matches.append(
                        ContractMatch(
                            term=metadata["term"],
                            term_id=term_id,
                            clause_ref=metadata["clause"],
                            category=category,
                            matched_keyword=metadata["keyword"],
                            position=(match.start(), match.end()),
                            confidence=self._calculate_confidence(
                                text, match, metadata
                            ),
                        )
                    )

        return matches

    def _calculate_confidence(
        self, text: str, match: re.Match, metadata: Dict
    ) -> float:
        """
        Calculate confidence score for a match.

        Higher confidence if:
        - Multiple related keywords appear nearby
        - Formal language patterns present
        - Clause references mentioned
        """
        confidence = 0.6  # Base confidence for keyword match

        # Check for clause references nearby (within 200 chars)
        start = max(0, match.start() - 200)
        end = min(len(text), match.end() + 200)
        context = text[start:end].lower()

        if re.search(r"clause\s*\d+\.?\d*", context):
            confidence += 0.15

        if any(
            phrase in context
            for phrase in ["pursuant to", "in accordance with", "under the contract"]
        ):
            confidence += 0.1

        if any(
            phrase in context for phrase in ["hereby", "formal notice", "notification"]
        ):
            confidence += 0.1

        return min(confidence, 1.0)

    def _detect_claim_types(self, text: str) -> Dict[str, float]:
        """Detect likely claim types based on pattern matching."""
        scores = {}

        for claim_type, patterns in self._claim_patterns.items():
            match_count = sum(1 for p in patterns if p.search(text))
            if match_count > 0:
                # Normalize score based on number of patterns matched
                scores[claim_type] = min(match_count / len(patterns) * 1.5, 1.0)

        return scores

    def _suggest_categories(self, result: AnalysisResult) -> List[str]:
        """Suggest VeriCase categories based on analysis results."""
        categories = []

        if result.relevant_events:
            categories.append("Delay Claims")

            # More specific categorization
            event_ids = {m.term_id for m in result.relevant_events}
            if "RE7" in event_ids:
                categories.append("Weather Delays")
            if "RE1" in event_ids:
                categories.append("Variation Disputes")

        if result.relevant_matters:
            categories.append("Loss and Expense")

            matter_ids = {m.term_id for m in result.relevant_matters}
            if "RM6" in matter_ids:
                categories.append("Design Issues")

        if result.notice_indicators:
            categories.append("Formal Notices")

        # Add from claim type indicators
        claim_scores = result.claim_type_indicators
        if claim_scores.get("eot_indicators", 0) > 0.3:
            if "Delay Claims" not in categories:
                categories.append("Delay Claims")
        if claim_scores.get("loss_expense_indicators", 0) > 0.3:
            if "Loss and Expense" not in categories:
                categories.append("Loss and Expense")

        return list(set(categories))

    def find_relevant_events(self, text: str) -> List[Dict]:
        """
        Convenience method to find only Relevant Events.

        Returns list of dicts with term, clause, and confidence.
        """
        result = self.analyze_text(text)
        return [
            {
                "term": m.term,
                "clause": m.clause_ref,
                "matched_keyword": m.matched_keyword,
                "confidence": m.confidence,
            }
            for m in result.relevant_events
        ]

    def find_relevant_matters(self, text: str) -> List[Dict]:
        """
        Convenience method to find only Relevant Matters.

        Returns list of dicts with term, clause, and confidence.
        """
        result = self.analyze_text(text)
        return [
            {
                "term": m.term,
                "clause": m.clause_ref,
                "matched_keyword": m.matched_keyword,
                "confidence": m.confidence,
            }
            for m in result.relevant_matters
        ]

    def get_category_keywords(self, category: str) -> List[str]:
        """Get all keywords for a specific category (for UI/config display)."""
        defined_terms = self.config.get("defined_terms", {})
        if category in defined_terms:
            keywords = []
            for item in defined_terms[category].get("items", []):
                keywords.extend(item.get("keywords", []))
            return keywords
        return []

    def export_for_ai_prompt(self) -> str:
        """
        Export configuration as prompt context for AI categorization.

        Use this to inject contract knowledge into AI model prompts.
        """
        output = (
            f"CONTRACT KNOWLEDGE: {self.config.get('contract_type', 'Unknown')}\n\n"
        )

        defined_terms = self.config.get("defined_terms", {})

        if "relevant_events" in defined_terms:
            output += "RELEVANT EVENTS (Extension of Time grounds, Clause 2.26):\n"
            for item in defined_terms["relevant_events"].get("items", []):
                output += f"- {item['term']} ({item['clause']}): {', '.join(item['keywords'][:3])}\n"
            output += "\n"

        if "relevant_matters" in defined_terms:
            output += "RELEVANT MATTERS (Loss & Expense grounds, Clause 4.20):\n"
            for item in defined_terms["relevant_matters"].get("items", []):
                output += f"- {item['term']} ({item['clause']}): {', '.join(item['keywords'][:3])}\n"
            output += "\n"

        return output


# Convenience function for quick integration
def analyze_email(text: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Quick analysis function for integration with existing VeriCase pipeline.

    Returns a dictionary suitable for adding to Excel output columns.
    """
    ci = ContractIntelligence(config_path)
    result = ci.analyze_text(text)

    return {
        "AI_RelevantEvents": "; ".join(
            [f"{m.term} ({m.clause_ref})" for m in result.relevant_events]
        ),
        "AI_RelevantMatters": "; ".join(
            [f"{m.term} ({m.clause_ref})" for m in result.relevant_matters]
        ),
        "AI_ContractCategories": "; ".join(result.suggested_categories),
        "AI_NoticeDetected": len(result.notice_indicators) > 0,
        "AI_EOT_Confidence": result.claim_type_indicators.get("eot_indicators", 0),
        "AI_L&E_Confidence": result.claim_type_indicators.get(
            "loss_expense_indicators", 0
        ),
    }


if __name__ == "__main__":
    # Demo usage
    sample_text = """
    Dear Sir,
    
    We hereby give notice pursuant to Clause 2.24 of the Contract that the Works 
    have been delayed due to exceptionally adverse weather conditions experienced 
    during the week commencing 15th January 2024.
    
    This constitutes a Relevant Event under Clause 2.26.7 and we hereby claim an 
    extension of time to the Completion Date.
    
    We also notify you that we have incurred loss and expense as a result of the 
    late provision of Employer's Requirements drawings, which is a Relevant Matter 
    under Clause 4.20.6.
    
    Regards,
    Project Manager
    """

    ci = ContractIntelligence()
    result = ci.analyze_text(sample_text)

    print("=== Contract Analysis Demo ===\n")
    print(f"Relevant Events found: {len(result.relevant_events)}")
    for re in result.relevant_events:
        print(
            f"  - {re.term} (Clause {re.clause_ref}) [confidence: {re.confidence:.2f}]"
        )

    print(f"\nRelevant Matters found: {len(result.relevant_matters)}")
    for rm in result.relevant_matters:
        print(
            f"  - {rm.term} (Clause {rm.clause_ref}) [confidence: {rm.confidence:.2f}]"
        )

    print(f"\nSuggested categories: {result.suggested_categories}")
    print(f"\nClaim type indicators: {result.claim_type_indicators}")
