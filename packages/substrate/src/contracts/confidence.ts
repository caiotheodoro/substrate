import { z } from 'zod';

/**
 * C5 — Confidence API contract.
 *
 * Served by 02's Trust scorer as a drop-in `confidence_score` provider for
 * 01's gate and 03's tiering. Score is calibrated on evidence, not self-report.
 */
export const ConfidenceResponseSchema = z.object({
  score: z.number().min(0).max(1),
  band: z.enum(['execute-band', 'escalation-band', 'reject-band']),
  /** Per-feature contribution, for the escalation surface. */
  explain: z.record(z.string(), z.unknown()),
  modelVersion: z.string(),
});

export type ConfidenceResponse = z.infer<typeof ConfidenceResponseSchema>;

export const ConfidenceRequestSchema = z.object({
  decisionId: z.string(),
  confidenceFeatures: z.record(z.string(), z.unknown()),
});

export type ConfidenceRequest = z.infer<typeof ConfidenceRequestSchema>;