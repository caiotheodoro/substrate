import type { ZodSchema } from 'zod';
import { z } from 'zod';

export interface ToolResult {
  ok: boolean;
  data?: unknown;
  error?: string;
}

export interface ToolSpec {
  name: string;
  description: string;
  inputSchema: ZodSchema;
  run: (args: Record<string, unknown>) => Promise<ToolResult>;
}

export interface ToolContext {
  clock: () => string;
  setClock?: (iso: string) => void;
}

export function createMockTools(ctx?: Partial<ToolContext>): ToolSpec[] {
  const clock = ctx?.clock ?? (() => new Date().toISOString());
  const setClock = ctx?.setClock ?? (() => undefined);
  const virtualFs = new Map<string, string>();
  const httpbin: Array<Record<string, unknown>> = [];
  let failOnceArmed = true;

  return [
    {
      name: 'echo',
      description: 'Echoes the given text back. Deterministic.',
      inputSchema: z.object({ text: z.string() }),
      async run(args) {
        return { ok: true, data: { echoed: args.text } };
      },
    },
    {
      name: 'fake-clock',
      description: 'Returns the current (injectable) time, or sets it.',
      inputSchema: z.object({ set: z.string().optional() }),
      async run(args) {
        if (typeof args.set === 'string') {
          setClock(args.set);
          return { ok: true, data: { now: args.set } };
        }
        return { ok: true, data: { now: clock() } };
      },
    },
    {
      name: 'file',
      description: 'Virtual in-memory file read/write under a root path.',
      inputSchema: z.object({
        op: z.enum(['read', 'write']),
        path: z.string(),
        content: z.string().optional(),
      }),
      async run(args) {
        const path = String(args.path);
        if (args.op === 'write') {
          virtualFs.set(path, String(args.content ?? ''));
          return { ok: true, data: { path, bytes: String(args.content ?? '').length } };
        }
        if (!virtualFs.has(path)) return { ok: false, error: `no such file: ${path}` };
        return { ok: true, data: { path, content: virtualFs.get(path) } };
      },
    },
    {
      name: 'httpbin',
      description: 'In-process mock HTTP endpoint: records the request and returns it.',
      inputSchema: z.object({ method: z.string().default('GET'), url: z.string(), body: z.unknown().optional() }),
      async run(args) {
        const record = { method: args.method, url: args.url, body: args.body };
        httpbin.push(record);
        return { ok: true, data: { received: record, requests: httpbin.length } };
      },
    },
    {
      name: 'delay',
      description: 'Delays for the given milliseconds (max 250).',
      inputSchema: z.object({ ms: z.number().min(0).max(250) }),
      async run(args) {
        await new Promise((resolve) => setTimeout(resolve, Number(args.ms)));
        return { ok: true, data: { delayedMs: args.ms } };
      },
    },
    {
      name: 'fail-once',
      description: 'Fails on the first call, succeeds afterwards.',
      inputSchema: z.object({ label: z.string().default('op') }),
      async run(args) {
        if (failOnceArmed) {
          failOnceArmed = false;
          return { ok: false, error: `transient failure on ${String(args.label ?? 'op')}` };
        }
        return { ok: true, data: { label: args.label, attempt: 2 } };
      },
    },
  ];
}

export class MockToolRegistry {
  private tools: ToolSpec[];
  constructor(tools?: ToolSpec[]) {
    this.tools = tools ?? createMockTools();
  }
  list(): ToolSpec[] {
    return [...this.tools];
  }
  async call(name: string, args: Record<string, unknown>): Promise<ToolResult> {
    const tool = this.tools.find((t) => t.name === name);
    if (!tool) return { ok: false, error: `unknown tool: ${name}` };
    try {
      const parsed = tool.inputSchema.safeParse(args);
      if (!parsed.success) {
        return { ok: false, error: `invalid args for ${name}: ${parsed.error.message}` };
      }
      return await tool.run(parsed.data as Record<string, unknown>);
    } catch (e) {
      return { ok: false, error: (e as Error).message };
    }
  }
}
