-- HuggingFace Dataset Integration Schema — Neon Postgres 18
--
-- Stores all 10 Anthropic HuggingFace datasets as native Postgres tables.
-- Synced via Parquet API (HF Pro: 2,500 API calls/5min) into Neon
-- (Scale plan: 16 CU autoscaling, 750 compute-hours/mo, pgvector HNSW).
--
-- Datasets loaded into dedicated hf_anthropic schema, cross-referenced
-- from the claude_world world model via foreign keys and pgvector similarity.

create extension if not exists pg_graphql;
create extension if not exists vector;

create schema if not exists hf_anthropic;
comment on schema hf_anthropic is
  e'@graphql({"inflect_names": true})\nAnthropic HuggingFace datasets synced via Parquet API. 10 datasets, ~2.3M rows.';

-- ════════════════════════════════════════════════════════════════════
-- Sync metadata — tracks ETL state per dataset
-- ════════════════════════════════════════════════════════════════════

create table hf_anthropic.sync_state (
  dataset_id    text primary key,
  last_synced   timestamptz,
  row_count     integer not null default 0,
  parquet_bytes bigint not null default 0,
  etag          text,
  neon_branch   text default 'main'
);

insert into hf_anthropic.sync_state (dataset_id) values
  ('Anthropic/EconomicIndex'),
  ('Anthropic/AnthropicInterviewer'),
  ('Anthropic/alignment-faking-rl'),
  ('Anthropic/values-in-the-wild'),
  ('Anthropic/election_questions'),
  ('Anthropic/persuasion'),
  ('Anthropic/discrim-eval'),
  ('Anthropic/llm_global_opinions'),
  ('Anthropic/hh-rlhf'),
  ('Anthropic/model-written-evals');

-- ════════════════════════════════════════════════════════════════════
-- 1. EconomicIndex (15k downloads, 502 likes)
--    Economic impact of AI on labor markets. Multiple releases.
--    Source: Anthropic/EconomicIndex
-- ════════════════════════════════════════════════════════════════════

create table hf_anthropic.economic_index (
  id             integer generated always as identity primary key,
  release_date   date not null,
  geo_id         text not null,
  geography      text not null,
  date_start     date not null,
  date_end       date not null,
  platform       text not null,
  facet          text not null,
  level          smallint not null default 0,
  variable       text not null,
  cluster_name   text not null,
  value          double precision
);

comment on table hf_anthropic.economic_index is
  'AI economic impact: task penetration, job exposure, learning curves (Opus 4.5/4.6). '
  'World model role: weights fact_outcome tasks by real-world economic impact.';

create index idx_econ_geo on hf_anthropic.economic_index (geo_id, date_start);
create index idx_econ_facet on hf_anthropic.economic_index (facet, variable);

create table hf_anthropic.economic_job_exposure (
  id             integer generated always as identity primary key,
  occupation     text not null,
  onet_code      text,
  exposure_score double precision not null,
  task_count     integer,
  release_date   date not null
);

comment on table hf_anthropic.economic_job_exposure is
  'Job-level AI exposure scores from labor_market_impacts/job_exposure.csv.';

-- ════════════════════════════════════════════════════════════════════
-- 2. AnthropicInterviewer (1,250 transcripts, 367 likes)
--    Professional AI integration interviews across 3 cohorts.
--    Source: Anthropic/AnthropicInterviewer
-- ════════════════════════════════════════════════════════════════════

create type hf_anthropic.interviewer_cohort as enum (
  'workforce', 'creatives', 'scientists'
);

create table hf_anthropic.interviewer_transcripts (
  transcript_id  text primary key,
  cohort         hf_anthropic.interviewer_cohort not null,
  text           text not null,
  char_count     integer generated always as (length(text)) stored,
  embedding      vector(384)
);

comment on table hf_anthropic.interviewer_transcripts is
  '1,250 professional AI interviews. World model role: seed agent_belief '
  'with real professional usage patterns; pgvector enables semantic similarity '
  'search against current session context.';

create index idx_interviewer_embed on hf_anthropic.interviewer_transcripts
  using hnsw (embedding vector_cosine_ops);

-- ════════════════════════════════════════════════════════════════════
-- 3. alignment-faking-rl (2.14M rows, 17.2 GB, 15 likes)
--    RL evaluation transcripts testing alignment faking behavior.
--    Source: Anthropic/alignment-faking-rl
--    NOTE: Loaded into Neon staging branch, not production.
-- ════════════════════════════════════════════════════════════════════

