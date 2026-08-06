import type { Express } from 'express';
import express from 'express';
import type { SandboxManagerCore } from './manager';
import type { Stores } from '../types';

export function createSandboxManagerApp(manager: SandboxManagerCore, stores?: Stores): Express {
  const app = express();
  app.use(express.json());

  app.get('/healthz', (_req, res) => res.json({ ok: true }));

  app.post('/sandboxes', async (req, res) => {
    const { image, leaseMs, name } = req.body as { image: string; leaseMs?: number; name?: string };
    try {
      const lease = await manager.acquire({ image, leaseMs, name });
      res.status(201).json({ lease });
    } catch (e) {
      res.status(500).json({ error: (e as Error).message });
    }
  });

  app.post('/sandboxes/:id/keepalive', async (req, res) => {
    const lease = await manager.keepalive(req.params.id);
    if (!lease) return res.status(404).json({ error: 'no lease' });
    res.json({ lease });
  });

  app.get('/sandboxes/:id/liveness', async (req, res) => {
    res.json(await manager.liveness(req.params.id));
  });

  app.post('/sandboxes/:id/exec', async (req, res) => {
    const { cmd, opts } = req.body as { cmd?: string[]; opts?: { timeoutMs?: number; maxOutputBytes?: number } };
    if (!cmd || !Array.isArray(cmd)) return res.status(400).json({ error: 'cmd array required' });
    try {
      const result = await manager.exec(req.params.id, cmd, opts);
      res.json({ result });
    } catch (e) {
      res.status(503).json({ error: (e as Error).message });
    }
  });

  app.post('/sandboxes/:id/artifacts', async (req, res) => {
    const { path, data } = req.body as { path?: string; data?: string };
    if (!path) return res.status(400).json({ error: 'path required' });
    await manager.putArtifact(req.params.id, path, Buffer.from(data ?? '', 'base64'));
    res.status(201).json({ uploaded: true, path });
  });

  app.get('/sandboxes/:id/artifacts', async (req, res) => {
    const { path } = req.query as { path?: string };
    if (!path) return res.status(400).json({ error: 'path query required' });
    const data = await manager.getArtifact(req.params.id, path);
    res.json({ path, data: data.toString('base64') });
  });

  app.delete('/sandboxes/:id', async (req, res) => {
    await manager.release(req.params.id);
    res.json({ released: true });
  });

  app.get('/sandboxes', async (_req, res) => {
    res.json({ leases: stores ? await stores.sandboxLeases.list() : [] });
  });

  return app;
}