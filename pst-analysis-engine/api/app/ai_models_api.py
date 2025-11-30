"""API endpoints for 2025 AI model management"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from .auth import get_current_user_email
from .models import AppSetting
from .db import get_db
from .ai_models_2025 import (
    AI_MODELS_2025, 
    MODEL_CATEGORIES, 
    COST_TIERS,
    get_all_models,
    get_models_by_provider,
    get_default_model,
    get_models_by_capability,
    get_reasoning_models,
    get_coding_models,
    get_search_models
)

router = APIRouter(prefix="/api/v1/ai-models", tags=["AI Models 2025"])

class ModelInfo(BaseModel):
    id: str
    name: str
    description: str
    provider: str
    type: str
    capabilities: List[str]
    context_window: int
    cost_tier: str
    deployment: Optional[str] = "api"
    is_default: bool = False

class ProviderConfig(BaseModel):
    provider: str
    models: List[ModelInfo]
    default_model: str
    api_key_configured: bool

class ModelSelectionRequest(BaseModel):
    provider: str
    model_id: str
    use_case: Optional[str] = None

@router.get("/providers")
async def list_providers(
    current_user_email: str = Depends(get_current_user_email),
    db: Session = Depends(get_db)
):
    """List all AI providers with their models and configuration status"""
    providers = []
    
    for provider_name, config in AI_MODELS_2025.items():
        # Check if API key is configured
        api_key_setting = None
        if provider_name == "openai":
            api_key_setting = db.query(AppSetting).filter(AppSetting.key == "openai_api_key").first()
        elif provider_name == "anthropic":
            api_key_setting = db.query(AppSetting).filter(AppSetting.key == "anthropic_api_key").first()
        elif provider_name == "google":
            api_key_setting = db.query(AppSetting).filter(AppSetting.key == "gemini_api_key").first()
        elif provider_name == "xai":
            api_key_setting = db.query(AppSetting).filter(AppSetting.key == "grok_api_key").first()
        elif provider_name == "perplexity":
            api_key_setting = db.query(AppSetting).filter(AppSetting.key == "perplexity_api_key").first()
        
        api_key_configured = bool(api_key_setting and api_key_setting.value)
        
        # Convert models to ModelInfo
        models = []
        default_model = config.get("default")
        
        for model in config["models"]:
            model_info = ModelInfo(
                id=model["id"],
                name=model["name"],
                description=model["description"],
                provider=provider_name,
                type=model["type"],
                capabilities=model["capabilities"],
                context_window=model["context_window"],
                cost_tier=model["cost_tier"],
                deployment=model.get("deployment", "api"),
                is_default=(model["id"] == default_model)
            )
            models.append(model_info)
        
        provider_config = ProviderConfig(
            provider=provider_name,
            models=models,
            default_model=default_model,
            api_key_configured=api_key_configured
        )
        providers.append(provider_config)
    
    return {
        "providers": providers,
        "categories": MODEL_CATEGORIES,
        "cost_tiers": COST_TIERS
    }

@router.get("/models")
async def list_all_models(
    capability: Optional[str] = None,
    cost_tier: Optional[str] = None,
    provider: Optional[str] = None,
    current_user_email: str = Depends(get_current_user_email)
):
    """List all available models with optional filtering"""
    models = get_all_models()
    
    # Apply filters
    if capability:
        models = [m for m in models if capability in m.get("capabilities", [])]
    
    if cost_tier:
        models = [m for m in models if m.get("cost_tier") == cost_tier]
    
    if provider:
        models = [m for m in models if m.get("provider") == provider]
    
    # Convert to ModelInfo objects
    model_infos = []
    for model in models:
        default_model = get_default_model(model["provider"])
        model_info = ModelInfo(
            id=model["id"],
            name=model["name"],
            description=model["description"],
            provider=model["provider"],
            type=model["type"],
            capabilities=model["capabilities"],
            context_window=model["context_window"],
            cost_tier=model["cost_tier"],
            deployment=model.get("deployment", "api"),
            is_default=(model["id"] == default_model)
        )
        model_infos.append(model_info)
    
    return {
        "models": model_infos,
        "total": len(model_infos),
        "filters_applied": {
            "capability": capability,
            "cost_tier": cost_tier,
            "provider": provider
        }
    }

@router.get("/reasoning")
async def get_reasoning_models_endpoint(current_user_email: str = Depends(get_current_user_email)):
    """Get all models optimized for reasoning tasks"""
    models = get_reasoning_models()
    return {
        "models": models,
        "description": "Models optimized for complex reasoning, analysis, and problem-solving",
        "recommended_for": ["legal analysis", "case research", "document analysis", "strategic planning"]
    }

@router.get("/coding")
async def get_coding_models_endpoint(current_user_email: str = Depends(get_current_user_email)):
    """Get all models optimized for coding tasks"""
    models = get_coding_models()
    return {
        "models": models,
        "description": "Models optimized for code generation, debugging, and technical tasks",
        "recommended_for": ["automation scripts", "data processing", "API integration", "technical documentation"]
    }

@router.get("/search")
async def get_search_models_endpoint(current_user_email: str = Depends(get_current_user_email)):
    """Get all models with web search capabilities"""
    models = get_search_models()
    return {
        "models": models,
        "description": "Models with real-time web search and research capabilities",
        "recommended_for": ["legal research", "case precedents", "current events", "fact checking"]
    }

@router.post("/select")
async def select_model(
    request: ModelSelectionRequest,
    current_user_email: str = Depends(get_current_user_email),
    db: Session = Depends(get_db)
):
    """Select a model as default for a provider"""
    # Validate model exists
    provider_models = get_models_by_provider(request.provider)
    model_exists = any(m["id"] == request.model_id for m in provider_models)
    
    if not model_exists:
        raise HTTPException(404, f"Model {request.model_id} not found for provider {request.provider}")
    
    # Update default model setting
    setting_key = f"{request.provider}_model"
    setting = db.query(AppSetting).filter(AppSetting.key == setting_key).first()
    
    if setting:
        setting.value = request.model_id
    else:
        setting = AppSetting(
            key=setting_key,
            value=request.model_id,
            description=f"Default {request.provider} model"
        )
        db.add(setting)
    
    db.commit()
    
    return {
        "success": True,
        "provider": request.provider,
        "selected_model": request.model_id,
        "use_case": request.use_case
    }

@router.get("/recommendations")
async def get_model_recommendations(
    use_case: str,
    current_user_email: str = Depends(get_current_user_email)
):
    """Get model recommendations for specific use cases"""
    recommendations = {
        "legal_analysis": {
            "primary": ["claude-opus-4.5", "gpt-5.1", "gemini-3.0-deep-think"],
            "budget": ["claude-sonnet-4.5", "grok-4.1-thinking"],
            "reasoning": "These models excel at complex legal reasoning and document analysis"
        },
        "document_review": {
            "primary": ["claude-sonnet-4.5", "gpt-5.1", "gemini-3.0-pro"],
            "budget": ["claude-haiku-4.5", "gemini-3.0-flash"],
            "reasoning": "Fast, accurate models for processing large volumes of documents"
        },
        "legal_research": {
            "primary": ["sonar-reasoning-pro", "sonar-pro", "gemini-3.0-deep-think"],
            "budget": ["sonar", "grok-4.1-thinking"],
            "reasoning": "Models with web access for finding current legal precedents and cases"
        },
        "contract_analysis": {
            "primary": ["claude-opus-4.5", "gpt-5.1", "o3"],
            "budget": ["claude-sonnet-4.5", "o3-mini"],
            "reasoning": "Specialized reasoning models for complex contract interpretation"
        },
        "automation": {
            "primary": ["gpt-5.1-codex-max", "claude-sonnet-4.5"],
            "budget": ["phi-4-reasoning", "gemini-3.0-flash"],
            "reasoning": "Coding-optimized models for building legal automation tools"
        },
        "cost_effective": {
            "primary": ["phi-4-reasoning", "phi-4-reasoning-plus", "claude-haiku-4.5"],
            "budget": ["phi-4-mini", "gemini-3.0-flash"],
            "reasoning": "High-quality models with lower costs for budget-conscious deployments"
        }
    }
    
    if use_case not in recommendations:
        available_cases = list(recommendations.keys())
        raise HTTPException(400, f"Use case '{use_case}' not supported. Available: {available_cases}")
    
    return {
        "use_case": use_case,
        "recommendations": recommendations[use_case],
        "all_use_cases": list(recommendations.keys())
    }

@router.get("/status")
async def get_models_status(
    current_user_email: str = Depends(get_current_user_email),
    db: Session = Depends(get_db)
):
    """Get overall status of AI model configuration"""
    status = {}
    
    for provider in AI_MODELS_2025.keys():
        # Check API key
        api_key_configured = False
        if provider == "openai":
            setting = db.query(AppSetting).filter(AppSetting.key == "openai_api_key").first()
        elif provider == "anthropic":
            setting = db.query(AppSetting).filter(AppSetting.key == "anthropic_api_key").first()
        elif provider == "google":
            setting = db.query(AppSetting).filter(AppSetting.key == "gemini_api_key").first()
        elif provider == "xai":
            setting = db.query(AppSetting).filter(AppSetting.key == "grok_api_key").first()
        elif provider == "perplexity":
            setting = db.query(AppSetting).filter(AppSetting.key == "perplexity_api_key").first()
        else:
            setting = None
        
        api_key_configured = bool(setting and setting.value)
        
        # Get default model
        default_model = get_default_model(provider)
        
        status[provider] = {
            "api_key_configured": api_key_configured,
            "default_model": default_model,
            "models_available": len(get_models_by_provider(provider)),
            "ready": api_key_configured or provider == "microsoft"  # Microsoft models are self-hosted
        }
    
    total_ready = sum(1 for s in status.values() if s["ready"])
    
    return {
        "providers": status,
        "summary": {
            "total_providers": len(status),
            "ready_providers": total_ready,
            "configuration_complete": total_ready > 0,
            "recommended_next_steps": [
                "Configure API keys for desired providers",
                "Select appropriate models for your use cases",
                "Test model performance with sample queries"
            ] if total_ready == 0 else []
        }
    }
