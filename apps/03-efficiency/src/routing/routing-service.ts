import type { Server } from 'node:http';
import { StepRecordSchema } from '@substrate/substrate';
import { jsonRouter, listen, sendJson, sendText, envPort } from '../lib/http.js';
import { isMainModule } from '../lib/paths.js';
import type { LedgerStore } from '../ledger/store.js';
import { completionToStep } from '../ledger/provider-adapter.js';
import { fullFingerprint } from '../cache/prompt-fingerprinter.js';
import { loadPriceCatalog } from '../tco/price-catalog.js';
import { priceRowOf } from '../tco/tco-model.js';
import {
  DEFAULT_THRESHOLDS,
  confidenceToTier,
  type TierThresholds,
} from './confidence-adapter.js';
import {
  DEFAULT_POLICY,
  routeFor,
  tierOfRoute,
  type RouteTuple,
  type RoutingPolicy,
  type Tier,
} from './routing-policy.js';

/**
 * A-E-15 routing-service (:8102) — OpenAI-compatible gateway that routes
 * each chat completion by policy and emits a C4 StepRecord per call.
 *
 * The gateway is plain node:http (no framework). Upstreams are OpenAI-
 * compatible HTTP endpoints: Ollama (:11434) and LiteLLM (:4000) are
 * compose services this gateway proxies-to-or-routes-between; the routing
 * policy decides which upstream a request goes to. `x_substrate_*`
 * headers carry 01/02 context: confidence (C5) and the decisionId join key.
 *
 * All StepRecords written to the ledger carry decisionId.
 */

export interface UpstreamResponse {
  status: number;
  json: unknown;
}

export interface UpstreamClient {
  postChatCompletion(body: unknown): Promise<UpstreamResponse>;
}

