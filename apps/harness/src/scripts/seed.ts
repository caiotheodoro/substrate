import { writeFileSync } from 'node:fs';
import { KNOWN_SHOCKS, SHOCK_INTERVENTIONS } from '@substrate/scenarios';
import { createPool, migrate } from '../db';
import { createPostgresStores } from '../db/postgres';
import { goldenCorpusIndex } from '../cli/cli';

const pool = createPool();
try {
  await migrate(pool);
  const stores = createPostgresStores(pool);
  await stores.thresholds.set('default', { executeThreshold: 0.7, rejectThreshold: 0.3, note: 'seed default' });
  await stores.thresholds.set('approvals', { executeThreshold: 0.8, rejectThreshold: 0.4, note: 'seed approvals' });
  await stores.thresholds.set('codegen', { executeThreshold: 0.75, rejectThreshold: 0.35, note: 'seed codegen' });
  const manifest = {
    scenarios: KNOWN_SHOCKS.map((s) => ({ id: s.id, window: s.window, version: s.version })),
    interventions: SHOCK_INTERVENTIONS.map((i) => i.id),
    goldens: goldenCorpusIndex(),
  };
  writeFileSync(new URL('../../golden-corpus/manifest.json', import.meta.url), JSON.stringify(manifest, null, 2) + '\n', 'utf8');
  console.log(`seeded thresholds + scenario manifest (${manifest.scenarios.length} shocks, ${manifest.interventions.length} interventions)`);
} finally {
  await pool.end();
}
