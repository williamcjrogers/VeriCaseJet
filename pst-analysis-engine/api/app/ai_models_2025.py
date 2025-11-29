"""2025 AI Model Configurations for VeriCase"""

# Latest AI Models - Updated January 2025
AI_MODELS_2025 = {
    "openai": {
        "models": [
            {
                "id": "gpt-5.1",
                "name": "GPT-5.1",
                "description": "Flagship general model with advanced reasoning",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "code", "analysis"],
                "context_window": 200000,
                "cost_tier": "premium"
            },
            {
                "id": "gpt-5.1-codex-max",
                "name": "GPT-5.1 Codex Max",
                "description": "Frontier coding and agentic model",
                "type": "coding",
                "capabilities": ["code", "agents", "reasoning", "analysis"],
                "context_window": 200000,
                "cost_tier": "premium"
            },
            {
                "id": "o3",
                "name": "o3",
                "description": "Dedicated reasoning model",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "problem_solving"],
                "context_window": 128000,
                "cost_tier": "premium"
            },
            {
                "id": "o3-mini",
                "name": "o3-mini",
                "description": "Fast reasoning model",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard"
            }
        ],
        "default": "gpt-5.1"
    },
    
    "anthropic": {
        "models": [
            {
                "id": "claude-opus-4.5",
                "name": "Claude Opus 4.5",
                "description": "Highest-end Claude model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "analysis", "code", "research"],
                "context_window": 200000,
                "cost_tier": "premium"
            },
            {
                "id": "claude-sonnet-4.5",
                "name": "Claude Sonnet 4.5",
                "description": "Main workhorse model",
                "type": "workhorse",
                "capabilities": ["chat", "reasoning", "analysis", "code"],
                "context_window": 200000,
                "cost_tier": "standard"
            },
            {
                "id": "claude-haiku-4.5",
                "name": "Claude Haiku 4.5",
                "description": "Fast, lightweight model",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 200000,
                "cost_tier": "budget"
            }
        ],
        "default": "claude-sonnet-4.5"
    },
    
    "google": {
        "models": [
            {
                "id": "gemini-3.0-pro",
                "name": "Gemini 3.0 Pro",
                "description": "New flagship multimodal model",
                "type": "flagship",
                "capabilities": ["chat", "reasoning", "multimodal", "analysis", "code"],
                "context_window": 2000000,
                "cost_tier": "premium"
            },
            {
                "id": "gemini-3.0-flash",
                "name": "Gemini 3.0 Flash",
                "description": "Fast, low-latency variant",
                "type": "fast",
                "capabilities": ["chat", "analysis", "multimodal"],
                "context_window": 1000000,
                "cost_tier": "standard"
            },
            {
                "id": "gemini-3.0-deep-think",
                "name": "Gemini 3.0 Deep Think",
                "description": "Extended-reasoning mode of 3.0 Pro",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "research"],
                "context_window": 2000000,
                "cost_tier": "premium"
            }
        ],
        "default": "gemini-3.0-pro"
    },
    
    "xai": {
        "models": [
            {
                "id": "grok-4.1-thinking",
                "name": "Grok 4.1 (Thinking)",
                "description": "Reasoning/chain-of-thought variant",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "research"],
                "context_window": 128000,
                "cost_tier": "standard"
            },
            {
                "id": "grok-4.1",
                "name": "Grok 4.1 (Non-Thinking)",
                "description": "Fast chat variant",
                "type": "fast",
                "capabilities": ["chat", "analysis"],
                "context_window": 128000,
                "cost_tier": "standard"
            }
        ],
        "default": "grok-4.1"
    },
    
    "perplexity": {
        "models": [
            {
                "id": "sonar-pro",
                "name": "Sonar Pro",
                "description": "Advanced web-grounded search model",
                "type": "search",
                "capabilities": ["search", "research", "analysis", "web_access"],
                "context_window": 127000,
                "cost_tier": "premium"
            },
            {
                "id": "sonar",
                "name": "Sonar",
                "description": "Default, faster search model",
                "type": "search",
                "capabilities": ["search", "analysis", "web_access"],
                "context_window": 127000,
                "cost_tier": "standard"
            },
            {
                "id": "sonar-reasoning-pro",
                "name": "Sonar Reasoning Pro",
                "description": "Deep-research / reasoning model",
                "type": "reasoning",
                "capabilities": ["reasoning", "research", "analysis", "web_access"],
                "context_window": 127000,
                "cost_tier": "premium"
            }
        ],
        "default": "sonar-pro"
    },
    
    "microsoft": {
        "models": [
            {
                "id": "phi-4-reasoning",
                "name": "Phi-4-Reasoning",
                "description": "14B open-weight reasoning SLM",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "code"],
                "context_window": 16000,
                "cost_tier": "free",
                "deployment": "self_hosted"
            },
            {
                "id": "phi-4-reasoning-plus",
                "name": "Phi-4-Reasoning-Plus",
                "description": "RL-tuned, higher-accuracy variant",
                "type": "reasoning",
                "capabilities": ["reasoning", "analysis", "code"],
                "context_window": 16000,
                "cost_tier": "free",
                "deployment": "self_hosted"
            },
            {
                "id": "phi-4-mini-reasoning",
                "name": "Phi-4-Mini-Reasoning",
                "description": "Small on-device reasoning model",
                "type": "mini",
                "capabilities": ["reasoning", "analysis"],
                "context_window": 8000,
                "cost_tier": "free",
                "deployment": "self_hosted"
            },
            {
                "id": "phi-4-mini",
                "name": "Phi-4-Mini",
                "description": "Small on-device model",
                "type": "mini",
                "capabilities": ["chat", "analysis"],
                "context_window": 8000,
                "cost_tier": "free",
                "deployment": "self_hosted"
            }
        ],
        "default": "phi-4-reasoning"
    }
}

# Model categories for UI organization
MODEL_CATEGORIES = {
    "flagship": "🚀 Flagship Models",
    "workhorse": "⚡ Workhorse Models", 
    "reasoning": "🧠 Reasoning Models",
    "fast": "💨 Fast Models",
    "coding": "💻 Coding Models",
    "search": "🔍 Search Models",
    "mini": "📱 Mini Models"
}

# Cost tiers
COST_TIERS = {
    "free": {"label": "Free", "color": "green"},
    "budget": {"label": "Budget", "color": "blue"},
    "standard": {"label": "Standard", "color": "orange"},
    "premium": {"label": "Premium", "color": "red"}
}

def get_all_models():
    """Get all available models across all providers"""
    all_models = []
    for provider, config in AI_MODELS_2025.items():
        for model in config["models"]:
            model_info = model.copy()
            model_info["provider"] = provider
            all_models.append(model_info)
    return all_models

def get_models_by_provider(provider: str):
    """Get models for a specific provider"""
    return AI_MODELS_2025.get(provider, {}).get("models", [])

def get_default_model(provider: str):
    """Get default model for a provider"""
    return AI_MODELS_2025.get(provider, {}).get("default")

def get_models_by_capability(capability: str):
    """Get all models that support a specific capability"""
    matching_models = []
    for provider, config in AI_MODELS_2025.items():
        for model in config["models"]:
            if capability in model.get("capabilities", []):
                model_info = model.copy()
                model_info["provider"] = provider
                matching_models.append(model_info)
    return matching_models

def get_reasoning_models():
    """Get all models optimized for reasoning"""
    return get_models_by_capability("reasoning")

def get_coding_models():
    """Get all models optimized for coding"""
    return get_models_by_capability("code")

def get_search_models():
    """Get all models with web search capabilities"""
    return get_models_by_capability("web_access")