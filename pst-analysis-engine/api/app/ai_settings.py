"""
AI Settings Manager - Loads AI configuration from database with fallback to environment variables
"""
import logging
from typing import Optional
from functools import lru_cache
from sqlalchemy.orm import Session

from .models import AppSetting
from .config import settings as env_settings

logger = logging.getLogger(__name__)


class AISettings:
    """
    Manages AI provider settings, loading from database with env var fallbacks.
    Settings are cached but can be refreshed on demand.
    """
    
    _cache: dict = {}
    _cache_valid: bool = False
    
    # Default models for each provider
    DEFAULT_MODELS = {
        'openai': 'gpt-4-turbo',
        'anthropic': 'claude-sonnet-4-20250514',
        'gemini': 'gemini-2.0-flash',
        'grok': 'grok-2-1212',
        'perplexity': 'pplx-7b-chat'
    }
    
    @classmethod
    def refresh_cache(cls, db: Session) -> None:
        """Reload all AI settings from database"""
        cls._cache = {}
        
        try:
            ai_settings = db.query(AppSetting).filter(
                AppSetting.key.like('openai_%') |
                AppSetting.key.like('anthropic_%') |
                AppSetting.key.like('gemini_%') |
                AppSetting.key.like('grok_%') |
                AppSetting.key.like('perplexity_%') |
                AppSetting.key.like('ai_%')
            ).all()
            
            for setting in ai_settings:
                cls._cache[setting.key] = setting.value
                
            cls._cache_valid = True
            logger.debug(f"AI settings cache refreshed with {len(cls._cache)} settings")
            
        except Exception as e:
            logger.warning(f"Failed to load AI settings from database: {e}")
            cls._cache_valid = False
    
    @classmethod
    def get(cls, key: str, db: Optional[Session] = None, default: Optional[str] = None) -> Optional[str]:
        """
        Get an AI setting value.
        Priority: Database > Environment Variable > Default
        """
        # Try cache first
        if cls._cache_valid and key in cls._cache:
            return cls._cache[key]
        
        # Try database if session provided
        if db is not None:
            try:
                setting = db.query(AppSetting).filter(AppSetting.key == key).first()
                if setting and setting.value:
                    cls._cache[key] = setting.value
                    return setting.value
            except Exception as e:
                logger.debug(f"Failed to get setting {key} from DB: {e}")
        
        # Try environment variable (map key to env var name)
        env_map = {
            'openai_api_key': 'OPENAI_API_KEY',
            'anthropic_api_key': 'CLAUDE_API_KEY',
            'gemini_api_key': 'GEMINI_API_KEY',
            'grok_api_key': 'GROK_API_KEY',
            'perplexity_api_key': 'PERPLEXITY_API_KEY',
        }
        
        env_var = env_map.get(key)
        if env_var:
            env_value = getattr(env_settings, env_var, None)
            if env_value:
                return env_value
        
        return default
    
    @classmethod
    def get_api_key(cls, provider: str, db: Optional[Session] = None) -> Optional[str]:
        """Get API key for a specific provider"""
        key = f"{provider}_api_key"
        return cls.get(key, db)
    
    @classmethod
    def get_model(cls, provider: str, db: Optional[Session] = None) -> str:
        """Get selected model for a specific provider"""
        key = f"{provider}_model"
        return cls.get(key, db) or cls.DEFAULT_MODELS.get(provider, '')
    
    @classmethod
    def get_default_provider(cls, db: Optional[Session] = None) -> str:
        """Get the default AI provider"""
        return cls.get('ai_default_provider', db) or 'gemini'
    
    @classmethod
    def is_web_search_enabled(cls, db: Optional[Session] = None) -> bool:
        """Check if web search is enabled for AI queries"""
        value = cls.get('ai_web_search_enabled', db)
        return value == 'true' if value else False
    
    @classmethod
    def get_all_configured_providers(cls, db: Optional[Session] = None) -> dict:
        """Get status of all AI providers"""
        providers = {
            'openai': {
                'name': 'OpenAI (GPT)',
                'available': bool(cls.get_api_key('openai', db)),
                'model': cls.get_model('openai', db),
                'task': 'Chronology & Event Analysis'
            },
            'anthropic': {
                'name': 'Anthropic (Claude)',
                'available': bool(cls.get_api_key('anthropic', db)),
                'model': cls.get_model('anthropic', db),
                'task': 'Narrative Construction'
            },
            'gemini': {
                'name': 'Google (Gemini)',
                'available': bool(cls.get_api_key('gemini', db)),
                'model': cls.get_model('gemini', db),
                'task': 'Pattern Recognition'
            },
            'grok': {
                'name': 'xAI (Grok)',
                'available': bool(cls.get_api_key('grok', db)),
                'model': cls.get_model('grok', db),
                'task': 'Gap Analysis'
            },
            'perplexity': {
                'name': 'Perplexity',
                'available': bool(cls.get_api_key('perplexity', db)),
                'model': cls.get_model('perplexity', db),
                'task': 'Evidence-Focused Queries'
            }
        }
        return providers


# Convenience functions for direct import
def get_ai_api_key(provider: str, db: Optional[Session] = None) -> Optional[str]:
    return AISettings.get_api_key(provider, db)

def get_ai_model(provider: str, db: Optional[Session] = None) -> str:
    return AISettings.get_model(provider, db)

def get_ai_providers_status(db: Optional[Session] = None) -> dict:
    return AISettings.get_all_configured_providers(db)

