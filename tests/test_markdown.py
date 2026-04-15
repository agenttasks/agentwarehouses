"""Tests for the markdown-it-py parser module.

Covers all extraction methods: title, description, headings, code blocks,
links, sections, frontmatter, body text, and HTML fallbacks. Also tests
backward compatibility with the spider _extract_* static method API.
"""
from __future__ import annotations

import pytest

from agentwarehouses.markdown import MarkdownParser

# ── Sample documents ─────────────────────────────────────────────────

CLAUDE_CODE_DOC = """\
# Claude Code overview

> An agentic coding tool for your terminal

## Getting started

Install Claude Code and start coding.

## Features

- Code editing
- File search

### Advanced features

Use hooks and MCP servers.
"""

FRONTMATTER_DOC = """\
---
title: "Test Document"
date: 2026-04-15
tags: [test, markdown]
---

# Actual Title

> Summary line

## Section One

Content here.
"""

CODE_BLOCKS_DOC = """\
# Installation

Install via pip:

```bash
pip install agentwarehouses
```

Then configure:

```python
from agentwarehouses import settings
settings.BOT_NAME = "ClaudeBot"
```

## Usage

Run the crawler.
"""

LINKS_DOC = """\
# Resources

Check the [documentation](https://docs.example.com) and
the [API reference](https://api.example.com/v1).

## Related

See [GitHub](https://github.com/example).
"""

HTML_FALLBACK_DOC = """\
<html>
<head>
<title>HTML Page Title</title>
<meta name="description" content="An HTML description">
</head>
<body>
<p>No markdown headings here.</p>
</body>
</html>
"""

EMPTY_DOC = ""

MINIMAL_DOC = "Just some plain text with no markdown structure."

DEEP_HEADINGS_DOC = """\
# H1
## H2
### H3
#### H4
##### H5
###### H6
"""


# ── Title extraction ─────────────────────────────────────────────────


@pytest.mark.unit
class TestTitle:
    def test_extracts_h1(self) -> None:
        result = MarkdownParser().parse("# My Title\n\nContent")
        assert result.title == "My Title"

    def test_first_h1_wins(self) -> None:
        result = MarkdownParser().parse("# First\n\n# Second")
        assert result.title == "First"

    def test_empty_when_no_heading(self) -> None:
        result = MarkdownParser().parse(MINIMAL_DOC)
        assert result.title == ""

    def test_empty_doc(self) -> None:
        result = MarkdownParser().parse(EMPTY_DOC)
        assert result.title == ""

    def test_h2_not_used_as_title(self) -> None:
        result = MarkdownParser().parse("## Section\n\nContent")
        assert result.title == ""

    def test_whitespace_stripped(self) -> None:
        result = MarkdownParser().parse("#   Padded Title  \n")
        assert result.title == "Padded Title"

    def test_html_title_fallback(self) -> None:
        result = MarkdownParser().parse(HTML_FALLBACK_DOC)
        assert result.title == "HTML Page Title"

    def test_markdown_preferred_over_html(self) -> None:
        text = "# Markdown Title\n<title>HTML Title</title>"
        result = MarkdownParser().parse(text)
        assert result.title == "Markdown Title"

    def test_frontmatter_title_not_used_as_title(self) -> None:
        result = MarkdownParser().parse(FRONTMATTER_DOC)
        assert result.title == "Actual Title"


# ── Description extraction ───────────────────────────────────────────


