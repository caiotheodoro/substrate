import { z } from 'zod';

/**
 * C2 — Decision record contract.
 *
 * One row per gated decision. `confidenceFeatures` come from OUTSIDE the
 * model's weights (tool-call returns, retrieval verdicts, schema checks,
 * outcome prediction) — never logprobs / self-consistency / self-eval.
 */
export const GateVerdictSchema = z.enum(['execute', 'escalate', 'reject']);
export type GateVerdict = z.infer<typeof GateVerdictSchema>;

export const ConfidenceFeaturesSchema = z.record(z.string(), z.unknown());

export const DecisionRecordSchema = z.object({
  decisionId: z.string().min(1),
  turnId: z.string().min(1),
  action: z.string().min(1),
  confidenceFeatures: ConfidenceFeaturesSchema,
  verdict: GateVerdictSchema,
  /** Confirmed outcome once known; null until reconciled. */
  outcome: z.boolean().nullable(),
  confirmedAt: z.string().nullable(),
});

export type DecisionRecord = z.infer<typeof DecisionRecordSchema>;

/**
 * The gate primitive: two thresholds, not one. The band between them is the
 * escalation band — a designed cost/risk curve, never a framework default.
 */
export function gate(
  confidence: number,
  executeThreshold: number,
  rejectThreshold: number,
): GateVerdict {
  if (confidence >= executeThreshold) return 'execute';
  if (confidence < rejectThreshold) return 'reject';
  return 'escalate';
}
