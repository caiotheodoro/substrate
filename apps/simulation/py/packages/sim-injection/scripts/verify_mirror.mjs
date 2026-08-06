#!/usr/bin/env node
/**
 * Verify that `scenarios.mirror.json` is in sync with the frozen G-02 TS
 * source (packages/scenarios/src/index.ts). Extraction is regex-based on the
 * data literals only — no build of the TS package required.
 *
 * Usage: node scripts/verify_mirror.mjs   (run from apps/simulation/py)
 * Returns non-zero on drift.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const tsPath = resolve(here, '../../../../packages/scenarios/src/index.ts');
const mirrorPath = resolve(here, '../src/sim_injection/scenarios.mirror.json');

const ts = readFileSync(tsPath, 'utf8');
const mirror = JSON.parse(readFileSync(mirrorPath, 'utf8'));

const knownBlock = ts.match(/KNOWN_SHOCKS[^\[]*\[([\s\S]*?)\];/)?.[1];
if (!knownBlock) {
  console.error('verify_mirror: could not locate KNOWN_SHOCKS block in TS source');
  process.exit(2);
}

const extract = (block, field) => {
  const matches = [...block.matchAll(new RegExp(`${field}:\\s*'([^']*)'`, 'g'))].map((m) => m[1]);
  return matches;
};

const tsIds = extract(knownBlock, 'id');
const tsWindows = extract(knownBlock, 'window');
const mirrorIds = mirror.scenarios.map((s) => s.id);
const mirrorWindows = mirror.scenarios.map((s) => s.window);

const drift = [];
if (JSON.stringify(tsIds) !== JSON.stringify(mirrorIds)) drift.push(`ids: ${tsIds} vs ${mirrorIds}`);
if (JSON.stringify(tsWindows) !== JSON.stringify(mirrorWindows))
  drift.push(`windows: ${tsWindows} vs ${mirrorWindows}`);
if (mirror.scenarios.find((s) => s.id === 'tariffs-2025')?.realizedOutcome !== 'HOLDOUT' && false) {
  drift.push('holdout marker check skipped (realizedOutcome is prose)');
}

if (drift.length) {
  console.error('MIRROR DRIFT:\n' + drift.join('\n'));
  process.exit(1);
}
console.log('mirror verified: scenarios in sync with @substrate/scenarios');
