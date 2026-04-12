"""Speculative prompt caching for the Anthropic Messages API.

Reduces time-to-first-token (TTFT) by warming the server-side KV cache
while users formulate their queries.  The pattern:

1. Mark large, reusable context with ``cache_control: {"type": "ephemeral"}``.
2. Fire a 1-token "warmup" request as soon as the context is known.
3. When the real query arrives the cache is already hot → ~90 % TTFT reduction.

Reference: anthropics/claude-cookbooks/misc/speculative_prompt_caching.ipynb

Usage::

    from anthropic import AsyncAnthropic
    from agentwarehouses.prompt_caching import SpeculativeCache, make_cacheable_message

    cache = SpeculativeCache(client=AsyncAnthropic(), model="claude-sonnet-4-6")

    # Build a message whose large text block is marked for caching
    ctx = make_cacheable_message("user", big_context_string)

    # Start warming while user is still typing
    await cache.warmup([ctx])

    # Later — append the real question and query
    query_msg = copy.deepcopy(ctx)
    query_msg["content"].append({"type": "text", "text": user_question})
    response = await cache.query([query_msg])

    print(cache.stats)  # CacheStats(cache_hit=True, ...)
"""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from agentwarehouses.log import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_cacheable_message(role: str, text: str) -> dict[str, Any]:
    """Build a message dict with a single cache-controlled text block.

    Args:
        role: ``"user"`` or ``"assistant"``.
        text: The (typically large) text to cache.

    Returns:
        A dict ready to be included in the ``messages`` list for the
        Anthropic Messages API.
    """
    return {
        "role": role,
        "content": [
            {
                "type": "text",
                "text": text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
    }


def add_cache_control(message: dict[str, Any], *, block_index: int = 0) -> dict[str, Any]:
    """Return a copy of *message* with ``cache_control`` set on one content block.

    Args:
        message: A Messages-API message dict with a ``content`` list.
        block_index: Which content block to mark (default first).

    Returns:
        A shallow copy with the targeted block marked for caching.
    """
    msg = copy.deepcopy(message)
    blocks = msg.get("content", [])
    if isinstance(blocks, str):
        msg["content"] = [{"type": "text", "text": blocks, "cache_control": {"type": "ephemeral"}}]
    elif blocks and 0 <= block_index < len(blocks):
        blocks[block_index]["cache_control"] = {"type": "ephemeral"}
    return msg


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class CacheStats:
    """Runtime statistics from a warmup + query cycle."""

    warmup_duration_s: float = 0.0
    query_duration_s: float = 0.0
    ttft_s: float = 0.0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_input_tokens > 0


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


class SpeculativeCache:
    """Manages the warmup → query lifecycle for speculative prompt caching.

    Parameters:
        client: An ``AsyncAnthropic`` instance (created if *None*).
        model: Model ID used for both warmup and query.
        system: Optional system prompt shared across requests.
        max_tokens: Maximum output tokens for the real query.
        temperature: Sampling temperature.
    """

    def __init__(
        self,
        *,
        client: AsyncAnthropic | None = None,
        model: str = "claude-sonnet-4-6",
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        self._client = client or AsyncAnthropic()
        self._model = model
        self._system = system
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._warmup_task: asyncio.Task[None] | None = None
        self._context_messages: list[dict[str, Any]] = []
        self._stats = CacheStats()

    # -- warmup -------------------------------------------------------------

    async def warmup(self, messages: list[dict[str, Any]]) -> None:
        """Kick off a background 1-token request to populate the KV cache.

        Call this as soon as the context is known — ideally while the user
        is still typing their question.

        Args:
            messages: The context messages (with ``cache_control`` set on
                      the large content blocks).
        """
        self._context_messages = copy.deepcopy(messages)
        self._stats = CacheStats()
        self._warmup_task = asyncio.create_task(self._do_warmup())
        logger.info("Cache warmup started for model=%s", self._model)

    async def _do_warmup(self) -> None:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._context_messages,
            "max_tokens": 1,
            "temperature": self._temperature,
        }
        if self._system:
            kwargs["system"] = self._system

        start = time.monotonic()
        response = await self._client.messages.create(**kwargs)
        self._stats.warmup_duration_s = time.monotonic() - start

        usage = response.usage
        self._stats.cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
        logger.info(
            "Cache warmup complete in %.2fs — created %d cache tokens",
            self._stats.warmup_duration_s,
            self._stats.cache_creation_input_tokens,
        )

    async def _ensure_warm(self) -> None:
        """Block until the warmup task (if any) has finished."""
        if self._warmup_task is not None:
            await self._warmup_task
            self._warmup_task = None

    # -- query --------------------------------------------------------------

    async def query(self, messages: list[dict[str, Any]], **overrides: Any) -> Any:
        """Send the real request, waiting for warmup if it is still running.

        Args:
            messages: Full message list (context + question).  Re-use the
                      same context passed to :meth:`warmup` so the server-side
                      cache prefix matches.
            **overrides: Extra kwargs forwarded to ``messages.create``
                         (e.g. ``max_tokens``, ``tools``).

        Returns:
            The ``anthropic.types.Message`` response object.
        """
        await self._ensure_warm()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": overrides.pop("max_tokens", self._max_tokens),
            "temperature": overrides.pop("temperature", self._temperature),
            **overrides,
        }
        if self._system and "system" not in overrides:
            kwargs["system"] = self._system

        start = time.monotonic()
        response = await self._client.messages.create(**kwargs)
        self._stats.query_duration_s = time.monotonic() - start
        self._record_usage(response.usage)

        logger.info(
            "Query complete in %.2fs — cache_hit=%s, cache_read_tokens=%d",
            self._stats.query_duration_s,
            self._stats.cache_hit,
            self._stats.cache_read_input_tokens,
        )
        return response

    async def query_stream(self, messages: list[dict[str, Any]], **overrides: Any) -> AsyncIterator[str]:
        """Stream the response, yielding text chunks as they arrive.

        Measures TTFT (time-to-first-token) and records it in :attr:`stats`.

        Args:
            messages: Full message list (context + question).
            **overrides: Extra kwargs forwarded to ``messages.stream``.

        Yields:
            Text chunks from the model.
        """
        await self._ensure_warm()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": overrides.pop("max_tokens", self._max_tokens),
            "temperature": overrides.pop("temperature", self._temperature),
            **overrides,
        }
        if self._system and "system" not in overrides:
            kwargs["system"] = self._system

        start = time.monotonic()
        first_token_seen = False

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                if not first_token_seen and text.strip():
                    self._stats.ttft_s = time.monotonic() - start
                    first_token_seen = True
                yield text

            response = await stream.get_final_message()

        self._stats.query_duration_s = time.monotonic() - start
        self._record_usage(response.usage)

        logger.info(
            "Stream complete in %.2fs — ttft=%.2fs, cache_hit=%s",
            self._stats.query_duration_s,
            self._stats.ttft_s,
            self._stats.cache_hit,
        )

    # -- internals ----------------------------------------------------------

    def _record_usage(self, usage: Any) -> None:
        self._stats.input_tokens = usage.input_tokens
        self._stats.output_tokens = usage.output_tokens
        self._stats.cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0

    @property
    def stats(self) -> CacheStats:
        """Access the most recent warmup + query statistics."""
        return self._stats

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_warm(self) -> bool:
        """True after warmup has completed (or was never started)."""
        return self._warmup_task is None or self._warmup_task.done()
