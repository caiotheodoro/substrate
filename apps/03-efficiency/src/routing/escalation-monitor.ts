import type { Server } from 'node:http';
import { z } from 'zod';
import { jsonRouter, listen, sendJson, sendText, envPort } from '../lib/http.js';
import { isMainModule } from '../lib/paths.js';
import type { Tier } from './routing-policy.js';

/**
 * A-E-18 escalation-monitor (:8104) — tiering-cascade meter.
 *
 * Aggressive small-model routing is only honest if its cost — the cascade
 * of escalations and rejects it creates — is measured per tier. The
 * monitor ingests per-decision verdicts (from 01's gate) tagged with the
 * routing tier the step was served on and exposes escalation/reject rates
 * per tier, as JSON and as prometheus text for the dashboards.
 */

export const TierVerdictSchema = z.object({
  decisionId: z.string(),
  tier: z.enum(['small', 'medium', 'frontier']),
  verdict: z.enum(['execute', 'escalate', 'reject']),
  ts: z.string(),
});

export type TierVerdict = z.infer<typeof TierVerdictSchema>;

export interface TierRates {
  count: number;
  execute: number;
  escalate: number;
  reject: number;
  escalationRate: number;
  rejectRate: number;
}

export function computeTierRates(verdicts: readonly TierVerdict[]): Record<Tier, TierRates> {
  const rates: Record<Tier, TierRates> = {
    small: { count: 0, execute: 0, escalate: 0, reject: 0, escalationRate: 0, rejectRate: 0 },
    medium: { count: 0, execute: 0, escalate: 0, reject: 0, escalationRate: 0, rejectRate: 0 },
    frontier: { count: 0, execute: 0, escalate: 0, reject: 0, escalationRate: 0, rejectRate: 0 },
  };
  for (const v of verdicts) {
    const row = rates[v.tier];
    if (row === undefined) continue;
    row.count++;
    row[v.verdict]++;
  }
  for (const row of Object.values(rates)) {
    row.escalationRate = row.count === 0 ? 0 : row.escalate / row.count;
    row.rejectRate = row.count === 0 ? 0 : row.reject / row.count;
  }
  return rates;
}

export function createEscalationMonitorServer() {
  const verdicts: TierVerdict[] = [];
  return jsonRouter([
    {
      method: 'POST',
      path: '/observe',
      handler: async (_req, res, _url, body) => {
        const verdict = TierVerdictSchema.parse(body);
        verdicts.push(verdict);
        sendJson(res, 200, { result: 'recorded' });
      },
    },
    {
      method: 'GET',
      path: '/rates',
      handler: (_req, res) => sendJson(res, 200, computeTierRates(verdicts)),
    },
    {
      method: 'GET',
      path: '/health',
      handler: (_req, res) => sendJson(res, 200, { ok: true }),
    },
    {
      method: 'GET',
      path: '/metrics',
      handler: (_req, res) => {
        const rates = computeTierRates(verdicts);
        const lines = ['# TYPE substrate_tier_verdict_total counter'];
        for (const [tier, row] of Object.entries(rates)) {
          for (const verdict of ['execute', 'escalate', 'reject'] as const) {
            lines.push(`substrate_tier_verdict_total{tier="${tier}",verdict="${verdict}"} ${row[verdict]}`);
          }
        }
        lines.push('');
        sendText(res, 200, lines.join('\n'));
      },
    },
  ]);
}

export async function startEscalationMonitor(port = envPort(8104)): Promise<{ server: Server; port: number }> {
  const server = createEscalationMonitorServer();
  const bound = await listen(server, port);
  return { server, port: bound };
}

if (isMainModule(import.meta.url)) {
  startEscalationMonitor().then(
    ({ port }) => process.stdout.write(`escalation-monitor on :${port}\n`),
    (err) => {
      process.stderr.write(String(err) + '\n');
      process.exit(1);
    },
  );
}
