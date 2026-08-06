import { createHash } from 'node:crypto';
import type {
  DecisionRecord,
  Event,
  StoredEvent,
  StepRecord,
} from '@substrate/substrate';
import { canonicalJson, idempotencyKey } from '@substrate/substrate';
import type {
  Escalation,
  PendingAction,
  RunRecord,
  SandboxLease,
  Stores,
  ThresholdBand,
} from '../types';

export function createMemoryStores(clock?: { now(): string; nextId?(prefix: string): string }): Stores {
  const tsNow = clock?.now ?? (() => new Date().toISOString());
  const runs = new Map<string, RunRecord>();
  const events = new Map<string, StoredEvent[]>();
  const decisions = new Map<string, DecisionRecord>();
  const pendingActions = new Map<string, PendingAction>();
  const escalations = new Map<string, Escalation>();
  const sandboxLeases = new Map<string, SandboxLease>();
  const thresholds = new Map<string, ThresholdBand>();
  const costLedger: StepRecord[] = [];
  const listeners = new Set<(e: StoredEvent) => void>();

  return {
    runs: {
      async create(r) {
        runs.set(r.id, { ...r });
      },
      async get(id) {
        return runs.get(id) ?? null;
      },
      async update(id, patch) {
        const cur = runs.get(id);
        if (cur) runs.set(id, { ...cur, ...patch });
      },
      async list() {
        return [...runs.values()];
      },
    },
    events: {
      async tail(runId: string) {
        const list = events.get(runId) ?? [];
        const last = list.at(-1);
        return { seq: last ? last.seq : -1, chainHash: last ? last.chainHash : null };
      },
      async append(runId, evts, prev) {
        const list = events.get(runId) ?? [];
        const stored: StoredEvent[] = [];
        let seq = prev.seq;
        let hash = prev.chainHash;
        const existing = new Set(list.map((e) => e.idempotencyKey));
        for (const ev of evts) {
          const seqNext = seq + 1;
          const key = assignmentIdempotencyKey(ev, runId, seqNext);
          if (existing.has(key)) continue;
          seq = seqNext;
          hash = chainHashOf(hash, runId, seq, key, ev);
          const storedEvent: StoredEvent = {
            ...ev,
            runId,
            seq,
            idempotencyKey: key,
            chainHash: hash,
            ts: ev.family === 'capture' ? (ev as { ts: string }).ts : tsNow(),
          };
          existing.add(key);
          stored.push(storedEvent);
          listeners.forEach((fn) => fn(storedEvent));
        }
        if (stored.length > 0) events.set(runId, [...list, ...stored]);
        return stored;
      },
      async list(runId) {
        return [...(events.get(runId) ?? [])].sort((a, b) => a.seq - b.seq);
      },
    },
    decisions: {
      async insert(d) {
        decisions.set(d.decisionId, { ...d });
      },
      async get(id) {
        return decisions.get(id) ?? null;
      },
      async list() {
        return [...decisions.values()];
      },
      async confirmOutcome(id, outcome) {
        const d = decisions.get(id);
        if (d) decisions.set(id, { ...d, outcome, confirmedAt: isoNow() });
      },
    },
    pendingActions: {
      async insert(a) {
        pendingActions.set(a.id, { ...a });
      },
      async list(runId) {
        return [...pendingActions.values()].filter((a) => a.runId === runId);
      },
      async get(id) {
        return pendingActions.get(id) ?? null;
      },
      async resolve(id, answer, by) {
        const a = pendingActions.get(id);
        if (a) pendingActions.set(id, { ...a, answer, status: 'resolved', resolvedAt: isoNow(), resolvedBy: by });
      },
    },
    escalations: {
      async insert(e) {
        escalations.set(e.id, { ...e });
      },
      async list() {
        return [...escalations.values()];
      },
      async get(id) {
        return escalations.get(id) ?? null;
      },
      async decide(id, verdict, by) {
        const e = escalations.get(id);
        if (e) escalations.set(id, { ...e, verdict, resolvedAt: isoNow(), decidedBy: by });
      },
    },
    sandboxLeases: {
      async upsert(l) {
        sandboxLeases.set(l.id, { ...l });
      },
      async get(id) {
        return sandboxLeases.get(id) ?? null;
      },
      async remove(id) {
        sandboxLeases.delete(id);
      },
      async list() {
        return [...sandboxLeases.values()];
      },
    },
    thresholds: {
      async set(taskType, band) {
        thresholds.set(taskType, { taskType, ...band });
      },
      async get(taskType) {
        return thresholds.get(taskType) ?? null;
      },
      async list() {
        return [...thresholds.values()];
      },
    },
    costLedger: {
      async insert(step) {
        costLedger.push(step);
      },
      async list() {
        return [...costLedger];
      },
    },
    emit: {
      on(fn) {
        listeners.add(fn);
        return () => listeners.delete(fn);
      },
    },
  };
}

export function chainHashOf(prev: string | null, runId: string, seq: number, key: string | null, ev: Event): string {
  const line = canonicalJson({
    runId,
    seq,
    prev,
    event: ev,
    key,
  });
  return sha256(line);
}

export function sha256(input: string): string {
  return createHash('sha256').update(input).digest('hex');
}

export function assignmentIdempotencyKey(ev: Event, runId: string, seq: number): string {
  if (ev.family === 'capture') {
    const c = ev as { toolCallId: string; attempt?: number };
    return idempotencyKey(runId, c.toolCallId, c.attempt ?? 0);
  }
  return `${runId}:${ev.family}:${seq}`;
}

let isoNow = () => new Date().toISOString();
export function setIsoNow(fn: () => string) {
  isoNow = fn;
}