"""Claude Builder docs spider — crawls Anthropic's full-stack app builder documentation.

Models Anthropic's three-bot crawling framework (Mythos system card, FMTI 2025):
  - ClaudeBot      — training data collection (this spider's role)
  - Claude-User    — per-request user-initiated fetches
  - Claude-SearchBot — search index crawling

Training data pipeline (per Anthropic transparency report):
  1. Discovery     — llms.txt + sitemap sources
  2. Collection    — fetch candidate pages (ClaudeBot UA)
  3. Deduplication — rbloom Bloom filter (content_hash + URL)
  4. Classification — categorize by content type from URL path
  5. Serialization — JSONL output for downstream filtering

Data sources follow the Mythos composition model:
  - Public web content (this spider)
  - Licensed third-party data (not crawled)
  - Opted-in user data (not crawled)
  - Contractor annotations (not crawled)
  - Synthetic data (not crawled)

Ref: https://support.claude.com/en/articles/8896518
Ref: https://claude.com/crawling/bots.json
Ref: https://crfm.stanford.edu/fmti/December-2025/company-reports/Anthropic_FinalReport_FMTI2025.html

Usage:
    scrapy crawl claude_builder
    scrapy crawl claude_builder -a max_pages=50
    scrapy crawl claude_builder -a sources=llms,sitemap
    scrapy crawl claude_builder -a bot_role=training
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import scrapy
from rbloom import Bloom
from scrapy.http import Response
from twisted.python.failure import Failure

from agentwarehouses.items import DocPageItem
from agentwarehouses.markdown import MarkdownParser

# llms.txt link pattern: - [Title](URL): description
LLMS_ENTRY_RE = re.compile(r"- \[([^\]]+)\]\(([^)]+)\)(?::\s*(.+))?")

# Sitemap <loc> extraction
SITEMAP_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")

# Language filter: skip non-English docs
LANG_FILTER_RE = re.compile(r"/(?:ja|de|fr|ko|zh|pt|es)(?:-[a-z]{2})?/")

# Anthropic's three-bot framework user agents
# Ref: https://support.claude.com/en/articles/8896518
BOT_USER_AGENTS: dict[str, str] = {
    "training": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"
    ),
    "user": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +claudebot@anthropic.com)"
    ),
    "search": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +claudebot@anthropic.com)"
    ),
}

# Content-type classification from URL paths — models the "deduplication and
# classification" stage described in Anthropic's FMTI 2025 transparency report
CONTENT_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("/tutorials/", "tutorial"),
    ("/kairos/", "kairos"),
    ("/api/", "api_reference"),
    ("/security/", "security"),
    ("/deployment/", "deployment"),
    ("/guides/", "builder_guide"),
]


class ClaudeBuilderSpider(scrapy.Spider):
    """Multi-source Claude Builder documentation crawler using Anthropic's ClaudeBot framework.

    Models the training data collection pipeline described in Anthropic's
    Mythos system card and FMTI 2025 transparency report. Collects public
    web content as "potential future training candidates" — content is
    fetched, deduplicated, classified, and serialized for downstream filtering.

    Three-bot roles (selectable via -a bot_role=):
      training (default) — ClaudeBot UA, collects training data candidates
      user               — Claude-User UA, fetches for user requests
      search             — Claude-SearchBot UA, indexes for search quality

    Content types classified from URL paths:
      - builder_guide: General builder documentation
      - api_reference: API and SDK reference pages
      - tutorial: Step-by-step tutorials
      - security: Security scanning and best practices
      - deployment: App deployment and hosting
      - kairos: KAIROS autonomous agent docs
      - page: Unclassified documentation pages
    """

    name = "claude_builder"
    allowed_domains = ["builder.claude.ai"]

    custom_settings: dict[bool | float | int | str | None, Any] | None = {
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_TIMEOUT": 30,
        "RETRY_TIMES": 3,
    }

    # Discovery endpoints
    SOURCES = {
        "llms": "https://builder.claude.ai/docs/llms.txt",
        "sitemap": "https://builder.claude.ai/sitemap.xml",
    }

    def __init__(
        self,
        max_pages: int = 0,
        sources: str = "llms,sitemap",
        bot_role: str = "training",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_pages = int(max_pages)  # 0 = unlimited
        self.active_sources = [s.strip() for s in sources.split(",")]
        self.bot_role = bot_role

        # Set UA per Anthropic's three-bot framework
        ua = BOT_USER_AGENTS.get(bot_role)
        if ua:
            self.custom_settings = {**(self.custom_settings or {}), "USER_AGENT": ua}
        else:
            self.logger.warning("Unknown bot_role '%s', using default UA", bot_role)

        # Bloom filter: 2K capacity, 0.01% FP rate (~35 KiB memory)
        self.seen: Bloom = Bloom(2000, 0.0001)
        # Content hash dedup — mirrors Anthropic's "deduplication" stage
        self.seen_hashes: Bloom = Bloom(2000, 0.0001)
        self._stats: dict[str, int] = {
            "discovery_urls": 0,
            "pages_fetched": 0,
            "pages_skipped_dedup": 0,
            "pages_skipped_content_dedup": 0,
            "pages_skipped_lang": 0,
            "pages_failed": 0,
            "tutorials_found": 0,
            "kairos_found": 0,
        }
        self._parser = MarkdownParser()

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """Yield requests for each active discovery source."""
        for source_name in self.active_sources:
            url = self.SOURCES.get(source_name)
            if not url:
                self.logger.warning("Unknown source: %s", source_name)
                continue
            self.logger.info("Starting discovery from: %s (%s) role=%s", source_name, url, self.bot_role)
            if source_name == "sitemap":
                yield scrapy.Request(
                    url,
                    callback=self.parse_sitemap,
                    cb_kwargs={"source": source_name},
                    errback=self.handle_error,
                )
            else:
                yield scrapy.Request(
                    url,
                    callback=self.parse_llms_txt,
                    cb_kwargs={"source": source_name},
                    errback=self.handle_error,
                )

    def parse_llms_txt(self, response: Response, *, source: str) -> Generator[scrapy.Request | DocPageItem, None, None]:
        """Parse llms.txt and yield requests for each linked page."""
        entries = LLMS_ENTRY_RE.findall(response.text)
        self.logger.info("[%s] Found %d entries in llms.txt", source, len(entries))

        for _title, url, _description in entries:
            if not self._should_crawl(url):
                continue
            self._stats["discovery_urls"] += 1
            content_type = self._classify_url(url)
            yield scrapy.Request(
                url,
                callback=self.parse_doc_page,
                cb_kwargs={"source": source, "content_type": content_type},
                errback=self.handle_error,
            )

    def parse_sitemap(self, response: Response, *, source: str) -> Generator[scrapy.Request, None, None]:
        """Parse sitemap XML and yield requests for doc pages."""
        urls = SITEMAP_LOC_RE.findall(response.text)
        self.logger.info("[%s] Found %d URLs in sitemap", source, len(urls))

        for url in urls:
            if not self._should_crawl(url):
                continue
            content_type = self._classify_url(url)
            self._stats["discovery_urls"] += 1
            yield scrapy.Request(
                url,
                callback=self.parse_doc_page,
                cb_kwargs={"source": source, "content_type": content_type},
                errback=self.handle_error,
            )

    def parse_doc_page(
        self,
        response: Response,
        *,
        source: str,
        content_type: str,
    ) -> Generator[DocPageItem, None, None]:
        """Extract content from a fetched documentation page.

        Implements the collection → dedup → classification pipeline:
        1. Fetch page content
        2. SHA256 content hash for cross-URL dedup (same content, different URL)
        3. Classify content type (already done at discovery)
        4. Yield item for downstream serialization
        """
        if self.max_pages and self._stats["pages_fetched"] >= self.max_pages:
            return

        text: str = response.text
        content_hash = hashlib.sha256(text.encode()).hexdigest()

        # Content-level dedup: skip if identical content seen at different URL
        if content_hash in self.seen_hashes:
            self._stats["pages_skipped_content_dedup"] += 1
            return
        self.seen_hashes.add(content_hash)

        self._stats["pages_fetched"] += 1

        parsed = self._parser.parse(text)

        item = DocPageItem()
        item["url"] = response.url
        item["title"] = parsed.title
        item["description"] = parsed.description
        item["headings"] = parsed.headings_as_dicts()
        item["body_markdown"] = text
        item["content_length"] = len(text)
        item["crawled_at"] = datetime.now(timezone.utc).isoformat()
        item["source"] = source
        item["content_type"] = content_type
        item["content_hash"] = content_hash

        yield item

    def _classify_url(self, url: str) -> str:
        """Classify content type from URL path.

        Models the "classification" stage of Anthropic's data pipeline
        (FMTI 2025 transparency report: "deduplication and classification").
        """
        for pattern, ctype in CONTENT_TYPE_PATTERNS:
            if pattern in url:
                if ctype == "tutorial":
                    self._stats["tutorials_found"] += 1
                elif ctype == "kairos":
                    self._stats["kairos_found"] += 1
                return ctype
        return "page"

    def _should_crawl(self, url: str) -> bool:
        """Check URL against bloom filter and language filter."""
        # Language filter
        if LANG_FILTER_RE.search(url):
            self._stats["pages_skipped_lang"] += 1
            return False
        # Max pages guard
        if self.max_pages and self._stats["pages_fetched"] >= self.max_pages:
            return False
        # URL-level bloom dedup
        if url in self.seen:
            self._stats["pages_skipped_dedup"] += 1
            return False
        self.seen.add(url)
        return True

    def handle_error(self, failure: Failure) -> None:
        """Log errors without crashing the crawl."""
        self._stats["pages_failed"] += 1
        self.logger.error(
            "ERROR: %s fetching %s",
            failure.type.__name__,  # type: ignore[union-attr]
            failure.request.url,  # type: ignore[attr-defined]
        )

    def closed(self, reason: str) -> None:
        """Log crawl summary stats on spider close."""
        self.logger.info(
            "Crawl complete: role=%s discovered=%d fetched=%d "
            "url_dedup=%d content_dedup=%d lang_skipped=%d "
            "failed=%d tutorials=%d kairos=%d reason=%s",
            self.bot_role,
            self._stats["discovery_urls"],
            self._stats["pages_fetched"],
            self._stats["pages_skipped_dedup"],
            self._stats["pages_skipped_content_dedup"],
            self._stats["pages_skipped_lang"],
            self._stats["pages_failed"],
            self._stats["tutorials_found"],
            self._stats["kairos_found"],
            reason,
        )

    @staticmethod
    def _extract_title(text: str) -> str:
        """Extract title from first H1 heading or HTML title tag."""
        return MarkdownParser().parse(text).title

    @staticmethod
    def _extract_description(text: str) -> str:
        """Extract description from first blockquote or meta description."""
        return MarkdownParser().parse(text).description

    @staticmethod
    def _extract_headings(text: str) -> list[dict[str, Any]]:
        """Extract all headings as a list of (level, text) for structure analysis."""
        return MarkdownParser().parse(text).headings_as_dicts()
