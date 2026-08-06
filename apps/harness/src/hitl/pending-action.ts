import { z } from 'zod';
import type { PendingAction, Stores } from '../types';

export interface PendingActionRequest {
  runId: string;
  turnId: string;
  kind: 'question' | 'form' | 'decision';
  prompt: string;
  schema?: Record<string, unknown>;
}

export function createPendingAction(req: PendingActionRequest): PendingAction {
  return {
    id: '',
    runId: req.runId,
    turnId: req.turnId,
    kind: req.kind,
    prompt: req.prompt,
    schema: req.schema ?? {},
    answer: null,
    status: 'pending',
    createdAt: new Date().toISOString(),
    resolvedAt: null,
    resolvedBy: null,
  };
}

export async function requestAction(
  stores: Stores,
  req: PendingActionRequest,
  id: string,
  now: () => string = () => new Date().toISOString(),
): Promise<PendingAction> {
  const action: PendingAction = {
    ...createPendingAction(req),
    id,
    createdAt: now(),
  };
  await stores.pendingActions.insert(action);
  return action;
}

export function requiredFields(schema: Record<string, unknown>): string[] {
  const props = schema['properties'];
  const required = schema['required'];
  if (Array.isArray(required)) return required.filter((f): f is string => typeof f === 'string');
  if (props && typeof props === 'object') {
    return Object.keys(props).filter((k) => {
      const field = (props as Record<string, unknown>)[k];
      return typeof field === 'object' && field !== null && (field as Record<string, unknown>)['required'] === true;
    });
  }
  return [];
}

export function allReady(actions: PendingAction[]): boolean {
  return actions.every((a) => a.status === 'resolved' || requiredFields(a.schema).every((f) => a.answer?.[f] !== undefined));
}

export async function atomicResolve(
  stores: Stores,
  ids: string[],
  answers: Record<string, Record<string, unknown>>,
  by: string,
): Promise<PendingAction[]> {
  const resolved: PendingAction[] = [];
  for (const id of ids) {
    const current = await stores.pendingActions.get(id);
    if (!current) continue;
    await stores.pendingActions.resolve(id, answers[id] ?? {}, by);
    resolved.push((await stores.pendingActions.get(id))!);
  }
  return resolved;
}

export function requestActionTool(stores: Stores, opts?: { idGen?: () => string; now?: () => string }) {
  const idGen = opts?.idGen ?? (() => `pa-${Math.random().toString(36).slice(2, 10)}`);
  const now = opts?.now ?? (() => new Date().toISOString());
  return {
    name: 'request_action',
    description: 'Request human input (question, form, or decision). The run pauses until the dock resolves it.',
    inputSchema: z.object({
      kind: z.enum(['question', 'form', 'decision']),
      prompt: z.string(),
      schema: z.record(z.string(), z.unknown()).optional(),
      runId: z.string().optional(),
      turn: z.union([z.string(), z.number()]).optional(),
    }),
    async run(args: Record<string, unknown>) {
      const runId = (args['runId'] as string) ?? '';
      const action = await requestAction(
        stores,
        {
          runId,
          turnId: String(args['turn'] ?? '?'),
          kind: (args['kind'] as 'question') ?? 'question',
          prompt: String(args['prompt'] ?? ''),
          schema: (args['schema'] as Record<string, unknown>) ?? {},
        },
        idGen(),
        now,
      );
      return { ok: true, data: { actionId: action.id, status: action.status, kind: action.kind } };
    },
  };
}
