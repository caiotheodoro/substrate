import { createHash } from 'node:crypto';
import { canonicalJson } from '@substrate/substrate';
import { REGIONS, type PromptRegion } from '../lib/prompt-regions.js';


/**
 * A-E-10 prompt-fingerprinter — region hashes for cache analysis.
 *
 * Each prompt is split into six regions (C7 PromptRegionSchema): identity,
 * task, tools, schemas, few-shot, dynamic. A region hash is sha-256 over
 * canonicalJson (stable key ordering, no whitespace) of the region value,
 * so byte-identical regions produce byte-identical hashes and a change in
 * ONE region changes exactly that region's hash.
 */

export type PromptRegions = Partial<Record<PromptRegion, unknown>>;

export function regionFingerprint(region: PromptRegion, value: unknown): string {
  return createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex');
}

export function fingerprintRegions(regions: PromptRegions): Record<PromptRegion, string> {
  const out = {} as Record<PromptRegion, string>;
  for (const region of REGIONS) {
    if (regions[region] !== undefined) {
      out[region] = regionFingerprint(region, regions[region]);
    }
  }
  return out;
}

/** Whole-prompt fingerprint — the stable identity of a prompt across turns. */
export function fullFingerprint(regions: PromptRegions): string {
  return createHash('sha256').update(canonicalJson(regions), 'utf8').digest('hex');
}

/** Fingerprint of only the regions a cache plan declares stable. */
export function stableBlockFingerprint(
  regions: PromptRegions,
  stable: readonly PromptRegion[],
): string {
  const subset: PromptRegions = {};
  for (const region of stable) {
    if (regions[region] !== undefined) subset[region] = regions[region];
  }
  return createHash('sha256').update(canonicalJson(subset), 'utf8').digest('hex');
}

/** Regions that changed between two prompts (by fingerprint). */
export function changedRegions(
  before: PromptRegions,
  after: PromptRegions,
): PromptRegion[] {
  const changed: PromptRegion[] = [];
  for (const region of REGIONS) {
    const a = canonicalJson(before[region]);
    const b = canonicalJson(after[region]);
    if (a !== b) changed.push(region);
  }
  return changed;
}
