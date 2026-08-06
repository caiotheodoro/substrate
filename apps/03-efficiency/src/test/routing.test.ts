import { describe, expect, it } from 'vitest';
import { DEFAULT_POLICY, routeFor, selectTier } from '../routing/routing-policy.js';
import { confidenceToTier, DEFAULT_THRESHOLDS } from '../routing/confidence-adapter.js';
import { createRoutingServer, type UpstreamClient } from '../routing/routing-service.js';
import { MemoryLedgerStore } from '../ledger/store.js';
import { listen } from '../lib/http.js';
import { calibrateThresholds, tieredCost } from '../routing/calibrator.js';
import { createEscalationMonitorServer } from '../routing/escalation-monitor.js';

describe('A-E-14 routing-policy', () => {
  it('selects the cheapest tier whose confidence minimum is met', () => {
    expect(selectTier(DEFAULT_POLICY, 0.95)).toBe('small');
    expect(selectTier(DEFAULT_POLICY, 0.85)).toBe('small');
    expect(selectTier(DEFAULT_POLICY, 0.75)).toBe('medium');
    expect(selectTier(DEFAULT_POLICY, 0.5)).toBe('frontier');
  });

  it('a reject band never routes to a cheap tier', () => {
    expect(selectTier(DEFAULT_POLICY, 0.95, 'reject-band')).toBe('frontier');
    expect(selectTier(DEFAULT_POLICY, 0.95, 'execute-band')).toBe('small');
  });

  it('routes to the tuple of the selected tier', () => {
    expect(routeFor(DEFAULT_POLICY, 0.9)).toEqual({
      model: 'llama3.1:8b',
      provider: 'ollama',
      quantization: 'q4_k_m',
    });
    expect(routeFor(DEFAULT_POLICY, 0.3)).toEqual({
      model: 'llama3.3:70b',
      provider: 'litellm',
      quantization: null,
    });
  });
});

describe('A-E-16 confidence-adapter', () => {
  it('maps C5 confidence responses to tiers via thresholds', () => {
    expect(confidenceToTier({ score: 0.9, band: 'execute-band', explain: {}, modelVersion: 'v1' })).toBe('small');
    expect(confidenceToTier({ score: 0.75, band: 'execute-band', explain: {}, modelVersion: 'v1' })).toBe('medium');
    expect(confidenceToTier({ score: 0.6, band: 'execute-band', explain: {}, modelVersion: 'v1' })).toBe('frontier');
    expect(confidenceToTier({ score: 0.8, band: 'escalation-band', explain: {}, modelVersion: 'v1' })).toBe('medium');
    expect(confidenceToTier({ score: 0.95, band: 'reject-band', explain: {}, modelVersion: 'v1' })).toBe('frontier');
  });

  it('default thresholds respect the tier order invariant', () => {
    expect(DEFAULT_THRESHOLDS.small).toBeGreaterThan(DEFAULT_THRESHOLDS.medium);
  });
});

