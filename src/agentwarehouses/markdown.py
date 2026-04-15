"""Markdown parser optimized for Claude Code document extraction.

Uses markdown-it-py's AST for structured parsing instead of regex,
replacing the duplicated _extract_title/_extract_description/_extract_headings
methods across all three spiders (llmstxt, neon_docs, claude_builder).

Designed for reuse: session traces, blog posts, Clio facet extraction,
and any future markdown file processing.

Usage:
    from agentwarehouses.markdown import MarkdownParser

    parser = MarkdownParser()
    result = parser.parse(text)

    result.title          # First H1 text
    result.description    # First blockquote text
    result.headings       # [{"level": 1, "text": "..."}, ...]
    result.code_blocks    # [{"lang": "python", "code": "..."}, ...]
    result.links          # [{"text": "...", "href": "..."}, ...]
    result.sections       # [{"level": 2, "title": "...", "body": "..."}, ...]
    result.frontmatter    # YAML frontmatter dict (if present)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token


@dataclass
class Heading:
    """A single heading extracted from markdown."""

    level: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "text": self.text}


@dataclass
class CodeBlock:
    """A fenced code block."""

    lang: str
    code: str


@dataclass
class Link:
    """A hyperlink extracted from inline content."""

    text: str
    href: str


@dataclass
class Section:
    """A heading and its body content until the next heading of equal/higher level."""

    level: int
    title: str
    body: str


@dataclass
class ParseResult:
    """Structured output from parsing a markdown document.

    Fields match what the spiders extract, plus additional structure
    useful for Clio, sessions, and future parsers.
    """

    title: str = ""
    description: str = ""
    headings: list[Heading] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body_text: str = ""

    def headings_as_dicts(self) -> list[dict[str, Any]]:
        """Return headings in the same format spiders currently use."""
        return [h.to_dict() for h in self.headings]


# Regex for YAML frontmatter block at start of document
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)

# HTML fallbacks (for non-markdown pages)
_HTML_TITLE_RE = re.compile(r"<title>([^<]+)</title>")
_HTML_META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"')


class MarkdownParser:
    """AST-based markdown parser using markdown-it-py.

    Replaces the regex-based extraction duplicated across spiders.
    Thread-safe: the MarkdownIt instance is stateless after init.
    """

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark", {"breaks": False, "html": True})

    def parse(self, text: str) -> ParseResult:
        """Parse markdown text into structured components.

        Handles:
          - YAML frontmatter (stripped before AST parsing)
          - Headings (H1-H6) with level and text
          - First H1 as title
          - First blockquote as description
          - Fenced code blocks with language
          - Links from inline content
          - Sections (heading + body until next heading)
          - Fallback to HTML <title> and <meta description>
        """
        result = ParseResult()

        # Extract frontmatter before parsing
        body = text
        fm_match = _FRONTMATTER_RE.match(text)
        if fm_match:
            result.frontmatter = self._parse_frontmatter(fm_match.group(1))
            body = text[fm_match.end():]

        tokens = self._md.parse(body)

        self._extract_headings(tokens, result)
        self._extract_blockquote(tokens, result)
        self._extract_code_blocks(tokens, result)
        self._extract_links(tokens, result)
        self._extract_body_text(tokens, result)
        self._extract_sections(tokens, result)

        # HTML fallbacks for title and description
        if not result.title:
            m = _HTML_TITLE_RE.search(text)
            if m:
                result.title = m.group(1).strip()

        if not result.description:
            m = _HTML_META_DESC_RE.search(text)
            if m:
                result.description = m.group(1).strip()

        return result

    def parse_file(self, path: str) -> ParseResult:
        """Parse a markdown file from disk."""
        from pathlib import Path
        return self.parse(Path(path).read_text(encoding="utf-8"))

    # ── Extraction methods ───────────────────────────────────────────

    @staticmethod
    def _extract_headings(tokens: list[Token], result: ParseResult) -> None:
        """Extract all headings; set title from first H1."""
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.type == "heading_open" and tok.tag:
                level = int(tok.tag[1])  # h1 -> 1, h2 -> 2, etc.
                # Next token is inline with the heading text
                if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                    text = tokens[i + 1].content.strip()
                    result.headings.append(Heading(level=level, text=text))
                    if level == 1 and not result.title:
                        result.title = text
            i += 1

    @staticmethod
    def _extract_blockquote(tokens: list[Token], result: ParseResult) -> None:
        """Extract description from first blockquote."""
        in_blockquote = False
        for tok in tokens:
            if tok.type == "blockquote_open":
                in_blockquote = True
            elif tok.type == "blockquote_close":
                if result.description:
                    return  # Only take the first blockquote
                in_blockquote = False
            elif in_blockquote and tok.type == "inline" and not result.description:
                result.description = tok.content.strip()

    @staticmethod
    def _extract_code_blocks(tokens: list[Token], result: ParseResult) -> None:
        """Extract fenced code blocks with language annotation."""
        for tok in tokens:
            if tok.type == "fence":
                lang = tok.info.strip().split()[0] if tok.info.strip() else ""
                result.code_blocks.append(CodeBlock(lang=lang, code=tok.content))

    @staticmethod
    def _extract_links(tokens: list[Token], result: ParseResult) -> None:
        """Extract links from inline token children."""
        for tok in tokens:
            if tok.type == "inline" and tok.children:
                i = 0
                children = tok.children
                while i < len(children):
                    child = children[i]
                    if child.type == "link_open" and child.attrs:
                        href = child.attrs.get("href", "")
                        # Collect text from following tokens until link_close
                        link_text_parts: list[str] = []
                        i += 1
                        while i < len(children) and children[i].type != "link_close":
                            if children[i].content:
                                link_text_parts.append(children[i].content)
                            i += 1
                        result.links.append(Link(
                            text="".join(link_text_parts),
                            href=str(href),
                        ))
                    i += 1

    @staticmethod
    def _extract_body_text(tokens: list[Token], result: ParseResult) -> None:
        """Extract plain body text from paragraphs (no headings, no code)."""
        parts: list[str] = []
        in_heading = False
        in_code = False
        for tok in tokens:
            if tok.type == "heading_open":
                in_heading = True
            elif tok.type == "heading_close":
                in_heading = False
            elif tok.type == "fence":
                in_code = True
            elif tok.type in ("fence_close", "code_block"):
                in_code = False
            elif tok.type == "inline" and not in_heading and not in_code:
                parts.append(tok.content)
        result.body_text = "\n".join(parts)

    @staticmethod
    def _extract_sections(tokens: list[Token], result: ParseResult) -> None:
        """Split document into sections by heading.

        Each section contains the heading and all body content until
        the next heading of equal or higher level.
        """
        current_section: Section | None = None
        body_parts: list[str] = []
        in_heading = False

        for tok in tokens:
            if tok.type == "heading_open" and tok.tag:
                # Close previous section
                if current_section is not None:
                    current_section.body = "\n".join(body_parts).strip()
                    result.sections.append(current_section)
                    body_parts = []

                level = int(tok.tag[1])
                current_section = Section(level=level, title="", body="")
                in_heading = True

            elif tok.type == "heading_close":
                in_heading = False

            elif tok.type == "inline" and in_heading and current_section is not None:
                current_section.title = tok.content.strip()

            elif tok.type == "inline" and not in_heading:
                body_parts.append(tok.content)

            elif tok.type == "fence":
                body_parts.append(f"```{tok.info}\n{tok.content}```")

        # Close final section
        if current_section is not None:
            current_section.body = "\n".join(body_parts).strip()
            result.sections.append(current_section)

    @staticmethod
    def _parse_frontmatter(raw: str) -> dict[str, Any]:
        """Parse YAML frontmatter string into a dict.

        Uses yaml.safe_load if available, falls back to simple key: value parsing.
        """
        try:
            import yaml
            return yaml.safe_load(raw) or {}
        except Exception:
            # Fallback: simple key: value parsing
            result: dict[str, Any] = {}
            for line in raw.strip().split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    result[key.strip()] = val.strip().strip('"').strip("'")
            return result
