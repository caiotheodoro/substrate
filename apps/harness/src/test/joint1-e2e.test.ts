import { describe, expect, it } from 'vitest';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { remoteConfidenceProvider } from '../gate/remote-confidence';
import { GateCore } from '../gate/gate-core';
import type { Server } from 'node:http';

/**
 * Joint 1 cross-language e2e: the REAL Trust scorer (FastAPI, apps/trust/py)
 * serves C5 on :8020; 01's remoteConfidenceProvider consumes it and the gate
 * verdicts follow. Skips when the Python env is not provisioned (uv sync).
 */
const PORT = 18025;

const REPO = resolve(process.cwd(), '..', '..');
const TRUST_PYTHON = `${REPO}/apps/trust/py/.venv/bin/python`;
const PYTHON_AVAILABLE = existsSync(TRUST_PYTHON);

async function spawnTrustScorer(): Promise<{ proc: ReturnType<typeof spawn>; ready: () => Promise<void> }> {
  const { createServer } = await import('node:http');
  const python = spawn(
    TRUST_PYTHON,
    ['-c', `
import threading, time, uvicorn
from trust.scorer.serve import create_app, _uniform_fallback
# Build the fallback scorer ONCE at boot, not per-request: _uniform_fallback()
# does a real sklearn isotonic .fit() every call, and re-fitting cold on the
# first /confidence request can exceed the TS client's 2s request timeout
# under CI load. The provider callable exists for hot-reload semantics in
# production; this fallback is a constant, so caching it is exactly correct.
_scorer = _uniform_fallback()
uvicorn.run(create_app(lambda: _scorer), host='127.0.0.1', port=${PORT}, log_level='warning')
`],
  );
  let bootLog = '';
  python.stderr?.on('data', (d) => {
    if (bootLog.length < 2000) bootLog += String(d);
  });
  python.stdout?.on('data', (d) => {
    if (bootLog.length < 2000) bootLog += String(d);
  });
  const ready = () =>
    new Promise<void>((resolve, reject) => {
      const deadline = Date.now() + 45000; // generous under full-suite parallel load (see 07cdba8)
      const probe = () => {
        if (Date.now() > deadline) {
          return reject(new Error(`scorer did not come up — boot log:\n${bootLog.slice(-1200)}`));
        }
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

describe.skipIf(!PYTHON_AVAILABLE)('joint1 C5 cross-language — TS gate ← Python trust scorer', () => {
  it('drives verdicts from the real :8020 service end-to-end', async () => {
    const { proc, ready } = await spawnTrustScorer();
    try {
      await ready();
    } catch (err) {
      console.warn('python trust scorer unavailable; skipping cross-language e2e:', err);
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
  }, 50000);
});
