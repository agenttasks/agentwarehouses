/**
 * Claude-UDA Kimball Facts — Zod schemas for SDK output_format
 *
 * Projected from domain_model.ttl. Three fact tables at different grains:
 *   - FactSession:  one row per session (accumulating snapshot)
 *   - FactToolUse:  one row per tool invocation
 *   - FactMessage:  one row per conversation message
 *
 * Foreign keys reference surrogate keys from kimball_dimensions.ts.
 * Use with Claude Agent SDK structured output to extract analytics events.
 */

import { z } from "zod";
import { SessionStatus, MessageRole } from "./kimball_dimensions.js";

// ════════════════════════════════════════════════════════════════════
// FactSession — grain: one row per session
// ════════════════════════════════════════════════════════════════════

export const FactSession = z.object({
  session_key: z.number().int().describe("Surrogate key"),
  session_id: z
    .string()
    .describe("Natural key — e.g. session_01H5TrSfgA9x3vXTNYHnW4f8"),
  status: SessionStatus,

  // Dimension foreign keys
  user_key: z.number().int().describe("FK to DimUser"),
  device_key: z.number().int().describe("FK to DimDevice"),
  surface_key: z.number().int().describe("FK to DimUserSurface"),
  model_key: z.number().int().describe("FK to DimModel (primary model)"),
  start_time_key: z.number().int().describe("Role-played FK to DimTime"),
  end_time_key: z
    .number()
    .int()
    .nullable()
    .describe("Role-played FK to DimTime, null if session still active"),

  // Measures
  duration_seconds: z.number().nonnegative(),
  message_count: z.number().int().nonnegative(),
  tool_use_count: z.number().int().nonnegative(),
  token_input_count: z.number().int().nonnegative(),
  token_output_count: z.number().int().nonnegative(),
  turn_count: z.number().int().nonnegative(),
  cost_usd: z.number().nonnegative(),
});
export type FactSession = z.infer<typeof FactSession>;

// ════════════════════════════════════════════════════════════════════
// FactToolUse — grain: one row per tool invocation
// ════════════════════════════════════════════════════════════════════

export const FactToolUse = z.object({
  tool_use_key: z.number().int().describe("Surrogate key"),

  // Dimension foreign keys
  session_key: z.number().int().describe("FK to FactSession"),
  user_key: z.number().int().describe("FK to DimUser"),
  tool_key: z.number().int().describe("FK to DimTool"),
  model_key: z.number().int().describe("FK to DimModel"),
  time_key: z.number().int().describe("FK to DimTime"),

  // Measures
  duration_ms: z.number().int().nonnegative(),
  input_tokens: z.number().int().nonnegative(),
  output_tokens: z.number().int().nonnegative(),
  is_cache_hit: z.boolean(),
  was_approved: z.boolean(),
  error_occurred: z.boolean(),
});
export type FactToolUse = z.infer<typeof FactToolUse>;

// ════════════════════════════════════════════════════════════════════
// FactMessage — grain: one row per message
// ════════════════════════════════════════════════════════════════════

export const FactMessage = z.object({
  message_key: z.number().int().describe("Surrogate key"),

  // Dimension foreign keys
  session_key: z.number().int().describe("FK to FactSession"),
  user_key: z.number().int().describe("FK to DimUser"),
  model_key: z.number().int().describe("FK to DimModel"),
  time_key: z.number().int().describe("FK to DimTime"),

  // Measures
  role: MessageRole,
  content_length: z.number().int().nonnegative(),
  token_count: z.number().int().nonnegative(),
  has_tool_use: z.boolean(),
  thinking_tokens: z
    .number()
    .int()
    .nonnegative()
    .nullable()
    .describe("Extended thinking tokens, null if thinking not used"),
  cache_creation_tokens: z
    .number()
    .int()
    .nonnegative()
    .nullable()
    .describe("Prompt cache creation tokens"),
  cache_read_tokens: z
    .number()
    .int()
    .nonnegative()
    .nullable()
    .describe("Prompt cache read tokens"),
});
export type FactMessage = z.infer<typeof FactMessage>;
