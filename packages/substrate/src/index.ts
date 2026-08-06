export type GateVerdict = 'execute' | 'escalate' | 'reject';

export interface DecisionRecord {
  /** Unique decision id. */
  decisionId: string;
  /** Harness turn id. */
  turnId: string;
  /** Proposed action descriptor. */
  action: string;
  /** Confidence features (never raw logprobs). */
  confidenceFeatures: Record<string, unknown>;
  /** Gate verdict. */
  verdict: GateVerdict;
  /** Confirmed outcome once known; null until reconciled. */
  outcome: boolean | null;
  /** When the outcome was confirmed. */
  confirmedAt: string | null;
}

export type RetrievalVerdict =
  | { kind: 'support' }
  | { kind: 'contradict' }
  | { kind: 'silent' };

export type Event =
  | { family: 'stream'; kind: string; payload: unknown }
  | { family: 'capture'; toolCallId: string; result: unknown; ts: string }
  | { family: 'narrative'; kind: string; payload: unknown };