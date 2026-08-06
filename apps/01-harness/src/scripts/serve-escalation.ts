import { createPool, migrate } from '../db';
import { createPostgresStores } from '../db/postgres';
import { createEscalationApp } from '../gate/escalation';

const port = Number(process.env.PORT ?? 8935);
const pool = createPool();
await migrate(pool);
const app = createEscalationApp(createPostgresStores(pool));
app.listen(port, () => console.log(`escalation surface on :${port}`));
