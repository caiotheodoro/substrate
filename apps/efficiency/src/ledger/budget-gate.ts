import type { Server } from 'node:http';
import { z } from 'zod';
import { jsonRouter, listen, sendJson, sendText, envPort } from '../lib/http.js';
import { isMainModule } from '../lib/paths.js';
import type { LedgerStore } from './store.js';

/**
 * A-E-06 budget-gate (:8103) — a budget blow is a DECISION, never a crash.
 *
 * POST /gate  {decisionId, stepIdx, estimatedTokens, budget} →
 *   {decisionId, stepIdx, estimatedTokens, budget, outcome: pass|blow}
 * The gate always answers 200 with an outcome; the caller (01's gate) is
 * what turns a `blow` into an execute/escalate/reject decision. Every
 * outcome is written to the ledger as a BudgetEvent (always decisionId-keyed).
 *
 * GET /events — audit trail. GET /metrics — prometheus counters.
 */

export const GateRequestSchema = z.object({
  decisionId: z.string(),
  stepIdx: z.number().int().nonnegative(),
  estimatedTokens: z.number().nonnegative(),
  budget: z.number().nonnegative(),
});

export type GateRequest = z.infer<typeof GateRequestSchema>;
export type GateOutcome = 'pass' | 'blow';

export function evaluateBudget(req: GateRequest): GateOutcome {
  return req.estimatedTokens <= req.budget ? 'pass' : 'blow';
}

export function createBudgetGateServer(store: LedgerStore): Server {
  let passes = 0;
  let blows = 0;

  return jsonRouter([
    {
      method: 'POST',
      path: '/gate',
      handler: async (_req, res, _url, body) => {
        const req = GateRequestSchema.parse(body);
        const outcome = evaluateBudget(req);
        if (outcome === 'pass') passes++;
        else blows++;
        await store.insertBudgetEvent({ ...req, outcome });
        sendJson(res, 200, { ...req, outcome });
      },
    },
    {
      method: 'GET',
      path: '/events',
      handler: async (_req, res) =>
        sendJson(res, 200, { events: await store.listBudgetEvents() }),
    },
    {
      method: 'GET',
      path: '/metrics',
      handler: (_req, res) =>
        sendText(res, 200, [
          '# TYPE substrate_budget_gate_total counter',
          `substrate_budget_gate_total{outcome="pass"} ${passes}`,
          `substrate_budget_gate_total{outcome="blow"} ${blows}`,
          '',
        ].join('\n')),
    },
  ]);
}

export async function startBudgetGate(port = envPort(8103)): Promise<{ server: Server; port: number }> {
  const store = await import('./store.js').then((m) => m.createLedgerStore('memory'));
  const server = createBudgetGateServer(store);
  const bound = await listen(server, port);
  return { server, port: bound };
}

if (isMainModule(import.meta.url)) {
  startBudgetGate().then(
    ({ port }) => process.stdout.write(`budget-gate on :${port}\n`),
    (err) => {
      process.stderr.write(String(err) + '\n');
      process.exit(1);
    },
  );
}
