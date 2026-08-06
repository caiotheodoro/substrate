import { Pool } from 'pg';

export const DEFAULT_DATABASE_URL = 'postgres://substrate:substrate@localhost:5432/harness';

export function createPool(url = process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL): Pool {
  return new Pool({ connectionString: url });
}

export async function migrate(pool: Pool, url = (pool as unknown as { options?: { connectionString?: string } }).options?.connectionString ?? process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL): Promise<void> {
  const { runner } = await import('node-pg-migrate');
  await runner({
    databaseUrl: url,
    dir: new URL('../../migrations', import.meta.url).pathname,
    migrationsTable: 'pgmigrations',
    direction: 'up',
    count: Infinity,
    logger: {
      info: () => undefined,
      warn: () => undefined,
      error: () => undefined,
    },
  });
}
