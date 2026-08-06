import type { Server } from 'node:http';
import type { CacheEventRecord } from '../ledger/schema.js';
import { jsonRouter, listen, sendJson, sendText, envPort } from '../lib/http.js';
import { isMainModule } from '../lib/paths.js';

/**
 * A-E-11 cache-analytics — hit-rate by region + reuse-vs-stagnation.
 *
 * `analyze` answers two questions from CacheEventRecords:
 *  1. hit-rate by region: which prompt regions actually benefit from the
 *     cache, measured per region hash bucket;
 *  2. is a hit *reuse-by-design* (the stable block was reused while the
 *     dynamic region moved on) or *stagnation* (the entire prompt —
 *     dynamic region included — is frozen across steps)? Chasing raw hit
 *     rate can freeze prompts that should evolve; this classifier is the
 *     guard against cache myopia.
 *
 * Service (:8101): POST /observe feeds events, POST /analyze returns the
 * report, GET /metrics prometheus counters.
 */

export type ReuseClass = 'reuse-by-design' | 'stagnation' | 'miss' | 'write';

export interface RegionHitStats {
  total: number;
  hits: number;
  rate: number;
}

export interface CacheAnalysis {
  byRegion: Record<string, RegionHitStats>;
  classification: Record<ReuseClass, number>;
  total: number;
  hitRate: number;
  stagnationShare: number;
}

export function analyzeCacheEvents(events: CacheEventRecord[]): CacheAnalysis {
  const byRegion: Record<string, RegionHitStats> = {};
  const lastSeen = new Map<string, string>();
  const classification: Record<ReuseClass, number> = {
    'reuse-by-design': 0,
    stagnation: 0,
    miss: 0,
    write: 0,
  };

  for (const event of events) {
    const stableKey = stableKeyOf(event.regionHashes);
    if (stableKey !== null) {
      const stats = (byRegion[stableKey] ??= { total: 0, hits: 0, rate: 0 });
      stats.total++;
      if (event.cacheEvent === 'hit') stats.hits++;
      stats.rate = stats.hits / stats.total;
    }

    const full = fullHashOf(event.regionHashes);
    if (event.cacheEvent === 'hit') {
      const previousFull = lastSeen.get(stableKey ?? '__none__');
      if (stableKey !== null && previousFull !== undefined && previousFull === full) {
        classification.stagnation++;
      } else {
        classification['reuse-by-design']++;
      }
    } else if (event.cacheEvent === 'write') {
      classification.write++;
    } else {
      classification.miss++;
    }
    if (stableKey !== null) lastSeen.set(stableKey, full);
  }

  const total = events.length;
  const hits = classification['reuse-by-design'] + classification.stagnation;
  return {
    byRegion,
    classification,
    total,
    hitRate: total === 0 ? 0 : hits / total,
    stagnationShare: hits === 0 ? 0 : classification.stagnation / hits,
  };
}

/** Stable regions = everything except the dynamic region (C7 semantics). */
const STABLE_REGIONS = ['identity', 'task', 'tools', 'schemas', 'few-shot'] as const;

function stableKeyOf(regionHashes: Record<string, string>): string | null {
  const parts: string[] = [];
  for (const region of STABLE_REGIONS) {
    const h = regionHashes[region];
    if (h !== undefined) parts.push(`${region}:${h}`);
  }
  return parts.length === 0 ? null : parts.join('|');
}

function fullHashOf(regionHashes: Record<string, string>): string {
  return Object.keys(regionHashes)
    .sort()
    .map((k) => `${k}:${regionHashes[k]}`)
    .join('|');
}

export function createCacheAnalyticsServer(store: {
  listCacheEvents(): Promise<CacheEventRecord[]>;
  insertCacheEvent(event: CacheEventRecord): Promise<unknown>;
}) {
  let observed = 0;
  return jsonRouter([
    {
      method: 'POST',
      path: '/observe',
      handler: async (_req, res, _url, body) => {
        const event = body as CacheEventRecord;
        await store.insertCacheEvent(event);
        observed++;
        sendJson(res, 200, { result: 'inserted' });
      },
    },
    {
      method: 'POST',
      path: '/analyze',
      handler: async (_req, res) => {
        const events = await store.listCacheEvents();
        sendJson(res, 200, analyzeCacheEvents(events));
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
      handler: async (_req, res) => {
        const events = await store.listCacheEvents();
        const byRegion: Record<string, { hits: number; misses: number }> = {};
        for (const event of events) {
          for (const [region, hash] of Object.entries(event.regionHashes)) {
            const stats = (byRegion[`${region}:${hash.slice(0, 8)}`] ??= { hits: 0, misses: 0 });
            if (event.cacheEvent === 'hit') stats.hits++;
            else if (event.cacheEvent === 'miss') stats.misses++;
          }
        }
        const lines = [
          '# TYPE substrate_cache_events_observed_total counter',
          `substrate_cache_events_observed_total ${observed}`,
          '# TYPE substrate_cache_region_hit_total counter',
        ];
        for (const [region, stats] of Object.entries(byRegion)) {
          lines.push(`substrate_cache_region_hit_total{region="${region}",state="hit"} ${stats.hits}`);
          lines.push(`substrate_cache_region_hit_total{region="${region}",state="miss"} ${stats.misses}`);
        }
        lines.push('');
        sendText(res, 200, lines.join('\n'));
      },
    },
  ]);
}

export async function startCacheAnalytics(port = envPort(8101)): Promise<{
  server: Server;
  port: number;
}> {
  const { createLedgerStore } = await import('../ledger/store.js');
  const store = await createLedgerStore('memory');
  const server = createCacheAnalyticsServer(store);
  const bound = await listen(server, port);
  return { server, port: bound };
}

if (isMainModule(import.meta.url)) {
  startCacheAnalytics().then(
    ({ port }) => process.stdout.write(`cache-analytics on :${port}\n`),
    (err) => {
      process.stderr.write(String(err) + '\n');
      process.exit(1);
    },
  );
}
