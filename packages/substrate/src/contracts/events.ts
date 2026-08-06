import { z } from 'zod';

/**
 * C1 — Event log contract.
 *
 * Three families, append-only, canonical JSON, monotonic seq per run,
 * unique idempotency key per event. `capture` is ground truth and is
 * NEVER flag-gated; `narrative` is LLM-authored and only affects display.
 */
export const EventSchema = z.discriminatedUnion('family', [
  z.object({
    family: z.literal('stream'),
    kind: z.string(),
    payload: z.unknown(),
  }),
  z.object({
    family: z.literal('capture'),
    toolCallId: z.string(),
    result: z.unknown(),
    ts: z.string(),
  }),
  z.object({
    family: z.literal('narrative'),
    kind: z.string(),
    payload: z.unknown(),
  }),
]);

export type Event = z.infer<typeof EventSchema>;

export const StoredEventSchema = EventSchema.and(
  z.object({
    runId: z.string(),
    seq: z.number().int().nonnegative(),
    idempotencyKey: z.string().min(1),
    /** sha-256 of canonical JSON of (family, kind/payload) chain up to this event. */
    chainHash: z.string().regex(/^[0-9a-f]{64}$/),
    ts: z.string(),
  }),
);

export type StoredEvent = z.infer<typeof StoredEventSchema>;

/**
 * Canonical JSON: stable key ordering (sorted recursively) + no whitespace.
 * The byte-exact serialization used by golden runs and prompt fingerprints.
 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`;
  }
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(obj[k])}`).join(',')}}`;
}

/**
 * Idempotency key spec: `<runId>:<toolCallId>:<attempt>` — a replayed tool
 * result is a replayed event, never a re-executed side effect.
 */
export function idempotencyKey(runId: string, toolCallId: string, attempt: number): string {
  return `${runId}:${toolCallId}:${attempt}`;
}
