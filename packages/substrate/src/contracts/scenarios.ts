import { z } from 'zod';

/**
 * C6 — Scenario contract.
 *
 * Historical shocks + synthetic worlds, reusable by simulation,
 * stress-testing (01), and gated data generation (02). `version` makes the
 * scenario library a registry, not a wiki.
 */
export const ShockScenarioSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  realizedOutcome: z.string(),
  window: z.string(),
  /** Narrative "state of the world" before the shock (seed material). */
  seed: z.string(),
  version: z.string().default('1.0.0'),
  /** FRED/ALFRED series families used for point-in-time retro-validation. */
  series: z.array(z.string()).default([]),
});

export type ShockScenario = z.infer<typeof ShockScenarioSchema>;

/** Injection = standardized, replayable intervention (A-S-23). */
export const ShockInterventionSchema = z.object({
  id: z.string().min(1),
  profile: z.string().min(1),
  magnitude: z.number(),
  channels: z.array(z.string()).min(1),
  start: z.string(),
  seed: z.string().default('1.0.0'),
});

export type ShockIntervention = z.infer<typeof ShockInterventionSchema>;

export type WorldTemplate = Record<string, unknown>;