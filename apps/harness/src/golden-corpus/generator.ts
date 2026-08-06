import type { ChatResponse, LLMProvider } from '../llm/llm';
import { FileRecordingStore, RecordedLLM } from '../llm/llm';
import { createMemoryStores } from '../db/memory';
import { RunEngine, EngineClock, ToolRunner } from '../engine/engine';
import { GateCore, heuristicConfidenceProvider } from '../gate/gate-core';
import { createMockTools, MockToolRegistry, ToolSpec } from '../mock-tools/tools';
import { requestActionTool } from '../hitl/pending-action';
import { serializeGolden, GoldenMeta } from '../replay/golden';
import { FIXED_NOW } from '../replay/replay';

export interface ScriptCtx {
  turn: number;
  runId: string;
}

export class ScriptedProvider implements LLMProvider {
  private turn = 0;
  constructor(private script: Array<(ctx: ScriptCtx) => ChatResponse>, private runIdGetter: () => string) {}

  async complete(): Promise<ChatResponse> {
    this.turn += 1;
    const idx = Math.min(this.turn - 1, this.script.length - 1);
    const fn = this.script[idx];
    if (!fn) return { content: '', toolCalls: [] };
    return fn({ turn: this.turn, runId: this.runIdGetter() });
  }
}

export function sequenceClock(): EngineClock {
  let n = 0;
  return {
    now: () => FIXED_NOW,
    nextId: (prefix) => `${prefix}-${++n}`,
  };
}

export interface RecordSpec {
  id: string;
  task: string;
  runId: string;
  maxTurns: number;
  script: Array<(ctx: ScriptCtx) => ChatResponse>;
  toolExtras?: ToolSpec[];
  resolve: {
    actionAnswers?: Record<string, unknown>;
    escalationVerdict?: 'approved' | 'rejected';
  };
}

export const GOLDEN_SPECS: RecordSpec[] = [
  {
    id: 'run-echo',
    task: 'Say hello.',
    runId: 'run-echo-1',
    maxTurns: 2,
    script: [
      (ctx) => ({
        content: `I will echo the greeting (turn ${ctx.turn}).`,
        toolCalls: [{ name: 'echo', args: { text: 'hello' } }],
      }),
      () => ({ content: 'Echoed.', toolCalls: [] }),
    ],
    resolve: {},
  },
  {
    id: 'run-form',
    task: 'Collect the user name and age via the form.',
    runId: 'run-form-1',
    maxTurns: 2,
    script: [
      (ctx) => ({
        content: 'I need your name and age.',
        toolCalls: [
          {
            name: 'request_action',
            args: {
              kind: 'form',
              prompt: 'Provide name and age.',
              schema: { properties: { name: { type: 'string' }, age: { type: 'integer' } } },
              runId: ctx.runId,
              turn: ctx.turn,
            },
          },
        ],
      }),
      () => ({ content: 'Thank you.', toolCalls: [] }),
    ],
    resolve: {
      actionAnswers: { name: 'Ada', age: 36 },
    },
  },
  {
    id: 'run-gated',
    task: 'Approve the refund for ORD-42.',
    runId: 'run-gated-1',
    maxTurns: 2,
    script: [
      () => ({
        content: 'I will process the refund.',
        toolCalls: [{ name: 'order-refund', args: { orderId: 'ORD-42' } }],
      }),
      () => ({ content: 'Refund approved.', toolCalls: [] }),
    ],
    toolExtras: [
      {
        name: 'order-refund',
        description: 'Approves a customer refund. Risky action.',
        inputSchema: { properties: { orderId: { type: 'string' } }, required: ['orderId'] } as never,
        run: async (args) => ({ ok: true, data: { refundApproved: true, orderId: String(args.orderId ?? '') } }),
      },
    ],
    resolve: {
      escalationVerdict: 'approved',
    },
  },
];

export async function recordCorpusRun(spec: RecordSpec, outDir: string): Promise<void> {
  const { writeFileSync, mkdirSync } = await import('node:fs');
  mkdirSync(outDir, { recursive: true });
  const clock = sequenceClock();
  const stores = createMemoryStores({ now: () => FIXED_NOW });
  const llmPath = `${outDir}/${spec.id}.llm.jsonl`;
  const recording = new FileRecordingStore(llmPath);
  const holder = { runId: spec.runId };
  const scripted = new ScriptedProvider(spec.script, () => holder.runId);
  const llm = new RecordedLLM(recording, scripted, false);
  const gate = new GateCore(
    { executeThreshold: 0.7, rejectThreshold: 0.3 },
    heuristicConfidenceProvider(),
    (prefix) => clock.nextId(prefix),
  );
  const tools = new MockToolRegistry([...createMockTools(), requestActionTool(stores, { idGen: () => clock.nextId('pa'), now: () => FIXED_NOW }), ...(spec.toolExtras ?? [])]);
  const engine = await RunEngine.start(
    { stores, llm, tools, gate, clock, maxTurns: spec.maxTurns, hardCapTurns: spec.maxTurns + 1 },
    spec.task,
  );
  holder.runId = engine.id;
  const runId = engine.id;
  const runPromise = engine.run(spec.maxTurns);
  await resolveMidRun(stores, runId, spec, () => clock.nextId('pa'));
  await runPromise;

  const events = await stores.events.list(runId);
  const meta: GoldenMeta = {
    runId,
    task: spec.task,
    tools: spec.toolExtras?.length ? 'mock-tools+extras' : 'mock-tools',
    clock: 'fixed-2026-01-01',
  };
  const golden = serializeGolden(events, meta);
  writeFileSync(`${outDir}/${spec.id}.golden.jsonl`, golden, 'utf8');
  const recordings = await recording.list();
  const llmLines = recordings.map((r) => JSON.stringify(r)).join('\n') + '\n';
  writeFileSync(llmPath, llmLines, 'utf8');
}

async function resolveMidRun(
  stores: ReturnType<typeof createMemoryStores>,
  runId: string,
  spec: RecordSpec,
  idGen: () => string,
): Promise<void> {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const pending = await stores.pendingActions.list(runId);
    for (const action of pending.filter((a) => a.status === 'pending')) {
      await stores.pendingActions.resolve(action.id, spec.resolve.actionAnswers ?? {}, 'golden-script');
    }
    const escalations = await stores.escalations.list();
    for (const esc of escalations.filter((e) => e.verdict === 'pending')) {
      await stores.escalations.decide(esc.id, spec.resolve.escalationVerdict ?? 'approved', 'golden-script');
    }
    const run = await stores.runs.get(runId);
    if (run && run.status === 'ended') return;
    if (pending.length === 0 && escalations.length === 0 && !run) return;
    await sleep(5);
  }
  void idGen;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}