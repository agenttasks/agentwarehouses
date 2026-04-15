# Claude-UDA World Model Architecture

> A cross-device, cross-platform world model for Claude Code and Claude Co-work,
> powered by Neon Postgres 18 + pg_graphql, informed by Netflix UDA knowledge
> graphs and the Snowflake Labs Agent World Model synthesis pipeline.

## 1. Problem Statement

Claude Code operates across 6 surfaces (CLI, VS Code, JetBrains, Web, Desktop Mac,
Desktop Windows) and will soon coordinate teams of agents via Claude Co-work. Today,
each session is ephemeral — there is no unified model of the user's world that
persists across devices, surfaces, sessions, and agent teams.

**What we need**: A single source of truth — a "world model" — that captures:
- Who the user is and how they evolve (Type 2 SCD)
- What environments they work in (codebases, devices, surfaces)
- What the agent believes, plans, and does (actions, observations, reasoning)
- How agents coordinate (teams, tasks, messages)
- What outcomes result (task completion, code quality, user approval)

**Why Neon Postgres 18**: Serverless Postgres with branching, pg_graphql (zero-middleware
GraphQL), pgvector (embeddings), pg_cron (scheduled tasks), and connection pooling.
Replaces Snowflake's warehouse model with a serverless, always-on, GraphQL-native store
accessible from any device via a single endpoint.

---

## 2. Reference Architecture Sources

| Source | What We Take | What We Replace |
|--------|-------------|-----------------|
| **Netflix UDA** | Knowledge graph metamodel, domain-model-once/project-everywhere, semantic mappings between containers | Internal Netflix RDF infra → pg_graphql + Turtle files |
| **Snowflake AWM** | 5-stage synthesis pipeline (scenario→task→schema→spec→code→verify), trajectory recording, MCP-native environments | SQLite + Snowflake → Neon Postgres 18; OpenAI → Claude API |
| **Anthropic HF datasets** | values-in-the-wild (3,307 behavioral values), EconomicIndex (task penetration), alignment-faking-rl (safety testing) | Static CSVs → live dimension tables in the world model |
| **Claude Code extensibility** | 25 hook events, MCP protocol, skills/plugins/agent-teams, 37 built-in tools, memory scopes | File-based state → Postgres-backed persistent world state |

---

## 3. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT SURFACES                              │
│  CLI  │  VS Code  │  JetBrains  │  Web  │  Desktop  │  Co-work    │
└───┬───┴─────┬─────┴──────┬──────┴───┬───┴─────┬─────┴──────┬──────┘
    │         │            │          │         │            │
    ▼         ▼            ▼          ▼         ▼            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     HOOK EVENT BUS (25 events)                      │
│  SessionStart │ PreToolUse │ PostToolUse │ TaskCreated │ ...        │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  WORLD MODEL INGEST LAYER                           │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Event Router │  │  Trajectory  │  │  HuggingFace Data Loader │  │
│  │ (hook→fact)  │  │  Recorder    │  │  (values, econ, evals)   │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘  │
│         │                 │                        │                │
└─────────┼─────────────────┼────────────────────────┼────────────────┘
          │                 │                        │
          ▼                 ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│              NEON POSTGRES 18 — WORLD MODEL STORE                   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                 claude_world SCHEMA                          │    │
