import re
from datetime import datetime, timezone

import scrapy
from rbloom import Bloom

from agentwarehouses.items import DocPageItem


class LlmstxtSpider(scrapy.Spider):
    """Crawl every documentation page listed in llms.txt.

    The spider fetches the llms.txt index, extracts all .md page URLs,
    deduplicates them with a rbloom Bloom filter, and downloads each
    markdown page to extract title, description, and body content.
    """

    name = "llmstxt"
    allowed_domains = ["code.claude.com"]
    start_urls = ["https://code.claude.com/docs/llms.txt"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
        "DOWNLOAD_DELAY": 0.25,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Bloom filter: expect up to 500 URLs, false-positive rate 0.01%
        self.seen = Bloom(500, 0.0001)

    def parse(self, response):
        """Parse the llms.txt index and yield requests for each doc page."""
        text = response.text
        urls = re.findall(r"https://code\.claude\.com/docs/en/[\w./-]+\.md", text)
        self.logger.info("Found %d documentation URLs in llms.txt", len(urls))

        for url in urls:
            if url not in self.seen:
                self.seen.add(url)
                yield scrapy.Request(url, callback=self.parse_doc_page)

    def parse_doc_page(self, response):
        """Extract content from a fetched markdown documentation page."""
        text = response.text

        # Extract title from first heading
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else ""

        # Extract description from blockquote after title
        desc_match = re.search(r"^>\s*(.+)$", text, re.MULTILINE)
        description = desc_match.group(1).strip() if desc_match else ""

        item = DocPageItem()
        item["url"] = response.url
        item["title"] = title
        item["description"] = description
        item["body_markdown"] = text
        item["crawled_at"] = datetime.now(timezone.utc).isoformat()

        yield item
