import { describe, expect, it } from 'vitest';
import {
  BudgetEventSchema,
  ConfidenceResponseSchema,
  DecisionRecordSchema,
  DeltaPayloadSchema,
  EventSchema,
  PatchOpSchema,
  RetrievalVerdictSchema,
  StepRecordSchema,
  StoredEventSchema,
  brierScore,
  canonicalJson,
  coverage,
  expectedCalibrationError,
  gate,
  idempotencyKey,
  ndcgAtK,
} from './index';

describe('C1 event log', () => {
  it('accepts the three families and rejects unknown families', () => {
    expect(EventSchema.parse({ family: 'capture', toolCallId: 't1', result: {}, ts: 'x', attempt: 0 }).family).toBe('capture');
    expect(() => EventSchema.parse({ family: 'other' })).toThrow();
  });

  it('stored events require runId, seq, idempotencyKey, chainHash', () => {
    const ev = StoredEventSchema.parse({
      family: 'capture',
      toolCallId: 't1',
      result: {},
      ts: 'x',
      attempt: 0,
      runId: 'r1',
      seq: 0,
      idempotencyKey: 'r1:t1:0',
      chainHash: 'a'.repeat(64),
    });
    expect(ev.seq).toBe(0);
    expect(() => StoredEventSchema.parse({ ...ev, chainHash: 'short' })).toThrow();
  });

  it('canonicalJson is byte-stable regardless of key order', () => {
    expect(canonicalJson({ b: 1, a: [2, { d: 3, c: 4 }] })).toBe(
      canonicalJson({ a: [2, { c: 4, d: 3 }], b: 1 }),
    );
  });

  it('idempotency key is deterministic per run/tool/attempt', () => {
    expect(idempotencyKey('r', 't', 0)).toBe('r:t:0');
  });
});

describe('C2 decisions', () => {
  it('parses a decision record', () => {
    const d = DecisionRecordSchema.parse({
      decisionId: 'd1',
      turnId: 'turn-1',
      action: 'execute:frobnicate',
      confidenceFeatures: { toolVerified: true },
      verdict: 'escalate',
      outcome: null,
      confirmedAt: null,
    });
    expect(d.verdict).toBe('escalate');
  });

  it('gate implements two-threshold semantics', () => {
    expect(gate(0.9, 0.7, 0.3)).toBe('execute');
    expect(gate(0.2, 0.7, 0.3)).toBe('reject');
    expect(gate(0.5, 0.7, 0.3)).toBe('escalate');
  });
});

describe('C3 retrieval verdict', () => {
  it('only allows the three states with recalibrated prob', () => {
    expect(RetrievalVerdictSchema.parse({ kind: 'silent', prob: 0.6, citedEvidence: null, claim: 'x' }).kind).toBe('silent');
    expect(() => RetrievalVerdictSchema.parse({ kind: 'cosine', prob: 0.6, citedEvidence: null, claim: 'x' })).toThrow();
  });
});

describe('C4 cost ledger', () => {
  it('parses a step record with exclusive buckets', () => {
    const s = StepRecordSchema.parse({
      decisionId: 'd1',
      stepIdx: 0,
      model: 'llama3.1',
      provider: 'ollama',
      quantization: 'q4_k_m',
      inputTokens: 100,
      cachedInputTokens: 900,
      outputTokens: 50,
      cacheEvent: 'hit',
      latencyMs: 120,
      promptFingerprint: 'abc',
      qualitySignal: 0.9,
      ts: 't',
    });
    expect(s.cachedInputTokens).toBe(900);
  });

  it('parses budget events and rejects bad outcomes', () => {
    expect(BudgetEventSchema.parse({ decisionId: 'd', stepIdx: 0, estimatedTokens: 1, budget: 2, outcome: 'pass' }).outcome).toBe('pass');
    expect(() => BudgetEventSchema.parse({ decisionId: 'd', stepIdx: 0, estimatedTokens: 1, budget: 2, outcome: 'maybe' })).toThrow();
  });
});

describe('C5 confidence API', () => {
  it('enforces score range and band vocabulary', () => {
    expect(ConfidenceResponseSchema.parse({ score: 0.8, band: 'execute-band', explain: {}, modelVersion: 'v1' }).band).toBe('execute-band');
    expect(() => ConfidenceResponseSchema.parse({ score: 1.2, band: 'execute-band', explain: {}, modelVersion: 'v1' })).toThrow();
  });
});

describe('C7 wire discipline', () => {
  it('parses RFC 6902 patch ops', () => {
    const ops = PatchOpSchema.array().parse([
      { op: 'replace', path: '/title', value: 'New' },
      { op: 'move', path: '/a', from: '/b' },
      { op: 'test', path: '/title', value: 'New' },
    ]);
    expect(ops).toHaveLength(3);
  });

  it('parses delta payloads', () => {
    const d = DeltaPayloadSchema.parse({ kind: 'render_ui', base: null, ops: [{ op: 'add', path: '/btn', value: 1 }] });
    expect(d.ops[0]!.op).toBe('add');
  });
});

describe('eval core', () => {
  it('brier score on perfect calibration', () => {
    expect(brierScore([0, 1], [0, 1])).toBe(0);
    expect(brierScore([1, 0], [0, 1])).toBeCloseTo(1, 5);
  });

  it('ECE is zero for a single perfectly calibrated bin', () => {
    const { ece } = expectedCalibrationError([1], [1], 10);
    expect(ece).toBe(0);
  });

  it('coverage counts interval hits', () => {
    expect(coverage([0.5], [0], [1], 0.95)).toBe(1);
    expect(coverage([2], [0], [1], 0.95)).toBe(0);
  });

  it('ndcg ranks escalation-worthy decisions first', () => {
    const good = ndcgAtK([1, 0, 0], 3);
    const bad = ndcgAtK([0, 0, 1], 3);
    expect(good).toBeGreaterThan(bad);
  });
});