│  │                                                             │    │
│  │  DIMENSIONS          FACTS              WORLD STATE         │    │
│  │  ┌──────────┐  ┌────────────────┐  ┌──────────────────┐    │    │
│  │  │ dim_user  │  │ fact_session   │  │ world_snapshot   │    │    │
│  │  │ dim_device│  │ fact_tool_use  │  │ agent_belief     │    │    │
│  │  │ dim_model │  │ fact_message   │  │ codebase_context │    │    │
│  │  │ dim_tool  │  │ fact_hook_event│  │ environment_state│    │    │
│  │  │ dim_time  │  │ fact_trajectory│  │ memory_store     │    │    │
│  │  │ dim_surface│ │ fact_team_task │  │ skill_registry   │    │    │
│  │  │ dim_repo  │  │ fact_outcome   │  │ plugin_catalog   │    │    │
│  │  │ dim_skill │  │ fact_reasoning │  │ mcp_server_state │    │    │
│  │  │ dim_value │  │               │  │                  │    │    │
│  │  └──────────┘  └────────────────┘  └──────────────────┘    │    │
│  │                                                             │    │
│  │  EXTENSIONS                                                 │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │    │
│  │  │pg_graphql│  │ pgvector │  │ pg_cron  │  │pg_partman│   │    │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    pg_graphql AUTO-GENERATED API                     │
│                                                                     │
│  Query { dimUser, factSession, worldSnapshot, agentBelief, ... }    │
│  Mutation { insertFactToolUse, upsertWorldSnapshot, ... }           │
│  Subscription { onFactHookEvent, onTeamTaskUpdate, ... }            │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Foreign keys → nested GraphQL objects (automatic)            │  │
│  │  RLS policies → per-user/per-org data isolation              │  │
│  │  Comments → GraphQL descriptions + @graphql directives       │  │
│  └───────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
        ┌──────────┐    ┌──────────┐    ┌──────────────┐
        │ Claude   │    │ Agent    │    │ UDA Knowledge │
        │ Code     │    │ SDK      │    │ Graph (TTL)   │
        │ Surfaces │    │ Apps     │    │ Projections   │
        └──────────┘    └──────────┘    └──────────────┘
```

---

## 4. World Model Schema — Beyond Star Schema

The existing star schema (dim_user, fact_session, etc.) captures **telemetry**.
The world model adds three new schema families:

### 4.1 Trajectory Tables (from Snowflake AWM)

Captures the full agent reasoning loop, not just outcomes.

```
fact_trajectory
  trajectory_key   SERIAL PK
  session_key      FK → fact_session
  iteration        INT         -- turn number within session
  role             message_role
  tool_calls       JSONB       -- [{tool_name, arguments, tool_use_id}]
  tool_responses   JSONB       -- [{tool_use_id, content, duration_ms}]
  reasoning_text   TEXT        -- assistant's visible reasoning
  thinking_text    TEXT        -- extended thinking content
  thinking_tokens  INT
  timestamp        FK → dim_time

fact_reasoning (causal chain)
  reasoning_key    SERIAL PK
  trajectory_key   FK → fact_trajectory
  parent_key       FK → fact_reasoning (self-referential for chains)
  reasoning_type   reasoning_type  -- plan, observation, decision, correction
  content          TEXT
  confidence       NUMERIC(3,2)
  embedding        vector(384)     -- pgvector for semantic similarity
```

### 4.2 World State Tables (persistent agent beliefs)

Captures what the agent "knows" about the user's world at any point in time.

```
world_snapshot (Type 2 SCD — versioned world state)
  snapshot_key     SERIAL PK
  session_key      FK → fact_session
  user_key         FK → dim_user
  snapshot_type    snapshot_type  -- codebase, environment, preferences
  state_json       JSONB          -- flexible structured state
  embedding        vector(384)    -- semantic embedding of state
  effective_from   TIMESTAMPTZ
  effective_to     TIMESTAMPTZ    -- NULL = current
  is_current       BOOLEAN

codebase_context
  context_key      SERIAL PK
  user_key         FK → dim_user
  repo_key         FK → dim_repo
  branch           TEXT
  language_mix     JSONB       -- {"python": 0.6, "typescript": 0.3, ...}
  framework_stack  JSONB       -- ["scrapy", "pydantic", "zod"]
  file_count       INT
  test_coverage    NUMERIC(5,2)
  last_commit_sha  TEXT
  snapshot_at      TIMESTAMPTZ

agent_belief
  belief_key       SERIAL PK
  session_key      FK → fact_session
  belief_type      belief_type    -- user_intent, task_state, blocker, assumption
  content          TEXT
  confidence       NUMERIC(3,2)
  source           TEXT           -- what evidence supports this belief
  created_at       TIMESTAMPTZ
  invalidated_at   TIMESTAMPTZ    -- NULL = still held
  embedding        vector(384)

