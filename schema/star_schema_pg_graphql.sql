-- Claude-UDA Star Schema — Postgres 18 DDL with pg_graphql
--
-- Implements the Ralph Kimball star schema from domain_model.ttl.
-- pg_graphql auto-generates a GraphQL API from these tables, with
-- foreign key relationships becoming nested object fields.
--
-- Requirements: Postgres 18+, pg_graphql extension
-- Run: psql -f schema/star_schema_pg_graphql.sql

-- ════════════════════════════════════════════════════════════════════
-- Extensions & Schema
-- ════════════════════════════════════════════════════════════════════

create extension if not exists pg_graphql;

create schema if not exists claude_analytics;

comment on schema claude_analytics is
  'Claude Code session analytics star schema. '
  'UDA domain: https://rdf.agentwarehouses.dev/onto/claude#ClaudeAnalytics';

-- ════════════════════════════════════════════════════════════════════
-- Enumerations (Controlled Vocabularies)
-- ════════════════════════════════════════════════════════════════════

create type claude_analytics.plan_tier as enum (
  'free', 'pro', 'team', 'enterprise', 'max'
);
comment on type claude_analytics.plan_tier is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#PlanTier';

create type claude_analytics.surface_type as enum (
  'cli', 'vscode', 'jetbrains', 'web', 'desktop_mac', 'desktop_windows'
);
comment on type claude_analytics.surface_type is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#SurfaceType';

create type claude_analytics.model_family as enum (
  'opus', 'sonnet', 'haiku'
);
comment on type claude_analytics.model_family is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#ModelFamily';

create type claude_analytics.tool_category as enum (
  'read', 'write', 'edit', 'bash', 'search', 'agent', 'mcp', 'other'
);
comment on type claude_analytics.tool_category is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#ToolCategory';

create type claude_analytics.message_role as enum (
  'user', 'assistant', 'system', 'tool'
);
comment on type claude_analytics.message_role is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#MessageRole';

create type claude_analytics.session_status as enum (
  'active', 'completed', 'abandoned', 'errored', 'compacted'
);
comment on type claude_analytics.session_status is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#SessionStatus';

create type claude_analytics.device_os as enum (
  'macos', 'linux', 'windows', 'chromeos'
);
comment on type claude_analytics.device_os is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#DeviceOS';

-- ════════════════════════════════════════════════════════════════════
-- Conformed Dimensions
-- ════════════════════════════════════════════════════════════════════

-- DimUser — Type 2 Slowly Changing Dimension
create table claude_analytics.dim_user (
  user_key       integer generated always as identity primary key,
  user_id        text        not null,
  email          text        not null,
  plan_tier      claude_analytics.plan_tier not null,
  org_id         text,
  org_name       text,
  effective_from timestamptz not null default now(),
  effective_to   timestamptz,
  is_current     boolean     not null default true
);

comment on table claude_analytics.dim_user is
  'Type 2 SCD: each row is a version of a user''s profile. '
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#DimUser';

create index idx_dim_user_current on claude_analytics.dim_user (user_id)
  where is_current = true;

create index idx_dim_user_natural on claude_analytics.dim_user (user_id, effective_from);

-- DimDevice
create table claude_analytics.dim_device (
  device_key integer generated always as identity primary key,
  device_id  text    not null unique,
  os         claude_analytics.device_os not null,
  os_version text    not null,
  arch       text    not null,
  cpu_cores  integer,
  memory_gb  numeric(6,1)
);

comment on table claude_analytics.dim_device is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#DimDevice';

-- DimUserSurface
create table claude_analytics.dim_user_surface (
  surface_key       integer generated always as identity primary key,
  surface_type      claude_analytics.surface_type not null,
  surface_version   text not null,
  extension_version text
);

comment on table claude_analytics.dim_user_surface is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#DimUserSurface';

create unique index idx_dim_surface_natural
  on claude_analytics.dim_user_surface (surface_type, surface_version, extension_version);

-- DimModel
create table claude_analytics.dim_model (
  model_key          integer generated always as identity primary key,
  model_id           text    not null unique,
  model_family       claude_analytics.model_family not null,
  context_window     integer not null,
  max_output_tokens  integer not null,
  supports_thinking  boolean not null default true
);

