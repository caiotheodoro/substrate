import { z } from 'zod';

/**
 * C3 — Retrieval verdict contract.
 *
 * Three states, never cosine-similarity-as-truth. The cheapest
 * outside-the-model evidence that exists at scale; produced by 04,
 * consumed by 02 (feature), 01 (event log), and 04's own grounded gate.
 */
export const RetrievalVerdictSchema = z.object({
  kind: z.enum(['support', 'contradict', 'silent']),
  /** Model probability; recalibrated by Trust's pipeline, never raw. */
  prob: z.number().min(0).max(1),
  /** Concrete evidence reference (doc id / subgraph path), when present. */
  citedEvidence: z.string().nullable(),
  claim: z.string(),
});

export type RetrievalVerdict = z.infer<typeof RetrievalVerdictSchema>;
