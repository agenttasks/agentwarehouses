"""Tests for the Claude Builder spider — three-bot framework, dedup, and classification.

Tests model Anthropic's actual crawling architecture as documented in:
  - Mythos system card (April 2026)
  - FMTI 2025 transparency report (Stanford CRFM)
  - https://support.claude.com/en/articles/8896518
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from scrapy.http import TextResponse

from agentwarehouses.spiders.claude_builder_spider import (
    BOT_USER_AGENTS,
    ClaudeBuilderSpider,
)

SAMPLE_LLMS_TXT = """\
# Claude Builder Docs

- [Getting Started](https://builder.claude.ai/docs/getting-started.md): Build your first app
- [IDE Guide](https://builder.claude.ai/guides/ide.md): Using the integrated development environment
- [KAIROS Agent](https://builder.claude.ai/kairos/overview.md): Autonomous background agent
- [Deploy Apps](https://builder.claude.ai/deployment/quickstart.md): Deploy your app
- [Security Scanning](https://builder.claude.ai/security/overview.md): Built-in security checks
- [REST API](https://builder.claude.ai/api/reference.md): API reference
- [First App Tutorial](https://builder.claude.ai/tutorials/first-app.md): Step-by-step tutorial
"""

SAMPLE_SITEMAP = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://builder.claude.ai/docs/getting-started.md</loc></url>
  <url><loc>https://builder.claude.ai/guides/ide.md</loc></url>
  <url><loc>https://builder.claude.ai/tutorials/first-app.md</loc></url>
  <url><loc>https://builder.claude.ai/kairos/overview.md</loc></url>
  <url><loc>https://builder.claude.ai/api/reference.md</loc></url>
</urlset>
"""

SAMPLE_DOC_PAGE = """\
# Claude Builder IDE

> Build full-stack applications with an integrated development environment

## Overview

Claude Builder provides a complete IDE for building applications from prompts.

## Features

- Live preview
- Back-end logic generation
- Database integration with Neon
- Security scanning

## Getting Started

Describe your app idea and Claude handles the rest.
"""

SAMPLE_KAIROS_PAGE = """\
# KAIROS Autonomous Agent

> Monitor your codebase and fix errors overnight

## What is KAIROS?

KAIROS is an autonomous background agent that continuously monitors your
application codebase, identifies issues, and sends push notifications
upon completion.

## Configuration

Set up KAIROS to watch your deployed applications.
"""


# ── Three-bot framework ──────────────────────────────────────────────


@pytest.mark.unit
class TestThreeBotFramework:
    """Verify Anthropic's three-bot UA framework (ClaudeBot, Claude-User, Claude-SearchBot)."""

    def test_bot_user_agents_has_three_roles(self) -> None:
        assert set(BOT_USER_AGENTS.keys()) == {"training", "user", "search"}

    def test_training_ua_contains_claudebot(self) -> None:
        assert "ClaudeBot/1.0" in BOT_USER_AGENTS["training"]
        assert "claudebot@anthropic.com" in BOT_USER_AGENTS["training"]

    def test_user_ua_contains_claude_user(self) -> None:
        assert "Claude-User/1.0" in BOT_USER_AGENTS["user"]

    def test_search_ua_contains_claude_searchbot(self) -> None:
        assert "Claude-SearchBot/1.0" in BOT_USER_AGENTS["search"]

    def test_all_uas_have_mozilla_prefix(self) -> None:
        for ua in BOT_USER_AGENTS.values():
            assert ua.startswith("Mozilla/5.0 AppleWebKit/537.36")

    def test_default_bot_role_is_training(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.bot_role == "training"

    def test_custom_bot_role_user(self) -> None:
        spider = ClaudeBuilderSpider(bot_role="user")
        assert spider.bot_role == "user"

    def test_custom_bot_role_search(self) -> None:
        spider = ClaudeBuilderSpider(bot_role="search")
        assert spider.bot_role == "search"

    def test_training_role_sets_ua_in_custom_settings(self) -> None:
        spider = ClaudeBuilderSpider(bot_role="training")
        assert spider.custom_settings["USER_AGENT"] == BOT_USER_AGENTS["training"]

    def test_user_role_sets_ua_in_custom_settings(self) -> None:
        spider = ClaudeBuilderSpider(bot_role="user")
        assert spider.custom_settings["USER_AGENT"] == BOT_USER_AGENTS["user"]

    def test_search_role_sets_ua_in_custom_settings(self) -> None:
        spider = ClaudeBuilderSpider(bot_role="search")
        assert spider.custom_settings["USER_AGENT"] == BOT_USER_AGENTS["search"]


# ── Spider init ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestClaudeBuilderSpiderInit:
    def test_spider_name(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.name == "claude_builder"

    def test_allowed_domains(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.allowed_domains == ["builder.claude.ai"]

    def test_default_sources(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.active_sources == ["llms", "sitemap"]

    def test_custom_sources(self) -> None:
        spider = ClaudeBuilderSpider(sources="llms")
        assert spider.active_sources == ["llms"]

    def test_max_pages_default(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.max_pages == 0

    def test_max_pages_custom(self) -> None:
        spider = ClaudeBuilderSpider(max_pages=50)
        assert spider.max_pages == 50

    def test_bloom_filter_initialized(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.seen is not None
        spider.seen.add("https://builder.claude.ai/docs/test")
        assert "https://builder.claude.ai/docs/test" in spider.seen
        assert "https://builder.claude.ai/docs/other" not in spider.seen

    def test_content_hash_bloom_initialized(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.seen_hashes is not None
        spider.seen_hashes.add("abc123")
        assert "abc123" in spider.seen_hashes
        assert "def456" not in spider.seen_hashes

    def test_stats_initialized(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._stats == {
            "discovery_urls": 0,
            "pages_fetched": 0,
            "pages_skipped_dedup": 0,
            "pages_skipped_content_dedup": 0,
            "pages_skipped_lang": 0,
            "pages_failed": 0,
            "tutorials_found": 0,
            "kairos_found": 0,
        }

    def test_custom_settings_robotstxt_obey(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider.custom_settings["ROBOTSTXT_OBEY"] is True

    def test_source_urls(self) -> None:
        assert ClaudeBuilderSpider.SOURCES["llms"] == "https://builder.claude.ai/docs/llms.txt"
        assert ClaudeBuilderSpider.SOURCES["sitemap"] == "https://builder.claude.ai/sitemap.xml"


# ── Extract methods ──────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractMethods:
    def test_extract_title(self) -> None:
        assert ClaudeBuilderSpider._extract_title("# My Title\n\nContent") == "My Title"

    def test_extract_title_missing(self) -> None:
        assert ClaudeBuilderSpider._extract_title("No heading here") == ""

    def test_extract_title_with_whitespace(self) -> None:
        assert ClaudeBuilderSpider._extract_title("#   Padded Title  \n") == "Padded Title"

    def test_extract_title_html_fallback(self) -> None:
        assert ClaudeBuilderSpider._extract_title("<title>HTML Title</title>") == "HTML Title"

    def test_extract_title_prefers_markdown(self) -> None:
        text = "# Markdown Title\n<title>HTML Title</title>"
        assert ClaudeBuilderSpider._extract_title(text) == "Markdown Title"

    def test_extract_description(self) -> None:
        assert ClaudeBuilderSpider._extract_description("# T\n\n> Description here") == "Description here"

    def test_extract_description_missing(self) -> None:
        assert ClaudeBuilderSpider._extract_description("# T\n\nNo blockquote") == ""

    def test_extract_description_meta_fallback(self) -> None:
        text = '<meta name="description" content="Meta desc">'
        assert ClaudeBuilderSpider._extract_description(text) == "Meta desc"

    def test_extract_headings(self) -> None:
        text = "# Title\n## Section One\n### Subsection\n## Section Two"
        headings = ClaudeBuilderSpider._extract_headings(text)
        assert len(headings) == 4
        assert headings[0] == {"level": 1, "text": "Title"}
        assert headings[1] == {"level": 2, "text": "Section One"}
        assert headings[2] == {"level": 3, "text": "Subsection"}
        assert headings[3] == {"level": 2, "text": "Section Two"}

    def test_extract_headings_empty(self) -> None:
        assert ClaudeBuilderSpider._extract_headings("Plain text") == []

    def test_extract_headings_h6(self) -> None:
        headings = ClaudeBuilderSpider._extract_headings("###### Deep heading")
        assert headings == [{"level": 6, "text": "Deep heading"}]


# ── Classification pipeline ──────────────────────────────────────────


@pytest.mark.unit
class TestClassifyUrl:
    """Test content-type classification (FMTI 2025: 'deduplication and classification')."""

    def test_classify_tutorial(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._classify_url("https://builder.claude.ai/tutorials/first-app.md") == "tutorial"
        assert spider._stats["tutorials_found"] == 1

    def test_classify_kairos(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._classify_url("https://builder.claude.ai/kairos/overview.md") == "kairos"
        assert spider._stats["kairos_found"] == 1

    def test_classify_api(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._classify_url("https://builder.claude.ai/api/reference.md") == "api_reference"

    def test_classify_security(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._classify_url("https://builder.claude.ai/security/overview.md") == "security"

    def test_classify_deployment(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._classify_url("https://builder.claude.ai/deployment/quickstart.md") == "deployment"

    def test_classify_guide(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._classify_url("https://builder.claude.ai/guides/ide.md") == "builder_guide"

    def test_classify_default_page(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._classify_url("https://builder.claude.ai/docs/getting-started.md") == "page"


# ── URL dedup ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestShouldCrawl:
    def test_allows_valid_url(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._should_crawl("https://builder.claude.ai/docs/test.md") is True

    def test_filters_language(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._should_crawl("https://builder.claude.ai/ja/docs/test.md") is False
        assert spider._stats["pages_skipped_lang"] == 1

    def test_filters_language_with_region(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._should_crawl("https://builder.claude.ai/zh-cn/docs/test.md") is False
        assert spider._stats["pages_skipped_lang"] == 1

    def test_deduplicates(self) -> None:
        spider = ClaudeBuilderSpider()
        assert spider._should_crawl("https://builder.claude.ai/docs/test.md") is True
        assert spider._should_crawl("https://builder.claude.ai/docs/test.md") is False
        assert spider._stats["pages_skipped_dedup"] == 1

    def test_respects_max_pages(self) -> None:
        spider = ClaudeBuilderSpider(max_pages=1)
        spider._stats["pages_fetched"] = 1
        assert spider._should_crawl("https://builder.claude.ai/docs/test.md") is False


# ── Discovery: llms.txt ──────────────────────────────────────────────


@pytest.mark.integration
class TestParseLlmsTxt:
    def _fake_response(self, body: str, url: str = "https://builder.claude.ai/docs/llms.txt") -> TextResponse:
        return TextResponse(url=url, body=body.encode("utf-8"))

    def test_parse_extracts_urls(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_LLMS_TXT)
        requests = list(spider.parse_llms_txt(response, source="llms"))
        assert len(requests) == 7

    def test_parse_updates_stats(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_LLMS_TXT)
        list(spider.parse_llms_txt(response, source="llms"))
        assert spider._stats["discovery_urls"] == 7

    def test_parse_deduplicates(self) -> None:
        spider = ClaudeBuilderSpider()
        body = SAMPLE_LLMS_TXT + "\n- [Dup](https://builder.claude.ai/docs/getting-started.md): duplicate"
        response = self._fake_response(body)
        requests = list(spider.parse_llms_txt(response, source="llms"))
        urls = [r.url for r in requests]
        assert urls.count("https://builder.claude.ai/docs/getting-started.md") == 1

    def test_parse_empty_index(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response("# Empty index\nNo URLs here")
        requests = list(spider.parse_llms_txt(response, source="llms"))
        assert len(requests) == 0
        assert spider._stats["discovery_urls"] == 0

    def test_parse_sets_errback(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_LLMS_TXT)
        requests = list(spider.parse_llms_txt(response, source="llms"))
        assert requests[0].errback is not None

    def test_parse_classifies_content_types(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_LLMS_TXT)
        requests = list(spider.parse_llms_txt(response, source="llms"))
        content_types = [r.cb_kwargs["content_type"] for r in requests]
        assert "kairos" in content_types
        assert "deployment" in content_types
        assert "security" in content_types
        assert "tutorial" in content_types


# ── Discovery: sitemap ───────────────────────────────────────────────


@pytest.mark.integration
class TestParseSitemap:
    def _fake_response(self, body: str, url: str = "https://builder.claude.ai/sitemap.xml") -> TextResponse:
        return TextResponse(url=url, body=body.encode("utf-8"))

    def test_parse_sitemap_extracts_urls(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_SITEMAP)
        requests = list(spider.parse_sitemap(response, source="sitemap"))
        assert len(requests) == 5

    def test_parse_sitemap_updates_stats(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_SITEMAP)
        list(spider.parse_sitemap(response, source="sitemap"))
        assert spider._stats["discovery_urls"] == 5

    def test_parse_sitemap_deduplicates(self) -> None:
        spider = ClaudeBuilderSpider()
        sitemap = SAMPLE_SITEMAP.replace(
            "</urlset>",
            "  <url><loc>https://builder.claude.ai/docs/getting-started.md</loc></url>\n</urlset>",
        )
        response = self._fake_response(sitemap)
        requests = list(spider.parse_sitemap(response, source="sitemap"))
        urls = [r.url for r in requests]
        assert urls.count("https://builder.claude.ai/docs/getting-started.md") == 1

    def test_parse_sitemap_sets_errback(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_SITEMAP)
        requests = list(spider.parse_sitemap(response, source="sitemap"))
        assert all(r.errback is not None for r in requests)


# ── Page extraction + content dedup ──────────────────────────────────


@pytest.mark.integration
class TestParseDocPage:
    def _fake_response(
        self, body: str, url: str = "https://builder.claude.ai/docs/getting-started.md"
    ) -> TextResponse:
        return TextResponse(url=url, body=body.encode("utf-8"))

    def test_parse_doc_page_yields_item(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_DOC_PAGE)
        items = list(spider.parse_doc_page(response, source="llms", content_type="page"))
        assert len(items) == 1

    def test_parse_doc_page_extracts_fields(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_DOC_PAGE)
        item = list(spider.parse_doc_page(response, source="llms", content_type="page"))[0]
        assert item["url"] == "https://builder.claude.ai/docs/getting-started.md"
        assert item["title"] == "Claude Builder IDE"
        assert item["description"] == "Build full-stack applications with an integrated development environment"
        assert len(item["headings"]) == 4
        assert item["content_length"] > 100
        assert item["crawled_at"].endswith("+00:00")
        assert item["source"] == "llms"
        assert item["content_type"] == "page"
        assert len(item["content_hash"]) == 64  # SHA256 hex digest

    def test_parse_doc_page_increments_stats(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_DOC_PAGE)
        list(spider.parse_doc_page(response, source="llms", content_type="page"))
        assert spider._stats["pages_fetched"] == 1

    def test_parse_doc_page_empty_body(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response("")
        item = list(spider.parse_doc_page(response, source="llms", content_type="page"))[0]
        assert item["title"] == ""
        assert item["description"] == ""
        assert item["content_length"] == 0

    def test_parse_doc_page_respects_max_pages(self) -> None:
        spider = ClaudeBuilderSpider(max_pages=1)
        spider._stats["pages_fetched"] = 1
        response = self._fake_response(SAMPLE_DOC_PAGE)
        items = list(spider.parse_doc_page(response, source="llms", content_type="page"))
        assert len(items) == 0

    def test_parse_doc_page_content_hash_deterministic(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_DOC_PAGE)
        item1 = list(spider.parse_doc_page(response, source="llms", content_type="page"))[0]
        spider2 = ClaudeBuilderSpider()
        item2 = list(spider2.parse_doc_page(response, source="llms", content_type="page"))[0]
        assert item1["content_hash"] == item2["content_hash"]

    def test_parse_doc_page_content_dedup_skips_duplicate_content(self) -> None:
        """Same content at two different URLs should be deduplicated."""
        spider = ClaudeBuilderSpider()
        resp1 = self._fake_response(SAMPLE_DOC_PAGE, url="https://builder.claude.ai/docs/page-a.md")
        resp2 = self._fake_response(SAMPLE_DOC_PAGE, url="https://builder.claude.ai/docs/page-b.md")
        items1 = list(spider.parse_doc_page(resp1, source="llms", content_type="page"))
        items2 = list(spider.parse_doc_page(resp2, source="llms", content_type="page"))
        assert len(items1) == 1
        assert len(items2) == 0  # deduped by content hash
        assert spider._stats["pages_skipped_content_dedup"] == 1

    def test_parse_doc_page_different_content_not_deduped(self) -> None:
        """Different content at different URLs should both pass."""
        spider = ClaudeBuilderSpider()
        resp1 = self._fake_response(SAMPLE_DOC_PAGE, url="https://builder.claude.ai/docs/page-a.md")
        resp2 = self._fake_response(SAMPLE_KAIROS_PAGE, url="https://builder.claude.ai/kairos/overview.md")
        items1 = list(spider.parse_doc_page(resp1, source="llms", content_type="page"))
        items2 = list(spider.parse_doc_page(resp2, source="llms", content_type="kairos"))
        assert len(items1) == 1
        assert len(items2) == 1
        assert spider._stats["pages_skipped_content_dedup"] == 0

    def test_parse_kairos_page(self) -> None:
        spider = ClaudeBuilderSpider()
        response = self._fake_response(SAMPLE_KAIROS_PAGE, url="https://builder.claude.ai/kairos/overview.md")
        item = list(spider.parse_doc_page(response, source="llms", content_type="kairos"))[0]
        assert item["title"] == "KAIROS Autonomous Agent"
        assert item["description"] == "Monitor your codebase and fix errors overnight"
        assert item["content_type"] == "kairos"


# ── Error handling ───────────────────────────────────────────────────


@pytest.mark.integration
class TestHandleError:
    def test_handle_error_increments_failed_stats(self) -> None:
        spider = ClaudeBuilderSpider()
        failure = MagicMock()
        failure.request.url = "https://builder.claude.ai/docs/broken"
        failure.type.__name__ = "SomeError"
        spider.handle_error(failure)
        assert spider._stats["pages_failed"] == 1

    def test_handle_error_multiple(self) -> None:
        spider = ClaudeBuilderSpider()
        for i in range(3):
            failure = MagicMock()
            failure.request.url = f"https://builder.claude.ai/docs/broken-{i}"
            failure.type.__name__ = "TimeoutError"
            spider.handle_error(failure)
        assert spider._stats["pages_failed"] == 3


# ── Closed / stats ──────────────────────────────────────────────────


@pytest.mark.unit
class TestClosedMethod:
    def test_closed_logs_stats(self) -> None:
        spider = ClaudeBuilderSpider()
        spider._stats = {
            "discovery_urls": 20,
            "pages_fetched": 15,
            "pages_skipped_dedup": 3,
            "pages_skipped_content_dedup": 1,
            "pages_skipped_lang": 1,
            "pages_failed": 1,
            "tutorials_found": 4,
            "kairos_found": 2,
        }
        # closed() just logs, should not raise
        spider.closed("finished")


# ── Start requests ───────────────────────────────────────────────────


@pytest.mark.integration
class TestStartRequests:
    def test_start_requests_yields_for_active_sources(self) -> None:
        spider = ClaudeBuilderSpider(sources="llms,sitemap")
        requests = list(spider.start_requests())
        assert len(requests) == 2
        urls = [r.url for r in requests]
        assert "https://builder.claude.ai/docs/llms.txt" in urls
        assert "https://builder.claude.ai/sitemap.xml" in urls

    def test_start_requests_single_source(self) -> None:
        spider = ClaudeBuilderSpider(sources="llms")
        requests = list(spider.start_requests())
        assert len(requests) == 1
        assert requests[0].url == "https://builder.claude.ai/docs/llms.txt"

    def test_start_requests_unknown_source_skipped(self) -> None:
        spider = ClaudeBuilderSpider(sources="llms,unknown")
        requests = list(spider.start_requests())
        assert len(requests) == 1

    def test_start_requests_sets_errback(self) -> None:
        spider = ClaudeBuilderSpider(sources="llms")
        requests = list(spider.start_requests())
        assert requests[0].errback is not None

    def test_start_requests_sitemap_uses_parse_sitemap(self) -> None:
        spider = ClaudeBuilderSpider(sources="sitemap")
        requests = list(spider.start_requests())
        assert requests[0].callback == spider.parse_sitemap

    def test_start_requests_llms_uses_parse_llms_txt(self) -> None:
        spider = ClaudeBuilderSpider(sources="llms")
        requests = list(spider.start_requests())
        assert requests[0].callback == spider.parse_llms_txt
