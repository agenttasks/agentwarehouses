---
name: research-session
description: Manage research sessions for fetching, analyzing, and writing up documentation sites like transformer-circuits.pub. Maintains consistent session structure, page templates, scratchpad, and blog post output.
disable-model-invocation: false
---
# Research Session

## When to use

When researching documentation sites (transformer-circuits.pub, Anthropic system cards,
safety research papers) and you need structured note-taking with consistent output.

Use this skill to:
- Start a new research session for a topic
- Fetch and catalog pages from a documentation site
- Maintain a scratchpad of findings
- Write a styled blog post summarizing research

## Session lifecycle

### 1. Start a session

```python
from sessions.manager import SessionManager

mgr = SessionManager()
sid = mgr.create_session(topic="transformer-circuits-pub")
# Returns: "001" (or existing session ID if same topic today)
```

This creates `sessions/session_001/` with:
- `session.yaml` — auto-populated metadata (device, surface, user_agent, timestamps)
- `pages/` — directory for fetched page records
- `scratchpad.md` — initialized from template with checklist

### 2. Fetch and record pages

For each page you WebFetch, record it:

```python
mgr.add_page(
    sid,
    url="https://transformer-circuits.pub/2025/attribution-graphs/index.html",
    title="Circuit Tracing: Revealing Computational Graphs",
    content=fetched_content,
    content_type="article",
    metadata={"authors": "Ameisen et al.", "year": "2025"},
)
```

Pages get deterministic filenames: `{url_hash}_{title_slug}.yaml`

### 3. Record findings in scratchpad

```python
mgr.write_scratchpad(sid, "Key finding: attribution graphs reveal...")
```

Appends timestamped entries to `scratchpad.md`.

### 4. Write blog post

```python
mgr.write_blog_post(
    sid,
    title="Understanding Circuit Tracing",
    summary="How Anthropic maps computational graphs in Claude",
    body="## Background\n\n...",
    tags=["interpretability", "circuits", "safety"],
)
```

Renders `blog_post.md` from Jinja2 template with consistent frontmatter.

## Session directory structure

```
sessions/
  lookup.yaml                 # Append-only lookup table (all sessions)
  templates/
    scratchpad.md.j2          # Scratchpad template
    blog_post.md.j2           # Blog post template
  session_001/
    session.yaml              # Auto-populated session metadata
    pages/
      a1b2c3d4_circuit-tracing.yaml
      e5f6g7h8_attribution-graphs.yaml
    scratchpad.md             # Running research notes
    blog_post.md              # Final styled writeup
```

## Session metadata (auto-populated)

The `session.yaml` file is auto-populated with:

| Field | Source | Example |
|-------|--------|---------|
| id | Lookup table sequence | "001" |
| topic | User-provided | "transformer-circuits-pub" |
| slug | Derived from topic | "transformer-circuits-pub" |
| surface | `CLAUDE_CODE_ENTRYPOINT` env | "cli", "web", "ide", "sdk" |
| device | `platform.system()-machine` | "linux-x86_64" |
| user_agent | Default ClaudeBot | "ClaudeBot/1.0" |
| status | Lifecycle state | "active" |
| pages_fetched | Auto-incremented | 5 |
| last_updated | Auto-set on changes | ISO 8601 UTC |

## Lookup table (deterministic)

`sessions/lookup.yaml` is append-only. Same topic on the same day always
resolves to the same session (no duplicates). Format:

```yaml
- id: "001"
  topic: transformer-circuits-pub
  created: "2026-04-15T12:00:00+00:00"
  surface: cli
  device: linux-x86_64
  user_agent: ClaudeBot/1.0
  status: active
```

## Blog post style guide

Blog posts use a consistent format with:
- YAML frontmatter (title, date, author, tags, session, topic, status)
- Block quote summary
- Markdown body
- Session attribution footer

## Packages available (research extra)

These packages from Anthropic's safety-research repos are installed:

| Package | Purpose | Source repo |
|---------|---------|-------------|
| anthropic | Claude API | anthropics/anthropic-sdk-python |
| httpx | Async HTTP | anthropics/anthropic-sdk-python |
| beautifulsoup4 | HTML parsing | anthropics/anthropic-retrieval-demo |
| nltk | Text processing | anthropics/anthropic-retrieval-demo |
| tiktoken | Token counting | safety-research/safety-tooling |
| jinja2 | Templating | safety-research/safety-tooling |
| pyyaml | Config parsing | safety-research/bloom |
| rich | Terminal formatting | anthropics/anthropic-cookbook |
| wandb | Experiment tracking | safety-research/safety-tooling |
| matplotlib | Visualization | safety-research/safety-tooling |
| plotly | Interactive viz | safety-research/safety-tooling |
| pydantic | Data validation | anthropics/anthropic-sdk-python |
| tenacity | Retry logic | safety-research/safety-tooling |
| python-dotenv | Env config | anthropics/anthropic-cookbook |
