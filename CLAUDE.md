# agentwarehouses

Scrapy-based llms.txt crawler that indexes Claude Code documentation pages.

## Build & Run

```bash
pip install -e ".[dev]"         # install with dev deps
scrapy crawl llmstxt            # run the crawler
scrapy crawl llmstxt -a output_dir=custom/path  # custom output dir
ruff check src/                 # lint
pytest tests/                   # test
```

## Architecture

- **Entry point**: `llmstxt` spider fetches `https://code.claude.com/docs/llms.txt`, extracts `.md` URLs
- **Dedup**: rbloom Bloom filter (not sets) — memory-efficient for large URL sets
- **Serialization**: orjson pipeline writes `output/docs.jsonl` as newline-delimited JSON
- **Quality gate**: `StatsValidatorPipeline` grades each crawled page for completeness
- **Concurrency**: AutoThrottle adapts rate; `CONCURRENT_REQUESTS=16`, `PER_DOMAIN=8`

## Conventions

- BOT_NAME is `Claudebot`, USER_AGENT identifies as `Claudebot/2.1.104`
- Always obey robots.txt (`ROBOTSTXT_OBEY = True`)
- Use absolute file paths in all tool calls and configs
- Keep test output minimal — log verbose data to files, use grep-friendly `ERROR:` lines
- Prefer `str_replace` with sufficient context for unique matches when editing
- When context is large, offload investigation to subagents; return condensed summaries

## Workflow

1. **Explore** (Plan Mode): read code, understand scope
2. **Plan**: create todos, identify files to change
3. **Implement**: one feature at a time, commit after each
4. **Verify**: run `scrapy crawl llmstxt`, check `output/docs.jsonl`, run `pytest`

## Context Management

- Use `/compact` between unrelated tasks
- Move reference material to `.claude/skills/` — skills cost nothing until invoked
- CLAUDE.md costs every request — keep under 200 lines
- Subagents get clean context; use for investigation, return summaries under 2000 tokens

## File Layout

```
src/agentwarehouses/
  settings.py          — Scrapy settings (Claudebot config, concurrency, pipelines)
  items.py             — DocPageItem schema
  spiders/             — Spider implementations
  pipelines/           — orjson writer, stats validator
.claude/
  settings.json        — Hooks (SessionStart, PostToolUse, Compaction)
  skills/              — Invocable skills (/crawl-audit, /think)
  agents/              — Subagents (page-analyzer, crawl-reviewer)
  rules/               — Project rules
  hooks/               — Hook scripts
```
