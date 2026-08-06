import { createPool, migrate } from '../db';
import { createPostgresStores } from '../db/postgres';
import { startHarnessApi } from '../api/api';
import { ollamaClient } from '../llm/llm';

const port = Number(process.env.PORT ?? 8930);
const pool = createPool();
await migrate(pool);
const api = await startHarnessApi(port, {
  stores: createPostgresStores(pool),
  engineOpts: { llm: ollamaClient() },
});
console.log(`harness api on :${port} (ws :${port}/ws, sse :${port}/runs/:id/events/stream)`);