@pytest.mark.unit
class TestDescription:
    def test_extracts_blockquote(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert result.description == "An agentic coding tool for your terminal"

    def test_first_blockquote_only(self) -> None:
        text = "# T\n\n> First quote\n\n> Second quote"
        result = MarkdownParser().parse(text)
        assert result.description == "First quote"

    def test_empty_when_no_blockquote(self) -> None:
        result = MarkdownParser().parse("# T\n\nNo blockquote here")
        assert result.description == ""

    def test_html_meta_fallback(self) -> None:
        result = MarkdownParser().parse(HTML_FALLBACK_DOC)
        assert result.description == "An HTML description"

    def test_empty_doc(self) -> None:
        result = MarkdownParser().parse(EMPTY_DOC)
        assert result.description == ""


# ── Headings ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHeadings:
    def test_all_levels(self) -> None:
        result = MarkdownParser().parse(DEEP_HEADINGS_DOC)
        assert len(result.headings) == 6
        for i, h in enumerate(result.headings, 1):
            assert h.level == i
            assert h.text == f"H{i}"

    def test_claude_code_doc(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert len(result.headings) == 4
        assert result.headings[0].to_dict() == {"level": 1, "text": "Claude Code overview"}
        assert result.headings[1].to_dict() == {"level": 2, "text": "Getting started"}
        assert result.headings[2].to_dict() == {"level": 2, "text": "Features"}
        assert result.headings[3].to_dict() == {"level": 3, "text": "Advanced features"}

    def test_headings_as_dicts(self) -> None:
        result = MarkdownParser().parse("# Title\n## Section")
        dicts = result.headings_as_dicts()
        assert dicts == [
            {"level": 1, "text": "Title"},
            {"level": 2, "text": "Section"},
        ]

    def test_empty_doc(self) -> None:
        result = MarkdownParser().parse(EMPTY_DOC)
        assert result.headings == []

    def test_plain_text(self) -> None:
        result = MarkdownParser().parse(MINIMAL_DOC)
        assert result.headings == []


# ── Code blocks ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestCodeBlocks:
    def test_extracts_fenced_blocks(self) -> None:
        result = MarkdownParser().parse(CODE_BLOCKS_DOC)
        assert len(result.code_blocks) == 2

    def test_code_block_language(self) -> None:
        result = MarkdownParser().parse(CODE_BLOCKS_DOC)
        assert result.code_blocks[0].lang == "bash"
        assert result.code_blocks[1].lang == "python"

    def test_code_block_content(self) -> None:
        result = MarkdownParser().parse(CODE_BLOCKS_DOC)
        assert "pip install" in result.code_blocks[0].code
        assert "BOT_NAME" in result.code_blocks[1].code

    def test_no_code_blocks(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert result.code_blocks == []

    def test_unlabeled_code_block(self) -> None:
        text = "# T\n\n```\nplain code\n```\n"
        result = MarkdownParser().parse(text)
        assert len(result.code_blocks) == 1
        assert result.code_blocks[0].lang == ""


# ── Links ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestLinks:
    def test_extracts_links(self) -> None:
        result = MarkdownParser().parse(LINKS_DOC)
        assert len(result.links) == 3

    def test_link_text_and_href(self) -> None:
        result = MarkdownParser().parse(LINKS_DOC)
        doc_link = next(lnk for lnk in result.links if "documentation" in lnk.text)
        assert doc_link.href == "https://docs.example.com"

    def test_no_links(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert result.links == []


# ── Sections ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSections:
    def test_splits_into_sections(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert len(result.sections) == 4

    def test_section_titles(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        titles = [s.title for s in result.sections]
        assert titles == [
            "Claude Code overview",
            "Getting started",
            "Features",
            "Advanced features",
        ]

    def test_section_levels(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        levels = [s.level for s in result.sections]
        assert levels == [1, 2, 2, 3]

    def test_section_body_content(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        # The "Getting started" section body
        getting_started = result.sections[1]
        assert "Install Claude Code" in getting_started.body

    def test_empty_doc(self) -> None:
        result = MarkdownParser().parse(EMPTY_DOC)
        assert result.sections == []


# ── Frontmatter ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestFrontmatter:
    def test_extracts_frontmatter(self) -> None:
        from datetime import date

        result = MarkdownParser().parse(FRONTMATTER_DOC)
        assert result.frontmatter["title"] == "Test Document"
        assert result.frontmatter["date"] == date(2026, 4, 15)

    def test_frontmatter_tags(self) -> None:
        result = MarkdownParser().parse(FRONTMATTER_DOC)
        assert result.frontmatter["tags"] == ["test", "markdown"]

    def test_no_frontmatter(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert result.frontmatter == {}

    def test_frontmatter_stripped_from_parsing(self) -> None:
        result = MarkdownParser().parse(FRONTMATTER_DOC)
        # Title should come from the # heading, not frontmatter
        assert result.title == "Actual Title"
        # Frontmatter YAML delimiters should not appear as headings
        assert all("---" not in h.text for h in result.headings)


# ── Body text ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBodyText:
    def test_extracts_paragraph_text(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert "Install Claude Code" in result.body_text

    def test_excludes_heading_text(self) -> None:
        result = MarkdownParser().parse("# Title\n\nBody only")
        # body_text should not include heading text
        assert "Title" not in result.body_text
        assert "Body only" in result.body_text

    def test_empty_doc(self) -> None:
        result = MarkdownParser().parse(EMPTY_DOC)
        assert result.body_text == ""


# ── Parser reuse / thread-safety ─────────────────────────────────────


@pytest.mark.unit
class TestParserReuse:
    def test_parser_produces_consistent_results(self) -> None:
        parser = MarkdownParser()
        r1 = parser.parse(CLAUDE_CODE_DOC)
        r2 = parser.parse(CLAUDE_CODE_DOC)
        assert r1.title == r2.title
        assert len(r1.headings) == len(r2.headings)

    def test_parser_handles_different_docs(self) -> None:
        parser = MarkdownParser()
        r1 = parser.parse(CLAUDE_CODE_DOC)
        r2 = parser.parse(CODE_BLOCKS_DOC)
        assert r1.title != r2.title
        assert len(r1.code_blocks) != len(r2.code_blocks)


# ── Backward compatibility with spider API ───────────────────────────


@pytest.mark.integration
class TestSpiderBackcompat:
    """Verify the parser produces identical output to what spiders relied on."""

    def test_title_matches_regex(self) -> None:
        import re

        text = CLAUDE_CODE_DOC
        regex_title = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        parser_title = MarkdownParser().parse(text).title
        assert parser_title == regex_title.group(1).strip()  # type: ignore[union-attr]

    def test_description_matches_regex(self) -> None:
        import re

        text = CLAUDE_CODE_DOC
        regex_desc = re.search(r"^>\s*(.+)$", text, re.MULTILINE)
        parser_desc = MarkdownParser().parse(text).description
        assert parser_desc == regex_desc.group(1).strip()  # type: ignore[union-attr]

    def test_headings_match_regex(self) -> None:
        import re

        text = CLAUDE_CODE_DOC
        regex_headings = [
            {"level": len(m.group(1)), "text": m.group(2).strip()}
            for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE)
        ]
        parser_headings = MarkdownParser().parse(text).headings_as_dicts()
        assert parser_headings == regex_headings

    def test_html_title_fallback_matches_regex(self) -> None:
        import re

        text = HTML_FALLBACK_DOC
        regex_title = re.search(r"<title>([^<]+)</title>", text)
        parser_title = MarkdownParser().parse(text).title
        assert parser_title == regex_title.group(1).strip()  # type: ignore[union-attr]

    def test_html_meta_fallback_matches_regex(self) -> None:
        import re

        text = HTML_FALLBACK_DOC
        regex_desc = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', text)
        parser_desc = MarkdownParser().parse(text).description
        assert parser_desc == regex_desc.group(1).strip()  # type: ignore[union-attr]


# ── AST layer tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestDocumentAST:
    """Verify the immutable AST intermediate representation."""

    def test_ast_is_available(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert result.ast is not None

    def test_ast_headings_are_tuples(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert isinstance(result.ast.headings, tuple)

    def test_ast_paragraphs_are_tuples(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert isinstance(result.ast.paragraphs, tuple)

    def test_ast_nodes_are_frozen(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        with pytest.raises(AttributeError):
            result.ast.headings[0].text = "mutated"  # type: ignore[misc]

    def test_ast_frontmatter_attached(self) -> None:
        result = MarkdownParser().parse(FRONTMATTER_DOC)
        assert result.ast is not None
        assert result.ast.frontmatter["title"] == "Test Document"

    def test_ast_sections_match_convenience(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        assert len(result.ast.sections) == len(result.sections)
        for ast_s, conv_s in zip(result.ast.sections, result.sections):
            assert ast_s.title == conv_s.title
            assert ast_s.level == conv_s.level

    def test_ast_blockquote_paragraphs_flagged(self) -> None:
        result = MarkdownParser().parse(CLAUDE_CODE_DOC)
        bq_paras = [p for p in result.ast.paragraphs if p.in_blockquote]
        assert len(bq_paras) >= 1
        assert bq_paras[0].text == "An agentic coding tool for your terminal"

    def test_single_pass_produces_all_node_types(self) -> None:
        result = MarkdownParser().parse(CODE_BLOCKS_DOC)
        assert len(result.ast.headings) > 0
        assert len(result.ast.paragraphs) > 0
        assert len(result.ast.code_blocks) > 0
