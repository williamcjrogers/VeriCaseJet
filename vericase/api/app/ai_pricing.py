"""
Shared AI pricing and cost utilities.

This module is the single source of truth for token pricing across
metrics, registries, and routing cost heuristics.
All prices are approximate USD per 1M tokens.
"""

from __future__ import annotations


# Pricing per 1M tokens (input/output) in USD.
TOKEN_PRICING_PER_1M: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    "gpt-5.1": {"input": 5.00, "output": 20.00},
    # Anthropic direct
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-3-5-haiku-20241022": {"input": 0.25, "output": 1.25},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    # Gemini
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash-lite": {"input": 0.05, "output": 0.20},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # Bedrock (approximate blended rates)
    "amazon.nova-pro-v1:0": {"input": 0.80, "output": 3.20},
    "amazon.nova-lite-v1:0": {"input": 0.06, "output": 0.24},
    "amazon.nova-micro-v1:0": {"input": 0.035, "output": 0.14},
    "anthropic.claude-3-5-sonnet-20241022-v2:0": {"input": 3.00, "output": 15.00},
    "anthropic.claude-3-5-haiku-20241022-v1:0": {"input": 0.25, "output": 1.25},
    "anthropic.claude-sonnet-4-5-20250929-v1:0": {"input": 3.50, "output": 17.50},
    "anthropic.claude-opus-4-5-20251101-v1:0": {"input": 17.50, "output": 87.50},
    "anthropic.claude-haiku-4-5-20251001-v1:0": {"input": 0.30, "output": 1.50},
    "meta.llama3-3-70b-instruct-v1:0": {"input": 1.00, "output": 1.00},
    "mistral.mistral-large-2407-v1:0": {"input": 1.00, "output": 1.00},
    "cohere.command-r-plus": {"input": 2.00, "output": 8.00},
    "cohere.command-r": {"input": 1.00, "output": 4.00},
}


# Coarse cost tiers for balanced routing (1 cheapest, 5 most expensive).
COST_TIER_MAP: dict[str, int] = {
    "amazon.nova-micro-v1:0": 1,
    "amazon.nova-lite-v1:0": 1,
    "gemini-2.0-flash": 2,
    "gemini-2.0-flash-lite": 2,
    "gpt-4o-mini": 2,
    "claude-3-5-haiku-20241022": 2,
    "amazon.nova-pro-v1:0": 3,
    "gemini-1.5-pro": 3,
    "gpt-4o": 4,
    "claude-sonnet-4-20250514": 4,
    "anthropic.claude-3-5-sonnet-20241022-v2:0": 4,
    "o1": 5,
    "claude-opus-4-20250514": 5,
    "anthropic.claude-opus-4-5-20251101-v1:0": 5,
}


def get_cost_tier(model_id: str, default: int = 3) -> int:
    """Return a coarse cost tier for a model."""
    return COST_TIER_MAP.get(model_id, default)


def estimate_cost_usd(
    model_id: str,
    tokens_total: int,
    tokens_prompt: int | None = None,
    tokens_completion: int | None = None,
) -> float:
    """
    Estimate cost in USD.

    If prompt/completion split is provided, use directional pricing.
    Otherwise use an average blended rate.
    """
    pricing = TOKEN_PRICING_PER_1M.get(model_id)
    if not pricing:
        return (tokens_total / 1_000_000) * 1.0

    if tokens_prompt is not None and tokens_completion is not None:
        input_cost = (tokens_prompt / 1_000_000) * pricing["input"]
        output_cost = (tokens_completion / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    avg_rate = (pricing["input"] + pricing["output"]) / 2
    return (tokens_total / 1_000_000) * avg_rate

