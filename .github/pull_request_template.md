## Summary

<!-- 1-3 bullet points describing what this PR does -->

## Session context

<!-- Link to session trace if available (sessions/session_trace_*.md) -->

| Field | Value |
|-------|-------|
| Session ID | <!-- e.g. 01FSNRonfPyKuLgDezKEY3bq --> |
| Branch | <!-- e.g. claude/feature-name-y3UIf --> |
| Commits | <!-- count --> |

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Dependency update
- [ ] Documentation / session trace update

## Files changed

<!-- Summarize by component. Example:
| Component | Files | Tests |
|-----------|-------|-------|
| Spider    | `claude_builder_spider.py` | 72 |
| Parser    | `markdown.py` | 54 |
-->

## Parsing and markdown

<!-- If this PR touches markdown parsing, document:
- Which MarkdownParser features are used (headings, sections, code_blocks, links, frontmatter)
- Whether spider backward-compat tests pass (TestSpiderBackcompat)
- Whether AST immutability is preserved (TestDocumentAST)
-->

## Test plan

- [ ] `make lint` passes
- [ ] `make test-cov` passes (coverage >= 90%)
- [ ] `make typecheck` passes
- [ ] `ruff format --check` passes
- [ ] Backward-compat: parser output matches old regex extraction
- [ ] Tested manually (describe below)

## Checklist

- [ ] My code follows the project conventions (see CONTRIBUTING.md)
- [ ] I have added tests that prove my fix/feature works
- [ ] Commit messages follow conventional commits (`feat:`, `fix:`, `deps:`)
- [ ] Session trace updated if applicable (`sessions/session_trace_*.md`)
