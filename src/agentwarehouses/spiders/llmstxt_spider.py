import re
from datetime import datetime, timezone

import scrapy
from rbloom import Bloom
from scrapy.spidermiddlewares.httperror import HttpError
from twisted.internet.error import DNSLookupError, TimeoutError

from agentwarehouses.items import DocPageItem


class LlmstxtSpider(scrapy.Spider):
    """Crawl every documentation page listed in llms.txt.

    The spider fetches the llms.txt index, extracts all .md page URLs,
    deduplicates them with a rbloom Bloom filter, and downloads each
    markdown page to extract title, description, and body content.

    Usage:
        scrapy crawl llmstxt
        scrapy crawl llmstxt -a index_url=https://example.com/llms.txt
    """

    name = "llmstxt"
    allowed_domains = ["code.claude.com"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
        "DOWNLOAD_DELAY": 0.25,
    }

    def __init__(self, index_url=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.index_url = index_url or "https://code.claude.com/docs/llms.txt"
        self.start_urls = [self.index_url]
        # Bloom filter: expect up to 500 URLs, false-positive rate 0.01%
        self.seen = Bloom(500, 0.0001)
        self._stats = {"index_urls": 0, "pages_fetched": 0, "pages_failed": 0}

    def parse(self, response):
        """Parse the llms.txt index and yield requests for each doc page."""
        text = response.text
        urls = re.findall(r"https://code\.claude\.com/docs/en/[\w./-]+\.md", text)
        self._stats["index_urls"] = len(urls)
        self.logger.info("Found %d documentation URLs in llms.txt", len(urls))

        for url in urls:
            if url not in self.seen:
                self.seen.add(url)
                yield scrapy.Request(
                    url,
                    callback=self.parse_doc_page,
                    errback=self.handle_error,
                )

    def parse_doc_page(self, response):
        """Extract content from a fetched markdown documentation page."""
        self._stats["pages_fetched"] += 1
        text = response.text

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

        yield item

    def handle_error(self, failure):
        """Log errors without crashing the crawl."""
        self._stats["pages_failed"] += 1
        url = failure.request.url

        if failure.check(HttpError):
            status = failure.value.response.status
            self.logger.error("ERROR: HTTP %d fetching %s", status, url)
        elif failure.check(DNSLookupError):
            self.logger.error("ERROR: DNS lookup failed for %s", url)
        elif failure.check(TimeoutError):
            self.logger.error("ERROR: Timeout fetching %s", url)
        else:
            self.logger.error("ERROR: %s fetching %s", failure.type.__name__, url)

    def closed(self, reason):
        """Log crawl summary stats on spider close."""
        self.logger.info(
            "Crawl complete: index_urls=%d fetched=%d failed=%d reason=%s",
            self._stats["index_urls"],
            self._stats["pages_fetched"],
            self._stats["pages_failed"],
            reason,
        )

    @staticmethod
    def _extract_title(text):
        """Extract title from first H1 heading."""
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_description(text):
        """Extract description from first blockquote."""
        match = re.search(r"^>\s*(.+)$", text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_headings(text):
        """Extract all headings as a list of (level, text) for structure analysis."""
        return [
            {"level": len(m.group(1)), "text": m.group(2).strip()}
            for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
        ]
