import scrapy


class DocPageItem(scrapy.Item):
    url = scrapy.Field()
    title = scrapy.Field()
    description = scrapy.Field()
    body_markdown = scrapy.Field()
    crawled_at = scrapy.Field()
