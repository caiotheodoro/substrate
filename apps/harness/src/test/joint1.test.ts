import { describe, expect, it } from 'vitest';
import type { Server } from 'node:http';
import { remoteConfidenceProvider, resilientConfidenceProvider, TRUST_SCORER_URL } from '../gate/remote-confidence';
import { GateCore } from '../gate/gate-core';
import { gate } from '@substrate/substrate';

/**
 * Joint 1 e2e (C5): 01's gate consumes 02's Trust scorer over HTTP.
 *
 * The Trust scorer-serve app is FastAPI (Python); this test proves the
 * contract with an HTTP server speaking the exact same C5 shape that
 * `apps/trust/py/src/trust/scorer/serve.py` serves on :8020
 * (`POST /confidence → {score, band, explain, modelVersion}`).
 */
function c5Server(port: number): Promise<Server> {
  const { createServer } = require('node:http') as typeof import('node:http');
  return new Promise((resolve) => {
    const server = createServer((req, res) => {
      let body = '';
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        const parsed = JSON.parse(body) as { decisionId: string; confidenceFeatures: Record<string, unknown> };
        const features = parsed.confidenceFeatures;
        const risk = typeof features.riskScore === 'number' ? features.riskScore : 0.3;
        const score = Math.min(1, Math.max(0, 0.9 - risk * 1.2));
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(
          JSON.stringify({
            score,
            band: score >= 0.7 ? 'execute-band' : score < 0.3 ? 'reject-band' : 'escalation-band',
            explain: { riskScore: risk },
            modelVersion: 'trust-scorer-v1',
          }),
        );
      });
    });
    server.listen(port, () => resolve(server));
  });
}

describe('joint1 C5 — 01 gate ← 02 trust scorer', () => {
  it('remoteConfidenceProvider parses the C5 response and drives the gate verdict', async () => {
    const port = 18020;
    const server = await c5Server(port);
    try {
      const provider = remoteConfidenceProvider({ baseUrl: `http://127.0.0.1:${port}`, fetchImpl: fetch });
      const score = await provider.score({ riskScore: 0.1 });
      expect(score.score).toBeGreaterThanOrEqual(0.7);
      expect(score.modelVersion).toBe('trust-scorer-v1');

      const gateCore = new GateCore({ executeThreshold: 0.7, rejectThreshold: 0.3 }, provider);
      const lowRisk = await gateCore.decide('echo', { riskScore: 0.1 });
      expect(lowRisk.verdict).toBe('execute');
      const highRisk = await gateCore.decide('echo', { riskScore: 0.8 });
      expect(highRisk.verdict).toBe('reject');
    } finally {
      server.close();
    }
  });

  it('C5 band matches the gate thresholds (same two-threshold semantics)', async () => {
    const port = 18021;
    const server = await c5Server(port);
    try {
      const provider = remoteConfidenceProvider({ baseUrl: `http://127.0.0.1:${port}` });
      for (const risk of [0.05, 0.3, 0.6]) {
        const { score } = await provider.score({ riskScore: risk });
        const verdict = gate(score, 0.7, 0.3);
        if (score >= 0.7) expect(verdict).toBe('execute');
        else if (score < 0.3) expect(verdict).toBe('reject');
        else expect(verdict).toBe('escalate');
      }
    } finally {
      server.close();
    }
  });

  it('resilient provider falls back to heuristic when the remote is down', async () => {
    const provider = resilientConfidenceProvider({
      baseUrl: 'http://127.0.0.1:1',
      timeoutMs: 300,
    });
    const score = await provider.score({ riskScore: 0.5 });
    expect(score.score).toBeGreaterThanOrEqual(0);
    expect(score.score).toBeLessThanOrEqual(1);
    expect((score.explain as Record<string, unknown>).remoteFallback).toBeTruthy();
  });

  it('requireRemote mode propagates the failure (no silent fallback)', async () => {
    const provider = resilientConfidenceProvider({ baseUrl: 'http://127.0.0.1:1', timeoutMs: 300, requireRemote: true });
    await expect(provider.score({})).rejects.toThrow();
  });

  it('default endpoint points at the trust stack port', () => {
    expect(TRUST_SCORER_URL).toContain('8020');
  });
});
