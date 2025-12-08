"""
Migration Script: Consolidate AI Providers to 4 (OpenAI, Anthropic, Gemini, Bedrock)

This migration:
1. Deletes deprecated settings (grok_*, perplexity_*, phi_*)
2. Creates default function configs for quick_search and deep_analysis
3. Adds bedrock_enabled and bedrock_region settings if not present

Run this script after deploying the new AI provider consolidation code.

Usage:
    python -m api.app.migrations.consolidate_ai_providers
"""

import json
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sqlalchemy.orm import Session
from api.app.db import SessionLocal
from api.app.models import AppSetting

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Settings to delete (deprecated providers)
DEPRECATED_SETTINGS = [
    "grok_api_key",
    "grok_model",
    "perplexity_api_key",
    "perplexity_model",
    "phi_endpoint",
    "phi_model",
    "phi_enabled",
]

# Default function configurations (cost-aware defaults)
# Quick Search: Uses budget-tier models for speed
# Deep Analysis: Uses balanced-tier by default (Sonnet, not Opus) to control costs
DEFAULT_FUNCTION_CONFIGS = {
    "ai_function_quick_search": {
        "provider": "gemini",
        "model": "gemini-2.0-flash",  # Budget tier: ~$0.075/1M tokens
        "thinking_enabled": False,
        "max_duration_seconds": 30,
    },
    "ai_function_deep_analysis": {
        "provider": "anthropic",
        "model": "claude-4.5-sonnet",  # Balanced tier: ~$3/1M tokens (was Opus ~$75/1M)
        "thinking_enabled": True,
        "thinking_budget_tokens": 5000,  # Reduced from 10000 for cost efficiency
        "max_duration_seconds": 300,
        "orchestration": {
            "enabled": False,
            "mode": "parallel",
            "models": [],
        },
    },
}

# Cost tiers for model selection guidance
# These help admins understand the cost implications of their choices
MODEL_COST_TIERS = {
    "budget": {
        "description": "Fast & cheap - best for quick searches",
        "models": [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gpt-4o-mini",
            "claude-4.5-haiku",
            "amazon.titan-text-lite-v1",
        ],
    },
    "balanced": {
        "description": "Good quality at reasonable cost - recommended default",
        "models": [
            "gemini-2.0-pro",
            "gpt-4o",
            "claude-4.5-sonnet",
            "amazon.titan-text-premier-v1",
            "meta.llama3-70b-instruct-v1:0",
        ],
    },
    "premium": {
        "description": "Best quality - use for complex analysis",
        "models": [
            "gemini-3.0-pro",
            "o3",
            "gpt-5.1",
            "claude-4.5-opus",
            "anthropic.claude-4.5-opus-v1:0",
        ],
    },
}

# New settings to create if not present
NEW_SETTINGS = {
    # Bedrock settings
    "bedrock_enabled": {
        "value": "false",
        "description": "Enable Amazon Bedrock AI provider (uses IAM credentials)",
    },
    "bedrock_region": {
        "value": "us-east-1",
        "description": "AWS region for Bedrock",
    },
    "bedrock_model": {
        "value": "amazon.nova-pro-v1:0",
        "description": "Default Bedrock model",
    },
    # Resilience settings (Phase 8)
    "ai_fallback_enabled": {
        "value": "true",
        "description": "Enable automatic fallback to other providers when one fails",
    },
    "ai_fallback_log_attempts": {
        "value": "true",
        "description": "Log each fallback attempt for debugging",
    },
    # Bedrock-first mode for enterprise compliance
    "bedrock_route_claude": {
        "value": "false",
        "description": "Route all Claude requests through AWS Bedrock (recommended for SOC2/HIPAA)",
    },
}


def run_migration(db: Session) -> dict[str, int]:
    """
    Run the AI provider consolidation migration.

    Returns:
        dict with counts of deleted, created, and skipped settings
    """
    results = {
        "deleted": 0,
        "created": 0,
        "skipped": 0,
    }

    # Step 1: Delete deprecated settings
    logger.info("Step 1: Deleting deprecated settings...")
    for key in DEPRECATED_SETTINGS:
        setting = db.query(AppSetting).filter(AppSetting.key == key).first()
        if setting:
            logger.info(f"  Deleting: {key}")
            db.delete(setting)
            results["deleted"] += 1
        else:
            logger.info(f"  Not found (skipping): {key}")
            results["skipped"] += 1

    # Step 2: Create default function configs (if not present)
    logger.info("Step 2: Creating default function configs...")
    for key, config in DEFAULT_FUNCTION_CONFIGS.items():
        existing = db.query(AppSetting).filter(AppSetting.key == key).first()
        if existing:
            logger.info(f"  Already exists (skipping): {key}")
            results["skipped"] += 1
        else:
            logger.info(f"  Creating: {key}")
            new_setting = AppSetting(
                key=key,
                value=json.dumps(config),
                description=f"AI function configuration for {key.replace('ai_function_', '')}",
            )
            db.add(new_setting)
            results["created"] += 1

    # Step 3: Create new Bedrock settings (if not present)
    logger.info("Step 3: Creating Bedrock settings...")
    for key, setting_data in NEW_SETTINGS.items():
        existing = db.query(AppSetting).filter(AppSetting.key == key).first()
        if existing:
            logger.info(f"  Already exists (skipping): {key}")
            results["skipped"] += 1
        else:
            logger.info(f"  Creating: {key}")
            new_setting = AppSetting(
                key=key,
                value=setting_data["value"],
                description=setting_data["description"],
            )
            db.add(new_setting)
            results["created"] += 1

    # Commit all changes
    db.commit()

    return results


def main():
    """Main entry point for the migration script."""
    logger.info("=" * 60)
    logger.info("AI Provider Consolidation Migration")
    logger.info("=" * 60)
    logger.info("")
    logger.info("This migration consolidates AI providers to 4:")
    logger.info("  - OpenAI (GPT)")
    logger.info("  - Anthropic (Claude)")
    logger.info("  - Google (Gemini)")
    logger.info("  - Amazon Bedrock (Nova, Claude via Bedrock, Titan, etc.)")
    logger.info("")

    db = SessionLocal()
    try:
        results = run_migration(db)

        logger.info("")
        logger.info("=" * 60)
        logger.info("Migration Complete!")
        logger.info("=" * 60)
        logger.info(f"  Deleted:  {results['deleted']} deprecated settings")
        logger.info(f"  Created:  {results['created']} new settings")
        logger.info(f"  Skipped:  {results['skipped']} (already exist or not found)")
        logger.info("")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
