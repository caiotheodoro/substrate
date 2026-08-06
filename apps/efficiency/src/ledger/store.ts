import type { BudgetEvent, StepRecord } from '@substrate/substrate';
import type { CacheEventRecord } from './schema.js';

/**
 * A-E-03 ledger-db — storage behind the ledger API.
 *
 * Invariants enforced by every implementation:
 *  - unique (decision_id, step_idx) per step;
 *  - idempotent ingest: re-inserting an identical row is a no-op, a
 *    different row for the same key is a conflict;
 *  - cost rows always carry decisionId (inherited from StepRecord).
 *
 * `createLedgerStore('postgres')` maps to the pg16 schema in
 * `src/ledger/pg/ledger.sql`; tests use the memory store, so the whole
 * suite runs with no services up.
 */

export type InsertResult = 'inserted' | 'duplicate-identical' | 'conflict';

export interface LedgerStore {
  insertStep(step: StepRecord): Promise<InsertResult>;
  getStepsByDecision(decisionId: string): Promise<StepRecord[]>;
  listSteps(): Promise<StepRecord[]>;
  insertBudgetEvent(event: BudgetEvent): Promise<InsertResult>;
  listBudgetEvents(): Promise<BudgetEvent[]>;
  insertCacheEvent(event: CacheEventRecord): Promise<InsertResult>;
  listCacheEvents(): Promise<CacheEventRecord[]>;
}

export function stepKey(decisionId: string, stepIdx: number): string {
  return `${decisionId}:${stepIdx}`;
}

export class MemoryLedgerStore implements LedgerStore {
  private readonly steps = new Map<string, StepRecord>();
  private readonly budgetEvents = new Map<string, BudgetEvent>();
  private readonly cacheEvents = new Map<string, CacheEventRecord>();

  async insertStep(step: StepRecord): Promise<InsertResult> {
    const key = stepKey(step.decisionId, step.stepIdx);
    const existing = this.steps.get(key);
    if (existing !== undefined) {
      return JSON.stringify(existing) === JSON.stringify(step)
        ? 'duplicate-identical'
        : 'conflict';
    }
    this.steps.set(key, step);
    return 'inserted';
  }

  async getStepsByDecision(decisionId: string): Promise<StepRecord[]> {
    return [...this.steps.values()]
      .filter((s) => s.decisionId === decisionId)
      .sort((a, b) => a.stepIdx - b.stepIdx);
  }

  async listSteps(): Promise<StepRecord[]> {
    return [...this.steps.values()];
  }

  async insertBudgetEvent(event: BudgetEvent): Promise<InsertResult> {
    const key = stepKey(event.decisionId, event.stepIdx);
    const existing = this.budgetEvents.get(key);
    if (existing !== undefined) {
      return JSON.stringify(existing) === JSON.stringify(event)
        ? 'duplicate-identical'
        : 'conflict';
    }
    this.budgetEvents.set(key, event);
    return 'inserted';
  }

  async listBudgetEvents(): Promise<BudgetEvent[]> {
    return [...this.budgetEvents.values()];
  }

  async insertCacheEvent(event: CacheEventRecord): Promise<InsertResult> {
    const key = `${event.decisionId}:${event.stepIdx}`;
    const existing = this.cacheEvents.get(key);
    if (existing !== undefined) {
      return JSON.stringify(existing) === JSON.stringify(event)
        ? 'duplicate-identical'
        : 'conflict';
    }
    this.cacheEvents.set(key, event);
    return 'inserted';
  }

  async listCacheEvents(): Promise<CacheEventRecord[]> {
    return [...this.cacheEvents.values()];
  }
}

export type LedgerBackend = 'memory' | 'postgres';

/**
 * Postgres is only loaded when asked — the pg driver is an optional
 * runtime concern of the compose stack, never of the test suite.
 */
export async function createLedgerStore(
  backend: LedgerBackend = process.env.SUBSTRATE_LEDGER_DB === 'postgres' ? 'postgres' : 'memory',
  connectionString?: string,
): Promise<LedgerStore> {
  if (backend === 'memory') return new MemoryLedgerStore();
  const { PostgresLedgerStore } = await import('./pg-store.js');
  return new PostgresLedgerStore(
    connectionString ??
      process.env.SUBSTRATE_LEDGER_PG ??
      'postgres://substrate:substrate@localhost:5432/substrate',
  );
}
