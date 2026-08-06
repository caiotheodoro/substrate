
import type { PromptRegion } from '../lib/prompt-regions.js';
import { stableBlockFingerprint, type PromptRegions } from './prompt-fingerprinter.js';

/**
 * A-E-12 cache-simulator — would-be hit rate under a stable-block plan.
 *
 * Given a plan (which regions are declared cache-stable) and the actual
 * sequence of prompts, simulate the cache: a step hits iff its stable-block
 * fingerprint was written by an earlier step (with optional LRU capacity).
 * This is the answer to "what WOULD the hit rate be if we structured
 * prompts for reuse" — distinct from the observed hit rate of whatever
 * caching the provider happened to do.
 */

export interface CachePlan {
  stableRegions: readonly PromptRegion[];
  /** LRU capacity in stable blocks; Infinity = never evict. */
  capacity?: number;
}

export interface SimulatedStep {
  hit: boolean;
  stableKey: string;
  position: number;
}

export interface SimulationResult {
  hitRate: number;
  hits: number;
  total: number;
  steps: SimulatedStep[];
}

export function simulateCache(
  promptSequence: readonly PromptRegions[],
  plan: CachePlan,
): SimulationResult {
  const cache = new Set<string>();
  const order: string[] = [];
  const capacity = plan.capacity ?? Infinity;
  const steps: SimulatedStep[] = [];

  for (let i = 0; i < promptSequence.length; i++) {
    const regions = promptSequence[i]!;
    const key = stableBlockFingerprint(regions, plan.stableRegions);
    const hit = cache.has(key);
    if (hit) {
      order.splice(order.indexOf(key), 1);
      order.push(key);
    } else {
      cache.add(key);
      order.push(key);
      if (order.length > capacity) {
        const evicted = order.shift()!;
        cache.delete(evicted);
      }
    }
    steps.push({ hit, stableKey: key, position: i });
  }

  const hits = steps.filter((s) => s.hit).length;
  return {
    hitRate: steps.length === 0 ? 0 : hits / steps.length,
    hits,
    total: steps.length,
    steps,
  };
}

/** Would-be hit rate if only the first N regions were cache-stable. */
export function hitRateAtStabilityDepth(
  promptSequence: readonly PromptRegions[],
  stableDepth: number,
): number {
  const stable = stableDepth >= 5 ? ['identity','task','tools','schemas','few-shot'] : ['identity','task','tools','schemas','few-shot'].slice(0, stableDepth);
  return simulateCache(promptSequence, { stableRegions: stable as PromptRegion[] }).hitRate;
}
