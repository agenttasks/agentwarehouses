from agentwarehouses.spiders.llmstxt_spider import LlmstxtSpider


class TestLlmstxtSpider:
    def test_spider_name(self):
        spider = LlmstxtSpider()
        assert spider.name == "llmstxt"

    def test_default_index_url(self):
        spider = LlmstxtSpider()
        assert spider.index_url == "https://code.claude.com/docs/llms.txt"
        assert spider.start_urls == ["https://code.claude.com/docs/llms.txt"]

    def test_custom_index_url(self):
        spider = LlmstxtSpider(index_url="https://example.com/llms.txt")
        assert spider.index_url == "https://example.com/llms.txt"

    def test_bloom_filter_initialized(self):
        spider = LlmstxtSpider()
        assert spider.seen is not None
        spider.seen.add("https://example.com/test")
        assert "https://example.com/test" in spider.seen
        assert "https://example.com/other" not in spider.seen

    def test_extract_title(self):
        text = "# My Title\n\nSome content here."
        assert LlmstxtSpider._extract_title(text) == "My Title"

    def test_extract_title_missing(self):
        text = "No heading here, just text."
        assert LlmstxtSpider._extract_title(text) == ""

    def test_extract_description(self):
        text = "# Title\n\n> This is the description\n\nBody text."
        assert LlmstxtSpider._extract_description(text) == "This is the description"

    def test_extract_description_missing(self):
        text = "# Title\n\nNo blockquote here."
        assert LlmstxtSpider._extract_description(text) == ""

    def test_extract_headings(self):
        text = "# Title\n## Section One\n### Subsection\n## Section Two"
        headings = LlmstxtSpider._extract_headings(text)
        assert len(headings) == 4
        assert headings[0] == {"level": 1, "text": "Title"}
        assert headings[1] == {"level": 2, "text": "Section One"}
        assert headings[2] == {"level": 3, "text": "Subsection"}
        assert headings[3] == {"level": 2, "text": "Section Two"}

    def test_extract_headings_empty(self):
        text = "Just plain text without any headings."
        assert LlmstxtSpider._extract_headings(text) == []

    def test_allowed_domains(self):
        spider = LlmstxtSpider()
        assert spider.allowed_domains == ["code.claude.com"]

    def test_stats_initialized(self):
        spider = LlmstxtSpider()
        assert spider._stats == {"index_urls": 0, "pages_fetched": 0, "pages_failed": 0}
