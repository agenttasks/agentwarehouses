# Contributing to agentwarehouses

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (installed automatically by `make install-dev`)
- Git

## Setup

```bash
git clone https://github.com/agenttasks/agentwarehouses.git
cd agentwarehouses
make install-dev
```

## Development Workflow

1. **Create a branch** from `main`
2. **Make changes** — one feature per commit
3. **Run checks** before pushing:

```bash
make ci          # lint + test with 90% coverage threshold
```

Or individually:

```bash
make lint        # ruff check src/ tests/ scripts/
make test        # parallel tests (auto-detect CPUs)
make test-cov    # tests + coverage report
make typecheck   # mypy strict mode
```

## Test Markers

Tests are organized with pytest markers. Run subsets with:

```bash
make test-unit          # fast isolated unit tests
make test-models        # Pydantic model validation
make test-integration   # Scrapy response + filesystem tests
make test-evals         # AgentSkills.io eval schema validation
```

## Code Standards

### Return Types Required

All functions must have return type annotations. The project enforces `mypy --strict`.

```python
# Good
def process_item(self, item: Any, spider: scrapy.Spider) -> Any:

# Bad — missing return type
def process_item(self, item, spider):
```

### Coverage Threshold

Code coverage must stay above **90%** (currently 99.47%). The `make test-cov` target enforces this.

```bash
make test-cov    # fails if coverage drops below 90%
```

### Lint Rules

Ruff with `E`, `F`, `I`, `W` rules. Auto-fix with:

```bash
make lint-fix
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/) for release-please:

| Prefix | When | Version Bump |
|---|---|---|
| `feat(models):` | New model or field | minor |
| `fix(spider):` | Bug fix | patch |
| `deps(upstream):` | Upstream SDK bump | minor |
| `feat!:` | Breaking change | major |
| `docs:` | Documentation only | none |

## Project Structure

```
src/agentwarehouses/
  models/           — Pydantic 2.0 data models (19 modules, 125 types)
  spiders/          — Scrapy spider implementations
  pipelines/        — orjson writer, stats validator
  items.py          — DocPageItem schema
  log.py            — colorlog logger + OTEL config
  settings.py       — Scrapy settings (Claudebot config)
tests/
  conftest.py       — Shared fixtures + auto-markers
  test_spider.py    — Spider unit + integration tests
  test_pipelines.py — Pipeline tests
  test_log.py       — Logger + OTEL tests
  test_models.py    — Pydantic model validation (40 tests)
  test_eval_schema.py — AgentSkills.io eval validation
scripts/
  generate_crud_skills.py — Generates 36 CRUD skills from profiles
  install_pkgs.sh         — SessionStart hook for dependency install
.claude/
  agents/           — 10 persona subagents + 2 specialist agents
  skills/           — /crawl-audit, /think, /advisors, 36 CRUD skills
  hooks/            — post-edit-lint, log-tool-sizes
  rules/            — crawl-guidelines
  sessions/         — Session transcripts
```

## Adding a New Model

1. Create `src/agentwarehouses/models/{resource}.py`
2. Inherit from `BaseModel` (strict) or `LenientModel` (allows extras)
3. Add re-exports to `src/agentwarehouses/models/__init__.py`
4. Write tests in `tests/test_models.py`
5. Run `make ci` to verify

## Adding a New CRUD Skill

1. Add resource profile to `scripts/generate_crud_skills.py` in the `RESOURCES` dict
2. Run `make generate-skills`
3. Run `make test-evals` to validate generated evals
4. Optionally hand-edit the generated SKILL.md for richer content

## Adding a New Subagent

1. Create `.claude/agents/{name}.md` with YAML frontmatter:
   ```yaml
   ---
   name: agent-name
   description: >
     What this agent does and when to invoke it
   tools: Read, Grep, Glob, Bash
   model: opus
   ---
   ```
2. Write the system prompt body after the closing `---`
3. Include the emotional calibration section (see existing agents for template)
4. Add the agent to the `/advisors` skill if it's a general-purpose advisor

## SessionStart Hook

The project includes a SessionStart hook that runs `make install-dev` on both local and cloud sessions. This ensures dependencies are always current. See `.claude/settings.json` and `scripts/install_pkgs.sh`.
