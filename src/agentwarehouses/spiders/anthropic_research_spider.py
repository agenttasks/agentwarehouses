"""Multi-site Anthropic research spider — crawls HTML sites for AI research content.

Targets:
  1. transformer-circuits.pub     — Mechanistic interpretability papers
  2. www.anthropic.com/engineering — Engineering blog posts
  3. www.neuroai.science           — NeuroAI / Substack articles
  4. www.anthropic.com/research    — Research papers & announcements
  5. claude.com/blog               — Claude product blog

Extracts content from HTML pages using CSS selectors, with rbloom
Bloom filter for O(1) URL deduplication across all domains.

Usage:
    scrapy crawl anthropic_research
    scrapy crawl anthropic_research -a max_pages=20
    scrapy crawl anthropic_research -a output_dir=output/research
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import scrapy
from rbloom import Bloom
from scrapy.http import HtmlResponse, Response
from twisted.python.failure import Failure

from agentwarehouses.items import DocPageItem

# Skip non-content paths
SKIP_PATHS = re.compile(
    r"(?:"
    r"/(?:login|signup|sign-up|register|auth|oauth|cart|checkout|pricing|careers|jobs)"
    r"|\.(?:png|jpg|jpeg|gif|svg|webp|pdf|zip|tar|gz|mp4|mp3|woff|woff2|ttf|eot|ico)$"
    r"|/(?:api|rss|feed|atom)(?:/|$)"
    r"|#"  # fragment-only links
    r")",
    re.IGNORECASE,
)


class AnthropicResearchSpider(scrapy.Spider):
    """Multi-domain spider for Anthropic research and engineering content.

    Starts from 5 seed URLs, follows internal links on each domain
    to discover articles, and extracts structured content from HTML.
    """

    name = "anthropic_research"

    # Domains we're allowed to crawl
    allowed_domains = [
        "transformer-circuits.pub",
        "www.anthropic.com",
        "www.neuroai.science",
        "claude.com",
    ]

    # Seed URLs — the entry points for each site
    SEEDS: list[dict[str, str]] = [
        {
            "url": "https://transformer-circuits.pub/",
            "source": "transformer_circuits",
            "content_type": "research",
        },
        {
            "url": "https://www.anthropic.com/engineering",
            "source": "anthropic_engineering",
            "content_type": "engineering",
        },
        {
            "url": "https://www.neuroai.science/p/claude-code-for-scientists",
            "source": "neuroai_science",
            "content_type": "article",
        },
        {
            "url": "https://www.anthropic.com/research",
            "source": "anthropic_research",
            "content_type": "research",
        },
        {
            "url": "https://claude.com/blog",
            "source": "claude_blog",
            "content_type": "blog",
        },
    ]

    custom_settings: dict[str, Any] = {
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 4.0,
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_TIMEOUT": 30,
        "RETRY_TIMES": 3,
        "DEPTH_LIMIT": 3,
    }

    def __init__(
        self,
        max_pages: int = 0,
        output_dir: str = "output",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_pages = int(max_pages)
        self.output_dir = output_dir
        # Bloom filter: 10K URLs, 0.01% FP rate
        self.seen: Bloom = Bloom(10000, 0.0001)
        self._stats: dict[str, int] = {
            "seeds": len(self.SEEDS),
            "links_discovered": 0,
            "pages_fetched": 0,
            "pages_skipped_dedup": 0,
            "pages_skipped_path": 0,
            "pages_failed": 0,
        }

    def start_requests(self) -> Generator[scrapy.Request, None, None]:
        """Yield initial requests for each seed URL."""
        for seed in self.SEEDS:
            url = seed["url"]
            self.seen.add(url)
            self.logger.info("Seeding: %s (%s)", seed["source"], url)
            yield scrapy.Request(
                url,
                callback=self.parse_page,
                cb_kwargs={
                    "source": seed["source"],
                    "content_type": seed["content_type"],
                    "is_seed": True,
                },
                errback=self.handle_error,
            )

    def parse_page(
        self,
        response: Response,
        *,
        source: str,
        content_type: str,
        is_seed: bool = False,
    ) -> Generator[scrapy.Request | DocPageItem, None, None]:
        """Extract content from an HTML page and follow internal links."""
        if self.max_pages and self._stats["pages_fetched"] >= self.max_pages:
            return

        self._stats["pages_fetched"] += 1

        # Extract structured content
        title = self._extract_title(response)
        description = self._extract_description(response)
        headings = self._extract_headings(response)
        body_text = self._extract_body_text(response)
        content_hash = hashlib.sha256(body_text.encode()).hexdigest()

        item = DocPageItem()
        item["url"] = response.url
        item["title"] = title
        item["description"] = description
        item["headings"] = headings
        item["body_markdown"] = body_text
        item["content_length"] = len(body_text)
        item["crawled_at"] = datetime.now(timezone.utc).isoformat()
        item["source"] = source
        item["content_type"] = content_type
        item["content_hash"] = content_hash

        yield item

        # Follow internal links (from seed/listing pages, or article pages with depth)
        if isinstance(response, HtmlResponse):
            yield from self._follow_links(response, source=source, content_type=content_type)

    def _follow_links(
        self,
        response: HtmlResponse,
        *,
        source: str,
        content_type: str,
    ) -> Generator[scrapy.Request, None, None]:
        """Discover and follow internal links on the same domain."""
        parsed_base = urlparse(response.url)
        base_domain = parsed_base.netloc

        for href in response.css("a::attr(href)").getall():
            abs_url = urljoin(response.url, href)
            parsed = urlparse(abs_url)

            # Strip fragment
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"

            # Same domain only
            if parsed.netloc != base_domain:
                continue

            # Skip non-content paths
            if SKIP_PATHS.search(parsed.path):
                self._stats["pages_skipped_path"] += 1
                continue

            # Bloom dedup
            if clean_url in self.seen:
                self._stats["pages_skipped_dedup"] += 1
                continue

            # Max pages guard
            if self.max_pages and self._stats["pages_fetched"] >= self.max_pages:
                return

            self.seen.add(clean_url)
            self._stats["links_discovered"] += 1

            # Classify child content type from URL pattern
            child_type = self._classify_url(clean_url, source, content_type)

            yield scrapy.Request(
                clean_url,
                callback=self.parse_page,
                cb_kwargs={
                    "source": source,
                    "content_type": child_type,
                    "is_seed": False,
                },
                errback=self.handle_error,
            )

    def _classify_url(self, url: str, source: str, parent_type: str) -> str:
        """Classify a discovered URL into a content type."""
        path = urlparse(url).path.lower()

        if source == "transformer_circuits":
            if re.search(r"/\d{4}/", path):
                return "paper"
            return "research"

        if source in ("anthropic_engineering", "anthropic_research"):
            if "/engineering/" in path:
                return "engineering"
            if "/research/" in path:
                return "research"
            if "/news/" in path:
                return "news"
            return parent_type

        if source == "neuroai_science":
            if "/p/" in path:
                return "article"
            return "listing"

        if source == "claude_blog":
            if "/blog/" in path and path != "/blog/" and path != "/blog":
                return "blog_post"
            return "blog"

        return parent_type

    def handle_error(self, failure: Failure) -> None:
        """Log errors without crashing the crawl."""
        self._stats["pages_failed"] += 1
        url = failure.request.url  # type: ignore[attr-defined]
        failure_type = failure.type
        type_name = failure_type.__name__ if failure_type else "Unknown"
        self.logger.error("ERROR: %s fetching %s", type_name, url)

    def closed(self, reason: str) -> None:
        """Log crawl summary on close."""
        self.logger.info(
            "Crawl complete: seeds=%d discovered=%d fetched=%d "
            "dedup_skipped=%d path_skipped=%d failed=%d reason=%s",
            self._stats["seeds"],
            self._stats["links_discovered"],
            self._stats["pages_fetched"],
            self._stats["pages_skipped_dedup"],
            self._stats["pages_skipped_path"],
            self._stats["pages_failed"],
            reason,
        )

    # ── HTML Content Extraction ─────────────────────────────────────

    @staticmethod
    def _extract_title(response: Response) -> str:
        """Extract page title from <title>, og:title, or first <h1>."""
        if isinstance(response, HtmlResponse):
            # Try og:title first (most accurate for articles)
            og = response.css('meta[property="og:title"]::attr(content)').get()
            if og:
                return og.strip()

            # <title> tag
            title = response.css("title::text").get()
            if title:
                # Strip common suffixes like " | Anthropic"
                title = re.sub(r"\s*[|–—-]\s*(?:Anthropic|Claude).*$", "", title)
                return title.strip()

            # First h1
            h1 = response.css("h1::text").get()
            if h1:
                return h1.strip()

        return ""

    @staticmethod
    def _extract_description(response: Response) -> str:
        """Extract description from meta tags."""
        if isinstance(response, HtmlResponse):
            og = response.css('meta[property="og:description"]::attr(content)').get()
            if og:
                return og.strip()

            meta = response.css('meta[name="description"]::attr(content)').get()
            if meta:
                return meta.strip()

        return ""

    @staticmethod
    def _extract_headings(response: Response) -> list[dict[str, Any]]:
        """Extract all heading elements as structured data."""
        headings: list[dict[str, Any]] = []
        if isinstance(response, HtmlResponse):
            for level in range(1, 7):
                for heading in response.css(f"h{level}"):
                    text = heading.css("::text").getall()
                    joined = " ".join(t.strip() for t in text if t.strip())
                    if joined:
                        headings.append({"level": level, "text": joined})
        return headings

    @staticmethod
    def _extract_body_text(response: Response) -> str:
        """Extract the main textual content from the page.

        Tries common article/content selectors, falls back to <body>.
        Strips navigation, footer, and script elements.
        """
        if not isinstance(response, HtmlResponse):
            return response.text

        # Try content-specific selectors in priority order
        selectors = [
            "article",
            '[role="main"]',
            "main",
            ".post-content",
            ".article-content",
            ".entry-content",
            ".content",
            "#content",
            ".prose",
        ]

        for sel in selectors:
            node = response.css(sel)
            if node:
                # Remove script, style, nav, footer, header
                texts = node.css(
                    ":not(script):not(style):not(nav):not(footer):not(header)::text"
                ).getall()
                body = "\n".join(t.strip() for t in texts if t.strip())
                if len(body) > 100:
                    return body

        # Fallback: entire body text
        texts = response.css("body ::text").getall()
        return "\n".join(t.strip() for t in texts if t.strip())
