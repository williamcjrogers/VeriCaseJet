from typing import List, Optional
from pydantic import BaseModel, Field


class IssueExtraction(BaseModel):
    issue_name: str = Field(..., description="The legal or factual issue")
    legal_test: List[str] = Field(
        default_factory=list, description="The legal test applied"
    )
    key_factors_for: List[str] = Field(
        default_factory=list, description="Factors supporting the claimant/appellant"
    )
    key_factors_against: List[str] = Field(
        default_factory=list, description="Factors supporting the defendant/respondent"
    )
    holding: str = Field(..., description="The court's decision on this issue")
    confidence: float = Field(..., description="Confidence score (0-1)")


class QuantFact(BaseModel):
    metric_type: str = Field(
        ...,
        description=(
            "Normalized metric type (e.g., RFI_COUNT, VARIATION_COUNT, DELAY_DAYS, "
            "CLAIM_VALUE_GBP, AWARD_AMOUNT_GBP, EOT_DAYS_GRANTED)"
        ),
    )
    value: Optional[float] = Field(
        default=None,
        description="Raw numeric value as stated (if available)",
    )
    unit: Optional[str] = Field(
        default=None,
        description="Unit for `value` (e.g., count, days, weeks, months, gbp)",
    )
    normalized_value: Optional[float] = Field(
        default=None,
        description="Normalized numeric value in canonical units (if available)",
    )
    normalized_unit: Optional[str] = Field(
        default=None,
        description="Canonical unit for `normalized_value` (e.g., count, days, gbp)",
    )
    qualifier: Optional[str] = Field(
        default=None,
        description="Qualifier such as claimed/awarded/found/agreed/estimated",
    )
    court_accepted: Optional[bool] = Field(
        default=None,
        description="Whether the court appears to have accepted the figure (if known)",
    )
    source_quote: Optional[str] = Field(
        default=None,
        description="Verbatim excerpt supporting the quantitative fact",
    )
    confidence: float = Field(
        default=0.5,
        description="Confidence score (0-1)",
        ge=0.0,
        le=1.0,
    )


class CaseExtraction(BaseModel):
    case_id: str
    neutral_citation: str
    summary: str
    outcome: str = Field(..., description="Overall outcome (e.g., Allowed, Dismissed)")
    issues: List[IssueExtraction] = Field(default_factory=list)
    citations: List[str] = Field(
        default_factory=list, description="Cases cited in the judgment"
    )
    key_facts: List[str] = Field(
        default_factory=list, description="Key facts of the case"
    )
    themes: List[str] = Field(
        default_factory=list,
        description="High-level themes for trend analysis (e.g., payment notices, design liability)",
    )
    contentious_issues: List[str] = Field(
        default_factory=list,
        description="Recurring contentious issues/points in dispute",
    )
    contract_form: Optional[str] = Field(
        default=None,
        description="Contract form if mentioned (e.g., JCT, NEC, FIDIC, bespoke)",
    )
    procurement_route: Optional[str] = Field(
        default=None,
        description="Delivery/procurement route if stated (e.g., design and build)",
    )
    key_clauses: List[str] = Field(
        default_factory=list,
        description="Key clause or statutory references (e.g., HGCRA s.110, JCT clause 4.10)",
    )
    delay_causes: List[str] = Field(
        default_factory=list,
        description="Causes of delay where relevant (e.g., design change, access restrictions)",
    )
    defect_types: List[str] = Field(
        default_factory=list,
        description="Defect types/issues where relevant (e.g., cladding, fire stopping)",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Normalized tags for auto-tagging and trend detection",
    )
    construction_buckets: List[str] = Field(
        default_factory=list,
        description=(
            "Construction focus buckets (e.g., design, remediation, defect, delay)"
        ),
    )
    rfi_count: Optional[int] = Field(
        default=None,
        description="Number of RFIs mentioned in the case, if stated",
    )
    change_order_count: Optional[int] = Field(
        default=None,
        description="Number of change orders/variations mentioned, if stated",
    )
    delay_days: Optional[int] = Field(
        default=None,
        description="Number of delay days mentioned, if stated",
    )
    quant_facts: List[QuantFact] = Field(
        default_factory=list,
        description="Structured quantitative facts with supporting quotes",
    )
