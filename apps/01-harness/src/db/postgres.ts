import type { Pool, PoolClient } from 'pg';
import type {
  DecisionRecord,
  StoredEvent,
  StepRecord,
} from '@substrate/substrate';
import type {
  Escalation,
  PendingAction,
  RunRecord,
  SandboxLease,
  Stores,
  ThresholdBand,
} from '../types';
import { chainHashOf } from './memory';

export function createPostgresStores(pool: Pool): Stores {
  const tx = async <T>(fn: (client: PoolClient) => Promise<T>): Promise<T> => {
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      const res = await fn(client);
      await client.query('COMMIT');
      return res;
    } catch (e) {
      await client.query('ROLLBACK');
      throw e;
    } finally {
      client.release();
    }
  };

  return {
    runs: {
      async create(r) {
        await pool.query(
          'INSERT INTO runs (id, task, status, reason, max_turns, started_at, ended_at, seq) VALUES ($1,$2,$3,$4,$5,$6,$7)',
          [r.id, r.task, r.status, r.maxTurns, r.startedAt, r.endedAt, r.seq],
        );
      },
      async get(id) {
        const { rows } = await pool.query('SELECT * FROM runs WHERE id=$1', [id]);
        return rows[0] ? mapRun(rows[0]) : null;
      },
      async update(id, patch) {
        const allowed: [string, string][] = [
          ['status', 'status'],
          ['reason', 'reason'],
          ['ended_at', 'endedAt'],
          ['max_turns', 'maxTurns'],
          ['seq', 'seq'],
        ];
        for (const [col, field] of allowed) {
          if (field in patch && patch[field as keyof RunRecord] !== undefined) {
            await pool.query(`UPDATE runs SET ${col}=$2 WHERE id=$1`, [id, patch[field as keyof RunRecord]]);
          }
        }
      },
      async list() {
        const { rows } = await pool.query('SELECT * FROM runs ORDER BY started_at DESC');
        return rows.map(mapRun);
      },
    },
    events: {
      async tail(runId) {
        const { rows } = await pool.query(
          'SELECT seq, chain_hash FROM events WHERE run_id=$1 ORDER BY seq DESC LIMIT 1',
          [runId],
        );
        const row = rows[0];
        return { seq: row ? Number(row.seq) : -1, chainHash: row ? (row.chain_hash as string) : null };
      },
      async append(runId, evts, prev) {
        return tx(async (client) => {
          const stored: StoredEvent[] = [];
          let seq = prev.seq;
          let hash = prev.chainHash;
          const { rows } = await client.query(
            'SELECT idempotency_key FROM events WHERE run_id=$1',
            [runId],
          );
          const existing = new Set(rows.map((r) => r.idempotency_key as string));
          for (const ev of evts) {
            const key =
              ev.family === 'capture'
                ? `${runId}:${(ev as { toolCallId: string }).toolCallId}:${(ev as { attempt?: number }).attempt ?? 0}`
                : `${runId}:${ev.family}:${seq + 1 + stored.length}`;
            if (existing.has(key)) continue;
            seq += 1;
            const ts = ev.family === 'capture' ? (ev as { ts: string }).ts : new Date().toISOString();
            hash = chainHashOf(hash, runId, seq, key, ev);
            await client.query(
              'INSERT INTO events (run_id, seq, family, kind, payload, tool_call_id, result, ts, idempotency_key, chain_hash) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT DO NOTHING',
              [
                runId,
                seq,
                ev.family,
                ev.family === 'stream' || ev.family === 'narrative' ? ev.kind : null,
                ev.family === 'stream' || ev.family === 'narrative' ? JSON.stringify(ev.payload) : null,
                ev.family === 'capture' ? ev.toolCallId : null,
                ev.family === 'capture' ? JSON.stringify(ev.result) : null,
                ts,
                key,
                hash,
              ],
            );
            const storedEvent: StoredEvent = {
              ...ev,
              runId,
              seq,
              idempotencyKey: key,
              chainHash: hash,
              ts,
            };
            stored.push(storedEvent);
          }
          return stored;
        });
      },
      async list(runId) {
        const { rows } = await pool.query('SELECT * FROM events WHERE run_id=$1 ORDER BY seq', [runId]);
        return rows.map(mapEvent);
      },
    },
    decisions: {
      async insert(d) {
        await pool.query(
          'INSERT INTO decisions (decision_id, turn_id, action, confidence_features, verdict, outcome, confirmed_at) VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (decision_id) DO UPDATE SET verdict=EXCLUDED.verdict',
          [
            d.decisionId,
            d.turnId,
            d.action,
            JSON.stringify(d.confidenceFeatures),
            d.verdict,
            d.outcome,
            d.confirmedAt,
          ],
        );
      },
      async get(id) {
        const { rows } = await pool.query('SELECT * FROM decisions WHERE decision_id=$1', [id]);
        return rows[0] ? mapDecision(rows[0]) : null;
      },
      async list() {
        const { rows } = await pool.query('SELECT * FROM decisions ORDER BY turn_id, decision_id');
        return rows.map(mapDecision);
      },
      async confirmOutcome(id, outcome) {
        await pool.query('UPDATE decisions SET outcome=$2, confirmed_at=$3 WHERE decision_id=$1', [
          id,
          outcome,
          new Date().toISOString(),
        ]);
      },
    },
    pendingActions: {
      async insert(a) {
        await pool.query(
          'INSERT INTO pending_actions (id, run_id, turn_id, kind, prompt, schema, answer, status, created_at, resolved_at, resolved_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)',
          [a.id, a.runId, a.turnId, a.kind, a.prompt, JSON.stringify(a.schema), a.answer ? JSON.stringify(a.answer) : null, a.status, a.createdAt, a.resolvedAt, a.resolvedBy],
        );
      },
      async list(runId) {
        const { rows } = await pool.query('SELECT * FROM pending_actions WHERE run_id=$1 ORDER BY created_at', [runId]);
        return rows.map(mapPendingAction);
      },
      async get(id) {
        const { rows } = await pool.query('SELECT * FROM pending_actions WHERE id=$1', [id]);
        return rows[0] ? mapPendingAction(rows[0]) : null;
      },
      async resolve(id, answer, by) {
        await pool.query('UPDATE pending_actions SET answer=$2, status=$3, resolved_at=$4, resolved_by=$5 WHERE id=$1', [
          id,
          JSON.stringify(answer),
          'resolved',
          new Date().toISOString(),
          by,
        ]);
      },
    },
    escalations: {
      async insert(e) {
        await pool.query(
          'INSERT INTO escalations (escalation_id, run_id, decision_id, proposal, confidence, explain, verdict, created_at, resolved_at, decided_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)',
          [e.id, e.runId, e.decisionId, JSON.stringify(e.proposal), e.confidence, JSON.stringify(e.explain), e.verdict, e.createdAt, e.resolvedAt, e.decidedBy],
        );
      },
      async list() {
        const { rows } = await pool.query('SELECT * FROM escalations ORDER BY created_at DESC');
        return rows.map(mapEscalation);
      },
      async get(id) {
        const { rows } = await pool.query('SELECT * FROM escalations WHERE escalation_id=$1', [id]);
        return rows[0] ? mapEscalation(rows[0]) : null;
      },
      async decide(id, verdict, by) {
        await pool.query('UPDATE escalations SET verdict=$2, resolved_at=$3, decided_by=$4 WHERE escalation_id=$1', [
          id,
          verdict,
          new Date().toISOString(),
          by,
        ]);
      },
    },
    sandboxLeases: {
      async upsert(l) {
        await pool.query(
          'INSERT INTO sandbox_leases (id, container_id, image, lease_ms, expires_at, updated_at, status) VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (id) DO UPDATE SET expires_at=EXCLUDED.expires_at, updated_at=EXCLUDED.updated_at, status=EXCLUDED.status',
          [l.id, l.containerId, l.image, l.leaseMs, l.expiresAt, l.updatedAt, l.status],
        );
      },
      async get(id) {
        const { rows } = await pool.query('SELECT * FROM sandbox_leases WHERE id=$1', [id]);
        return rows[0] ? mapLease(rows[0]) : null;
      },
      async remove(id) {
        await pool.query('DELETE FROM sandbox_leases WHERE id=$1', [id]);
      },
      async list() {
        const { rows } = await pool.query('SELECT * FROM sandbox_leases');
        return rows.map(mapLease);
      },
    },
    thresholds: {
      async set(taskType, band) {
        await pool.query(
          'INSERT INTO thresholds (task_type, execute_threshold, reject_threshold, note) VALUES ($1,$2,$3,$4) ON CONFLICT (task_type) DO UPDATE SET execute_threshold=EXCLUDED.execute_threshold, reject_threshold=EXCLUDED.reject_threshold, note=EXCLUDED.note',
          [taskType, band.executeThreshold, band.rejectThreshold, band.note ?? null],
        );
      },
      async get(taskType) {
        const { rows } = await pool.query('SELECT * FROM thresholds WHERE task_type=$1', [taskType]);
        const row = rows[0];
        return row ? mapBand(row) : null;
      },
      async list() {
        const { rows } = await pool.query('SELECT * FROM thresholds');
        return rows.map(mapBand);
      },
    },
    costLedger: {
      async insert(step) {
        await pool.query(
          'INSERT INTO cost_ledger (decision_id, step_idx, model, provider, quantization, input_tokens, cached_input_tokens, output_tokens, cache_event, latency_ms, prompt_fingerprint, quality_signal, ts) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)',
          [step.decisionId, step.stepIdx, step.model, step.provider, step.quantization, step.inputTokens, step.cachedInputTokens, step.outputTokens, step.cacheEvent, step.latencyMs, step.promptFingerprint, step.qualitySignal, step.ts],
        );
      },
      async list() {
        const { rows } = await pool.query('SELECT * FROM cost_ledger');
        return rows.map(mapStep);
      },
    },
    emit: {
      on() {
        return () => undefined;
      },
    },
  };
}

