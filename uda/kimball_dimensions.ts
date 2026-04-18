/**
 * Claude-UDA Kimball Dimensions — Zod schemas for SDK output_format
 *
 * Projected from domain_model.ttl. These schemas enable Claude Agent SDK
 * structured output for star schema dimension records, ensuring type-safe
 * extraction of analytics data from Claude Code sessions.
 *
 * Usage with Claude SDK:
 *   const result = await client.messages.create({
 *     model: "claude-opus-4-6",
 *     messages: [...],
 *     output_format: { type: "json", schema: DimUser },
 *   });
 */

import { z } from "zod";

// ════════════════════════════════════════════════════════════════════
// Enumerations (Controlled Vocabularies)
// ════════════════════════════════════════════════════════════════════

export const PlanTier = z.enum(["free", "pro", "team", "enterprise", "max"]);
export type PlanTier = z.infer<typeof PlanTier>;

export const SurfaceType = z.enum([
  "cli",
  "vscode",
  "jetbrains",
  "web",
  "desktop_mac",
  "desktop_windows",
]);
export type SurfaceType = z.infer<typeof SurfaceType>;

export const ModelFamily = z.enum(["opus", "sonnet", "haiku"]);
export type ModelFamily = z.infer<typeof ModelFamily>;

export const ToolCategory = z.enum([
  "read",
  "write",
  "edit",
  "bash",
  "search",
  "agent",
  "mcp",
  "other",
]);
export type ToolCategory = z.infer<typeof ToolCategory>;

export const MessageRole = z.enum(["user", "assistant", "system", "tool"]);
export type MessageRole = z.infer<typeof MessageRole>;

export const SessionStatus = z.enum([
  "active",
  "completed",
  "abandoned",
  "errored",
  "compacted",
]);
export type SessionStatus = z.infer<typeof SessionStatus>;

export const DeviceOS = z.enum(["macos", "linux", "windows", "chromeos"]);
export type DeviceOS = z.infer<typeof DeviceOS>;

// ════════════════════════════════════════════════════════════════════
// DimUser — Type 2 Slowly Changing Dimension
// ════════════════════════════════════════════════════════════════════

export const DimUser = z.object({
  user_key: z.number().int().describe("Surrogate key"),
  user_id: z.string().describe("Natural key — Anthropic user ID"),
  email: z.string().email(),
  plan_tier: PlanTier,
  org_id: z.string().nullable().describe("Organization ID, null for individual users"),
  org_name: z.string().nullable().describe("Organization name"),
  effective_from: z.string().datetime().describe("SCD2 row validity start (ISO 8601)"),
  effective_to: z
    .string()
    .datetime()
    .nullable()
    .describe("SCD2 row validity end — null means current row"),
  is_current: z.boolean().describe("True if this is the active version of the user"),
});
export type DimUser = z.infer<typeof DimUser>;

// ════════════════════════════════════════════════════════════════════
// DimDevice
// ════════════════════════════════════════════════════════════════════

export const DimDevice = z.object({
  device_key: z.number().int().describe("Surrogate key"),
  device_id: z.string().describe("Natural key — device fingerprint"),
  os: DeviceOS,
  os_version: z.string().describe("e.g. 14.5, 6.8.0-rc1"),
  arch: z.string().describe("e.g. x86_64, arm64"),
  cpu_cores: z.number().int().nullable(),
  memory_gb: z.number().nullable(),
});
export type DimDevice = z.infer<typeof DimDevice>;

// ════════════════════════════════════════════════════════════════════
// DimUserSurface
// ════════════════════════════════════════════════════════════════════

export const DimUserSurface = z.object({
  surface_key: z.number().int().describe("Surrogate key"),
  surface_type: SurfaceType,
  surface_version: z.string().describe("e.g. 1.0.20"),
  extension_version: z
    .string()
    .nullable()
    .describe("IDE extension version, null for CLI/web"),
});
export type DimUserSurface = z.infer<typeof DimUserSurface>;

// ════════════════════════════════════════════════════════════════════
// DimModel
// ════════════════════════════════════════════════════════════════════

export const DimModel = z.object({
  model_key: z.number().int().describe("Surrogate key"),
  model_id: z.string().describe("e.g. claude-opus-4-6"),
  model_family: ModelFamily,
  context_window: z.number().int().describe("Max input tokens"),
  max_output_tokens: z.number().int().describe("Max output tokens"),
  supports_thinking: z.boolean(),
});
export type DimModel = z.infer<typeof DimModel>;

// ════════════════════════════════════════════════════════════════════
// DimTime — Conformed date-time dimension at minute grain
// ════════════════════════════════════════════════════════════════════

export const DimTime = z.object({
  time_key: z.number().int().describe("Surrogate key — YYYYMMDDHHmm"),
  full_datetime: z.string().datetime().describe("ISO 8601 timestamp"),
  date: z.string().date().describe("ISO 8601 date (YYYY-MM-DD)"),
  year: z.number().int(),
  quarter: z.number().int().min(1).max(4),
  month: z.number().int().min(1).max(12),
  day: z.number().int().min(1).max(31),
  hour: z.number().int().min(0).max(23),
  minute: z.number().int().min(0).max(59),
  day_of_week: z.string().describe("e.g. Monday"),
  is_weekend: z.boolean(),
});
export type DimTime = z.infer<typeof DimTime>;

// ════════════════════════════════════════════════════════════════════
// DimTool
// ════════════════════════════════════════════════════════════════════

export const DimTool = z.object({
  tool_key: z.number().int().describe("Surrogate key"),
  tool_name: z
    .string()
    .describe("e.g. Read, Edit, Bash, mcp__github__create_pull_request"),
  tool_category: ToolCategory,
  is_mcp: z.boolean(),
  mcp_server_name: z
    .string()
    .nullable()
    .describe("MCP server name, null for built-in tools"),
});
export type DimTool = z.infer<typeof DimTool>;