create table hf_anthropic.alignment_faking (
  id                    integer generated always as identity primary key,
  initialised_from      text not null,
  experiment_name       text not null,
  step                  smallint not null,
  task_id               text,
  user_input            text not null,
  is_free_tier_user     boolean not null,
  response              text not null,
  alignment_faking      boolean not null,
  alignment_faking_prob double precision,
  compliance            boolean not null,
  literal_compliance    boolean not null,
  total_reward          double precision not null,
  reward_pm             double precision,
  intervention          text not null,
  system_prompt         text not null
);

comment on table hf_anthropic.alignment_faking is
  '2.14M RL eval transcripts. Loaded into neon branch "hf-safety-testing" '
  'for isolated evaluation. World model role: adversarial trajectory baselines '
  'for fact_trajectory safety scoring.';

create index idx_af_experiment on hf_anthropic.alignment_faking (experiment_name, step);
create index idx_af_faking on hf_anthropic.alignment_faking (alignment_faking)
  where alignment_faking = true;

-- ════════════════════════════════════════════════════════════════════
-- 4. values-in-the-wild (6,910 rows, 149 likes)
--    3,307 values expressed by Claude across real conversations.
--    Source: Anthropic/values-in-the-wild
-- ════════════════════════════════════════════════════════════════════

create table hf_anthropic.values_frequencies (
  value_name     text primary key,
  pct_convos     double precision not null,
  embedding      vector(384)
);

comment on table hf_anthropic.values_frequencies is
  'How often each value appears in Claude conversations (pct of all convos). '
  'World model role: populates dim_value; enables value-aware session scoring.';

create index idx_values_freq_embed on hf_anthropic.values_frequencies
  using hnsw (embedding vector_cosine_ops);

create table hf_anthropic.values_tree (
  cluster_id           text primary key,
  name                 text not null,
  description          text,
  level                smallint not null,
  parent_cluster_id    text references hf_anthropic.values_tree(cluster_id),
  pct_total_occurrences double precision
);

comment on table hf_anthropic.values_tree is
  'Hierarchical taxonomy: level 0 = individual values, level 3 = top clusters. '
  'World model role: dim_value category hierarchy for rollup analytics.';

-- ════════════════════════════════════════════════════════════════════
-- 5. election_questions (743 rows, 20 likes)
--    Election-related safety evaluation questions.
--    Source: Anthropic/election_questions
-- ════════════════════════════════════════════════════════════════════

create type hf_anthropic.election_eval_type as enum (
  'eu_accuracy', 'harmlessness', 'persuasion_targeting'
);

create type hf_anthropic.safety_label as enum (
  'Harmless', 'Harmful'
);

create table hf_anthropic.election_questions (
  id         integer generated always as identity primary key,
  eval_type  hf_anthropic.election_eval_type not null,
  question   text not null,
  label      hf_anthropic.safety_label
);

comment on table hf_anthropic.election_questions is
  'Domain-specific safety evals for sensitive political topics. '
  'World model role: calibration data for fact_outcome safety gate.';

-- ════════════════════════════════════════════════════════════════════
-- 6. persuasion (3,939 rows, 208 likes)
--    Persuasiveness of human vs model-generated arguments.
--    Source: Anthropic/persuasion
-- ════════════════════════════════════════════════════════════════════

create table hf_anthropic.persuasion (
  id                   integer generated always as identity primary key,
  worker_id            text not null,
  claim                text not null,
  argument             text not null,
  source               text not null,
  prompt_type          text not null,
  rating_initial       text not null,
  rating_final         text not null,
  persuasiveness_metric smallint not null
);

comment on table hf_anthropic.persuasion is
  'Human vs model argument persuasiveness (75 claims x 52 workers). '
  'World model role: calibrate agent_belief confidence scoring — '
  'how persuasive is the agent''s reasoning relative to baselines?';

create index idx_persuasion_source on hf_anthropic.persuasion (source);

-- ════════════════════════════════════════════════════════════════════
-- 7. discrim-eval (18,900 rows, 55 likes)
--    Demographic bias testing: 70 scenarios x 9 ages x 3 genders x 5 races.
--    Source: Anthropic/discrim-eval
-- ════════════════════════════════════════════════════════════════════

create type hf_anthropic.discrim_fill_type as enum ('explicit', 'implicit');

create table hf_anthropic.discrim_eval (
  id                   integer generated always as identity primary key,
  filled_template      text not null,
  decision_question_id smallint not null,
  age                  smallint not null,
  gender               text not null,
  race                 text not null,
  fill_type            hf_anthropic.discrim_fill_type not null
);

