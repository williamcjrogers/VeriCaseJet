from __future__ import annotations

"""
Admin settings management endpoints
Allows admins to modify application settings like Textract page threshold
Includes AI provider configuration for runtime-supported providers (OpenAI, Anthropic, Gemini, Bedrock).
Additional providers may exist in the model registry but are not yet wired for execution.
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

RUNTIME_SUPPORTED_PROVIDERS = [
    "openai",
    "anthropic",
    "gemini",
    "bedrock",
    "xai",
    "perplexity",
]


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
    Get status of all runtime AI providers.
    """
    providers = get_ai_providers_status(db)

    # Add Bedrock-specific info
    if "bedrock" in providers:
        providers["bedrock"]["boto3_available"] = bedrock_available()

    return {
        "providers": providers,
        "supported_providers": RUNTIME_SUPPORTED_PROVIDERS,
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
    if provider not in RUNTIME_SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {provider}. Supported: {', '.join(RUNTIME_SUPPORTED_PROVIDERS)}",
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
        "supported_providers": RUNTIME_SUPPORTED_PROVIDERS,
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
            detail=f"Invalid function: {function_name}. Supported: quick_search, deep_analysis",
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
            detail=f"Invalid function: {function_name}. Supported: quick_search, deep_analysis",
        )

    # Validate provider
    if config.provider not in RUNTIME_SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {config.provider}. Supported: {', '.join(RUNTIME_SUPPORTED_PROVIDERS)}",
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
            detail=f"Failed to save function config for {function_name}",
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


class TestModelRequest(BaseModel):
    """Request to test a specific model"""

    model_id: str


