"""
Initialize default application settings
Run this after database migration to create default settings
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from api.app.db import SessionLocal
from api.app.models import AppSetting


# Optimal AI model configurations per provider
# These are the best models for VeriCase's legal analysis use case
AI_OPTIMAL_MODELS = {
    "openai": {
        "model": "gpt-4o",
        "description": "OpenAI GPT-4o - Best for chronology & event analysis",
    },
    "anthropic": {
        "model": "claude-sonnet-4-20250514",
        "description": "Claude Sonnet 4 - Best for narrative construction",
    },
    "gemini": {
        "model": "gemini-2.0-flash",
        "description": "Gemini 2.0 Flash - Fast pattern recognition",
    },
    "bedrock": {
        "model": "amazon.nova-pro-v1:0",
        "description": "Amazon Nova Pro - Cost-effective enterprise AI",
    },
    "xai": {
        "model": "grok-3",
        "description": "xAI Grok 3 - Real-time analysis & reasoning",
    },
    "perplexity": {
        "model": "sonar-pro",
        "description": "Perplexity Sonar Pro - Research & web search",
    },
}

# Environment variable to setting key mapping
ENV_TO_SETTING = {
    "OPENAI_API_KEY": "openai_api_key",
    "CLAUDE_API_KEY": "anthropic_api_key",
    "GEMINI_API_KEY": "gemini_api_key",
    "XAI_API_KEY": "xai_api_key",
    "PERPLEXITY_API_KEY": "perplexity_api_key",
    "BEDROCK_ENABLED": "bedrock_enabled",
    "BEDROCK_REGION": "bedrock_region",
}


def init_default_settings():
    """Create default settings if they don't exist"""
    db = SessionLocal()
    try:
        default_settings = [
            {
                "key": "textract_page_threshold",
                "value": "100",
                "description": "PDFs with more pages than this threshold will use Tika instead of AWS Textract",
            },
            {
                "key": "textract_max_pages",
                "value": "500",
                "description": "Maximum number of pages Textract can process (AWS limit)",
            },
            # AI Default Provider
            {
                "key": "ai_default_provider",
                "value": "gemini",
                "description": "Default AI provider for quick operations (gemini is cost-effective)",
            },
            # AI Fallback settings
            {
                "key": "ai_fallback_enabled",
                "value": "true",
                "description": "Enable automatic fallback to other providers on failure",
            },
        ]

        for setting_data in default_settings:
            existing = (
                db.query(AppSetting)
                .filter(AppSetting.key == setting_data["key"])
                .first()
            )
            if not existing:
                setting = AppSetting(
                    key=setting_data["key"],
                    value=setting_data["value"],
                    description=setting_data["description"],
                )
                db.add(setting)
                print(
                    f"Created default setting: {setting_data['key']} = {setting_data['value']}"
                )
            else:
                print(f"Setting {setting_data['key']} already exists")

        db.commit()
        print("Default settings initialized successfully!")

    except Exception as e:
        print(f"Error initializing settings: {e}")
        db.rollback()
    finally:
        db.close()


def sync_ai_keys_from_env():
    """
    Sync AI API keys from environment variables to database.
    This allows keys from AWS Secrets Manager to be visible in admin UI.
    """
    db = SessionLocal()
    try:
        synced = 0

        # Sync API keys from environment
        for env_var, setting_key in ENV_TO_SETTING.items():
            env_value = os.environ.get(env_var)
            if env_value and env_value.strip():
                existing = (
                    db.query(AppSetting).filter(AppSetting.key == setting_key).first()
                )
                if not existing:
                    # Create new setting from env var
                    setting = AppSetting(
                        key=setting_key,
                        value=env_value.strip(),
                        description=f"Auto-synced from {env_var}",
                    )
                    db.add(setting)
                    print(f"✓ Synced {setting_key} from {env_var}")
                    synced += 1
                elif not existing.value:
                    # Update empty setting
                    existing.value = env_value.strip()
                    print(f"✓ Updated {setting_key} from {env_var}")
                    synced += 1

        # Set optimal models for providers that have API keys
        for provider, config in AI_OPTIMAL_MODELS.items():
            # Check if this provider has an API key configured
            key_setting = f"{provider}_api_key"
            has_key = (
                db.query(AppSetting)
                .filter(
                    AppSetting.key == key_setting,
                    AppSetting.value.isnot(None),
                    AppSetting.value != "",
                )
                .first()
            )

            # Also check Bedrock (uses IAM, not API key)
            if provider == "bedrock":
                bedrock_enabled = (
                    db.query(AppSetting)
                    .filter(
                        AppSetting.key == "bedrock_enabled", AppSetting.value == "true"
                    )
                    .first()
                )
                has_key = bedrock_enabled or os.environ.get("BEDROCK_ENABLED") == "true"

            if has_key or os.environ.get(f"{provider.upper()}_API_KEY"):
                model_key = f"{provider}_model"
                existing_model = (
                    db.query(AppSetting).filter(AppSetting.key == model_key).first()
                )
                if not existing_model:
                    setting = AppSetting(
                        key=model_key,
                        value=config["model"],
                        description=config["description"],
                    )
                    db.add(setting)
                    print(f"✓ Set optimal model for {provider}: {config['model']}")
                    synced += 1

        db.commit()
        if synced > 0:
            print(f"Successfully synced {synced} AI settings from environment")
        else:
            print("No new AI settings to sync")

    except Exception as e:
        print(f"Error syncing AI settings: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("Initializing VeriCase default settings...")
    init_default_settings()
    print("\nSyncing AI API keys from environment...")
    sync_ai_keys_from_env()
