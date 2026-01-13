"""
Auto-tagger for Correspondence
Automatically tags emails with contract clauses, risks, and entitlements
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session
from .plugins import PluginRegistry
from .models import (
    ProjectContract,
    ContractType,
    CorrespondenceAnalysis,
)
from ..models import EmailMessage

logger = logging.getLogger(__name__)


class AutoTagger:
    """Service for auto-tagging correspondence"""

    def analyze_correspondence(
        self, db: Session, email: EmailMessage, project_contract: ProjectContract
    ) -> Optional[CorrespondenceAnalysis]:
        """Analyze an email and generate tags/risks"""

        # Get contract type
        contract_type = db.query(ContractType).get(project_contract.contract_type_id)
        if not contract_type:
            logger.warning(
                f"Contract type not found for project contract {project_contract.id}"
            )
            return None

        # Get plugin
        # Note: Plugin names in registry might differ slightly from DB names, need robust matching
        # For JCT 2016, DB name might be "JCT Design and Build 2016", plugin key "JCT Design and Build 2016"
        _plugin_key = f"{contract_type.name}"  # noqa: F841
        # Or if version is separate in DB but combined in plugin key logic
        # In JCT plugin: CONTRACT_NAME = "JCT Design and Build", CONTRACT_VERSION = "2016"
        # Registry key: "JCT Design and Build 2016"

        # Construct key from DB fields
        # Assuming DB name is "JCT Design and Build" and version is "2016"
        # But in models.py example data: name="JCT Design and Build 2016", version="2016"
        # So name already includes version?
        # Let's try to match what the plugin registers.

        # Try exact match on name first (if name includes version)
        plugin = PluginRegistry.get_plugin(contract_type.name)

        if not plugin:
            # Try constructing from name + version
            key_v = f"{contract_type.name} {contract_type.version}"
            plugin = PluginRegistry.get_plugin(key_v)

        if not plugin:
            # Fallback: iterate and check containment
            for key in PluginRegistry.get_all_plugins():
                if key in contract_type.name or contract_type.name in key:
                    plugin = PluginRegistry.get_plugin(key)
                    break

        if not plugin:
            logger.warning(f"No plugin found for {contract_type.name}")
            return None

        # Analyze text
        text_content = email.body_text_clean or email.body_text or ""
        if not text_content:
            return None

        analysis_result = plugin.analyze_text_for_entitlements(text_content)

        # Create analysis record
        analysis = CorrespondenceAnalysis(
            project_contract_id=project_contract.id,
            correspondence_id=email.id,
            raw_text=text_content[:10000],  # Truncate for storage if needed
            analysis_result=analysis_result,
            risk_score=0.0,  # Calculate based on risks
            entitlement_score=0.0,  # Calculate based on entitlements
            primary_clauses=[
                c["clause_number"] for c in analysis_result.get("matched_clauses", [])
            ],
            tags=[],  # Populate from analysis
            confidence_score=0.8,  # Placeholder
        )

        # Calculate scores and tags
        risks = analysis_result.get("risks", [])
        if risks:
            analysis.risk_score = min(len(risks) * 0.2, 1.0)  # Simple heuristic
            analysis.tags.extend(["Risk Identified"])

        entitlements = analysis_result.get("entitlements", [])
        if entitlements:
            analysis.entitlement_score = min(len(entitlements) * 0.2, 1.0)
            analysis.tags.extend([e["type"] for e in entitlements])

        db.add(analysis)
        db.commit()
        db.refresh(analysis)

        return analysis


auto_tagger = AutoTagger()
