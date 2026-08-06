import { z } from 'zod';

/**
 * C7 — Wire discipline contract.
 *
 * Registry-driven, schema-validated, delta-based payloads. The same contract
 * for UI, tool calls, and memory. Full payload on first turn, RFC 6902
 * JSON-Patch deltas on follow-ups, cache-friendly stable blocks.
 */

/** JSON-Patch op (RFC 6902 subset). */
export const PatchOpSchema = z.discriminatedUnion('op', [
  z.object({ op: z.literal('add'), path: z.string(), value: z.unknown() }),
  z.object({ op: z.literal('remove'), path: z.string() }),
  z.object({ op: z.literal('replace'), path: z.string(), value: z.unknown() }),
  z.object({ op: z.literal('move'), path: z.string(), from: z.string() }),
  z.object({ op: z.literal('copy'), path: z.string(), from: z.string() }),
  z.object({ op: z.literal('test'), path: z.string(), value: z.unknown() }),
]);

export type PatchOp = z.infer<typeof PatchOpSchema>;

/** Stable instruction regions that structure a cache-friendly prompt. */
export const PromptRegionSchema = z.enum([
  'identity',
  'task',
  'tools',
  'schemas',
  'few-shot',
  'dynamic',
]);

export const InstructionBlockSchema = z.object({
  id: z.string().min(1),
  region: PromptRegionSchema,
  content: z.string(),
  /** stable=true → safe to reorder-miss in cache; stable=false → dynamic. */
  stable: z.boolean(),
});

export type InstructionBlock = z.infer<typeof InstructionBlockSchema>;

export const RegistryEntrySchema = z.object({
  kind: z.string().min(1),
  version: z.string().min(1),
  /** JSON Schema (draft 2020-12) document. */
  schema: z.record(z.string(), z.unknown()),
});

export type RegistryEntry = z.infer<typeof RegistryEntrySchema>;

/** Delta payload: full state on first turn, ops on follow-ups. */
export const DeltaPayloadSchema = z.object({
  kind: z.string().min(1),
  base: z.unknown().nullable(),
  ops: z.array(PatchOpSchema),
});

export type DeltaPayload = z.infer<typeof DeltaPayloadSchema>;