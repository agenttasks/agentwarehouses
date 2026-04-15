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

## 5. Neon Postgres 18 Extension Stack (Scale Plan)

**Neon Scale plan** ($69/mo): 16 CU autoscaling (64 GB RAM), 750 compute-hours/mo,
25 branches/project, read replicas, IP allowlisting, SOC 2, 100 GB network transfer.

| Extension | Role in World Model | Premium Feature |
|-----------|-------------------|-----------------|
| **pg_graphql** | Auto-generates GraphQL API from all tables. FK → nested objects. RLS → per-user isolation. | `@graphql` comment directives, `inflect_names` for camelCase |
| **pgvector** | HNSW indexes on beliefs, skills, values, interview transcripts. Sub-10ms semantic search. | 384-dim embeddings, HNSW (no training needed), cosine similarity |
| **pg_cron** | HF dataset sync (daily/weekly/monthly), dim_time population, stale belief invalidation. | Runs on primary compute endpoint |
| **pg_partman** | Monthly partitions on fact_trajectory (highest volume). Auto-creates future partitions. | Reduces query time on multi-million row trajectory table |
| **pg_mooncake** | Columnstore tables + DuckDB execution for analytics aggregations on fact tables. | 10-100x faster OLAP queries on star schema |
| **pgjwt** | JWT generation/validation in Postgres. Claude Code OAuth → JWT → RLS policy chain. | Cross-device auth without middleware |
| **pgcrypto** | Hash sensitive fields (email, env vars) before storage. | gen_random_uuid() for session IDs |
| **pg_uuidv7** | Sortable UUIDs for distributed session IDs across 6 surfaces. | Time-ordered for efficient B-tree indexing |
| **pgmq** | Message queue for async hook event ingestion (PostToolUse → queue → batch insert). | Decouples hook latency from Postgres write latency |
| **pg_tiktoken** | Token counting in Postgres (validate fact_message.token_count against HF baselines). | OpenAI-compatible tokenizer in SQL |

### Neon Premium Features Used

| Feature | How We Use It |
|---------|--------------|
| **Instant branching** | `hf-safety-testing` branch for 2.14M adversarial trajectories; `hf-staging` for weekly dataset sync; `awm-synthesis` for synthetic environment generation |
| **Autoscale 0.25→16 CU** | Idle at 0.25 CU ($0.03/hr); scale to 16 CU (64 GB) during ETL ingest and HNSW index builds; back to 0.25 within 5 min |
| **Read replicas** | Analytics queries (Grafana, Sphere-style reporting) hit read replica; hook event writes go to primary |
| **Point-in-time recovery** | Branch from any timestamp — replay world model state at the moment a bug was introduced |
| **IP allowlisting** | Restrict pg_graphql endpoint to Claude Code hook IPs + your dev machines |
| **Connection pooling** | PgBouncer transaction mode: 10,000 max client connections across all surfaces |
| **Consumption API** | Monitor compute/storage/network usage programmatically; alert on cost anomalies |

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

## 7. HuggingFace Data Integration — All 10 Datasets

Full DDL: `schema/hf_datasets_schema.sql`
ETL pipeline: `scripts/hf_etl_pipeline.py`

### 7.1 Dataset → World Model Mapping