function mapRun(row: Record<string, unknown>): RunRecord {
  return {
    id: row.id as string,
    task: row.task as string,
    status: row.status as RunRecord['status'],
    reason: row.reason as string | null,
    maxTurns: Number(row.max_turns),
    startedAt: row.started_at as string,
    endedAt: row.ended_at as string | null,
    seq: Number(row.seq),
  };
}

function mapEvent(row: Record<string, unknown>): StoredEvent {
  const family = row.family as string;
  if (family === 'capture') {
    return {
      family: 'capture',
      toolCallId: row.tool_call_id as string,
      result: JSON.parse(row.result as string),
      attempt: Number(row.attempt ?? 0),
      ts: row.ts as string,
      runId: row.run_id as string,
      seq: Number(row.seq),
      idempotencyKey: row.idempotency_key as string,
      chainHash: row.chain_hash as string,
    };
  }
  return {
    family,
    kind: row.kind as string,
    payload: JSON.parse(row.payload as string),
    runId: row.run_id as string,
    seq: Number(row.seq),
    idempotencyKey: row.idempotency_key as string,
    chainHash: row.chain_hash as string,
    ts: row.ts as string,
  } as StoredEvent;
}

function mapDecision(row: Record<string, unknown>): DecisionRecord {
  const outcome = row.outcome === null ? null : Boolean(row.outcome);
  return {
    decisionId: row.decision_id as string,
    turnId: row.turn_id as string,
    action: row.action as string,
    confidenceFeatures: JSON.parse(row.confidence as string ?? '{}') as Record<string, unknown>,
    verdict: row.verdict as DecisionRecord['verdict'],
    outcome,
    confirmedAt: row.confirmed_at as string | null,
  };
}

