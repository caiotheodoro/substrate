import type { ConfidenceProvider, GateScore } from './gate-core';
import { heuristicConfidenceProvider } from './gate-core';
import { ConfidenceResponseSchema } from '@substrate/substrate';

/**
 * Joint 1 (C5): 01's gate consumes 02's Trust scorer as a drop-in
 * confidence provider — `POST :8020/confidence` → {score, band, explain,
 * modelVersion}. The heuristic provider is the offline fallback: when the
 * Trust service is unreachable (tests, local dev without `make up
 * profile=trust`), scoring degrades gracefully instead of failing the run.
 */
export const TRUST_SCORER_URL = process.env.SUBSTRATE_TRUST_URL ?? 'http://localhost:8020';

export interface RemoteConfidenceOptions {
  baseUrl?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  fallback?: ConfidenceProvider;
}

export function remoteConfidenceProvider(opts: RemoteConfidenceOptions = {}): ConfidenceProvider {
  const baseUrl = opts.baseUrl ?? TRUST_SCORER_URL;
  const timeoutMs = opts.timeoutMs ?? 2000;
  const fetchImpl = opts.fetchImpl ?? fetch;
  const fallback = opts.fallback ?? heuristicConfidenceProvider();

  return {
    async score(features) {
      const decisionId = String(features.decisionId ?? `g-${Math.random().toString(36).slice(2, 10)}`);
      const res = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/confidence`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ decisionId, confidenceFeatures: features }),
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) {
        throw new Error(`trust scorer error ${res.status}: ${await res.text()}`);
      }
      const body = ConfidenceResponseSchema.parse(await res.json());
      return { score: body.score, explain: body.explain, modelVersion: body.modelVersion } satisfies GateScore;
    },
  };
}

export interface ResilientGateOptions extends RemoteConfidenceOptions {
  /** When false (default), a remote failure falls back to the heuristic provider. */
  requireRemote?: boolean;
}

export function resilientConfidenceProvider(opts: ResilientGateOptions = {}): ConfidenceProvider {
  const remote = remoteConfidenceProvider(opts);
  const fallback = opts.fallback ?? heuristicConfidenceProvider();
  let disabled = false;
  return {
    async score(features) {
      if (opts.requireRemote) {
        return remote.score(features);
      }
      if (disabled) {
        return fallback.score(features);
      }
      try {
        return await remote.score(features);
      } catch (err) {
        disabled = true;
        const fb = await fallback.score(features);
        return { ...fb, explain: { ...fb.explain, remoteFallback: String((err as Error).message) } };
      }
    },
  };
}
