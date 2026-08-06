import type { BudgetEvent, StepRecord } from '@substrate/substrate';
import { BudgetEventSchema, StepRecordSchema } from '@substrate/substrate';

/**
 * Joint 3 (C4): 01's engine consults 03's budget-gate (:8103) and writes
 * cost steps to the ledger (:8100) — keyed by decisionId, never crashing.
 *
 * Offline behavior: when 03 is unreachable (tests, compose not up) the gate
 * PASSES every step (budget is not enforced) and ledger writes are dropped,
 * so runs are deterministic without the efficiency stack.
 */

export interface BudgetGateClient {
  gate(req: {
    decisionId: string;
    stepIdx: number;
    estimatedTokens: number;
    budget: number;
  }): Promise<'pass' | 'blow'>;
  recordStep(step: StepRecord): Promise<void>;
}

export const BUDGET_GATE_URL = process.env.SUBSTRATE_BUDGET_URL ?? 'http://localhost:8103';
export const LEDGER_URL = process.env.SUBSTRATE_LEDGER_URL ?? 'http://localhost:8100';

export interface RemoteBudgetOptions {
  gateUrl?: string;
  ledgerUrl?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export function remoteBudgetGateClient(opts: RemoteBudgetOptions = {}): BudgetGateClient {
  const gateUrl = opts.gateUrl ?? BUDGET_GATE_URL;
  const ledgerUrl = opts.ledgerUrl ?? LEDGER_URL;
  const timeoutMs = opts.timeoutMs ?? 2000;
  const fetchImpl = opts.fetchImpl ?? fetch;

  return {
    async gate(req) {
      const res = await fetchImpl(`${gateUrl.replace(/\/$/, '')}/gate`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(req),
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) throw new Error(`budget gate error ${res.status}: ${await res.text()}`);
      const body = BudgetEventSchema.parse(await res.json());
      return body.outcome;
    },
    async recordStep(step) {
      const res = await fetchImpl(`${ledgerUrl.replace(/\/$/, '')}/steps`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(step),
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok && res.status !== 409) {
        throw new Error(`ledger error ${res.status}: ${await res.text()}`);
      }
    },
  };
}

export interface ResilientBudgetOptions extends RemoteBudgetOptions {
  /** When true, remote failures throw instead of passing. */
  requireRemote?: boolean;
}

export function resilientBudgetGateClient(opts: ResilientBudgetOptions = {}): BudgetGateClient {
  const remote = remoteBudgetGateClient(opts);
  let disabled = false;
  return {
    async gate(req) {
      if (opts.requireRemote) return remote.gate(req);
      if (disabled) return 'pass';
      try {
        return await remote.gate(req);
      } catch (err) {
        disabled = true;
        // Degrade to pass once; subsequent steps short-circuit.
        return 'pass';
      }
    },
    async recordStep(step) {
      if (opts.requireRemote) return remote.recordStep(step);
      if (disabled) return;
      try {
        await remote.recordStep(step);
      } catch {
        disabled = true;
      }
    },
  };
}

export function validateBudgetEvent(e: unknown): BudgetEvent {
  return BudgetEventSchema.parse(e);
}

export function validateStepRecord(s: unknown): StepRecord {
  return StepRecordSchema.parse(s);
}
