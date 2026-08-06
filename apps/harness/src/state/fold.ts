import type { StoredEvent } from '@substrate/substrate';

export interface RunState {
  runId: string | null;
  lastSeq: number;
  chainHash: string | null;
  toolResults: Map<string, unknown>;
  toolResultsByKey: Map<string, unknown>;
  narratives: Array<{ seq: number; kind: string; payload: unknown; ts: string }>;
  streams: Array<{ seq: number; kind: string; payload: unknown; ts: string }>;
  gates: Array<{ seq: number; payload: unknown; ts: string }>;
  turn: number;
  ended: { reason: string } | null;
  pendingActionsRequested: Array<{ seq: number; payload: unknown }>;
}

export function emptyState(): RunState {
  return {
    runId: null,
    lastSeq: -1,
    chainHash: null,
    toolResults: new Map(),
    toolResultsByKey: new Map(),
    narratives: [],
    streams: [],
    gates: [],
    turn: 0,
    ended: null,
    pendingActionsRequested: [],
  };
}

export function fold(events: StoredEvent[]): RunState {
  const state = emptyState();
  for (const e of events) {
    state.runId = e.runId;
    state.lastSeq = e.seq;
    state.chainHash = e.chainHash;
    if (e.family === 'capture') {
      state.toolResults.set(e.toolCallId, e.result);
      state.toolResultsByKey.set(e.idempotencyKey, e.result);
    } else if (e.family === 'narrative') {
      state.narratives.push({ seq: e.seq, kind: e.kind, payload: e.payload, ts: e.ts });
    } else {
      state.streams.push({ seq: e.seq, kind: e.kind, payload: e.payload, ts: e.ts });
      if (e.kind === 'turn.start') {
        const turn = (e.payload as { turn?: number }).turn ?? state.turn + 1;
        state.turn = Math.max(state.turn, turn);
      }
      if (e.kind === 'run.end') {
        const payload = e.payload as { reason?: string };
        state.ended = { reason: payload.reason ?? 'ended' };
      }
      if (e.kind === 'pending.action.requested') {
        state.pendingActionsRequested.push({ seq: e.seq, payload: e.payload });
      }
      if (e.kind === 'gate.decision') {
        state.gates.push({ seq: e.seq, payload: e.payload, ts: e.ts });
      }
    }
  }
  return state;
}

export function toolResult(events: StoredEvent[], toolCallId: string): unknown | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e && e.family === 'capture' && e.toolCallId === toolCallId) return e.result;
  }
  return undefined;
}

export interface StreamEvent {
  seq: number;
  kind: string;
  payload: unknown;
  ts: string;
}