function mapPendingAction(row: Record<string, unknown>): PendingAction {
  return {
    id: row.id as string,
    runId: row.run_id as string,
    turnId: row.turn_id as string,
    kind: row.kind as PendingAction['kind'],
    prompt: row.prompt as string,
    schema: JSON.parse(row.schema as string) as Record<string, unknown>,
    answer: row.answer ? (JSON.parse(row.answer as string) as Record<string, unknown>) : null,
    status: row.status as PendingAction['status'],
    createdAt: row.created_at as string,
    resolvedAt: row.resolved_at as string | null,
    resolvedBy: row.resolved_by as string | null,
  };
}

function mapEscalation(row: Record<string, unknown>): Escalation {
  return {
    id: row.escalation_id as string,
    runId: row.run_id as string | null,
    decisionId: row.decision_id as string,
    proposal: JSON.parse(row.proposal as string) as Escalation['proposal'],
    confidence: Number(row.confidence),
    explain: JSON.parse(row.explain as string) as Record<string, unknown>,
    verdict: row.verdict as Escalation['verdict'],
    createdAt: row.created_at as string,
    resolvedAt: row.resolved_at as string | null,
    decidedBy: row.decided_by as string | null,
  };
}

function mapLease(row: Record<string, unknown>): SandboxLease {
  return {
    id: row.id as string,
    containerId: row.container_id as string,
    image: row.image as string,
    leaseMs: Number(row.lease_ms),
    expiresAt: row.expires_at as string,
    updatedAt: row.updated_at as string,
    status: row.status as SandboxLease['status'],
  };
}

function mapBand(row: Record<string, unknown>): ThresholdBand {
  return {
    taskType: row.task_type as string,
    executeThreshold: Number(row.execute_threshold),
    rejectThreshold: Number(row.reject_threshold),
    note: row.note as string | undefined,
  };
}

function mapStep(row: Record<string, unknown>): StepRecord {
  return {
    decisionId: row.decision_id as string,
    stepIdx: Number(row.step_id),
    model: row.model as string,
    provider: row.provider as string,
    quantization: row.quantization as string | null,
    inputTokens: Number(row.input_tokens),
    cachedInputTokens: Number(row.cached_input_tokens),
    outputTokens: Number(row.output_tokens),
    cacheEvent: row.cache_event as StepRecord['cacheEvent'],
    latencyMs: Number(row.latency_ms),
    promptFingerprint: row.prompt_fingerprint as string | null,
    qualitySignal: row.quality_signal === null ? null : Number(row.quality_signal),
    ts: row.ts as string,
  };
}