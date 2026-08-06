import type { Server } from 'node:http';
import { BudgetEventSchema, CacheEventSchema, StepRecordSchema } from '@substrate/substrate';
import { jsonRouter, listen, sendJson, sendText, envPort } from '../lib/http.js';
import { isMainModule } from '../lib/paths.js';
import { CacheEventRecordSchema } from './schema.js';
import { createLedgerStore, type LedgerStore } from './store.js';

/**
 * A-E-02 ledger-api (:8100) — C4 ingest surface.
 *
 * POST /steps          ingest a StepRecord (idempotent; unique (decision_id, step_idx))
 * GET  /steps?decisionId=  replay a decision's step trail
 * POST /budget-events  record a budget gate outcome
 * POST /cache-events   record a cache event with region fingerprints
 * GET  /health         liveness
 * GET  /metrics        prometheus counters
 */
export function createLedgerServer(store: LedgerStore): Server {
  let inserted = 0;
  let conflicts = 0;
  let duplicates = 0;

  return jsonRouter([
    {
      method: 'POST',
      path: '/steps',
      handler: async (_req, res, _url, body) => {
        const step = StepRecordSchema.parse(body);
        const result = await store.insertStep(step);
        if (result === 'inserted') inserted++;
        else if (result === 'conflict') conflicts++;
        else duplicates++;
        const status = result === 'conflict' ? 409 : 200;
        sendJson(res, status, {
          decisionId: step.decisionId,
          stepIdx: step.stepIdx,
          result,
        });
      },
    },
    {
      method: 'GET',
      path: '/steps',
      handler: async (_req, res, url) => {
        const decisionId = url.searchParams.get('decisionId');
        const steps = decisionId === null
          ? await store.listSteps()
          : await store.getStepsByDecision(decisionId);
        sendJson(res, 200, { decisionId, steps });
      },
    },
    {
      method: 'POST',
      path: '/budget-events',
      handler: async (_req, res, _url, body) => {
        const event = BudgetEventSchema.parse(body);
        const result = await store.insertBudgetEvent(event);
        sendJson(res, result === 'conflict' ? 409 : 200, { result });
      },
    },
    {
      method: 'POST',
      path: '/cache-events',
      handler: async (_req, res, _url, body) => {
        const event = CacheEventRecordSchema.parse(body);
        const result = await store.insertCacheEvent(event);
        sendJson(res, result === 'conflict' ? 409 : 200, { result });
      },
    },
    {
      method: 'GET',
      path: '/health',
      handler: (_req, res) => sendJson(res, 200, { ok: true }),
    },
    {
      method: 'GET',
      path: '/metrics',
      handler: async (_req, res) =>
        sendText(res, 200, [
          '# TYPE substrate_ledger_steps_total counter',
          `substrate_ledger_steps_total{state="inserted"} ${inserted}`,
          `substrate_ledger_steps_total{state="duplicate"} ${duplicates}`,
          `substrate_ledger_steps_total{state="conflict"} ${conflicts}`,
          `substrate_ledger_budget_events_total ${(await store.listBudgetEvents()).length}`,
          `substrate_ledger_cache_events_total ${(await store.listCacheEvents()).length}`,
          '',
        ].join('\n')),
    },
  ]);
}

export async function startLedgerApi(port = envPort(8100)): Promise<{ server: Server; port: number }> {
  const store = await createLedgerStore();
  const server = createLedgerServer(store);
  const bound = await listen(server, port);
  return { server, port: bound };
}

if (isMainModule(import.meta.url)) {
  startLedgerApi().then(
    ({ port }) => process.stdout.write(`ledger-api on :${port}\n`),
    (err) => {
      process.stderr.write(String(err) + '\n');
      process.exit(1);
    },
  );
}

export { CacheEventSchema, StepRecordSchema };
