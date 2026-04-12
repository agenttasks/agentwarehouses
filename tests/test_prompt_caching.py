"""Tests for prompt caching models and speculative cache utility."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from agentwarehouses.models import (
    CacheableTextBlock,
    CacheControl,
    CacheUsage,
    SpeculativeCacheConfig,
)
from agentwarehouses.prompt_caching import (
    CacheStats,
    SpeculativeCache,
    add_cache_control,
    make_cacheable_message,
)

# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestCacheControl:
    def test_default_type(self):
        cc = CacheControl()
        assert cc.type == "ephemeral"

    def test_only_ephemeral(self):
        with pytest.raises(ValidationError):
            CacheControl(type="permanent")


class TestCacheableTextBlock:
    def test_without_cache_control(self):
        b = CacheableTextBlock(text="hello")
        assert b.cache_control is None

    def test_with_cache_control(self):
        b = CacheableTextBlock(text="hello", cache_control=CacheControl())
        assert b.cache_control is not None
        assert b.cache_control.type == "ephemeral"

    def test_serialization_round_trip(self):
        b = CacheableTextBlock(text="ctx", cache_control=CacheControl())
        data = b.model_dump()
        assert data["cache_control"] == {"type": "ephemeral"}
        restored = CacheableTextBlock.model_validate(data)
        assert restored == b


class TestCacheUsage:
    def test_cache_hit_property(self):
        hit = CacheUsage(input_tokens=10, output_tokens=5, cache_read_input_tokens=100)
        assert hit.cache_hit is True

    def test_cache_miss_property(self):
        miss = CacheUsage(input_tokens=10, output_tokens=5)
        assert miss.cache_hit is False

    def test_total_input_tokens(self):
        u = CacheUsage(
            input_tokens=10,
            output_tokens=5,
            cache_creation_input_tokens=100,
            cache_read_input_tokens=50,
        )
        assert u.total_input_tokens == 160

    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            CacheUsage(input_tokens=-1, output_tokens=0)


class TestSpeculativeCacheConfig:
    def test_defaults(self):
        cfg = SpeculativeCacheConfig()
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.warmup_max_tokens == 1
        assert cfg.temperature == 0.0
        assert cfg.max_tokens == 4096
        assert cfg.system is None

    def test_warmup_tokens_pinned_to_1(self):
        with pytest.raises(ValidationError):
            SpeculativeCacheConfig(warmup_max_tokens=2)

    def test_custom_model(self):
        cfg = SpeculativeCacheConfig(model="claude-opus-4-6", system="You are helpful.")
        assert cfg.model == "claude-opus-4-6"
        assert cfg.system == "You are helpful."


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestMakeCacheableMessage:
    def test_creates_user_message(self):
        msg = make_cacheable_message("user", "big context here")
        assert msg["role"] == "user"
        assert len(msg["content"]) == 1
        assert msg["content"][0]["type"] == "text"
        assert msg["content"][0]["text"] == "big context here"
        assert msg["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_creates_assistant_message(self):
        msg = make_cacheable_message("assistant", "response context")
        assert msg["role"] == "assistant"


class TestAddCacheControl:
    def test_adds_to_first_block(self):
        msg = {"role": "user", "content": [{"type": "text", "text": "hello"}]}
        result = add_cache_control(msg)
        assert result["content"][0]["cache_control"] == {"type": "ephemeral"}
        # Original unchanged
        assert "cache_control" not in msg["content"][0]

    def test_adds_to_specific_block(self):
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        }
        result = add_cache_control(msg, block_index=1)
        assert "cache_control" not in result["content"][0]
        assert result["content"][1]["cache_control"] == {"type": "ephemeral"}

    def test_converts_string_content(self):
        msg = {"role": "user", "content": "plain string"}
        result = add_cache_control(msg)
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "plain string"
        assert result["content"][0]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# CacheStats tests
# ---------------------------------------------------------------------------


class TestCacheStats:
    def test_defaults(self):
        s = CacheStats()
        assert s.cache_hit is False
        assert s.warmup_duration_s == 0.0

    def test_cache_hit(self):
        s = CacheStats(cache_read_input_tokens=500)
        assert s.cache_hit is True


# ---------------------------------------------------------------------------
# SpeculativeCache tests (mocked Anthropic client)
# ---------------------------------------------------------------------------


def _make_mock_client(
    warmup_cache_creation: int = 1000,
    query_cache_read: int = 1000,
    query_input: int = 50,
    query_output: int = 200,
):
    """Build a mock AsyncAnthropic whose messages.create returns plausible usage."""
    warmup_usage = SimpleNamespace(
        input_tokens=0,
        output_tokens=1,
        cache_creation_input_tokens=warmup_cache_creation,
        cache_read_input_tokens=0,
    )
    warmup_response = SimpleNamespace(usage=warmup_usage)

    query_usage = SimpleNamespace(
        input_tokens=query_input,
        output_tokens=query_output,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=query_cache_read,
    )
    query_response = SimpleNamespace(
        usage=query_usage,
        content=[SimpleNamespace(type="text", text="Answer text")],
        stop_reason="end_turn",
    )

    mock_create = AsyncMock(side_effect=[warmup_response, query_response])

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = mock_create

    return client, mock_create


@pytest.mark.asyncio
class TestSpeculativeCache:
    async def test_warmup_then_query(self):
        client, mock_create = _make_mock_client()
        cache = SpeculativeCache(client=client, model="claude-sonnet-4-6")

        ctx = make_cacheable_message("user", "large context")
        await cache.warmup([ctx])
        # warmup fires a background task — wait for it
        await cache._ensure_warm()

        query_msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "large context"},
                    {"type": "text", "text": "What is X?"},
                ],
            }
        ]
        response = await cache.query(query_msgs)

        assert mock_create.call_count == 2
        # First call = warmup with max_tokens=1
        warmup_kwargs = mock_create.call_args_list[0]
        assert warmup_kwargs.kwargs["max_tokens"] == 1
        # Second call = real query
        assert response.stop_reason == "end_turn"

    async def test_stats_after_query(self):
        client, _ = _make_mock_client(
            warmup_cache_creation=5000,
            query_cache_read=5000,
            query_input=100,
            query_output=300,
        )
        cache = SpeculativeCache(client=client, model="claude-sonnet-4-6")

        ctx = make_cacheable_message("user", "context")
        await cache.warmup([ctx])
        await cache._ensure_warm()
        await cache.query([{"role": "user", "content": "question"}])

        assert cache.stats.cache_hit is True
        assert cache.stats.cache_creation_input_tokens == 5000
        assert cache.stats.cache_read_input_tokens == 5000
        assert cache.stats.input_tokens == 100
        assert cache.stats.output_tokens == 300

    async def test_is_warm_property(self):
        client, _ = _make_mock_client()
        cache = SpeculativeCache(client=client)

        # Before warmup — trivially warm (no task)
        assert cache.is_warm is True

        ctx = make_cacheable_message("user", "ctx")
        await cache.warmup([ctx])
        # Task may or may not be done immediately; await it
        await cache._ensure_warm()
        assert cache.is_warm is True

    async def test_system_prompt_forwarded(self):
        client, mock_create = _make_mock_client()
        cache = SpeculativeCache(
            client=client,
            system="You are an expert.",
        )
        ctx = make_cacheable_message("user", "ctx")
        await cache.warmup([ctx])
        await cache._ensure_warm()
        await cache.query([{"role": "user", "content": "q"}])

        for call in mock_create.call_args_list:
            assert call.kwargs["system"] == "You are an expert."

    async def test_query_without_warmup(self):
        """query() works even if warmup was never called."""
        query_usage = SimpleNamespace(
            input_tokens=50,
            output_tokens=100,
            cache_creation_input_tokens=1000,
            cache_read_input_tokens=0,
        )
        query_response = SimpleNamespace(
            usage=query_usage,
            content=[SimpleNamespace(type="text", text="Answer")],
            stop_reason="end_turn",
        )
        client = MagicMock()
        client.messages = MagicMock()
        client.messages.create = AsyncMock(return_value=query_response)

        cache = SpeculativeCache(client=client)
        response = await cache.query([{"role": "user", "content": "hi"}])
        assert response.stop_reason == "end_turn"
        assert cache.stats.cache_hit is False

    async def test_overrides_forwarded(self):
        client, mock_create = _make_mock_client()
        cache = SpeculativeCache(client=client, max_tokens=100)

        ctx = make_cacheable_message("user", "ctx")
        await cache.warmup([ctx])
        await cache._ensure_warm()
        await cache.query(
            [{"role": "user", "content": "q"}],
            max_tokens=8192,
        )

        query_call = mock_create.call_args_list[1]
        assert query_call.kwargs["max_tokens"] == 8192
