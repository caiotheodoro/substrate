import { createPool, migrate } from '../db';
import { createPostgresStores } from '../db/postgres';
import { createGateApp } from '../gate/gate-server';

const port = Number(process.env.PORT ?? 8934);
const pool = createPool();
await migrate(pool);
const app = createGateApp(createPostgresStores(pool));
app.listen(port, () => console.log(`gate server on :${port}`));