@router.post("/ai/test-model/{provider}")
async def test_specific_model(
    provider: str,
    request: Annotated[TestModelRequest, Body(...)],
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Test a SPECIFIC model (not just the provider).
    Use this to verify the user has access to a particular model before configuring it.
    """
    import time

    if provider not in RUNTIME_SUPPORTED_PROVIDERS:
        return {
            "success": False,
            "error": f"Invalid provider: {provider}. Supported: {', '.join(RUNTIME_SUPPORTED_PROVIDERS)}",
        }

    model_id = request.model_id
    test_prompt = "Reply with just 'OK' to confirm you can access this model."
    start_time = time.time()

    try:
        from .ai_runtime import complete_chat
        from .ai_settings import get_ai_api_key

        api_key = get_ai_api_key(provider, db)

        if not api_key and provider != "bedrock":
            return {
                "success": False,
                "error": f"{provider.title()} API key not configured",
            }

        # Try to call the specific model
        response = await complete_chat(
            provider=provider,
            model_id=model_id,
            prompt=test_prompt,
            api_key=api_key,
            max_tokens=50,
            temperature=0.0,
        )

        elapsed = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "provider": provider,
            "model": model_id,
            "response_time_ms": elapsed,
            "response_preview": (response[:100] if response else "OK"),
            "message": f"Successfully connected to {model_id}",
        }

    except Exception as e:
        error_msg = str(e)

        # Parse common errors for better messages
        if (
            "does not have access" in error_msg.lower()
            or "model not found" in error_msg.lower()
        ):
            return {
                "success": False,
                "provider": provider,
                "model": model_id,
                "error": f"Your API key does not have access to model '{model_id}'. Check your OpenAI project permissions.",
                "error_type": "model_access",
            }
        elif (
            "invalid api key" in error_msg.lower()
            or "authentication" in error_msg.lower()
        ):
            return {
                "success": False,
                "provider": provider,
                "model": model_id,
                "error": "Invalid API key. Please check your credentials.",
                "error_type": "auth_error",
            }
        elif "rate limit" in error_msg.lower():
            return {
                "success": False,
                "provider": provider,
                "model": model_id,
                "error": "Rate limited. Please try again in a moment.",
                "error_type": "rate_limit",
            }
        else:
            return {
                "success": False,
                "provider": provider,
                "model": model_id,
                "error": error_msg,
                "error_type": "unknown",
            }


@router.get("/ai/fetch-models/{provider}")
async def fetch_available_models(
    provider: str,
    db: DbSession,
    admin: AdminDep,
) -> dict[str, Any]:
    """
    Fetch the list of models the user actually has access to from the provider's API.
    This queries the provider directly to discover available models.
    """
    from .ai_settings import get_ai_api_key

    if provider not in RUNTIME_SUPPORTED_PROVIDERS:
        return {
            "success": False,
            "error": f"Invalid provider: {provider}",
        }

    api_key = get_ai_api_key(provider, db)

    if not api_key and provider != "bedrock":
        return {
            "success": False,
            "error": f"{provider.title()} API key not configured",
            "models": [],
        }

    try:
        if provider == "openai":
            return await _fetch_openai_models(api_key)
        elif provider == "anthropic":
            # Anthropic doesn't have a models list API, return known models
            return {
                "success": True,
                "provider": "anthropic",
                "models": [
                    {
                        "id": "claude-sonnet-4-20250514",
                        "name": "Claude Sonnet 4",
                        "type": "flagship",
                    },
                    {
                        "id": "claude-opus-4-20250514",
                        "name": "Claude Opus 4",
                        "type": "premium",
                    },
                    {
                        "id": "claude-3-5-sonnet-20241022",
                        "name": "Claude 3.5 Sonnet",
                        "type": "flagship",
                    },
                    {
                        "id": "claude-3-5-haiku-20241022",
                        "name": "Claude 3.5 Haiku",
                        "type": "fast",
                    },
                    {
                        "id": "claude-3-opus-20240229",
                        "name": "Claude 3 Opus",
                        "type": "premium",
                    },
                ],
                "note": "Anthropic doesn't provide a models list API. These are known models - test to verify access.",
            }
        elif provider == "gemini":
            return await _fetch_gemini_models(api_key)
        elif provider == "bedrock":
            return await _fetch_bedrock_models(db)
        elif provider == "xai":
            return await _fetch_xai_models(api_key)
        elif provider == "perplexity":
            return await _fetch_perplexity_models(api_key)
        else:
            return {"success": False, "error": f"Unknown provider: {provider}"}

    except Exception as e:
        logger.error(f"Failed to fetch models for {provider}: {e}")
        return {
            "success": False,
            "error": str(e),
            "models": [],
        }


async def _fetch_openai_models(api_key: str) -> dict[str, Any]:
    """Fetch available models from OpenAI API"""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"OpenAI API error: {response.status_code} - {response.text}",
                "models": [],
            }

        data = response.json()
        models = data.get("data", [])

        # Filter to chat/completion models, sorted by ID
        chat_models = []
        for m in models:
            model_id = m.get("id", "")
            # Include GPT models and o1/o3 reasoning models
            if any(
                prefix in model_id
                for prefix in ["gpt-4", "gpt-3.5", "gpt-5", "o1", "o3"]
            ):
                chat_models.append(
                    {
                        "id": model_id,
                        "name": model_id,
                        "owned_by": m.get("owned_by", "openai"),
                        "created": m.get("created"),
                    }
                )

        # Sort by ID (newer models first)
        chat_models.sort(key=lambda x: x["id"], reverse=True)

        return {
            "success": True,
            "provider": "openai",
            "models": chat_models,
            "total_models": len(models),
            "chat_models": len(chat_models),
        }


async def _fetch_gemini_models(api_key: str) -> dict[str, Any]:
    """Fetch available models from Google AI API"""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
            timeout=30.0,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Gemini API error: {response.status_code}",
                "models": [],
            }

        data = response.json()
        models = data.get("models", [])

        # Filter to generative models
        generative_models = []
        for m in models:
            name = m.get("name", "")
            if "generateContent" in m.get("supportedGenerationMethods", []):
                model_id = name.replace("models/", "")
                generative_models.append(
                    {
                        "id": model_id,
                        "name": m.get("displayName", model_id),
                        "description": m.get("description", ""),
                    }
                )

        return {
            "success": True,
            "provider": "gemini",
            "models": generative_models,
        }


async def _fetch_bedrock_models(db: Session) -> dict[str, Any]:
    """Fetch available models from AWS Bedrock"""
    if not bedrock_available():
        return {
            "success": False,
            "error": "boto3 not installed",
            "models": [],
        }

    try:
        import boto3

        region = get_bedrock_region(db)
        client = boto3.client("bedrock", region_name=region)

        response = client.list_foundation_models()
        models = response.get("modelSummaries", [])

        # Filter to text generation models
        text_models = []
        for m in models:
            if "TEXT" in m.get("outputModalities", []):
                text_models.append(
                    {
                        "id": m.get("modelId"),
                        "name": m.get("modelName"),
                        "provider": m.get("providerName"),
                    }
                )

        return {
            "success": True,
            "provider": "bedrock",
            "region": region,
            "models": text_models,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "models": [],
        }


async def _fetch_xai_models(api_key: str) -> dict[str, Any]:
    """Fetch available models from xAI (Grok) - OpenAI-compatible /models endpoint"""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"xAI API error: {response.status_code} - {response.text}",
                "models": [],
            }

        data = response.json()
        models = data.get("data", [])
        chat_models = [
            {
                "id": m.get("id", ""),
                "name": m.get("id", ""),
                "owned_by": m.get("owned_by", "xai"),
            }
            for m in models
            if isinstance(m, dict) and m.get("id")
        ]
        chat_models.sort(key=lambda x: x["id"], reverse=True)

        return {
            "success": True,
            "provider": "xai",
            "models": chat_models,
            "total_models": len(models),
        }


async def _fetch_perplexity_models(api_key: str) -> dict[str, Any]:
    """Fetch available models from Perplexity - OpenAI-compatible /models endpoint"""
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.perplexity.ai/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

        if response.status_code != 200:
            return {
                "success": False,
                "error": f"Perplexity API error: {response.status_code} - {response.text}",
                "models": [],
            }

        data = response.json()
        models = data.get("data", [])
        chat_models = [
            {
                "id": m.get("id", ""),
                "name": m.get("id", ""),
                "owned_by": m.get("owned_by", "perplexity"),
            }
            for m in models
            if isinstance(m, dict) and m.get("id")
        ]
        chat_models.sort(key=lambda x: x["id"], reverse=True)

        return {
            "success": True,
            "provider": "perplexity",
            "models": chat_models,
            "total_models": len(models),
        }