comment on table hf_anthropic.discrim_eval is
  '18,900 fairness scenarios (70 decisions x 135 demographic combos x 2 fill types). '
  'World model role: bias detection baselines for fact_outcome auditing.';

create index idx_discrim_demo on hf_anthropic.discrim_eval (gender, race, age);

-- ════════════════════════════════════════════════════════════════════
-- 8. llm_global_opinions (2,556 rows, 55 likes)
--    World Values Survey + Pew Global Attitudes adapted for LLMs.
--    Source: Anthropic/llm_global_opinions
-- ════════════════════════════════════════════════════════════════════

create table hf_anthropic.llm_global_opinions (
  id         integer generated always as identity primary key,
  question   text not null,
  options    jsonb not null,
  selections jsonb not null,
  source     text not null check (source in ('GAS', 'WVS'))
);

comment on table hf_anthropic.llm_global_opinions is
  'Cross-cultural opinion consistency benchmarks (Pew + World Values Survey). '
  'World model role: agent_belief consistency checks across regions/cultures.';

-- ════════════════════════════════════════════════════════════════════
-- 9. hh-rlhf (169k rows, 1.7k likes)
--    Human preference data on helpfulness and harmlessness.
--    Source: Anthropic/hh-rlhf
-- ════════════════════════════════════════════════════════════════════

create type hf_anthropic.rlhf_subset as enum (
  'harmless_base', 'helpful_base', 'helpful_online',
  'helpful_rejection_sampled', 'red_team'
);

create table hf_anthropic.hh_rlhf (
  id         integer generated always as identity primary key,
  subset     hf_anthropic.rlhf_subset not null,
  split      text not null default 'train',
  chosen     text not null,
  rejected   text not null
);

comment on table hf_anthropic.hh_rlhf is
  'Human preference pairs (chosen/rejected). World model role: '
  'calibrate fact_message quality scoring — is the agent''s response '
  'aligned with human preference baselines?';

create table hf_anthropic.hh_rlhf_red_team (
  id                       integer generated always as identity primary key,
  transcript               text not null,
  min_harmlessness_score   double precision,
  num_params               bigint,
  model_type               text,
  rating                   smallint,
  task_description         text,
  task_harmlessness_score  double precision,
  red_team_member_id       text,
  is_upworker              boolean,
  tags                     text[]
);

comment on table hf_anthropic.hh_rlhf_red_team is
  'Red team attack transcripts with success ratings. '
  'World model role: adversarial trajectory baselines (load into safety branch).';

-- ════════════════════════════════════════════════════════════════════
-- 10. model-written-evals (1k-10k rows, personality benchmarks)
--     Model-generated evaluation datasets for safety and personality.
--     Source: Anthropic/model-written-evals
-- ════════════════════════════════════════════════════════════════════

create type hf_anthropic.eval_category as enum (
  'sycophancy', 'persona', 'advanced_ai_risk',
  'gender_bias', 'social_bias', 'political'
);

create table hf_anthropic.model_written_evals (
  id           integer generated always as identity primary key,
  category     hf_anthropic.eval_category not null,
  question     text not null,
  answer_matching_behavior text,
  answer_not_matching_behavior text,
  label        text,
  tags         text[]
);

comment on table hf_anthropic.model_written_evals is
  'LLM-generated personality/safety benchmarks (sycophancy, persona, bias). '
  'World model role: dim_value personality consistency + fact_reasoning baselines.';

-- ════════════════════════════════════════════════════════════════════
-- Cross-references: HF datasets → World Model
-- ════════════════════════════════════════════════════════════════════

comment on schema hf_anthropic is
  e'@graphql({"inflect_names": true})\n'
  'Anthropic HuggingFace datasets. Cross-referenced from claude_world schema:\n'
  '  dim_value ← values_frequencies + values_tree (behavioral taxonomy)\n'
  '  fact_outcome ← economic_index (task impact weights)\n'
  '  agent_belief ← interviewer_transcripts (professional usage priors)\n'
  '  fact_trajectory ← alignment_faking + hh_rlhf_red_team (safety baselines)\n'
  '  fact_message ← hh_rlhf (preference quality calibration)\n'
  '  fact_reasoning ← persuasion (confidence calibration)\n'
  '  fact_outcome ← discrim_eval + election_questions (fairness/safety gates)\n'
  '  dim_value ← model_written_evals (personality consistency)\n'
  '  agent_belief ← llm_global_opinions (cross-cultural consistency)';
