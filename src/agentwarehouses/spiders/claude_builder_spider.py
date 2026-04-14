"""Claude Builder docs spider — crawls documentation for Anthropic's full-stack app builder.

Discovers Claude Builder documentation pages from multiple sources:
  1. builder.claude.ai/docs/llms.txt  — AI-curated doc index
  2. builder.claude.ai/sitemap.xml    — full doc sitemap

Claude Builder is Anthropic's no-code application builder (research preview),
evolving Artifacts into a full-stack development environment with IDE, back-end
logic, security scanning, and KAIROS autonomous agent integration.

Usage:
    scrapy crawl claude_builder
    scrapy crawl claude_builder -a max_pages=50
    scrapy crawl claude_builder -a sources=llms,sitemap
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

# llms.txt link pattern: - [Title](URL): description
LLMS_ENTRY_RE = re.compile(r"- \[([^\]]+)\]\(([^)]+)\)(?::\s*(.+))?")

# Sitemap <loc> extraction
SITEMAP_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")

# Valid Builder doc paths
BUILDER_DOC_RE = re.compile(
    r"^https://builder\.claude\.ai/(?:docs|guides|api|tutorials|security|deployment|kairos)/"
)

# Language filter: skip non-English docs
LANG_FILTER_RE = re.compile(r"/(?:ja|de|fr|ko|zh|pt|es)(?:-[a-z]{2})?/")


class ClaudeBuilderSpider(scrapy.Spider):
    """Multi-source Claude Builder documentation crawler with rbloom dedup.

    Crawls llms.txt and sitemap sources to index Claude Builder's full-stack
    app builder documentation. Deduplicates URLs across all sources using a
    Bloom filter (2,000 capacity, 0.01% FP).

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

    custom_settings: dict[str, Any] = {
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
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_pages = int(max_pages)  # 0 = unlimited
        self.active_sources = [s.strip() for s in sources.split(",")]
        # Bloom filter: 2K capacity, 0.01% FP rate (~35 KiB memory)
        self.seen: Bloom = Bloom(2000, 0.0001)
        self._stats: dict[str, int] = {
            "discovery_urls": 0,
            "pages_fetched": 0,
            "pages_skipped_dedup": 0,
            "pages_skipped_lang": 0,
            "pages_failed": 0,
            "tutorials_found": 0,
            "kairos_found": 0,
        }

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """Yield requests for each active discovery source."""
        for source_name in self.active_sources:
            url = self.SOURCES.get(source_name)
            if not url:
                self.logger.warning("Unknown source: %s", source_name)
                continue
            self.logger.info("Starting discovery from: %s (%s)", source_name, url)
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

    def parse_llms_txt(
        self, response: Response, *, source: str
    ) -> Generator[scrapy.Request | DocPageItem, None, None]:
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

    def parse_sitemap(
        self, response: Response, *, source: str
    ) -> Generator[scrapy.Request, None, None]:
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
        """Extract content from a fetched documentation page."""
        if self.max_pages and self._stats["pages_fetched"] >= self.max_pages:
            return

        self._stats["pages_fetched"] += 1
        text: str = response.text
        content_hash = hashlib.sha256(text.encode()).hexdigest()

        title = self._extract_title(text)
        description = self._extract_description(text)
        headings = self._extract_headings(text)

        item = DocPageItem()
        item["url"] = response.url
        item["title"] = title
        item["description"] = description
        item["headings"] = headings
        item["body_markdown"] = text
        item["content_length"] = len(text)
        item["crawled_at"] = datetime.now(timezone.utc).isoformat()
        item["source"] = source
        item["content_type"] = content_type
        item["content_hash"] = content_hash

        yield item

    def _classify_url(self, url: str) -> str:
        """Classify content type from URL path."""
        if "/tutorials/" in url:
            self._stats["tutorials_found"] += 1
            return "tutorial"
        if "/kairos/" in url:
            self._stats["kairos_found"] += 1
            return "kairos"
        if "/api/" in url:
            return "api_reference"
        if "/security/" in url:
            return "security"
        if "/deployment/" in url:
            return "deployment"
        if "/guides/" in url:
            return "builder_guide"
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
        # Bloom dedup
        if url in self.seen:
            self._stats["pages_skipped_dedup"] += 1
            return False
        self.seen.add(url)
        return True

    def handle_error(self, failure: Failure) -> None:
        """Log errors without crashing the crawl."""
        self._stats["pages_failed"] += 1
        self.logger.error("ERROR: %s fetching %s", failure.type.__name__, failure.request.url)

    def closed(self, reason: str) -> None:
        """Log crawl summary stats on spider close."""
        self.logger.info(
            "Crawl complete: discovered=%d fetched=%d dedup_skipped=%d "
            "lang_skipped=%d failed=%d tutorials=%d kairos=%d reason=%s",
            self._stats["discovery_urls"],
            self._stats["pages_fetched"],
            self._stats["pages_skipped_dedup"],
            self._stats["pages_skipped_lang"],
            self._stats["pages_failed"],
            self._stats["tutorials_found"],
            self._stats["kairos_found"],
            reason,
        )

    @staticmethod
    def _extract_title(text: str) -> str:
        """Extract title from first H1 heading or HTML title tag."""
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip()
        match = re.search(r"<title>([^<]+)</title>", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_description(text: str) -> str:
        """Extract description from first blockquote or meta description."""
        match = re.search(r"^>\s*(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip()
        match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_headings(text: str) -> list[dict[str, Any]]:
        """Extract all headings as a list of (level, text) for structure analysis."""
        return [
            {"level": len(m.group(1)), "text": m.group(2).strip()}
            for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
        ]