| # | Dataset | Rows | World Model Role | Target Tables |
|---|---------|------|-----------------|---------------|
| 1 | **EconomicIndex** (15k DL) | Millions | Weight tasks by real-world economic impact; Opus 4.5/4.6 learning curves | `economic_index`, `economic_job_exposure` → calibrates `fact_outcome` |
| 2 | **AnthropicInterviewer** (1.5k DL) | 1,250 | Seed agent beliefs with professional AI usage patterns; pgvector semantic search | `interviewer_transcripts` (w/ HNSW embedding) → seeds `agent_belief` |
| 3 | **alignment-faking-rl** (556 DL) | 2.14M | Adversarial trajectory baselines for safety scoring | `alignment_faking` → baselines for `fact_trajectory` (safety branch) |
| 4 | **values-in-the-wild** (469 DL) | 6,910 | Behavioral value taxonomy (3,307 values + hierarchical clusters) | `values_frequencies` + `values_tree` → populates `dim_value` |
| 5 | **election_questions** (301 DL) | 2,600 | Domain-specific safety gates for sensitive topics | `election_questions` → `fact_outcome` safety calibration |
| 6 | **persuasion** (1.6k DL) | 3,939 | Calibrate agent confidence scoring (human vs model persuasiveness) | `persuasion` → calibrates `agent_belief.confidence` |
| 7 | **discrim-eval** (396 DL) | 18,900 | Bias detection baselines (70 scenarios × 135 demographics × 2 types) | `discrim_eval` → `fact_outcome` fairness auditing |
| 8 | **llm_global_opinions** (1.8k DL) | 2,556 | Cross-cultural consistency checks (Pew + World Values Survey) | `llm_global_opinions` → `agent_belief` consistency validation |
| 9 | **hh-rlhf** (35.8k DL) | 169k | Human preference pairs for response quality calibration | `hh_rlhf` + `hh_rlhf_red_team` → calibrates `fact_message` quality |
| 10 | **model-written-evals** | 1k-10k | Personality/sycophancy/safety benchmarks | `model_written_evals` → `dim_value` personality + `fact_reasoning` |

### 7.2 Premium Feature Usage

**HuggingFace Pro** ($9/mo):
- Parquet API for bulk dataset download (no row-by-row pagination)
- 2,500 API calls/5min (vs 1,000 free) — sync all 10 datasets in one pg_cron run
- 12,000 resolver calls/5min for metadata queries
- Private dataset storage for processed/enriched versions
- Data Studio on private datasets for validation before Postgres ingest

**Neon Scale** ($69/mo base):
- **Instant branching**: Load alignment-faking-rl (17.2 GB) and red-team data into
  isolated `hf-safety-testing` branch — zero impact on production
- **Autoscale to 16 CU** (64 GB RAM) during bulk ETL ingest, scale back to 0.25 CU at idle
- **Read replicas** for analytics queries while ETL writes to primary
- **750 compute-hours/mo** covers continuous pg_cron sync + query workload
- **pg_cron** schedules: daily EconomicIndex sync, weekly values refresh, monthly full resync
- **HNSW indexes** on pgvector columns for sub-10ms semantic search across beliefs/values

### 7.3 Neon Branching Strategy

```
main (production world model — always serving GraphQL via pg_graphql)
  │
  ├── hf-staging (weekly: sync all 10 datasets, validate, merge to main)
  │     └── pg_cron: SELECT cron.schedule('hf-sync', '0 3 * * 0', ...)
  │
  ├── hf-safety-testing (alignment-faking-rl + red-team data — never merged)
  │     └── 2.14M adversarial trajectories for isolated safety evaluation
  │     └── Branched from main, gets production dim_* tables automatically
  │
  ├── hf-econ-staging (monthly: EconomicIndex new releases)
  │     └── Validate Opus 4.6 learning curves before production exposure
  │
  └── awm-synthesis (AWM pipeline generates synthetic environments here)
        └── 1,000 scenarios × 10 tasks = 10,000 synthetic trajectories
        └── Verify against production dim_tool / dim_model, then merge facts
```

### 7.4 ETL Pipeline Architecture

```
HuggingFace Parquet API                    Neon Postgres 18
─────────────────────                      ────────────────
                                           
GET /parquet?dataset=Anthropic/X           ┌─── main branch ─────────┐
  → Parquet file URLs (S3 signed)          │ hf_anthropic schema     │
  → Download with httpx                    │   economic_index        │
  → Read with pyarrow                      │   interviewer_transcripts│
  → COPY INTO via psycopg3                 │   values_frequencies    │
  → Update sync_state                      │   persuasion            │
                                           │   discrim_eval          │
Scheduling (pg_cron):                      │   election_questions    │
  Daily:  EconomicIndex (new releases)     │   llm_global_opinions   │
  Weekly: values-in-the-wild refresh       │   hh_rlhf              │
  Monthly: full resync all 10 datasets     │   model_written_evals   │
                                           └─────────────────────────┘
                                           
                                           ┌─ hf-safety-testing ─────┐
                                           │   alignment_faking      │
                                           │   hh_rlhf_red_team     │
                                           └─────────────────────────┘
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