export class HttpUpstreamClient implements UpstreamClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async postChatCompletion(body: unknown): Promise<UpstreamResponse> {
    const res = await this.fetchImpl(`${this.baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    return { status: res.status, json: await res.json().catch(() => null) };
  }
}

export interface RoutingDeps {
  policy?: RoutingPolicy;
  thresholds?: TierThresholds;
  ledger: LedgerStore;
  upstreams: Record<string, UpstreamClient>;
  now?: () => string;
  qualitySignalOf?: (confidence: number | undefined) => number | null;
}

interface SubstrateContext {
  decisionId?: string;
  confidence?: number;
  band?: 'execute-band' | 'escalation-band' | 'reject-band';
}

function parseContext(body: unknown, headers: Record<string, string | string[] | undefined>): SubstrateContext {
  const obj = (body as { x_substrate?: SubstrateContext } | null)?.x_substrate ?? {};
  const headerConf = Number(headers['x-substrate-confidence'] ?? NaN);
  return {
    decisionId: obj.decisionId ?? (typeof headers['x-substrate-decision-id'] === 'string' ? headers['x-substrate-decision-id'] : undefined),
    confidence: obj.confidence ?? (Number.isNaN(headerConf) ? undefined : headerConf),
    band: obj.band,
  };
}

function usageOf(upstreamJson: unknown): Record<string, unknown> | null {
  const usage = (upstreamJson as { usage?: unknown } | null)?.usage;
  return usage !== null && typeof usage === 'object' ? (usage as Record<string, unknown>) : null;
}

export function createRoutingServer(deps: RoutingDeps): Server {
  const policy = deps.policy ?? DEFAULT_POLICY;
  const thresholds = deps.thresholds ?? DEFAULT_THRESHOLDS;
  const now = deps.now ?? (() => new Date().toISOString());
  const qualitySignalOf = deps.qualitySignalOf ?? ((c) => (c === undefined ? null : c));
  const requestsByTier = new Map<Tier, number>();
  const estCostByTier = new Map<Tier, number>();
  const latencyBuckets = [0.1, 0.3, 0.5, 1, 2, 5, 10, 30];
  const latencyCount = new Map<number, number>();
  let latencySum = 0;
  let total = 0;
  const catalog = loadPriceCatalog();

  return jsonRouter([
    {
      method: 'POST',
      path: '/v1/chat/completions',
      handler: async (req, res, _url, body) => {
        if (body === null || typeof body !== 'object') {
          sendJson(res, 400, { error: 'request body must be a JSON object' });
          return;
        }
        const ctx = parseContext(body, req.headers);
        const confidence = ctx.confidence ?? 0.5;
        const tier = confidenceToTier({ score: confidence, band: ctx.band ?? 'execute-band', explain: {}, modelVersion: 'substrate' }, thresholds);
        const route = routeFor(policy, confidence, ctx.band);
        requestsByTier.set(tier, (requestsByTier.get(tier) ?? 0) + 1);
        total++;

        const upstream = deps.upstreams[route.provider];
        if (upstream === undefined) {
          sendJson(res, 503, {
            error: `no upstream configured for provider "${route.provider}"`,
            tier,
            route,
          });
          return;
        }

        const started = performance.now();
        const upstreamBody = { ...(body as Record<string, unknown>) };
        delete (upstreamBody as Record<string, unknown>)['x_substrate'];
        upstreamBody['model'] = route.model;
        const upstreamRes = await upstream.postChatCompletion(upstreamBody);
        const latencyMs = performance.now() - started;
        latencySum += latencyMs;
        for (const bucket of latencyBuckets) {
          if (latencyMs / 1000 <= bucket) {
            latencyCount.set(bucket, (latencyCount.get(bucket) ?? 0) + 1);
          }
        }

        const usage = usageOf(upstreamRes.json);
        if (usage !== null) {
          const messages = (body as { messages?: unknown }).messages;
          const decisionId = ctx.decisionId ?? `routed-${total}-${now()}`;
          const step = completionToStep(
            { provider: route.provider === 'anthropic' ? 'anthropic' : 'litellm', usage: usage as never },
            {
              decisionId,
              stepIdx: 0,
              model: route.model,
              provider: route.provider,
              quantization: route.quantization,
              promptFingerprint: Array.isArray(messages) ? fullFingerprint({ dynamic: messages }) : null,
              qualitySignal: qualitySignalOf(ctx.confidence),
              ts: now(),
            },
            latencyMs,
          );
          StepRecordSchema.parse(step);
          await deps.ledger.insertStep(step);
          try {
            const row = priceRowOf(catalog, {
              provider: step.provider,
              model: step.model,
              quantization: step.quantization,
              cache: step.cacheEvent !== 'miss',
            });
            const perM = 1e6;
            const est = (step.inputTokens * row.inputPerMtok + step.cachedInputTokens * row.cachedInputPerMtok + step.outputTokens * row.outputPerMtok) / perM;
            estCostByTier.set(tier, (estCostByTier.get(tier) ?? 0) + est);
          } catch {
            // provider/model not in the local catalog → no cost estimate
          }
        }

        if (upstreamRes.status !== 200) {
          sendJson(res, upstreamRes.status, { error: 'upstream error', upstream: upstreamRes.json, tier });
          return;
        }
        sendJson(res, 200, upstreamRes.json);
      },
    },
    {
      method: 'GET',
      path: '/v1/models',
      handler: (_req, res) =>
        sendJson(res, 200, {
          object: 'list',
          data: policy.tiers.map((t) => ({ id: t.route.model, object: 'model', owned_by: t.route.provider })),
        }),
    },
    {
      method: 'GET',
      path: '/health',
      handler: (_req, res) => sendJson(res, 200, { ok: true }),
    },
    {
      method: 'GET',
      path: '/metrics',
      handler: (_req, res) =>
        sendText(res, 200, [
          '# TYPE substrate_routing_requests_total counter',
          ...[...requestsByTier.entries()].map(
            ([tier, count]) => `substrate_routing_requests_total{tier="${tier}"} ${count}`,
          ),
          `substrate_routing_requests_total{tier="total"} ${total}`,
          '# TYPE substrate_routing_est_cost_usd_total counter',
          ...[...estCostByTier.entries()].map(
            ([tier, usd]) => `substrate_routing_est_cost_usd_total{tier="${tier}"} ${usd.toFixed(6)}`,
          ),
          '# TYPE substrate_routing_latency_seconds histogram',
          ...[...latencyBuckets].map(
            (bucket) => `substrate_routing_latency_seconds_bucket{le="${bucket}"} ${latencyCount.get(bucket) ?? 0}`,
          ),
          `substrate_routing_latency_seconds_sum ${latencySum / 1000}`,
          `substrate_routing_latency_seconds_count ${total}`,
          '',
        ].join('\n')),
    },
  ]);
}

export function routeForProvider(policy: RoutingPolicy, provider: string): RouteTuple | null {
  for (const tier of policy.tiers) {
    if (tier.route.provider === provider) return tier.route;
  }
  return null;
}

export async function startRoutingService(port = envPort(8102)): Promise<{
  server: Server;
  port: number;
  upstreams: Record<string, UpstreamClient>;
}> {
  const { createLedgerStore } = await import('../ledger/store.js');
  const ledger = await createLedgerStore('memory');
  const upstreams: Record<string, UpstreamClient> = {
    ollama: new HttpUpstreamClient(process.env.SUBSTRATE_OLLAMA_URL ?? 'http://localhost:11434'),
    litellm: new HttpUpstreamClient(process.env.SUBSTRATE_LITELLM_URL ?? 'http://localhost:4000'),
  };
  const server = createRoutingServer({ ledger, upstreams });
  const bound = await listen(server, port);
  return { server, port: bound, upstreams };
}

if (isMainModule(import.meta.url)) {
  startRoutingService().then(
    ({ port }) => process.stdout.write(`routing on :${port}\n`),
    (err) => {
      process.stderr.write(String(err) + '\n');
      process.exit(1);
    },
  );
}

export { tierOfRoute };
