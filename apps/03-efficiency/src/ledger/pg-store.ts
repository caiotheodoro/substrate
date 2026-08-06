import { Pool, type QueryResult } from 'pg';
import type { BudgetEvent, StepRecord } from '@substrate/substrate';
import type { CacheEventRecord } from './schema.js';
import type { InsertResult, LedgerStore } from './store.js';

/**
 * A-E-03 postgres backend. Mirrors the pg16 schema in `pg/ledger.sql`.
 * Ingest is idempotent: identical re-insert returns 'duplicate-identical',
 * a conflicting row for the same (decision_id, step_idx) returns 'conflict'.
 */
export class PostgresLedgerStore implements LedgerStore {
  private readonly pool: Pool;

  constructor(connectionString: string) {
    this.pool = new Pool({ connectionString, max: 5 });
  }

  async close(): Promise<void> {
    await this.pool.end();
  }

  async insertStep(step: StepRecord): Promise<InsertResult> {
    const existing = await this.pool.query(
      `SELECT to_jsonb(s)::text AS row FROM steps s WHERE decision_id = $1 AND step_idx = $2`,
      [step.decisionId, step.stepIdx],
    );
    if (existing.rows.length > 0) {
      return existing.rows[0]!.row === JSON.stringify(this.toRow(step))
        ? 'duplicate-identical'
        : 'conflict';
    }
    const res: QueryResult = await this.pool.query(
      `INSERT INTO steps
         (decision_id, step_idx, model, provider, quantization, input_tokens,
          cached_input_tokens, output_tokens, cache_event, latency_ms,
          prompt_fingerprint, quality_signal, ts)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
       ON CONFLICT (decision_id, step_idx) DO NOTHING`,
      [
        step.decisionId, step.stepIdx, step.model, step.provider, step.quantization,
        step.inputTokens, step.cachedInputTokens, step.outputTokens, step.cacheEvent,
        step.latencyMs, step.promptFingerprint, step.qualitySignal, step.ts,
      ],
    );
    return res.rowCount === 1 ? 'inserted' : 'conflict';
  }

  async getStepsByDecision(decisionId: string): Promise<StepRecord[]> {
    const res = await this.pool.query(
      `SELECT * FROM steps WHERE decision_id = $1 ORDER BY step_idx`,
      [decisionId],
    );
    return res.rows.map((r) => this.fromRow(r));
  }

  async listSteps(): Promise<StepRecord[]> {
    const res = await this.pool.query(`SELECT * FROM steps ORDER BY decision_id, step_idx`);
    return res.rows.map((r) => this.fromRow(r));
  }

  async insertBudgetEvent(event: BudgetEvent): Promise<InsertResult> {
    const existing = await this.pool.query(
      `SELECT to_jsonb(b)::text AS row FROM budget_events b WHERE decision_id = $1 AND step_idx = $2`,
      [event.decisionId, event.stepIdx],
    );
    if (existing.rows.length > 0) {
      return existing.rows[0]!.row === JSON.stringify(event)
        ? 'duplicate-identical'
        : 'conflict';
    }
    const res = await this.pool.query(
      `INSERT INTO budget_events (decision_id, step_idx, estimated_tokens, budget, outcome)
       VALUES ($1,$2,$3,$4,$5) ON CONFLICT (decision_id, step_idx) DO NOTHING`,
      [event.decisionId, event.stepIdx, event.estimatedTokens, event.budget, event.outcome],
    );
    return res.rowCount === 1 ? 'inserted' : 'conflict';
  }

  async listBudgetEvents(): Promise<BudgetEvent[]> {
    const res = await this.pool.query(`SELECT * FROM budget_events`);
    return res.rows.map((r) => ({
      decisionId: r.decision_id,
      stepIdx: r.step_idx,
      estimatedTokens: r.estimated_tokens,
      budget: r.budget,
      outcome: r.outcome,
    }));
  }

  async insertCacheEvent(event: CacheEventRecord): Promise<InsertResult> {
    const existing = await this.pool.query(
      `SELECT to_jsonb(c)::text AS row FROM cache_events c WHERE decision_id = $1 AND step_idx = $2`,
      [event.decisionId, event.stepIdx],
    );
    if (existing.rows.length > 0) {
      return existing.rows[0]!.row === JSON.stringify(event)
        ? 'duplicate-identical'
        : 'conflict';
    }
    const res = await this.pool.query(
      `INSERT INTO cache_events (decision_id, step_idx, region_hashes, cache_event, input_tokens, cached_input_tokens, ts)
       VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (decision_id, step_idx) DO NOTHING`,
      [
        event.decisionId, event.stepIdx, JSON.stringify(event.regionHashes),
        event.cacheEvent, event.inputTokens, event.cachedInputTokens, event.ts,
      ],
    );
    return res.rowCount === 1 ? 'inserted' : 'conflict';
  }

  async listCacheEvents(): Promise<CacheEventRecord[]> {
    const res = await this.pool.query(`SELECT * FROM cache_events`);
    return res.rows.map((r) => ({
      decisionId: r.decision_id,
      stepIdx: r.step_idx,
      regionHashes: r.region_hashes,
      cacheEvent: r.cache_event,
      inputTokens: r.input_tokens,
      cachedInputTokens: r.cached_input_tokens,
      ts: r.ts,
    }));
  }

  private toRow(step: StepRecord): Record<string, unknown> {
    return {
      decision_id: step.decisionId,
      step_idx: step.stepIdx,
      model: step.model,
      provider: step.provider,
      quantization: step.quantization,
      input_tokens: step.inputTokens,
      cached_input_tokens: step.cachedInputTokens,
      output_tokens: step.outputTokens,
      cache_event: step.cacheEvent,
      latency_ms: step.latencyMs,
      prompt_fingerprint: step.promptFingerprint,
      quality_signal: step.qualitySignal,
      ts: step.ts,
    };
  }

  private fromRow(r: Record<string, unknown>): StepRecord {
    return {
      decisionId: r['decision_id'] as string,
      stepIdx: r['step_idx'] as number,
      model: r['model'] as string,
      provider: r['provider'] as string,
      quantization: r['quantization'] as string | null,
      inputTokens: r['input_tokens'] as number,
      cachedInputTokens: r['cached_input_tokens'] as number,
      outputTokens: r['output_tokens'] as number,
      cacheEvent: r['cache_event'] as StepRecord['cacheEvent'],
      latencyMs: r['latency_ms'] as number,
      promptFingerprint: r['prompt_fingerprint'] as string | null,
      qualitySignal: r['quality_signal'] as number | null,
      ts: r['ts'] as string,
    };
  }
}
