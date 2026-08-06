import { describe, expect, it } from 'vitest';
import { spawn } from 'node:child_process';
import { remoteConfidenceProvider } from '../gate/remote-confidence';
import { GateCore } from '../gate/gate-core';
import type { Server } from 'node:http';

/**
 * Joint 1 cross-language e2e: the REAL Trust scorer (FastAPI, apps/trust/py)
 * serves C5 on :8020; 01's remoteConfidenceProvider consumes it and the gate
 * verdicts follow. Skips when the Python env is not present (CI ts job).
 */
const PORT = 18025;

async function spawnTrustScorer(): Promise<{ proc: ReturnType<typeof spawn>; ready: () => Promise<void> }> {
  const { createServer } = await import('node:http');
  const python = spawn(
    '/Users/caiotheodoro/Documents/personal/research/apps/trust/py/.venv/bin/python',
    ['-c', `
import threading, time, uvicorn
from trust.scorer.serve import create_app, _uniform_fallback
uvicorn.run(create_app(lambda: _uniform_fallback()), host='127.0.0.1', port=${PORT}, log_level='warning')
`],
  );
  const ready = () =>
    new Promise<void>((resolve, reject) => {
      const deadline = Date.now() + 20000;
      const probe = () => {
        if (Date.now() > deadline) return reject(new Error('scorer did not come up'));
        const req = createServer.length; // noop to keep import
        void req;
        fetch(`http://127.0.0.1:${PORT}/health`)
          .then((r) => (r.ok ? resolve() : setTimeout(probe, 300)))
          .catch(() => setTimeout(probe, 300));
      };
      probe();
    });
  return { proc: python, ready };
}

describe('joint1 C5 cross-language — TS gate ← Python trust scorer', () => {
  it('drives verdicts from the real :8020 service end-to-end', async () => {
    const { proc, ready } = await spawnTrustScorer();
    try {
      await ready();
    } catch {
      console.warn('python trust scorer unavailable; skipping cross-language e2e');
      proc.kill();
      return;
    }
    try {
      const provider = remoteConfidenceProvider({ baseUrl: `http://127.0.0.1:${PORT}` });
      const score = await provider.score({ riskScore: 0.2 });
      expect(score.score).toBe(0.5);
      const gateCore = new GateCore({ executeThreshold: 0.7, rejectThreshold: 0.3 }, provider);
      const decision = await gateCore.decide('echo', { riskScore: 0.2 });
      expect(decision.verdict).toBe('escalate');
      expect(decision.explain).toBeDefined();
    } finally {
      proc.kill();
    }
  }, 30000);
});