comment on table claude_analytics.dim_model is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#DimModel';

-- DimTime — Conformed date-time dimension at minute grain
create table claude_analytics.dim_time (
  time_key      integer     primary key,  -- YYYYMMDDHHmm
  full_datetime timestamptz not null,
  date          date        not null,
  year          smallint    not null,
  quarter       smallint    not null check (quarter between 1 and 4),
  month         smallint    not null check (month between 1 and 12),
  day           smallint    not null check (day between 1 and 31),
  hour          smallint    not null check (hour between 0 and 23),
  minute        smallint    not null check (minute between 0 and 59),
  day_of_week   text        not null,
  is_weekend    boolean     not null
);

comment on table claude_analytics.dim_time is
  'Conformed date-time dimension at minute grain. Role-played as start_time, end_time, event_time. '
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#DimTime';

-- DimTool
create table claude_analytics.dim_tool (
  tool_key        integer generated always as identity primary key,
  tool_name       text    not null unique,
  tool_category   claude_analytics.tool_category not null,
  is_mcp          boolean not null default false,
  mcp_server_name text
);

comment on table claude_analytics.dim_tool is
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#DimTool';

-- ════════════════════════════════════════════════════════════════════
-- Fact Tables
-- ════════════════════════════════════════════════════════════════════

-- FactSession — grain: one row per session (accumulating snapshot)
create table claude_analytics.fact_session (
  session_key        integer generated always as identity primary key,
  session_id         text    not null unique,
  status             claude_analytics.session_status not null default 'active',

  -- Dimension FKs (pg_graphql exposes these as nested objects)
  user_key           integer not null references claude_analytics.dim_user(user_key),
  device_key         integer not null references claude_analytics.dim_device(device_key),
  surface_key        integer not null references claude_analytics.dim_user_surface(surface_key),
  model_key          integer not null references claude_analytics.dim_model(model_key),
  start_time_key     integer not null references claude_analytics.dim_time(time_key),
  end_time_key       integer references claude_analytics.dim_time(time_key),

  -- Measures
  duration_seconds   numeric(12,2) not null default 0,
  message_count      integer       not null default 0,
  tool_use_count     integer       not null default 0,
  token_input_count  integer       not null default 0,
  token_output_count integer       not null default 0,
  turn_count         integer       not null default 0,
  cost_usd           numeric(10,6) not null default 0
);

comment on table claude_analytics.fact_session is
  'Grain: one row per Claude Code session. Accumulating snapshot updated as session progresses. '
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#FactSession';

create index idx_fact_session_user   on claude_analytics.fact_session (user_key);
create index idx_fact_session_start  on claude_analytics.fact_session (start_time_key);
create index idx_fact_session_status on claude_analytics.fact_session (status);

-- FactToolUse — grain: one row per tool invocation
create table claude_analytics.fact_tool_use (
  tool_use_key   integer generated always as identity primary key,

  -- Dimension FKs
  session_key    integer not null references claude_analytics.fact_session(session_key),
  user_key       integer not null references claude_analytics.dim_user(user_key),
  tool_key       integer not null references claude_analytics.dim_tool(tool_key),
  model_key      integer not null references claude_analytics.dim_model(model_key),
  time_key       integer not null references claude_analytics.dim_time(time_key),

  -- Measures
  duration_ms    integer not null default 0,
  input_tokens   integer not null default 0,
  output_tokens  integer not null default 0,
  is_cache_hit   boolean not null default false,
  was_approved   boolean not null default true,
  error_occurred boolean not null default false
);

comment on table claude_analytics.fact_tool_use is
  'Grain: one row per tool invocation within a session. '
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#FactToolUse';

create index idx_fact_tool_use_session on claude_analytics.fact_tool_use (session_key);
create index idx_fact_tool_use_tool    on claude_analytics.fact_tool_use (tool_key);
create index idx_fact_tool_use_time    on claude_analytics.fact_tool_use (time_key);
create index idx_fact_tool_use_user    on claude_analytics.fact_tool_use (user_key);

