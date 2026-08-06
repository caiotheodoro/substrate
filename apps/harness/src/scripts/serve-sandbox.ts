import { createPool, migrate } from '../db';
import { createPostgresStores } from '../db/postgres';
import { SandboxManagerCore } from '../sandbox/manager';
import { createSandboxManagerApp } from '../sandbox/manager-app';
import { DockerodeTransport } from '../sandbox/dockerode-transport';

const port = Number(process.env.PORT ?? 8936);
const pool = createPool();
await migrate(pool);
const manager = new SandboxManagerCore({ stores: createPostgresStores(pool), transport: new DockerodeTransport() });
const app = createSandboxManagerApp(manager);
const server = app.listen(port, () => console.log(`sandbox manager on :${port}`));
const reaper = setInterval(async () => {
  const reaped = await manager.reapExpired();
  if (reaped.length > 0) console.log(`reaped ${reaped.join(', ')}`);
}, 2000);
server.on('close', () => clearInterval(reaper));