environment_state
  env_key          SERIAL PK
  device_key       FK → dim_device
  surface_key      FK → dim_user_surface
  env_vars_hash    TEXT           -- hash of relevant env vars (no secrets)
  git_status       JSONB          -- {branch, ahead, behind, dirty_files}
  mcp_servers      JSONB          -- [{name, status, tool_count}]
  active_plugins   JSONB          -- [{name, version, scope}]
  active_skills    JSONB          -- [{name, last_invoked}]
  recorded_at      TIMESTAMPTZ
```

### 4.3 Team Coordination Tables (from Claude Co-work)

```
dim_team
  team_key         SERIAL PK
  team_name        TEXT UNIQUE
  created_by       FK → dim_user
  created_at       TIMESTAMPTZ

fact_team_task
  task_key         SERIAL PK
  team_key         FK → dim_team
  session_key      FK → fact_session    -- lead session
  assignee_key     FK → dim_user        -- teammate
  task_id          TEXT
  subject          TEXT
  status           task_status
  dependencies     JSONB                -- [task_id, ...]
  created_at       FK → dim_time
  completed_at     FK → dim_time
  duration_seconds NUMERIC(12,2)

fact_team_message
  message_key      SERIAL PK
  team_key         FK → dim_team
  from_session     FK → fact_session
  to_session       FK → fact_session    -- NULL = broadcast
  content_length   INT
  message_type     TEXT                 -- message, broadcast, task_update
  sent_at          FK → dim_time
```

### 4.4 New Dimensions

```
dim_repo
  repo_key         SERIAL PK
  repo_url         TEXT UNIQUE
  repo_name        TEXT
  primary_language TEXT
  framework        TEXT
  loc              INT
  is_monorepo      BOOLEAN

dim_skill
  skill_key        SERIAL PK
  skill_name       TEXT UNIQUE
  source           TEXT         -- project, plugin, enterprise
  plugin_name      TEXT         -- NULL if not from plugin
  is_user_invocable BOOLEAN
  description      TEXT
  embedding        vector(384)

