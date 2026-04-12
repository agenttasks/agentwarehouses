"""Prompt caching types for the Anthropic Messages API.

Covers cache_control markers, usage breakdowns, and speculative-cache config.
See: anthropics/claude-cookbooks/misc/speculative_prompt_caching.ipynb
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from agentwarehouses.models.base import BaseModel


class CacheControl(BaseModel):
    """Anthropic cache_control block attached to content items."""

    type: Literal["ephemeral"] = "ephemeral"


class CacheableTextBlock(BaseModel):
    """Text content block with an optional cache_control marker."""

    type: Literal["text"] = "text"
    text: str
    cache_control: CacheControl | None = None


class CacheUsage(BaseModel):
    """Token usage breakdown including prompt-cache metrics.

    Returned by the Messages API when cache_control is present.
    """

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_creation_input_tokens: int = Field(0, ge=0)
    cache_read_input_tokens: int = Field(0, ge=0)

    @property
    def cache_hit(self) -> bool:
        """True when the response read tokens from a warm cache."""
        return self.cache_read_input_tokens > 0

    @property
    def total_input_tokens(self) -> int:
        """Sum of fresh + cached input tokens."""
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


class SpeculativeCacheConfig(BaseModel):
    """Configuration for the speculative prompt-caching pattern.

    The pattern sends a 1-token warmup request while the user is still
    typing, so the KV cache is hot when the real query arrives.
    """

    model: str = Field("claude-sonnet-4-6", description="Model ID for both warmup and query")
    system: str | None = Field(None, description="System prompt shared across warmup and query")
    max_tokens: int = Field(4096, ge=1, description="Max output tokens for the real query")
    warmup_max_tokens: int = Field(1, ge=1, le=1, description="Always 1 — minimal warmup request")
    temperature: float = Field(0.0, ge=0.0, le=2.0)
