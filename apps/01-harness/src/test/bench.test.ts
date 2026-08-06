import { describe, expect, it } from 'vitest';
import { runGateBench, compareAtEscape, confusions, gateMetrics, guardrailOnly } from '../bench/gated-decision';
import { suiteSamples } from '../bench/gated-suite';
import { runDuplicateToolCallHavoc, runDeadSandboxHavoc, runMidRunCrashHavoc, runAllHavoc } from '../bench/havoc';
import { toJson, toSvg, toPng, buildParetoPlot, ParetoPlotData, paretoFrontierOf } from '../bench/reporter';

describe('gated-decision bench', () => {
  it('benchmarks three decision policies over a fixed sample grid', () => {
    const samples = suiteSamples();
    expect(samples.length).toBeGreaterThan(10);
    const rows = runGateBench(samples);
    expect(rows.length).toBeGreaterThan(0);
    const names = new Set(rows.map((r) => r.name));
    expect(names.has('gate-3state')).toBe(true);
    expect(names.has('guardrails-only')).toBe(true);
    expect(names.has('turn-boundary-hitl')).toBe(true);
    for (const row of rows) {
      expect(row.blownRate).toBeGreaterThanOrEqual(0);
      expect(row.escapeRate).toBeGreaterThanOrEqual(0);
    }
  });

  it('gate-3state beats guardrails-only at matched escape rates on the suite', () => {
    const samples = suiteSamples('approvals');
    const at = compareAtEscape(samples, 0.5);
    expect(at.gate.blownRate).toBeLessThanOrEqual(at.guardrailsOnly.blownRate + 1e-9);
  });

  it('confusions counts blown executions and escalations', () => {
    const metrics = confusions(
      [
        { score: 0.9, outcome: true },
        { score: 0.8, outcome: false },
        { score: 0.2, outcome: false },
      ],
      (score) => (score >= 0.7 ? 'execute' : 'escalate'),
    );
    expect(metrics.executed).toBe(2);
    expect(metrics.blown).toBe(1);
    expect(metrics.escalationRate).toBe(1 / 3);
    expect(metrics.total).toBe(3);
  });

  it('gateMetrics and guardrailOnly produce comparable shapes', () => {
    const samples = suiteSamples();
    const g = gateMetrics(samples, 0.7, 0.3);
    const gr = guardrailOnly(samples, 0.7);
    expect(g).toHaveProperty('escapeRate');
    expect(gr).toHaveProperty('blownRate');
  });
});

describe('havoc suite', () => {
  it('duplicate tool calls in one turn execute the side effect once', async () => {
    const r = await runDuplicateToolCallHavoc();
    expect(r.passed).toBe(true);
    expect(r.detail['executions']).toBe(1);
  });

  it('a dead sandbox causes a retry path, never double effects', async () => {
    const r = await runDeadSandboxHavoc();
    expect(r.passed).toBe(true);
  });

  it('a mid-run crash preserves captures and resumes without re-executing', async () => {
    const r = await runMidRunCrashHavoc();
    expect(r.passed).toBe(true);
  });

  it('runs the full havoc battery', async () => {
    const results = await runAllHavoc();
    expect(results).toHaveLength(3);
    for (const r of results) expect(r.passed).toBe(true);
  });
});

describe('reporter', () => {
  const data: ParetoPlotData = {
    title: 'test',
    frontier: [
      { escapeRate: 0.2, blownRate: 0.1, name: 'gate-3state' },
      { escapeRate: 0.4, blownRate: 0.2, name: 'guardrails-only' },
    ],
    rows: [
      { name: 'gate-3state', escapeRate: 0.3, blownRate: 0.12, params: { execute: 0.7, reject: 0.3 } },
      { name: 'guardrails-only', escapeRate: 0.3, blownRate: 0.25, params: { threshold: 0.7 } },
    ],
    baselines: [],
  };

  it('toJson serializes the plot data', () => {
    const json = toJson(data);
    expect(JSON.parse(json).rows).toHaveLength(2);
  });

  it('toSvg produces an svg document', () => {
    const svg = toSvg(data);
    expect(svg).toContain('<svg');
    expect(svg).toContain('</svg>');
  });

  it('toPng produces a decodable png buffer', () => {
    const png = toPng(data);
    expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
    expect(png.length).toBeGreaterThan(1000);
  });

  it('buildParetoPlot derives frontier from rows', () => {
    const rows = [
      { name: 'gate-3state', escapeRate: 0.3, blownRate: 0.12, executed: 3, blown: 1, escalationRate: 0.1, total: 10, params: { execute: 0.7, reject: 0.3 } },
      { name: 'guardrails-only', escapeRate: 0.3, blownRate: 0.25, executed: 3, blown: 2, escalationRate: 0.1, total: 10, params: { threshold: 0.7 } },
    ];
    const plot = buildParetoPlot(rows as never, 'test', paretoFrontierOf(rows as never));
    expect(plot.frontier.length).toBeGreaterThan(0);
    expect(plot.title).toBe('test');
  });
});