dim_value (from Anthropic's values-in-the-wild dataset)
  value_key        SERIAL PK
  value_name       TEXT UNIQUE
  category         TEXT         -- from HF dataset taxonomy
  description      TEXT
  embedding        vector(384)

dim_hook_event
  event_key        SERIAL PK
  event_name       TEXT UNIQUE  -- SessionStart, PreToolUse, ...
  event_category   TEXT         -- lifecycle, tool, team, config, io

fact_hook_event
  hook_event_key   SERIAL PK
  event_key        FK → dim_hook_event
  session_key      FK → fact_session
  time_key         FK → dim_time
  hook_type        TEXT         -- command, prompt, agent, http
  matcher          TEXT
  exit_code        SMALLINT
  duration_ms      INT
  decision         TEXT         -- allow, deny, ask, defer
  blocked          BOOLEAN

fact_outcome
  outcome_key      SERIAL PK
  session_key      FK → fact_session
  user_key         FK → dim_user
  task_description TEXT
  task_embedding   vector(384)
  completion       outcome_status  -- success, partial, failure, abandoned
  user_approved    BOOLEAN
  code_committed   BOOLEAN
  tests_passed     BOOLEAN
  files_changed    INT
  lines_added      INT
  lines_removed    INT
  pr_created       BOOLEAN
  evaluated_at     FK → dim_time
```

---

## 5. Neon Postgres 18 Extension Stack

| Extension | Role in World Model |
|-----------|-------------------|
| **pg_graphql** | Auto-generates GraphQL API from all tables. FK relationships become nested objects. RLS enforces per-user isolation. Zero middleware. |
| **pgvector** | Stores embeddings for agent beliefs, skill descriptions, values taxonomy, task descriptions. Enables semantic search across world state. |
| **pg_cron** | Scheduled jobs: dim_time population, stale belief invalidation, snapshot compaction, HuggingFace dataset sync. |
| **pg_partman** | Time-based partitioning for fact_trajectory (highest volume table). Monthly partitions with automatic creation. |
| **pg_jsonschema** | Validates JSONB columns (tool_calls, state_json, git_status) against stored schemas. |
| **pg_uuidv7** | Sortable UUIDs for distributed session IDs across surfaces. |
| **pgcrypto** | Hash sensitive fields (email, env vars) before storage. |
| **pg_session_jwt** | JWT-based auth for pg_graphql endpoint. User identity flows from Claude Code OAuth token → JWT → RLS policy. |

### pg_graphql Configuration

```sql
-- Expose world model schema
comment on schema claude_world is
  e'@graphql({"inflect_names": true})';

-- Example: nested query auto-generated from FKs
-- query {
--   factSessionCollection(filter: { userId: { eq: "user_123" } }) {
--     edges {
--       node {
--         sessionId
--         status
--         dimUser { email, planTier, orgName }
--         dimModel { modelId, modelFamily }
--         factToolUseCollection { edges { node {
--           dimTool { toolName, toolCategory }
--           durationMs
--           isCacheHit
--         }}}
--         factTrajectoryCollection(orderBy: [{ iteration: AscNullsLast }]) {
--           edges { node {
--             iteration
--             toolCalls
--             reasoningText
--           }}
--         }
--       }
--     }
--   }
-- }
```

---

## 6. AWM Synthesis Pipeline — Adapted for Claude Code

The Snowflake AWM generates synthetic tool-use environments. We adapt this for
Claude Code world model population and testing:

```
AWM PIPELINE (adapted)                 NEON POSTGRES TARGET
─────────────────────                  ────────────────────

Stage 1: Scenario Generation           dim_repo + codebase_context
  "Generate 1,000 realistic            (seed with real repo metadata
   Claude Code project scenarios"       from crawled GitHub data)

Stage 2: Task Generation               fact_outcome.task_description
  "For each scenario, generate          (10 tasks per scenario as
   10 realistic coding tasks"           ground truth for evaluation)

Stage 3: Schema Synthesis              claude_world schema itself
  "Generate Postgres DDL that           (the world model IS the schema;
   supports all tasks"                  AWM validates it end-to-end)

Stage 4: Environment Population        world_snapshot + environment_state
  "Populate with realistic state:       (INSERT realistic dimension and
   files, git history, MCP servers"     fact data for each scenario)

Stage 5: Agent Loop + Verification     fact_trajectory + fact_outcome
  "Run Claude Code agent, record        (trajectory = full action history;
   trajectory, verify completion"       outcome = did the task succeed?)
```

### Key Adaptation: MCP as the Universal Interface

The AWM exposes environments via MCP. Claude Code already speaks MCP natively.
The world model itself becomes an MCP server:

```
Claude Code Session
  ↓ (MCP tool call)
  world_model__query_belief(session_id, belief_type)
  world_model__record_trajectory(session_id, iteration, tool_calls)
  world_model__get_codebase_context(repo_url)
  world_model__upsert_snapshot(session_id, state_json)
  ↓ (pg_graphql)
  Neon Postgres 18
```

---

## 7. HuggingFace Data Integration

| Dataset | World Model Target | Sync Strategy |
|---------|-------------------|---------------|
| **values-in-the-wild** (3,307 values) | `dim_value` dimension table | One-time load + pg_cron weekly refresh |
| **EconomicIndex** (task penetration) | `fact_outcome` calibration — weight task types by real-world economic impact | Monthly sync from HF API |
| **AnthropicInterviewer** (1,250 transcripts) | `agent_belief` seed data — extract professional AI usage patterns | One-time ETL for belief priors |
| **alignment-faking-rl** (safety transcripts) | `fact_trajectory` test data — adversarial evaluation trajectories | Load into test branch (Neon branching) |
| **model-written-evals** (personality benchmarks) | `dim_value` + `fact_reasoning` — personality consistency baselines | One-time load |

### Neon Branching for HF Data Isolation

```
main branch (production world model)
  ├── hf-values-staging (load values-in-the-wild, validate, merge)
  ├── hf-econ-staging (load EconomicIndex updates, validate, merge)
  └── hf-safety-testing (load alignment-faking-rl, run evals, discard)
```

---

## 8. Cross-Device Sync Architecture

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│  CLI     │  │  VS Code │  │  Web     │  │  Co-work │
│  macOS   │  │  Linux   │  │  Browser │  │  Team    │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │             │
     │  Hook: SessionStart       │             │
     │  → record environment_state             │
     │  → fetch latest world_snapshot          │
     │  → load user preferences + beliefs      │
     │             │             │             │
     ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────┐
│           Neon Postgres 18 (Serverless)              │
│           Connection Pooling (pgbouncer)             │
│                                                     │
│   JWT auth → RLS → user sees only their data        │
│   pg_graphql → single /graphql endpoint             │
│   pgvector → semantic search across all state       │
│                                                     │
│   Same database, same schema, all devices.          │
└─────────────────────────────────────────────────────┘
```

### Hook-Based Sync Protocol

```json
// .claude/settings.json — hooks that maintain the world model
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "http",
        "url": "https://<neon-project>.neon.tech/graphql",
        "method": "POST",
        "body": "mutation { insertEnvironmentState(...) }"
      }]
    }],
    "PostToolUse": [{
      "hooks": [{
        "type": "command",
        "command": "world-model-ingest --event=tool_use"
      }]
    }],
    "TaskCompleted": [{
      "hooks": [{
        "type": "http",
        "url": "https://<neon-project>.neon.tech/graphql",
        "method": "POST",
        "body": "mutation { insertFactOutcome(...) }"
      }]
    }]
  }
}
```

---

## 9. UDA Projection Map

Following Netflix UDA's "model once, represent everywhere":

```
domain_model.ttl (single source of truth)
       │
       ├──→ schema.graphqls (pg_graphql serves this automatically)
       ├──→ schema.avro (Data Mesh / event streaming)
       ├──→ kimball_dimensions.ts (Zod — Agent SDK structured output)
       ├──→ kimball_facts.ts (Zod — Agent SDK structured output)
       ├──→ star_schema_pg_graphql.sql (Postgres DDL — executed on Neon)
       └──→ mappings.ttl (semantic links between all containers)

All projections are semantically equivalent.
The Postgres DDL is the executable truth; the others are projections.
```

---

## 10. Implementation Phases

### Phase 1: Foundation (Current Sprint)
- [x] Star schema DDL (dim_user through fact_message)
- [x] UDA domain model + GraphQL/Avro/Zod projections
- [x] Crawl Anthropic research corpus (1,512 pages)
- [ ] Deploy to Neon Postgres 18 with pg_graphql
- [ ] Validate auto-generated GraphQL API

### Phase 2: World State (Next Sprint)
- [ ] Add trajectory, reasoning, belief, and outcome tables
- [ ] Build MCP server that wraps pg_graphql for world model access
- [ ] Implement SessionStart hook → environment_state capture
- [ ] Implement PostToolUse hook → fact_trajectory recording
- [ ] Load values-in-the-wild into dim_value

### Phase 3: Agent Intelligence
- [ ] pgvector embeddings on beliefs, skills, values, tasks
- [ ] Semantic search: "find sessions where agent was stuck on similar problem"
- [ ] Belief persistence across sessions (world_snapshot SCD2)
- [ ] AWM-style synthetic environment generation adapted for Postgres

### Phase 4: Co-work & Teams
- [ ] Team coordination tables (dim_team, fact_team_task, fact_team_message)
- [ ] Cross-agent belief sharing via shared world_snapshot rows
- [ ] Task dependency graph stored in Postgres, queried via GraphQL
- [ ] Team performance analytics (velocity, coordination overhead)

### Phase 5: Closed-Loop Learning
- [ ] fact_outcome tracking (did tasks succeed? did user approve?)
- [ ] EconomicIndex integration for task impact weighting
- [ ] AWM verification pipeline adapted for Claude Code tasks
- [ ] Neon branching for A/B testing world model configurations
