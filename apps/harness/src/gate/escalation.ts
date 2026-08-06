import type { Express } from 'express';
import express from 'express';
import type { Stores } from '../types';

export interface EscalationServerOptions {
  idGen?: (prefix: string) => string;
  now?: () => string;
}

export function createEscalationApp(stores: Stores, opts?: EscalationServerOptions): Express {
  const app = express();
  app.use(express.json());
  const idGen = opts?.idGen ?? ((p: string) => `${p}-${Math.random().toString(36).slice(2, 10)}`);
  const now = opts?.now ?? (() => new Date().toISOString());
  const subscribers = new Set<(line: string) => void>();

  app.get('/healthz', (_req, res) => res.json({ ok: true }));

  app.get('/escalations', async (_req, res) => {
    const list = await stores.escalations.list();
    res.json({ escalations: list });
  });

  app.get('/escalations/:id', async (req, res) => {
    const e = await stores.escalations.get(req.params.id);
    if (!e) return res.status(404).json({ error: 'not found' });
    res.json({ escalation: e });
  });

  app.post('/escalations', async (req, res) => {
    const { runId, decisionId, proposal, confidence, explain } = req.body as {
      runId: string | null;
      decisionId: string;
      proposal: { action: string; turnId: string; confidenceFeatures: Record<string, unknown>; context?: string };
      confidence: number;
      explain: Record<string, unknown>;
    };
    const escalation = {
      id: idGen('esc'),
      runId: runId ?? null,
      decisionId,
      proposal,
      confidence,
      explain: explain ?? {},
      verdict: 'pending' as const,
      createdAt: now(),
      resolvedAt: null,
      decidedBy: null,
    };
    await stores.escalations.insert(escalation);
    broadcast(subscribers, JSON.stringify({ type: 'escalation.created', escalation }));
    res.status(201).json({ escalation });
  });

  app.post('/escalations/:id/approve', async (req, res) => {
    const e = await stores.escalations.get(req.params.id);
    if (!e) return res.status(404).json({ error: 'not found' });
    await stores.escalations.decide(e.id, 'approved', req.body?.by ?? 'reviewer');
    broadcast(subscribers, JSON.stringify({ type: 'escalation.decided', id: e.id, verdict: 'approved' }));
    res.json({ escalation: await stores.escalations.get(e.id) });
  });

  app.post('/escalations/:id/reject', async (req, res) => {
    const e = await stores.escalations.get(req.params.id);
    if (!e) return res.status(404).json({ error: 'not found' });
    await stores.escalations.decide(e.id, 'rejected', req.body?.by ?? 'reviewer');
    broadcast(subscribers, JSON.stringify({ type: 'escalation.decided', id: e.id, verdict: 'rejected' }));
    res.json({ escalation: await stores.escalations.get(e.id) });
  });

  app.post('/escalations/:id/veto', async (req, res) => {
    const e = await stores.escalations.get(req.params.id);
    if (!e) return res.status(404).json({ error: 'not found' });
    await stores.escalations.decide(e.id, 'vetoed', req.body?.by ?? 'reviewer');
    broadcast(subscribers, JSON.stringify({ type: 'escalation.decided', id: e.id, verdict: 'vetoed' }));
    res.json({ escalation: await stores.escalations.get(e.id) });
  });

  app.get('/escalations/stream', (req, res) => {
    res.setHeader('content-type', 'text/event-stream');
    res.setHeader('cache-control', 'no-cache');
    res.setHeader('connection', 'keep-alive');
    res.flushHeaders();
    const send = (line: string) => res.write(`data: ${line}\n\n`);
    subscribers.add(send);
    req.on('close', () => subscribers.delete(send));
  });

  return app;
}

function broadcast(subscribers: Set<(line: string) => void>, line: string) {
  for (const fn of subscribers) fn(line);
}