-- FactMessage — grain: one row per message
create table claude_analytics.fact_message (
  message_key          integer generated always as identity primary key,

  -- Dimension FKs
  session_key          integer not null references claude_analytics.fact_session(session_key),
  user_key             integer not null references claude_analytics.dim_user(user_key),
  model_key            integer not null references claude_analytics.dim_model(model_key),
  time_key             integer not null references claude_analytics.dim_time(time_key),

  -- Measures
  role                 claude_analytics.message_role not null,
  content_length       integer not null default 0,
  token_count          integer not null default 0,
  has_tool_use         boolean not null default false,
  thinking_tokens      integer,
  cache_creation_tokens integer,
  cache_read_tokens    integer
);

comment on table claude_analytics.fact_message is
  'Grain: one row per message in a session conversation. '
  'UDA: https://rdf.agentwarehouses.dev/onto/claude#FactMessage';

create index idx_fact_message_session on claude_analytics.fact_message (session_key);
create index idx_fact_message_time    on claude_analytics.fact_message (time_key);
create index idx_fact_message_role    on claude_analytics.fact_message (role);
create index idx_fact_message_user    on claude_analytics.fact_message (user_key);

-- ════════════════════════════════════════════════════════════════════
-- pg_graphql Configuration
-- ════════════════════════════════════════════════════════════════════

-- Expose the claude_analytics schema to pg_graphql.
-- pg_graphql reads table/column comments for descriptions and
-- auto-generates Query/Mutation types from tables + foreign keys.

comment on schema claude_analytics is e'@graphql({"inflect_names": true})';

-- Seed reference data: DimModel for current Claude model lineup
insert into claude_analytics.dim_model (model_id, model_family, context_window, max_output_tokens, supports_thinking) values
  ('claude-opus-4-6',            'opus',   1000000, 32000, true),
  ('claude-sonnet-4-6',          'sonnet', 200000,  16000, true),
  ('claude-haiku-4-5-20251001',  'haiku',  200000,  8192,  true);

-- Seed reference data: DimTool for built-in Claude Code tools
insert into claude_analytics.dim_tool (tool_name, tool_category, is_mcp, mcp_server_name) values
  ('Read',          'read',   false, null),
  ('Write',         'write',  false, null),
  ('Edit',          'edit',   false, null),
  ('Bash',          'bash',   false, null),
  ('Glob',          'search', false, null),
  ('Grep',          'search', false, null),
  ('Agent',         'agent',  false, null),
  ('TodoWrite',     'other',  false, null),
  ('WebFetch',      'read',   false, null),
  ('WebSearch',     'search', false, null),
  ('NotebookEdit',  'edit',   false, null),
  ('AskUserQuestion','other', false, null),
  ('Skill',         'other',  false, null),
  ('ToolSearch',    'search', false, null);

-- ════════════════════════════════════════════════════════════════════
-- Helper: Generate DimTime rows for a date range
-- ════════════════════════════════════════════════════════════════════

create or replace function claude_analytics.populate_dim_time(
  start_date date,
  end_date   date
) returns integer
language plpgsql as $$
declare
  ts    timestamptz;
  cnt   integer := 0;
begin
  ts := start_date::timestamptz;
  while ts < (end_date + interval '1 day')::timestamptz loop
    insert into claude_analytics.dim_time (
      time_key, full_datetime, date, year, quarter, month, day,
      hour, minute, day_of_week, is_weekend
    ) values (
      to_char(ts, 'YYYYMMDDHHmm24')::integer,
      ts,
      ts::date,
      extract(year from ts)::smallint,
      extract(quarter from ts)::smallint,
      extract(month from ts)::smallint,
      extract(day from ts)::smallint,
      extract(hour from ts)::smallint,
      extract(minute from ts)::smallint,
      to_char(ts, 'FMDay'),
      extract(isodow from ts) in (6, 7)
    ) on conflict (time_key) do nothing;
    ts := ts + interval '1 minute';
    cnt := cnt + 1;
  end loop;
  return cnt;
end;
$$;

comment on function claude_analytics.populate_dim_time is
  'Populates dim_time at minute grain for the given date range. '
  'Call once per day/batch to ensure time dimension coverage.';
