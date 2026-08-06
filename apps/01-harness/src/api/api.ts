import type { Express } from 'express';
import express from 'express';
import cors from 'cors';
import { WebSocketServer, WebSocket } from 'ws';
import type { Server } from 'node:http';
import { createMemoryStores } from '../db/memory';
import type { Stores } from '../types';
import { RunEngine, RunEngineOptions } from '../engine/engine';
import { GateCore, heuristicConfidenceProvider, DEFAULT_GATE_OPTIONS } from '../gate/gate-core';
import { MockToolRegistry } from '../mock-tools/tools';
import type { LLMProvider } from '../llm/llm';

export interface HarnessApiOptions {
  stores?: Stores;
  engineOpts?: Partial<Omit<RunEngineOptions, 'stores'>>;
}

export interface HarnessApi {
  app: Express;
  server: Server;
  ws: WebSocketServer;
  stores: Stores;
  run(task: string, maxTurns?: number): Promise<RunEngine>;
  close(): Promise<void>;
}

export interface HarnessApiRaw {
  app: Express;
  stores: Stores;
  engines: Map<string, RunEngine>;
}

export function createHarnessApiRaw(opts?: HarnessApiOptions): HarnessApiRaw {
  const stores = opts?.stores ?? createMemoryStores();
  const engines = new Map<string, RunEngine>();
  const app: Express = express();
  app.use(cors());
  app.use(express.json());

  app.get('/healthz', (_req, res) => res.json({ ok: true }));

  app.post('/runs', async (req, res) => {
    const { task, maxTurns } = req.body as { task?: string; maxTurns?: number };
    if (!task) return res.status(400).json({ error: 'task required' });
    const engine = await newEngine(stores, { ...opts?.engineOpts, maxTurns: maxTurns ?? opts?.engineOpts?.maxTurns }, task);
    engines.set(engine.id, engine);
    res.status(201).json({ runId: engine.id });
    void engine.run(engine.maxTurnsLimit());
  });

  app.get('/runs', async (_req, res) => {
    res.json({ runs: await stores.runs.list() });
  });

  app.get('/runs/:id', async (req, res) => {
    const run = await stores.runs.get(req.params.id);
    if (!run) return res.status(404).json({ error: 'not found' });
    res.json({ run });
  });

  app.get('/runs/:id/events', async (req, res) => {
    const events = await stores.events.list(req.params.id);
    const since = Number(req.query.since ?? -1);
    res.json({ events: events.filter((e) => e.seq > since) });
  });

  app.get('/runs/:id/events/stream', async (req, res) => {
    res.setHeader('content-type', 'text/event-stream');
    res.setHeader('cache-control', 'no-cache');
    res.setHeader('connection', 'keep-alive');
    res.flushHeaders();
    const send = (e: { seq: number }) => res.write(`id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`);
    const unsubscribe = stores.emit.on((e) => {
      if (e.runId === req.params.id) send(e);
    });
    const since = Number(req.headers['last-event-id'] ?? -1);
    const initial = (await stores.events.list(req.params.id)).filter((e) => e.seq > since);
    for (const e of initial) send(e);
    req.on('close', unsubscribe);
  });

  return { app, stores, engines };
}

export async function newEngine(
  stores: Stores,
  engineOpts: Partial<Omit<RunEngineOptions, 'stores'>> = {},
  task = 'inspect and report',
): Promise<RunEngine> {
  const gates = engineOpts.gate as unknown as { executeThreshold?: number; rejectThreshold?: number };
  const gate = new GateCore(
    {
      executeThreshold: gates?.executeThreshold ?? DEFAULT_GATE_OPTIONS.executeThreshold,
      rejectThreshold: gates?.rejectThreshold ?? DEFAULT_GATE_OPTIONS.rejectThreshold,
    },
    heuristicConfidenceProvider(),
    engineOpts.clock?.nextId,
  );
  const engine = await RunEngine.start(
    {
      ...engineOpts,
      stores,
      tools: engineOpts.tools ?? new MockToolRegistry(),
      gate,
      llm: engineOpts.llm ?? noopLLM(),
      clock: engineOpts.clock,
    } as RunEngineOptions,
    task,
  );
  return engine;
}

export async function startHarnessApi(port = 8930, opts?: HarnessApiOptions): Promise<HarnessApi> {
  const raw = createHarnessApiRaw(opts);
  const server = raw.app.listen(port);
  const ws = new WebSocketServer({ server, path: '/ws' });
  ws.on('connection', (socket) => {
    const unsubscribe = raw.stores.emit.on((e) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'event', runId: e.runId, seq: e.seq, event: e }));
      }
    });
    const send = (obj: unknown) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(String(obj));
    };
    socket.on('message', async (data) => {
      const msg = JSON.parse(String(data)) as { type: string; actionId?: string; answer?: Record<string, unknown> };
      if (msg.type === 'action.resolve' && msg.actionId && msg.answer) {
        await raw.stores.pendingActions.resolve(msg.actionId, msg.answer, 'ws');
        send({ type: 'action.resolved', actionId: msg.actionId });
      }
    });
    socket.on('close', () => unsubscribe());
  });

const api: HarnessApi = {
    app: raw.app,
    server,
    ws,
    stores: raw.stores,
    run: async (task: string, maxTurns?: number) => {
      const engine = await newEngine(raw.stores, { ...opts?.engineOpts, maxTurns: maxTurns ?? opts?.engineOpts?.maxTurns }, task);
      raw.engines.set(engine.id, engine);
      void engine.run(engine.maxTurnsLimit());
      return engine;
    },
    close: async () => {
      ws.close();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
  return api;
}

export function noopLLM(): LLMProvider {
  return {
    complete: async () => ({ content: 'I have reviewed this request and have nothing further to execute.', toolCalls: [] }),
  };
}

