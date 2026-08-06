import { parseArgs } from 'node:util';
import type { Stores } from '../types';
import { createMemoryStores } from '../db/memory';
import { createPool, migrate } from '../db';
import { createPostgresStores } from '../db/postgres';
import { GateCore, heuristicConfidenceProvider, thresholdSweep, paretoFrontier } from '../gate/gate-core';
import { ThresholdManager } from '../gate/thresholds';
import { RunEngine } from '../engine/engine';
import { MockToolRegistry } from '../mock-tools/tools';
import { ollamaClient } from '../llm/llm';
import { regenerateRun } from '../replay/replay';
import { goldenCorpusDir, loadGoldenRun } from '../replay/golden';
import { SandboxClient } from '../sandbox/client';

const USAGE = `
harness <command>

  run <task>                 run a live turn loop (Ollama default) and print the event log
  record <corpusId>          record a golden run from golden-corpus/<id>.spec.json into JSONL
  replay <corpusId>          re-run a golden from recorded inputs, assert byte-identity
  gate-tune [taskType]       estimate Pareto-optimal thresholds from the decisions log
  sandbox-probe <id>         keepalive+liveness probe against the sandbox manager
`;

export async function main(argv: string[] = process.argv.slice(2)): Promise<number> {
  if (argv.length === 0) {
    console.log(USAGE);
    return 0;
  }
  const cmd = argv[0];
  const { values, positionals } = parseArgs({
    args: argv.slice(1),
    allowPositionals: true,
    options: { task: { type: 'string', short: 't' } },
  });
  try {
    switch (cmd) {
      case 'run':
        return await cmdRun(positionals[0] ?? values.task ?? 'inspect and report');
      case 'record':
        return await cmdRecord(positionals[0] ?? 'run-echo');
      case 'replay':
        return await cmdReplay(positionals[0] ?? 'run-echo');
      case 'gate-tune':
        return await cmdGateTune(positionals[0] ?? 'default');
      case 'sandbox-probe':
        return await cmdSandboxProbe(positionals[0] ?? 'http://localhost:8936');
      default:
        console.error(`unknown command: ${cmd}`);
        return 1;
    }
  } catch (e) {
    console.error(`harness: ${(e as Error).message}`);
    return 1;
  }
}

async function cmdRun(task: string): Promise<number> {
  const pool = createPool();
  await migrate(pool);
  const stores = createPostgresStores(pool);
  const gate = new GateCore(
    { executeThreshold: 0.7, rejectThreshold: 0.3 },
    heuristicConfidenceProvider(),
  );
  const llm = ollamaClient();
  const engine = await RunEngine.start(
    { stores, llm, tools: new MockToolRegistry(), gate },
    task,
  );
  const out = await engine.run();
  console.log(`run ${out.run.id} → ${out.reason}`);
  for (const e of out.events) console.log(`${e.seq}\t${e.family}\t${'stream' === e.family ? e.kind : ''}\t${JSON.stringify('stream' === e.family ? (e as { payload?: unknown }).payload ?? '' : (e as { result?: unknown }).result ?? '')}`);
  await pool.end();
  return 0;
}

async function cmdRecord(id: string): Promise<number> {
  const { recordCorpusRun, GOLDEN_SPECS } = await import('../golden-corpus/generator');
  const spec = GOLDEN_SPECS.find((s) => s.id === id);
  if (!spec) {
    console.error(`no corpus spec ${id}`);
    return 1;
  }
  await recordCorpusRun(spec, goldenCorpusDir());
  console.log(`recorded ${id}`);
  return 0;
}

async function cmdReplay(id: string): Promise<number> {
  const fixtures = goldenCorpusIndex();
  const fixture = fixtures.find((f) => f.id === id);
  if (!fixture) {
    console.error(`no corpus entry ${id}`);
    return 1;
  }
  const loaded = loadGoldenRun(fixture, goldenCorpusDir());
  const result = await regenerateRun({ fixture: loaded });
  console.log(`${result.runId} byte-identical=${result.byteIdentical} rerolls=${result.rerolls}`);
  return result.byteIdentical ? 0 : 1;
}

export function goldenCorpusIndex(): Array<{ id: string; goldenPath: string; llmPath: string }> {
  return [
    { id: 'run-echo', goldenPath: 'run-echo.golden.jsonl', llmPath: 'run-echo.llm.jsonl' },
    { id: 'run-form', goldenPath: 'run-form.golden.jsonl', llmPath: 'run-form.llm.jsonl' },
    { id: 'run-gated', goldenPath: 'run-gated.golden.jsonl', llmPath: 'run-gated.llm.jsonl' },
  ];
}

async function cmdGateTune(task: string): Promise<number> {
  const pool = createPool();
  await migrate(pool).catch(() => undefined);
  const stores = createPostgresStores(pool);
  const tm = new ThresholdManager(stores);
  const decisions = await stores.decisions.list();
  if (decisions.length === 0) {
    const samples = makeSamples(400);
    const frontier = paretoFrontierPoints(samples);
    console.log('no decisions in DB → heuristic demo on synthetic samples');
    printFrontier(frontier);
    await pool.end();
    return 0;
  }
  const est = await tm.estimate(task, decisions);
  console.log(`current ${task}: exec=${est.current.executeThreshold} reject=${est.current.rejectThreshold}`);
  printFrontier(est.frontier.slice(0, 10));
  console.log(`recommended: exec=${est.recommended.executeThreshold} reject=${est.recommended.rejectThreshold}`);
  await pool.end();
  return 0;
}

async function cmdSandboxProbe(addr: string): Promise<number> {
  const client = new SandboxClient({ baseUrl: addr });
  const lease = await client.acquire('alpine:3.20', 30000);
  const liveness = await client.liveness(lease.id);
  console.log(`lease=${lease.id} liveness=${JSON.stringify(liveness)}`);
  const kept = await client.keepalive(lease.id);
  console.log(`keepalive → expiresAt=${kept.expiresAt}`);
  const exec = await client.exec(lease.id, ['echo', 'probe-ok']);
  console.log(`exec → exit=${exec.exitCode} stdout=${exec.stdout}`);
  await client.release(lease.id);
  console.log('released');
  return 0;
}

function printFrontier(points: { executeThreshold: number; rejectThreshold: number; blownRate: number; escalatedRate: number }[]): void {
  for (const p of points) {
    console.log(`exec=${p.executeThreshold} reject=${p.rejectThreshold} → escalate=${p.escalatedRate.toFixed(3)} blown=${p.blownRate.toFixed(3)}`);
  }
}

function makeSamples(n: number) {
  const samples: { score: number; outcome: boolean }[] = [];
  for (let i = 0; i < n; i++) {
    const score = 0.1 + ((i * 37) % 90) / 100;
    samples.push({ score, outcome: score > 0.6 });
  }
  return samples;
}

function paretoFrontierPoints(samples: { score: number; outcome: boolean }[]) {
  return paretoFrontier(thresholdSweep(samples));
}

export function storesFromEnv(): Stores {
  if (process.env.DATABASE_URL) return createPostgresStores(createPool());
  return createMemoryStores();
}