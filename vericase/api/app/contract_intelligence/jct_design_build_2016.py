"""
JCT Design and Build 2016 Contract Configuration
Contains comprehensive clause definitions, risk patterns, and semantic understanding
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from .plugins import ContractPlugin, PluginRegistry


class RiskLevel(Enum):
    """Risk levels for contract clause analysis"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EntitlementType(Enum):
    """Types of contractual entitlements"""

    TIME_EXTENSION = "time_extension"
    COST_RECOVERY = "cost_recovery"
    TERMINATION = "termination"
    COMPENSATION = "compensation"
    VARIATION = "variation"
    DISPUTE = "dispute"


@dataclass
class ContractClause:
    """Represents a contract clause with metadata and analysis rules"""

    clause_number: str
    title: str
    description: str
    risk_level: RiskLevel
    keywords: List[str]
    semantic_patterns: List[str]
    related_clauses: List[str]
    entitlement_types: List[EntitlementType]
    mitigation_strategies: List[str]
    time_implications: Optional[str] = None
    cost_implications: Optional[str] = None


class JCTDesignBuild2016(ContractPlugin):
    """JCT Design and Build 2016 contract configuration"""

    CONTRACT_NAME = "JCT Design and Build 2016"
    CONTRACT_VERSION = "2016"

    # Section 2: Definitions and Interpretation
    CLAUSES_2 = {
        "2.26.1": ContractClause(
            clause_number="2.26.1",
            title="Relevant Event - Variations",
            description="Variations and other matters treated as variations",
            risk_level=RiskLevel.MEDIUM,
            keywords=["variation", "change order", "instruction", "modified work"],
            semantic_patterns=[
                "variation instruction",
                "change to the works",
                "instruction requiring a variation",
                "expenditure of provisional sum",
            ],
            related_clauses=["5.1", "5.2"],
            entitlement_types=[
                EntitlementType.TIME_EXTENSION,
                EntitlementType.COST_RECOVERY,
            ],
            mitigation_strategies=[
                "Ensure variation instruction is in writing",
                "Submit quotation promptly",
                "Track time impact separately",
            ],
            time_implications="Extension of time for delay caused by variation",
            cost_implications="Valuation of variation",
        ),
        "2.26.2": ContractClause(
            clause_number="2.26.2",
            title="Relevant Event - Employer's Instructions",
            description="Instructions from the Employer affecting the works",
            risk_level=RiskLevel.MEDIUM,
            keywords=["instruction", "employer instruction", "compliance", "order"],
            semantic_patterns=[
                "compliance with instruction",
                "employer's instruction",
                "instruction affecting progress",
                "opening up for inspection",
            ],
            related_clauses=["3.10", "3.15"],
            entitlement_types=[EntitlementType.TIME_EXTENSION],
            mitigation_strategies=[
                "Confirm verbal instructions in writing",
                "Assess impact immediately",
                "Notify if instruction causes delay",
            ],
            time_implications="Extension of time if instruction delays completion",
            cost_implications="May be treated as variation",
        ),
        "2.26.3": ContractClause(
            clause_number="2.26.3",
            title="Relevant Event - Access Restrictions",
            description="Employer's failure to give access to the site or part of the site",
            risk_level=RiskLevel.HIGH,
            keywords=[
                "access",
                "restriction",
                "site access",
                "denied access",
                "refused access",
            ],
            semantic_patterns=[
                "unable to access site",
                "access denied to",
                "refused entry to site",
                "prevented from accessing",
                "site access restricted",
            ],
            related_clauses=["2.26", "2.27", "2.28"],
            entitlement_types=[
                EntitlementType.TIME_EXTENSION,
                EntitlementType.COST_RECOVERY,
            ],
            mitigation_strategies=[
                "Formal notice of access restriction required",
                "Document all access attempts and communications",
                "Assess impact on critical path activities",
            ],
            time_implications="Extension of time may be granted",
            cost_implications="May lead to loss and expense claims",
        ),
        "2.26.6": ContractClause(
            clause_number="2.26.6",
            title="Relevant Event - Statutory Undertakers",
            description="Delays caused by Statutory Undertakers",
            risk_level=RiskLevel.MEDIUM,
            keywords=[
                "statutory undertaker",
                "utility",
                "connection",
                "power",
                "water",
                "gas",
            ],
            semantic_patterns=[
                "delay by statutory undertaker",
                "utility connection delay",
                "waiting for power connection",
                "water company delay",
                "gas connection delay",
            ],
            related_clauses=["2.26"],
            entitlement_types=[EntitlementType.TIME_EXTENSION],
            mitigation_strategies=[
                "Early engagement with utilities",
                "Track all correspondence",
                "Document readiness for connection",
            ],
            time_implications="Extension of time for utility delays",
            cost_implications="Generally time only",
        ),
        "2.26.8": ContractClause(
            clause_number="2.26.8",
            title="Relevant Event - Exceptionally Adverse Weather",
            description="Exceptionally adverse weather conditions",
            risk_level=RiskLevel.MEDIUM,
            keywords=[
                "weather",
                "adverse weather",
                "exceptional weather",
                "storm",
                "flood",
                "snow",
                "wind",
            ],
            semantic_patterns=[
                "exceptionally poor weather",
                "adverse weather conditions",
                "weather preventing work",
                "storm damage",
                "flood conditions",
                "heavy snow",
                "high winds",
            ],
            related_clauses=["2.26", "2.27", "2.28"],
            entitlement_types=[EntitlementType.TIME_EXTENSION],
            mitigation_strategies=[
                "Maintain detailed weather records",
                "Compare with historical weather data (Met Office)",
                "Implement weather protection measures",
                "Document specific activities affected",
            ],
            time_implications="Extension of time for weather delays",
            cost_implications="Generally time only, no cost recovery",
        ),
        "2.26.12": ContractClause(
            clause_number="2.26.12",
            title="Relevant Event - Force Majeure",
            description="Force Majeure events",
            risk_level=RiskLevel.HIGH,
            keywords=[
                "force majeure",
                "unforeseeable",
                "act of god",
                "war",
                "terrorism",
            ],
            semantic_patterns=[
                "force majeure event",
                "beyond control",
                "unforeseeable circumstances",
                "act of terrorism",
                "civil commotion",
            ],
            related_clauses=["2.26", "8.11"],
            entitlement_types=[
                EntitlementType.TIME_EXTENSION,
                EntitlementType.TERMINATION,
            ],
            mitigation_strategies=[
                "Immediate notification",
                "Mitigate effects where possible",
                "Check insurance coverage",
            ],
            time_implications="Extension of time granted",
            cost_implications="Generally time only, potential termination rights",
        ),
    }

    # Section 5: Variations
    CLAUSES_5 = {
        "5.1.2": ContractClause(
            clause_number="5.1.2",
            title="Variation - Changes to Work",
            description="Changes to the work, including changes to working conditions",
            risk_level=RiskLevel.HIGH,
            keywords=[
                "variation",
                "change",
                "working conditions",
                "modified work",
                "altered scope",
            ],
            semantic_patterns=[
                "change to working conditions",
                "modified work requirements",
                "altered scope of work",
                "variation instruction",
                "changed methodology",
            ],
            related_clauses=["5.1", "5.2", "5.3", "5.4"],
            entitlement_types=[
                EntitlementType.VARIATION,
                EntitlementType.COST_RECOVERY,
                EntitlementType.TIME_EXTENSION,
            ],
            mitigation_strategies=[
                "Formal variation instruction required",
                "Document impact assessment",
                "Agree valuation method before proceeding",
            ],
            time_implications="May require extension of time",
            cost_implications="Subject to variation valuation",
        ),
    }

    # Section 4: Payment
    CLAUSES_4 = {
        "4.7": ContractClause(
            clause_number="4.7",
            title="Interim Payments",
            description="Provisions for interim payments and payment notices",
            risk_level=RiskLevel.CRITICAL,
            keywords=[
                "payment",
                "interim payment",
                "payment notice",
                "certificate",
                "withholding",
            ],
            semantic_patterns=[
                "payment due",
                "interim certificate",
                "payment notice issued",
                "withholding payment",
                "payment dispute",
            ],
            related_clauses=["4.8", "4.9", "4.10", "4.11"],
            entitlement_types=[EntitlementType.COMPENSATION, EntitlementType.DISPUTE],
            mitigation_strategies=[
                "Strict adherence to payment notice deadlines",
                "Maintain detailed payment records",
                "Follow payment dispute resolution procedures",
            ],
            time_implications="Payment timing critical for cash flow",
            cost_implications="Direct financial impact on project",
        ),
    }

    # Section 8: Termination
    CLAUSES_8 = {
        "8.4": ContractClause(
            clause_number="8.4",
            title="Termination by Contractor",
            description="Contractor's rights to terminate the contract",
            risk_level=RiskLevel.CRITICAL,
            keywords=[
                "termination",
                "contractor termination",
                "default",
                "breach",
                "insolvency",
            ],
            semantic_patterns=[
                "terminate the contract",
                "contractor termination rights",
                "employer default",
                "material breach",
                "insolvency event",
            ],
            related_clauses=["8.5", "8.6", "8.7", "8.8"],
            entitlement_types=[
                EntitlementType.TERMINATION,
                EntitlementType.COMPENSATION,
            ],
            mitigation_strategies=[
                "Formal notice of default required",
                "Opportunity to remedy breaches",
                "Legal advice recommended before termination",
            ],
            time_implications="Immediate cessation of works",
            cost_implications="Significant financial implications",
        ),
    }

    # Additional important clauses
    CLAUSES_OTHER = {
        "2.27": ContractClause(
            clause_number="2.27",
            title="Relevant Matters",
            description="Matters giving rise to loss and expense",
            risk_level=RiskLevel.HIGH,
            keywords=[
                "loss",
                "expense",
                "relevant matter",
                "disruption",
                "additional cost",
            ],
            semantic_patterns=[
                "loss and expense",
                "additional costs incurred",
                "disruption to works",
                "financial impact",
                "cost recovery",
            ],
            related_clauses=["2.26", "2.28", "4.19", "4.20"],
            entitlement_types=[EntitlementType.COST_RECOVERY],
            mitigation_strategies=[
                "Detailed cost records required",
                "Causal link to relevant matter must be established",
                "Formal application process",
            ],
            time_implications="May accompany time extension",
            cost_implications="Direct cost recovery",
        ),
        "2.28": ContractClause(
            clause_number="2.28",
            title="Extension of Time",
            description="Procedure for granting extensions of time",
            risk_level=RiskLevel.HIGH,
            keywords=["extension", "time", "EOT", "delay", "completion date"],
            semantic_patterns=[
                "extension of time",
                "time extension required",
                "delay to completion",
                "EOT application",
                "revised completion date",
            ],
            related_clauses=["2.26", "2.27", "2.29"],
            entitlement_types=[EntitlementType.TIME_EXTENSION],
            mitigation_strategies=[
                "Timely notification of delays",
                "Detailed delay analysis required",
                "Maintain contemporaneous records",
            ],
            time_implications="Adjustment to completion date",
            cost_implications="May prevent liquidated damages",
        ),
    }

    # Combine all clauses
    ALL_CLAUSES = {**CLAUSES_2, **CLAUSES_4, **CLAUSES_5, **CLAUSES_8, **CLAUSES_OTHER}

    @classmethod
    def get_clause(cls, clause_number: str) -> Optional[ContractClause]:
        """Get a specific clause by number"""
        return cls.ALL_CLAUSES.get(clause_number)

    @classmethod
    def find_clauses_by_keyword(cls, keyword: str) -> List[ContractClause]:
        """Find clauses containing a specific keyword"""
        return [
            clause
            for clause in cls.ALL_CLAUSES.values()
            if keyword.lower() in [k.lower() for k in clause.keywords]
            or any(
                keyword.lower() in pattern.lower()
                for pattern in clause.semantic_patterns
            )
        ]

    @classmethod
    def analyze_text_for_entitlements(cls, text: str) -> Dict[str, Any]:
        """Analyze text for potential contractual entitlements"""
        text_lower = text.lower()
        results = {"entitlements": [], "risks": [], "matched_clauses": []}

        for clause_number, clause in cls.ALL_CLAUSES.items():
            # Check keywords
            keyword_matches = [
                keyword for keyword in clause.keywords if keyword.lower() in text_lower
            ]

            # Check semantic patterns
            pattern_matches = [
                pattern
                for pattern in clause.semantic_patterns
                if pattern.lower() in text_lower
            ]

            if keyword_matches or pattern_matches:
                clause_result = {
                    "clause_number": clause_number,
                    "clause_title": clause.title,
                    "keyword_matches": keyword_matches,
                    "pattern_matches": pattern_matches,
                    "risk_level": clause.risk_level.value,
                    "entitlement_types": [et.value for et in clause.entitlement_types],
                    "description": clause.description,
                }
                results["matched_clauses"].append(clause_result)

                # Add to entitlements if relevant
                if clause.entitlement_types:
                    results["entitlements"].extend(
                        [
                            {
                                "type": et.value,
                                "clause": clause_number,
                                "description": f"Potential {et.value.replace('_', ' ')} under clause {clause_number}",
                            }
                            for et in clause.entitlement_types
                        ]
                    )

                # Add to risks
                results["risks"].append(
                    {
                        "clause": clause_number,
                        "risk_level": clause.risk_level.value,
                        "description": clause.description,
                        "mitigation": (
                            clause.mitigation_strategies[0]
                            if clause.mitigation_strategies
                            else ""
                        ),
                    }
                )

        return results

    @classmethod
    def get_all_clauses(cls) -> Dict[str, ContractClause]:
        """Get all clauses in the contract"""
        return cls.ALL_CLAUSES

    @classmethod
    def get_high_risk_clauses(cls) -> List[ContractClause]:
        """Get clauses with high or critical risk levels"""
        return [
            clause
            for clause in cls.ALL_CLAUSES.values()
            if clause.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
        ]


# Register the plugin
PluginRegistry.register(JCTDesignBuild2016)

# Example usage and testing
if __name__ == "__main__":
    # Test the contract analysis
    test_text = """
    The site team reported exceptionally poor weather conditions today, 
    with heavy rain preventing access to the main work area. 
    We were refused access to section B due to safety concerns raised by the client.
    This will require changes to our working conditions and methodology.
    """

    analysis = JCTDesignBuild2016.analyze_text_for_entitlements(test_text)
    print("Analysis Results:")
    print(f"Matched Clauses: {len(analysis['matched_clauses'])}")
    print(f"Entitlements: {len(analysis['entitlements'])}")
    print(f"Risks: {len(analysis['risks'])}")

    for clause in analysis["matched_clauses"]:
        print(f"\nClause {clause['clause_number']}: {clause['clause_title']}")
        print(f"  Risk Level: {clause['risk_level']}")
        print(f"  Keywords matched: {clause['keyword_matches']}")
        print(f"  Patterns matched: {clause['pattern_matches']}")
        print(f"  Entitlements: {clause['entitlement_types']}")
