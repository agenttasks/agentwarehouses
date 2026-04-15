"""Markdown parser optimized for Claude Code document extraction.

Design follows conventional-commits/parser principles:
  1. Single-pass token walker produces an immutable AST (DocumentAST)
  2. Pure accessor functions query the AST — no mutation
  3. ParseResult is a convenience format built from the AST
     (like conventional-commits' toConventionalChangelogFormat)
  4. HTML fallbacks are a separate layer, not mixed into parsing

Uses markdown-it-py's token stream as input. Replaces the duplicated
regex extraction across all three spiders.

Usage:
    from agentwarehouses.markdown import MarkdownParser

    parser = MarkdownParser()
    result = parser.parse(text)

    result.title          # First H1 text
    result.description    # First blockquote text
    result.headings       # [Heading(level=1, text="..."), ...]
    result.code_blocks    # [CodeBlock(lang="python", code="..."), ...]
    result.links          # [Link(text="...", href="..."), ...]
    result.sections       # [Section(level=2, title="...", body="..."), ...]
    result.frontmatter    # YAML frontmatter dict (if present)
    result.ast            # The immutable DocumentAST for custom queries
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

# ═══════════════════════════════════════════════════════════════════════
# Layer 1: Immutable AST nodes (like unist in conventional-commits)
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Heading:
    """A heading node. Immutable."""

    level: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "text": self.text}


@dataclass(frozen=True)
class CodeBlock:
    """A fenced code block node. Immutable."""

    lang: str
    code: str


@dataclass(frozen=True)
class Link:
    """A hyperlink node. Immutable."""

    text: str
    href: str


@dataclass(frozen=True)
class Paragraph:
    """A paragraph text node. Immutable."""

    text: str
    in_blockquote: bool = False


@dataclass(frozen=True)
class Section:
    """A heading and its body content until the next heading. Immutable."""

    level: int
    title: str
    body: str


@dataclass(frozen=True)
class DocumentAST:
    """Immutable AST produced by a single pass over markdown-it tokens.

    This is the intermediate representation — analogous to the unist tree
    in conventional-commits/parser. All accessor functions operate on this.
    """

    headings: tuple[Heading, ...]
    paragraphs: tuple[Paragraph, ...]
    code_blocks: tuple[CodeBlock, ...]
    links: tuple[Link, ...]
    sections: tuple[Section, ...]
    frontmatter: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════
# Layer 2: Convenience format (like toConventionalChangelogFormat)
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ParseResult:
    """Convenience format built from the AST.

    Provides the same fields spiders relied on, plus the underlying AST
    for custom queries. Read-only after construction.
    """

    title: str = ""
    description: str = ""
    headings: list[Heading] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body_text: str = ""
    ast: DocumentAST | None = None

    def headings_as_dicts(self) -> list[dict[str, Any]]:
        """Return headings in spider-compatible format."""
        return [h.to_dict() for h in self.headings]


# ═══════════════════════════════════════════════════════════════════════
# Layer 3: Single-pass token walker (the parser)
# ═══════════════════════════════════════════════════════════════════════

# Frontmatter regex (applied before token parsing)
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    """Parse YAML frontmatter string into a dict."""
    try:
        import yaml

        return yaml.safe_load(raw) or {}
    except Exception:
        result: dict[str, Any] = {}
        for line in raw.strip().split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                result[key.strip()] = val.strip().strip('"').strip("'")
        return result


def _walk_tokens(tokens: list[Token]) -> DocumentAST:
    """Single pass over markdown-it tokens to build the immutable AST.

    This is the core parser — analogous to conventional-commits/parser's
    grammar walker. Every token is visited exactly once. Block-level state
    (heading, blockquote) is tracked via flags; leaf nodes (inline, fence)
    produce AST nodes.
    """
    headings: list[Heading] = []
    paragraphs: list[Paragraph] = []
    code_blocks: list[CodeBlock] = []
    links: list[Link] = []

    # Section builder state — runs in the same pass
    sections: list[Section] = []
    section_title = ""
    section_level = 0
    section_body: list[str] = []
    in_section = False

    # Block-level state
    in_heading = False
    in_blockquote = False
    heading_level = 0

    for tok in tokens:
        # ── Block-level state transitions ────────────────────────
        if tok.type == "heading_open" and tok.tag:
            # Close previous section
            if in_section:
                sections.append(
                    Section(
                        level=section_level,
                        title=section_title,
                        body="\n".join(section_body).strip(),
                    )
                )
                section_body = []

            in_heading = True
            heading_level = int(tok.tag[1])
            section_level = heading_level
            section_title = ""
            in_section = True

        elif tok.type == "heading_close":
            in_heading = False

        elif tok.type == "blockquote_open":
            in_blockquote = True

        elif tok.type == "blockquote_close":
            in_blockquote = False

        # ── Leaf nodes ───────────────────────────────────────────
        elif tok.type == "fence":
            lang = tok.info.strip().split()[0] if tok.info.strip() else ""
            code_blocks.append(CodeBlock(lang=lang, code=tok.content))
            # Include in section body
            section_body.append(f"```{tok.info}\n{tok.content}```")

        elif tok.type == "inline":
            text = tok.content.strip()
            if in_heading:
                headings.append(Heading(level=heading_level, text=text))
                section_title = text
            else:
                paragraphs.append(Paragraph(text=text, in_blockquote=in_blockquote))
                section_body.append(text)

            # Extract links from inline children (same pass)
            if tok.children:
                _collect_links(tok.children, links)

    # Close final section
    if in_section:
        sections.append(
            Section(
                level=section_level,
                title=section_title,
                body="\n".join(section_body).strip(),
            )
        )

    return DocumentAST(
        headings=tuple(headings),
        paragraphs=tuple(paragraphs),
        code_blocks=tuple(code_blocks),
        links=tuple(links),
        sections=tuple(sections),
    )


def _collect_links(children: list[Token], links: list[Link]) -> None:
    """Extract links from inline token children."""
    i = 0
    while i < len(children):
        child = children[i]
        if child.type == "link_open" and child.attrs:
            href = str(child.attrs.get("href", ""))
            text_parts: list[str] = []
            i += 1
            while i < len(children) and children[i].type != "link_close":
                if children[i].content:
                    text_parts.append(children[i].content)
                i += 1
            links.append(Link(text="".join(text_parts), href=href))
        i += 1


# ═══════════════════════════════════════════════════════════════════════
# Layer 4: Pure accessors on the AST
# ═══════════════════════════════════════════════════════════════════════


def _title_from_ast(ast: DocumentAST) -> str:
    """First H1 heading text, or empty string."""
    for h in ast.headings:
        if h.level == 1:
            return h.text
    return ""


def _description_from_ast(ast: DocumentAST) -> str:
    """First blockquote paragraph text, or empty string."""
    for p in ast.paragraphs:
        if p.in_blockquote:
            return p.text
    return ""


def _body_text_from_ast(ast: DocumentAST) -> str:
    """All paragraph text outside blockquotes, joined by newlines."""
    return "\n".join(p.text for p in ast.paragraphs if not p.in_blockquote)


# ═══════════════════════════════════════════════════════════════════════
# Layer 5: HTML fallback (separate concern from markdown parsing)
# ═══════════════════════════════════════════════════════════════════════

_HTML_TITLE_RE = re.compile(r"<title>([^<]+)</title>")
_HTML_META_DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]+)"')


def _apply_html_fallbacks(result: ParseResult, raw_text: str) -> None:
    """Fill title/description from HTML tags if markdown parsing found nothing."""
    if not result.title:
        m = _HTML_TITLE_RE.search(raw_text)
        if m:
            result.title = m.group(1).strip()

    if not result.description:
        m = _HTML_META_DESC_RE.search(raw_text)
        if m:
            result.description = m.group(1).strip()


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════


class MarkdownParser:
    """AST-based markdown parser using markdown-it-py.

    Pipeline: frontmatter → single-pass token walk → immutable AST
    → pure accessors → convenience ParseResult → HTML fallbacks.

    Thread-safe: the MarkdownIt instance is stateless after init.
    """

    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark", {"breaks": False, "html": True})

    def parse(self, text: str) -> ParseResult:
        """Parse markdown text into structured components.

        Returns a ParseResult with both convenience fields and the
        underlying DocumentAST for custom queries.
        """
        # Pre-parse: extract frontmatter
        frontmatter: dict[str, Any] = {}
        body = text
        fm_match = _FRONTMATTER_RE.match(text)
        if fm_match:
            frontmatter = _parse_frontmatter(fm_match.group(1))
            body = text[fm_match.end() :]

        # Stage 1: Single-pass token walk → immutable AST
        tokens = self._md.parse(body)
        walked = _walk_tokens(tokens)
        ast = DocumentAST(
            headings=walked.headings,
            paragraphs=walked.paragraphs,
            code_blocks=walked.code_blocks,
            links=walked.links,
            sections=walked.sections,
            frontmatter=frontmatter,
        )

        # Stage 2: Pure accessors → convenience format
        result = ParseResult(
            title=_title_from_ast(ast),
            description=_description_from_ast(ast),
            headings=list(ast.headings),
            code_blocks=list(ast.code_blocks),
            links=list(ast.links),
            sections=list(ast.sections),
            frontmatter=frontmatter,
            body_text=_body_text_from_ast(ast),
            ast=ast,
        )

        # Stage 3: HTML fallback layer (separate concern)
        _apply_html_fallbacks(result, text)

        return result

    def parse_file(self, path: str) -> ParseResult:
        """Parse a markdown file from disk."""
        return self.parse(Path(path).read_text(encoding="utf-8"))
