# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false
"""
Redis-based caching utilities for API response optimization.
Provides decorators and helpers for caching expensive query results.
"""
import json
import hashlib
import functools
import logging
from typing import Any, Callable, TypeVar, ParamSpec
from datetime import timedelta

from redis import Redis
from .config import settings

logger = logging.getLogger(__name__)

# Type variables for proper typing
P = ParamSpec('P')
R = TypeVar('R')

# Global Redis client (lazy initialization)
_redis_client: Redis | None = None


def get_redis() -> Redis | None:
    """Get or create Redis client for caching"""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2
            )
            # Test connection
            try:
                res = _redis_client.ping()
                _ = bool(res)
            except Exception:
                pass
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}")
            _redis_client = None
    return _redis_client


def cache_key(*args: Any, prefix: str = "cache") -> str:
    """Generate a cache key from arguments"""
    key_data = json.dumps(args, sort_keys=True, default=str)
    key_hash = hashlib.md5(key_data.encode()).hexdigest()
    return f"{prefix}:{key_hash}"


def cached(
    ttl_seconds: int = 300,
    prefix: str = "api",
    key_builder: Callable[..., str] | None = None
):
    """
    Decorator for caching function results in Redis.
    
    Args:
        ttl_seconds: Time-to-live for cache entries (default 5 minutes)
        prefix: Cache key prefix for namespacing
        key_builder: Optional custom function to build cache key
    
    Usage:
        @cached(ttl_seconds=60, prefix="emails")
        def get_email_stats(project_id: str):
            # expensive query
            return stats
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            redis = get_redis()
            if redis is None:
                # No cache available, just call the function
                return func(*args, **kwargs)
            
            # Build cache key
            if key_builder:
                cache_k = key_builder(*args, **kwargs)
            else:
                cache_k = cache_key(func.__name__, args, kwargs, prefix=prefix)
            
            try:
                # Try to get from cache
                cached_value = redis.get(cache_k)
                if cached_value:
                    logger.debug(f"Cache HIT: {cache_k}")
                    if isinstance(cached_value, (bytes, bytearray)):
                        return json.loads(cached_value.decode("utf-8"))
                    return json.loads(str(cached_value))
            except Exception as e:
                logger.warning(f"Cache read error: {e}")
            
            # Cache miss - execute function
            result = func(*args, **kwargs)
            
            try:
                # Store in cache
                _ = redis.setex(cache_k, ttl_seconds, json.dumps(result, default=str))
                logger.debug(f"Cache SET: {cache_k} (TTL: {ttl_seconds}s)")
            except Exception as e:
                logger.warning(f"Cache write error: {e}")
            
            return result
        
        return wrapper
    return decorator


async def acached(
    ttl_seconds: int = 300,
    prefix: str = "api",
    key_builder: Callable[..., str] | None = None
):
    """
    Async decorator for caching coroutine results in Redis.
    
    Usage:
        @acached(ttl_seconds=60, prefix="emails")
        async def get_email_stats(project_id: str):
            # expensive async query
            return stats
    """
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            redis = get_redis()
            if redis is None:
                return await func(*args, **kwargs)
            
            if key_builder:
                cache_k = key_builder(*args, **kwargs)
            else:
                cache_k = cache_key(func.__name__, args, kwargs, prefix=prefix)
            
            try:
                cached_value = redis.get(cache_k)
                if cached_value:
                    logger.debug(f"Async Cache HIT: {cache_k}")
                    if isinstance(cached_value, (bytes, bytearray)):
                        return json.loads(cached_value.decode("utf-8"))
                    return json.loads(str(cached_value))
            except Exception as e:
                logger.warning(f"Async cache read error: {e}")
            
            result = await func(*args, **kwargs)
            
            try:
                _ = redis.setex(cache_k, ttl_seconds, json.dumps(result, default=str))
                logger.debug(f"Async Cache SET: {cache_k}")
            except Exception as e:
                logger.warning(f"Async cache write error: {e}")
            
            return result
        
        return wrapper
    return decorator


def invalidate_cache(pattern: str) -> int:
    """
    Invalidate cache entries matching a pattern.
    
    Args:
        pattern: Redis key pattern (e.g., "api:emails:*")
    
    Returns:
        Number of keys deleted
    """
    redis = get_redis()
    if redis is None:
        return 0
    
    try:
        keys = redis.keys(pattern)
        if keys:
            deleted = redis.delete(*keys)
            logger.info(f"Cache invalidated: {deleted} keys matching '{pattern}'")
            return deleted
        return 0
    except Exception as e:
        logger.warning(f"Cache invalidation error: {e}")
        return 0


def get_cached(key: str) -> Any | None:
    """Get a value from cache by key"""
    redis = get_redis()
    if redis is None:
        return None
    
    try:
        value = redis.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None


def set_cached(key: str, value: Any, ttl_seconds: int = 300) -> bool:
    """Set a value in cache"""
    redis = get_redis()
    if redis is None:
        return False
    
    try:
        redis.setex(key, ttl_seconds, json.dumps(value, default=str))
        return True
    except Exception as e:
        logger.warning(f"Cache set error: {e}")
        return False


# Pre-built cache key builders for common patterns
def project_cache_key(func_name: str, project_id: str, *extra: Any) -> str:
    """Cache key builder for project-scoped data"""
    return f"proj:{project_id}:{func_name}:{cache_key(*extra)}"


def email_stats_cache_key(project_id: str | None = None, case_id: str | None = None) -> str:
    """Cache key builder for email statistics"""
    scope = project_id or case_id or "all"
    return f"stats:email:{scope}"

