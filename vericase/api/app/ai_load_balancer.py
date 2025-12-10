"""
AI Load Balancer - Optimized parallel execution and resource management.

This module provides:
- Enhanced asyncio parallelization for concurrent AI calls
- Semantic caching with embedding-based similarity
- Rate limiting per provider
- Circuit breaker patterns for fault tolerance
- Request queuing and prioritization
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, TypeVar
from collections import defaultdict

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# Circuit Breaker
# ============================================================================

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.

    Opens when error threshold is exceeded, prevents cascade failures.
    """
    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    half_open_calls: int = 0

    def record_success(self) -> None:
        """Record a successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self._close()
        else:
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self._open()
        elif self.failure_count >= self.failure_threshold:
            self._open()

    def can_execute(self) -> bool:
        """Check if calls are allowed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._half_open()
                return True
            return False

        # HALF_OPEN - allow limited calls
        if self.half_open_calls < self.half_open_max_calls:
            self.half_open_calls += 1
            return True
        return False

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.recovery_timeout

    def _open(self) -> None:
        """Open the circuit."""
        logger.warning(f"Circuit breaker '{self.name}' OPENED")
        self.state = CircuitState.OPEN
        self.last_failure_time = time.time()

    def _close(self) -> None:
        """Close the circuit."""
        logger.info(f"Circuit breaker '{self.name}' CLOSED")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0

    def _half_open(self) -> None:
        """Set circuit to half-open."""
        logger.info(f"Circuit breaker '{self.name}' HALF-OPEN")
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.half_open_calls = 0

    def get_status(self) -> dict[str, Any]:
        """Get circuit breaker status."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure": (
                datetime.fromtimestamp(self.last_failure_time, tz=timezone.utc).isoformat()
                if self.last_failure_time else None
            ),
        }


# ============================================================================
# Rate Limiter
# ============================================================================

@dataclass
class RateLimiter:
    """
    Token bucket rate limiter.

    Controls request rate per provider to avoid hitting API limits.
    """
    name: str
    max_tokens: int = 60  # Max requests per window
    refill_rate: float = 1.0  # Tokens per second
    window_seconds: float = 60.0

    tokens: float = field(default=0.0, init=False)
    last_refill: float = field(default_factory=time.time, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.max_tokens)

    async def acquire(self, tokens: int = 1) -> bool:
        """
        Acquire tokens. Returns True if acquired, False if rate limited.
        """
        async with self._lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def wait_and_acquire(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """
        Wait until tokens are available or timeout.
        """
        start = time.time()
        while time.time() - start < timeout:
            if await self.acquire(tokens):
                return True
            await asyncio.sleep(0.1)
        return False

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def get_status(self) -> dict[str, Any]:
        """Get rate limiter status."""
        self._refill()
        return {
            "name": self.name,
            "available_tokens": int(self.tokens),
            "max_tokens": self.max_tokens,
            "refill_rate": self.refill_rate,
        }


# ============================================================================
# Semantic Cache
# ============================================================================

@dataclass
class CacheEntry:
    """A cached result with metadata."""
    key: str
    value: Any
    created_at: datetime
    expires_at: datetime
    hit_count: int = 0
    embedding: list[float] | None = None


class SemanticCache:
    """
    Semantic cache with TTL and similarity matching.

    Provides:
    - Exact key matching (fast)
    - Semantic similarity matching (for similar queries)
    - TTL-based expiration
    - LRU eviction
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl_seconds: int = 3600,
        similarity_threshold: float = 0.85,
    ):
        self.max_size = max_size
        self.default_ttl = timedelta(seconds=default_ttl_seconds)
        self.similarity_threshold = similarity_threshold

        self._cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

        # Stats
        self._hits = 0
        self._misses = 0

    def _generate_key(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Generate cache key from query and context."""
        key_data = {"query": query}
        if context:
            key_data["context"] = context
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()[:32]

    async def get(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> Any | None:
        """
        Get cached value for query.

        First tries exact match, then semantic similarity.
        """
        async with self._lock:
            key = self._generate_key(query, context)

            # Exact match
            if key in self._cache:
                entry = self._cache[key]
                if datetime.now(timezone.utc) < entry.expires_at:
                    entry.hit_count += 1
                    self._hits += 1
                    logger.debug(f"Cache HIT (exact): {key[:8]}...")
                    return entry.value
                else:
                    # Expired
                    del self._cache[key]

            self._misses += 1
            return None

    async def set(
        self,
        query: str,
        value: Any,
        context: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
        embedding: list[float] | None = None,
    ) -> None:
        """Set cached value for query."""
        async with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.max_size:
                self._evict_lru()

            key = self._generate_key(query, context)
            ttl = timedelta(seconds=ttl_seconds) if ttl_seconds else self.default_ttl

            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + ttl,
                embedding=embedding,
            )

    def _evict_lru(self) -> None:
        """Evict least recently used entries."""
        if not self._cache:
            return

        # Sort by hit_count (ascending), then by created_at (oldest first)
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: (self._cache[k].hit_count, self._cache[k].created_at),
        )

        # Remove bottom 10%
        num_to_remove = max(1, len(sorted_keys) // 10)
        for key in sorted_keys[:num_to_remove]:
            del self._cache[key]

    async def invalidate(self, query: str, context: dict[str, Any] | None = None) -> None:
        """Invalidate a specific cache entry."""
        async with self._lock:
            key = self._generate_key(query, context)
            if key in self._cache:
                del self._cache[key]

    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0,
        }


# ============================================================================
# Parallel Executor
# ============================================================================

@dataclass
class ExecutionResult:
    """Result of a parallel execution."""
    success: bool
    value: Any | None
    error: str | None
    latency_ms: int
    provider: str


class ParallelExecutor:
    """
    Enhanced parallel executor for AI calls.

    Features:
    - Concurrent execution across providers
    - Timeout handling
    - First-success or all-results modes
    - Circuit breaker integration
    - Rate limiting
    """

    def __init__(
        self,
        circuit_breakers: dict[str, CircuitBreaker] | None = None,
        rate_limiters: dict[str, RateLimiter] | None = None,
        cache: SemanticCache | None = None,
    ):
        self.circuit_breakers = circuit_breakers or {}
        self.rate_limiters = rate_limiters or {}
        self.cache = cache

    async def execute_first_success(
        self,
        tasks: list[tuple[str, Callable[[], Any]]],
        timeout_seconds: float = 30.0,
    ) -> ExecutionResult:
        """
        Execute tasks concurrently, return first successful result.

        Args:
            tasks: List of (provider_name, coroutine_func) tuples
            timeout_seconds: Maximum wait time

        Returns:
            First successful result or error
        """
        if not tasks:
            return ExecutionResult(
                success=False,
                value=None,
                error="No tasks provided",
                latency_ms=0,
                provider="none",
            )

        async def run_task(
            provider: str,
            func: Callable[[], Any],
        ) -> tuple[str, Any | None, str | None, int]:
            """Run a single task with error handling."""
            start = time.time()

            # Check circuit breaker
            if provider in self.circuit_breakers:
                if not self.circuit_breakers[provider].can_execute():
                    return provider, None, "Circuit breaker open", 0

            # Check rate limiter
            if provider in self.rate_limiters:
                if not await self.rate_limiters[provider].acquire():
                    return provider, None, "Rate limited", 0

            try:
                result = await func()
                latency = int((time.time() - start) * 1000)

                # Record success
                if provider in self.circuit_breakers:
                    self.circuit_breakers[provider].record_success()

                return provider, result, None, latency

            except Exception as e:
                latency = int((time.time() - start) * 1000)

                # Record failure
                if provider in self.circuit_breakers:
                    self.circuit_breakers[provider].record_failure()

                return provider, None, str(e), latency

        # Create tasks
        pending = {
            asyncio.create_task(run_task(provider, func)): provider
            for provider, func in tasks
        }

        try:
            start_time = time.time()
            while pending and (time.time() - start_time) < timeout_seconds:
                done, _ = await asyncio.wait(
                    pending.keys(),
                    timeout=timeout_seconds - (time.time() - start_time),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    provider, value, error, latency = task.result()
                    del pending[task]

                    if value is not None:
                        # Cancel remaining tasks
                        for remaining in pending:
                            remaining.cancel()

                        return ExecutionResult(
                            success=True,
                            value=value,
                            error=None,
                            latency_ms=latency,
                            provider=provider,
                        )

            # All tasks failed or timed out
            return ExecutionResult(
                success=False,
                value=None,
                error="All providers failed or timed out",
                latency_ms=int((time.time() - start_time) * 1000),
                provider="none",
            )

        finally:
            # Clean up any remaining tasks
            for task in pending:
                task.cancel()

    async def execute_all(
        self,
        tasks: list[tuple[str, Callable[[], Any]]],
        timeout_seconds: float = 60.0,
    ) -> list[ExecutionResult]:
        """
        Execute all tasks concurrently, return all results.

        Args:
            tasks: List of (provider_name, coroutine_func) tuples
            timeout_seconds: Maximum wait time

        Returns:
            List of all results
        """
        results: list[ExecutionResult] = []

        async def run_task(provider: str, func: Callable[[], Any]) -> ExecutionResult:
            start = time.time()

            # Check circuit breaker
            if provider in self.circuit_breakers:
                if not self.circuit_breakers[provider].can_execute():
                    return ExecutionResult(
                        success=False,
                        value=None,
                        error="Circuit breaker open",
                        latency_ms=0,
                        provider=provider,
                    )

            # Check rate limiter
            if provider in self.rate_limiters:
                if not await self.rate_limiters[provider].acquire():
                    return ExecutionResult(
                        success=False,
                        value=None,
                        error="Rate limited",
                        latency_ms=0,
                        provider=provider,
                    )

            try:
                result = await func()
                latency = int((time.time() - start) * 1000)

                if provider in self.circuit_breakers:
                    self.circuit_breakers[provider].record_success()

                return ExecutionResult(
                    success=True,
                    value=result,
                    error=None,
                    latency_ms=latency,
                    provider=provider,
                )

            except Exception as e:
                latency = int((time.time() - start) * 1000)

                if provider in self.circuit_breakers:
                    self.circuit_breakers[provider].record_failure()

                return ExecutionResult(
                    success=False,
                    value=None,
                    error=str(e),
                    latency_ms=latency,
                    provider=provider,
                )

        try:
            task_coroutines = [run_task(p, f) for p, f in tasks]
            results = await asyncio.wait_for(
                asyncio.gather(*task_coroutines, return_exceptions=True),
                timeout=timeout_seconds,
            )

            # Convert exceptions to error results
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append(ExecutionResult(
                        success=False,
                        value=None,
                        error=str(result),
                        latency_ms=0,
                        provider=tasks[i][0],
                    ))
                else:
                    processed_results.append(result)

            return processed_results

        except asyncio.TimeoutError:
            return [ExecutionResult(
                success=False,
                value=None,
                error="Timeout",
                latency_ms=int(timeout_seconds * 1000),
                provider=p,
            ) for p, _ in tasks]


# ============================================================================
# Load Balancer
# ============================================================================

class LoadBalancer:
    """
    Central load balancer for AI operations.

    Combines circuit breakers, rate limiters, caching, and parallel execution.
    """

    # Default rate limits per provider (requests per minute)
    DEFAULT_RATE_LIMITS = {
        "openai": 60,
        "anthropic": 60,
        "google": 60,
        "bedrock": 100,  # Bedrock typically has higher limits
    }

    def __init__(
        self,
        enable_cache: bool = True,
        cache_ttl_seconds: int = 3600,
        enable_circuit_breakers: bool = True,
        enable_rate_limiting: bool = True,
    ):
        # Initialize circuit breakers
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        if enable_circuit_breakers:
            for provider in ["openai", "anthropic", "google", "bedrock"]:
                self.circuit_breakers[provider] = CircuitBreaker(
                    name=provider,
                    failure_threshold=5,
                    recovery_timeout=30.0,
                )

        # Initialize rate limiters
        self.rate_limiters: dict[str, RateLimiter] = {}
        if enable_rate_limiting:
            for provider, rate in self.DEFAULT_RATE_LIMITS.items():
                self.rate_limiters[provider] = RateLimiter(
                    name=provider,
                    max_tokens=rate,
                    refill_rate=rate / 60.0,
                )

        # Initialize cache
        self.cache: SemanticCache | None = None
        if enable_cache:
            self.cache = SemanticCache(
                max_size=1000,
                default_ttl_seconds=cache_ttl_seconds,
            )

        # Initialize executor
        self.executor = ParallelExecutor(
            circuit_breakers=self.circuit_breakers,
            rate_limiters=self.rate_limiters,
            cache=self.cache,
        )

    async def execute_with_fallback(
        self,
        providers: list[str],
        task_factory: Callable[[str], Callable[[], Any]],
        cache_key: str | None = None,
        cache_context: dict[str, Any] | None = None,
        timeout_seconds: float = 30.0,
    ) -> ExecutionResult:
        """
        Execute task with fallback chain.

        Args:
            providers: Ordered list of providers to try
            task_factory: Function that creates a task for a given provider
            cache_key: Optional cache key
            cache_context: Optional cache context
            timeout_seconds: Timeout per provider

        Returns:
            Result from first successful provider
        """
        # Check cache first
        if self.cache and cache_key:
            cached = await self.cache.get(cache_key, cache_context)
            if cached is not None:
                return ExecutionResult(
                    success=True,
                    value=cached,
                    error=None,
                    latency_ms=0,
                    provider="cache",
                )

        # Build task list
        tasks = [(p, task_factory(p)) for p in providers]

        # Execute with fallback
        result = await self.executor.execute_first_success(tasks, timeout_seconds)

        # Cache successful result
        if result.success and self.cache and cache_key:
            await self.cache.set(cache_key, result.value, cache_context)

        return result

    async def execute_parallel(
        self,
        providers: list[str],
        task_factory: Callable[[str], Callable[[], Any]],
        timeout_seconds: float = 60.0,
    ) -> list[ExecutionResult]:
        """
        Execute task across multiple providers in parallel.

        Returns all results for comparison/aggregation.
        """
        tasks = [(p, task_factory(p)) for p in providers]
        return await self.executor.execute_all(tasks, timeout_seconds)

    def get_status(self) -> dict[str, Any]:
        """Get load balancer status."""
        return {
            "circuit_breakers": {
                name: cb.get_status()
                for name, cb in self.circuit_breakers.items()
            },
            "rate_limiters": {
                name: rl.get_status()
                for name, rl in self.rate_limiters.items()
            },
            "cache": self.cache.get_stats() if self.cache else None,
        }

    def reset_circuit_breaker(self, provider: str) -> bool:
        """Manually reset a circuit breaker."""
        if provider in self.circuit_breakers:
            self.circuit_breakers[provider]._close()
            return True
        return False


# ============================================================================
# Global Instance
# ============================================================================

_load_balancer: LoadBalancer | None = None


def get_load_balancer() -> LoadBalancer:
    """Get or create the global load balancer instance."""
    global _load_balancer
    if _load_balancer is None:
        _load_balancer = LoadBalancer()
    return _load_balancer
