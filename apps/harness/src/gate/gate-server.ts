import type { Express } from 'express';
import express from 'express';
import type { DecisionRecord } from '@substrate/substrate';
import { DecisionRecordSchema } from '@substrate/substrate';
import type { Stores } from '../types';
import { ConfidenceProvider, GateCore, GateOptions, heuristicConfidenceProvider } from './gate-core';
import { ThresholdManager } from './thresholds';

function defaultProvider(): ConfidenceProvider {
  return heuristicConfidenceProvider();
}

export interface GateServerOptions {
  taskType?: string;
  provider?: ConfidenceProvider;
  gates?: Partial<GateOptions>;
  idGen?: (prefix: string) => string;
  now?: () => string;
}

export function createGateApp(stores: Stores, opts?: GateServerOptions): Express {
  const app = express();
  app.use(express.json());
  const idGen = opts?.idGen ?? ((p: string) => `${p}-${Math.random().toString(36).slice(2, 10)}`);
  const now = opts?.now ?? (() => new Date().toISOString());
  const tm = new ThresholdManager(stores);

  app.get('/healthz', (_req, res) => res.json({ ok: true }));

  app.get('/thresholds', async (_req, res) => {
    res.json({ thresholds: await tm.list() });
  });

  app.put('/thresholds/:taskType', async (req, res) => {
    const band = await tm.set(req.params.taskType, {
      executeThreshold: Number(req.body.executeThreshold),
      rejectThreshold: Number(req.body.rejectThreshold),
      note: req.body.note,
    });
    res.json({ threshold: band });
  });

  app.post('/gate/decide', async (req, res) => {
    const { turnId, action, confidenceFeatures } = req.body as {
      turnId: string;
      action: string;
      confidenceFeatures: Record<string, unknown>;
    };
    if (!action) return res.status(400).json({ error: 'action required' });
    const band = await tm.get(opts?.taskType ?? req.body.taskType ?? 'default');
    const gate = new GateCore(
      { executeThreshold: band.executeThreshold, rejectThreshold: band.rejectThreshold },
      opts?.provider ?? defaultProvider(),
      idGen,
    );
    const decision = await gate.decide(action, confidenceFeatures ?? {});
    const record: DecisionRecord = DecisionRecordSchema.parse({
      decisionId: decision.decisionId,
      turnId,
      action,
      confidenceFeatures: confidenceFeatures ?? {},
      verdict: decision.verdict,
      outcome: null,
      confirmedAt: null,
    });
    await stores.decisions.insert(record);
    res.json({
      decisionId: decision.decisionId,
      verdict: decision.verdict,
      confidence: decision.score,
      explain: decision.explain,
      at: now(),
    });
  });

  app.get('/decisions', async (_req, res) => {
    res.json({ decisions: await stores.decisions.list() });
  });

  return app;
}