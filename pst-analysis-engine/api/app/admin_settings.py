from __future__ import annotations

"""
Admin settings management endpoints
Allows admins to modify application settings like Textract page threshold
Includes AI provider configuration for 4 providers: OpenAI, Anthropic, Gemini, Bedrock
"""
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import AppSetting, User, UserRole
from .security import current_user
from .ai_settings import (
    AISettings,
    get_ai_providers_status,
    get_function_config,
    is_bedrock_enabled,
    get_bedrock_region,
)
from .ai_models_2025 import AI_MODELS_2025, get_models_by_provider, get_provider_info
from .ai_providers import BedrockProvider, bedrock_available

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])

DbSession = Annotated[Session, Depends(get_db)]


class SettingResponse(BaseModel):
    key: str
    value: str
    description: str | None
    updated_at: str | None
    updated_by: str | None


class SettingUpdate(BaseModel):
    value: str
    description: str | None = None


def _require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    """Ensure user is an admin"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


AdminDep = Annotated[User, Depends(_require_admin)]


@router.get("", response_model=list[SettingResponse])
def list_settings(
    db: DbSession,
    admin: AdminDep,
):
    """List all application settings"""
    settings = db.query(AppSetting).order_by(AppSetting.key).all()
    return [
        SettingResponse(
            key=s.key,
            value=s.value,
            description=s.description,
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
            updated_by=str(s.updated_by) if s.updated_by else None,
        )
        for s in settings
    ]


@router.get("/{key}", response_model=SettingResponse)
def get_setting(
    key: str,
    db: DbSession,
    admin: AdminDep,
):
    """Get a specific setting by key"""
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return SettingResponse(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
        updated_by=str(setting.updated_by) if setting.updated_by else None,
    )


@router.put("/{key}", response_model=SettingResponse)
def update_setting(
    key: str,
    db: DbSession,
    admin: AdminDep,
    update: Annotated[SettingUpdate, Body(...)],
):
    """Update a setting (creates if doesn't exist)"""
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()

    if setting:
        setting.value = update.value
        if update.description is not None:
            setting.description = update.description
        setting.updated_by = admin.id
    else:
        setting = AppSetting(
            key=key,
            value=update.value,
            description=update.description,
            updated_by=admin.id,
        )
        db.add(setting)

    db.commit()
    db.refresh(setting)

    logger.info(f"Admin {admin.email} updated setting '{key}' to '{update.value}'")

    return SettingResponse(
        key=setting.key,
        value=setting.value,
        description=setting.description,
        updated_at=setting.updated_at.isoformat() if setting.updated_at else None,
        updated_by=str(setting.updated_by) if setting.updated_by else None,
    )


def get_setting_value(key: str, default: str, db: Session) -> str:
    """Helper function to get setting value from DB with fallback to default"""
    try:
        setting = db.query(AppSetting).filter(AppSetting.key == key).first()
        if setting:
            return setting.value
    except Exception as e:
        logger.debug(f"Failed to get setting '{key}' from DB: {e}")
    return default


# =============================================================================
# AI Provider Management Endpoints
# =============================================================================


class AIProviderStatus(BaseModel):
    """Status of an AI provider"""
    name: str
    available: bool
    model: str | None = None
    task: str | None = None
    region: str | None = None  # For Bedrock


class AIFunctionConfig(BaseModel):
    """Configuration for an AI function"""
    provider: str
    model: str
    thinking_enabled: bool = False
    thinking_budget_tokens: int | None = None
    max_duration_seconds: int = 30
    orchestration: dict[str, Any] | None = None


class AIFunctionConfigUpdate(BaseModel):
    """Update request for AI function config"""
    provider: str
    model: str
    thinking_enabled: bool = False
    thinking_budget_tokens: int | None = None
    max_duration_seconds: int = 30
    orchestration: dict[str, Any] | None = None


@router.get("/ai/providers")
def get_ai_providers(
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Get status of all AI providers (OpenAI, Anthropic, Gemini, Bedrock)
    """
    providers = get_ai_providers_status(db)

    # Add Bedrock-specific info
    if "bedrock" in providers:
        providers["bedrock"]["boto3_available"] = bedrock_available()

    return {
        "providers": providers,
        "supported_providers": ["openai", "anthropic", "gemini", "bedrock"],
    }


@router.get("/ai/models/{provider}")
def get_provider_models(
    provider: str,
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Get available models for a specific provider
    """
    if provider not in ["openai", "anthropic", "gemini", "bedrock"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {provider}. Supported: openai, anthropic, gemini, bedrock"
        )

    provider_info = get_provider_info(provider)
    models = get_models_by_provider(provider)

    return {
        "provider": provider,
        "info": provider_info,
        "models": models,
        "model_count": len(models),
    }


@router.get("/ai/models")
def get_all_ai_models(
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Get all available AI models grouped by provider
    """
    return {
        "providers": AI_MODELS_2025,
        "supported_providers": ["openai", "anthropic", "gemini", "bedrock"],
    }


@router.get("/ai/functions")
def get_ai_functions(
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Get configuration for all AI functions (quick_search, deep_analysis)
    """
    quick_search_config = get_function_config("quick_search", db)
    deep_analysis_config = get_function_config("deep_analysis", db)

    return {
        "functions": {
            "quick_search": quick_search_config,
            "deep_analysis": deep_analysis_config,
        },
        "available_functions": ["quick_search", "deep_analysis"],
    }


@router.get("/ai/functions/{function_name}")
def get_ai_function_config(
    function_name: str,
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Get configuration for a specific AI function
    """
    if function_name not in ["quick_search", "deep_analysis"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid function: {function_name}. Supported: quick_search, deep_analysis"
        )

    config = get_function_config(function_name, db)
    return {
        "function": function_name,
        "config": config,
    }


@router.put("/ai/functions/{function_name}")
def update_ai_function_config(
    function_name: str,
    db: DbSession,
    admin: AdminDep,
    config: Annotated[AIFunctionConfigUpdate, Body(...)],
) -> dict[str, Any]:
    """
    Update configuration for an AI function
    """
    if function_name not in ["quick_search", "deep_analysis"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid function: {function_name}. Supported: quick_search, deep_analysis"
        )

    # Validate provider
    if config.provider not in ["openai", "anthropic", "gemini", "bedrock"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {config.provider}"
        )

    # Build config dict
    config_dict: dict[str, Any] = {
        "provider": config.provider,
        "model": config.model,
        "thinking_enabled": config.thinking_enabled,
        "max_duration_seconds": config.max_duration_seconds,
    }

    if config.thinking_budget_tokens:
        config_dict["thinking_budget_tokens"] = config.thinking_budget_tokens

    if config.orchestration:
        config_dict["orchestration"] = config.orchestration

    # Save to database
    success = AISettings.set_function_config(function_name, config_dict, db)

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save function config for {function_name}"
        )

    logger.info(f"Admin {admin.email} updated AI function config for '{function_name}'")

    return {
        "success": True,
        "function": function_name,
        "config": config_dict,
    }


@router.post("/ai/bedrock/test")
async def test_bedrock_connection(
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Test Amazon Bedrock connection
    """
    if not bedrock_available():
        return {
            "success": False,
            "error": "boto3 not installed - Bedrock unavailable",
        }

    if not is_bedrock_enabled(db):
        return {
            "success": False,
            "error": "Bedrock not enabled in settings",
        }

    try:
        region = get_bedrock_region(db)
        provider = BedrockProvider(region=region)
        result = await provider.test_connection()
        return result
    except Exception as e:
        logger.error(f"Bedrock test failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }
