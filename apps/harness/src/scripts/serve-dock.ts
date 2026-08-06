import { createPool, migrate } from '../db';
import { createPostgresStores } from '../db/postgres';
import { createDockServer } from '../hitl/hitl-dock';

const port = Number(process.env.PORT ?? 8938);
const pool = createPool();
await migrate(pool);
const { server } = createDockServer(createPostgresStores(pool), port);
console.log(`hitl dock on :${port}`);
server.on('close', () => void pool.end());