describe('A-E-15 routing-service', () => {
  class FakeUpstream implements UpstreamClient {
    requestedBodies: unknown[] = [];
    constructor(
      private readonly usage: Record<string, unknown> = {
        prompt_tokens: 150,
        completion_tokens: 20,
        prompt_tokens_details: { cached_tokens: 50 },
      },
    ) {}
    async postChatCompletion(body: unknown) {
      this.requestedBodies.push(body);
      return { status: 200, json: { id: 'cmpl-1', object: 'chat.completion', created: 1, model: 'm', choices: [], usage: this.usage } };
    }
  }

  it('routes a confident request to the small tier and emits an exclusive-bucket StepRecord', async () => {
    const ledger = new MemoryLedgerStore();
    const upstream = new FakeUpstream();
    const server = createRoutingServer({ ledger, upstreams: { ollama: upstream, litellm: upstream } });
    const port = await listen(server, 0);
    const res = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-substrate-confidence': '0.95', 'x-substrate-decision-id': 'd-42' },
      body: JSON.stringify({ model: 'whatever', messages: [{ role: 'user', content: 'hi' }] }),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { usage: { prompt_tokens: number } };
    expect(body.usage.prompt_tokens).toBe(150);
    expect((upstream.requestedBodies[0] as { model: string }).model).toBe('llama3.1:8b');
    const steps = await ledger.listSteps();
    expect(steps).toHaveLength(1);
    expect(steps[0]!.decisionId).toBe('d-42');
    expect(steps[0]!.inputTokens).toBe(100);
    expect(steps[0]!.cachedInputTokens).toBe(50);
    expect(steps[0]!.inputTokens + steps[0]!.cachedInputTokens).toBe(150);
    server.close();
  });

  it('returns 503 when the routed provider has no upstream', async () => {
    const ledger = new MemoryLedgerStore();
    const server = createRoutingServer({ ledger, upstreams: {} });
    const port = await listen(server, 0);
    const res = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-substrate-confidence': '0.2' },
      body: JSON.stringify({ messages: [] }),
    });
    expect(res.status).toBe(503);
    server.close();
  });

  it('exposes the routed models under /v1/models', async () => {
    const ledger = new MemoryLedgerStore();
    const server = createRoutingServer({ ledger, upstreams: {} });
    const port = await listen(server, 0);
    const res = await fetch(`http://127.0.0.1:${port}/v1/models`).then((r) => r.json());
    expect((res as { data: { id: string }[] }).data.map((m) => m.id)).toEqual([
      'llama3.1:8b',
      'qwen2.5:14b',
      'llama3.3:70b',
    ]);
    server.close();
  });
});

describe('A-E-17 routing-calibrator', () => {
  it('picks thresholds that keep outcomes and cut cost', () => {
    const samples = [
      { confidence: 0.95, cost: 10, outcome: 1 },
      { confidence: 0.93, cost: 10, outcome: 1 },
      { confidence: 0.91, cost: 10, outcome: 1 },
      { confidence: 0.9, cost: 10, outcome: 1 },
      { confidence: 0.88, cost: 10, outcome: 1 },
      { confidence: 0.86, cost: 10, outcome: 1 },
      { confidence: 0.8, cost: 10, outcome: 1 },
      { confidence: 0.78, cost: 10, outcome: 1 },
      { confidence: 0.3, cost: 10, outcome: 0 },
      { confidence: 0.25, cost: 10, outcome: 0 },
    ];
    const result = calibrateThresholds(samples);
    expect(result.outcomeRate).toBeCloseTo(8 / 10, 5);
    expect(result.cost).toBeLessThan(result.baselineCost);
    expect(result.costReductionPct).toBeGreaterThan(50);
  });

  it('tiered cost applies the cheap multiplier below the small threshold', () => {
    const samples = [{ confidence: 0.99, cost: 10, outcome: 1 }];
    expect(tieredCost(samples, { small: 0.85, medium: 0.7 })).toBeCloseTo(1.2, 5);
  });
});

describe('A-E-18 escalation-monitor', () => {
  it('computes escalation/reject rates per tier', async () => {
    const server = createEscalationMonitorServer();
    const port = await listen(server, 0);
    const base = `http://127.0.0.1:${port}`;
    const observe = (tier: string, verdict: string) =>
      fetch(`${base}/observe`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ decisionId: 'd', tier, verdict, ts: 't' }),
      });
    await observe('small', 'execute');
    await observe('small', 'execute');
    await observe('small', 'escalate');
    await observe('medium', 'reject');
    const rates = (await fetch(`${base}/rates`).then((r) => r.json())) as Record<string, { escalationRate: number; rejectRate: number }>;
    expect(rates.small!.escalationRate).toBeCloseTo(1 / 3, 5);
    expect(rates.medium!.rejectRate).toBe(1);
    const metrics = await fetch(`${base}/metrics`).then((r) => r.text());
    expect(metrics).toContain('substrate_tier_verdict_total');
    server.close();
  });
});
