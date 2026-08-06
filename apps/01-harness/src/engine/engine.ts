import type { Event, StoredEvent, StepRecord } from '@substrate/substrate';
import { canonicalJson } from '@substrate/substrate';
import type { Stores, RunRecord, Escalation } from '../types';
import type { LLMProvider, ChatMessage } from '../llm/llm';
import type { GateCore } from '../gate/gate-core';
import type { ToolResult, ToolSpec } from '../mock-tools/tools';
import { fold, RunState } from '../state/fold';

export interface EngineClock {
  now(): string;
  nextId(prefix: string): string;
}

export function systemClock(): EngineClock {
  return {
    now: () => new Date().toISOString(),
    nextId: (prefix) => `${prefix}-${Math.random().toString(36).slice(2, 10)}`,
  };
}

export function scriptedClock(ids: string[], nowOverride = '2026-01-01T00:00:00.000Z'): EngineClock {
  let i = 0;
  const makeId = (prefix: string) => {
    const chosen = ids[i++];
    return chosen ? `${prefix}-${chosen}` : `${prefix}-${i}`;
  };
  return {
    now: () => nowOverride,
    nextId: makeId,
  };
}

export interface ToolRunner {
  list(): ToolSpec[];
  call(name: string, args: Record<string, unknown>): Promise<ToolResult>;
}

export interface RunEngineOptions {
  stores: Stores;
  llm: LLMProvider;
  tools: ToolRunner;
  gate: GateCore;
  clock?: EngineClock;
  taskType?: string;
  maxTurns?: number;
  hardCapTurns?: number;
  maxToolCallsPerTurn?: number;
  replayMode?: boolean;
  replayResults?: (toolCallId: string) => Promise<unknown>;
  onEvent?: (e: StoredEvent) => void;
  sandboxLabel?: string;
  budgetGate?: import('../ledger/budget-client').BudgetGateClient;
  budget?: { tokensPerStep: number; budgetPerDecision: number };
}

export interface RunOutcome {
  run: RunRecord;
  events: StoredEvent[];
  state: RunState;
  reason: string;
}

export const RISK_TABLE: Record<string, number> = {
  echo: 0,
  'fake-clock': 0,
  delay: 0,
  httpbin: 0.1,
  'fail-once': 0.1,
  file: 0.4,
  'request_action': 0.2,
  execute: 0.8,
  send: 0.85,
  approve: 0.9,
  refund: 0.85,
};

export class RunEngine {
  private opts: RunEngineOptions;
  private clock: EngineClock;
  private runId: string;
  private task: string;

  private constructor(opts: RunEngineOptions, runId: string, task: string) {
    this.opts = opts;
    this.clock = opts.clock ?? systemClock();
    this.runId = runId;
    this.task = task;
  }

  static async start(opts: RunEngineOptions, task: string): Promise<RunEngine> {
    const clock = opts.clock ?? systemClock();
    const runId = clock.nextId('run');
    const engine = new RunEngine(opts, runId, task);
    await engine.createRun();
    return engine;
  }

  static fromExisting(opts: RunEngineOptions, runId: string, task: string): RunEngine {
    return new RunEngine(opts, runId, task);
  }

  get id(): string {
    return this.runId;
  }

  maxTurnsLimit(): number {
    return this.opts.maxTurns ?? 8;
  }

  private async createRun(): Promise<void> {
    const now = this.clock.now();
    await this.opts.stores.runs.create({
      id: this.runId,
      task: this.task,
      status: 'running',
      reason: null,
      maxTurns: this.opts.maxTurns ?? 8,
      startedAt: now,
      endedAt: null,
      seq: -1,
    });
    await this.appendEvents([streamEvent('run.start', { task: this.task, startedAt: now })]);
  }

  async run(limitTurns?: number): Promise<RunOutcome> {
    const maxTurns = limitTurns ?? this.opts.maxTurns ?? 8;
    const hardCap = this.opts.hardCapTurns ?? maxTurns + 1;
    let turn = (await this.foldedState()).turn;

    while (true) {
      const state = await this.foldedState();
      if (state.ended) {
        const run = (await this.opts.stores.runs.get(this.runId))!;
        return { run, events: await this.opts.stores.events.list(this.runId), state, reason: state.ended.reason };
      }
      if (turn >= hardCap) {
        await this.endRun('hard-cap', { turn });
        return this.outcome(await this.foldedState(), 'hard-cap');
      }
      turn += 1;
      await this.turn(turn);
      const fresh = await this.foldedState();
      if (fresh.ended) return this.outcome(fresh, fresh.ended.reason);
      if (turn >= maxTurns) {
        await this.endRun('maxTurns', { turn });
        return this.outcome(await this.foldedState(), 'maxTurns');
      }
      const pending = await this.opts.stores.pendingActions.list(this.runId);
      if (pending.some((p) => p.status === 'pending')) {
        await this.waitForPendingActions();
      }
    }
  }

  private async outcome(state: RunState, reason: string): Promise<RunOutcome> {
    const run = (await this.opts.stores.runs.get(this.runId))!;
    const events = await this.opts.stores.events.list(this.runId);
    return { run, events, state: fold(events), reason };
  }

  private async turn(turn: number): Promise<void> {
    console.error("DBG turn start", turn);
    const state = await this.foldedState();
    const events: Event[] = [streamEvent('turn.start', { turn })];
    try {
      console.error("DBG llm");
      const response = await this.opts.llm.complete({ messages: this.buildPrompt(state) });;
      if (response.content) events.push(narrativeEvent('assistant.message', { turn, content: response.content }));
      const toolCalls = response.toolCalls ?? [];
      const maxPerTurn = this.opts.maxToolCallsPerTurn ?? 8;
      const bounded = toolCalls.slice(0, maxPerTurn);
      if (toolCalls.length > maxPerTurn) {
        events.push(streamEvent('tool.batch-truncated', { turn, requested: toolCalls.length, kept: maxPerTurn }));
      }
      const turnState = await this.foldedState();
      for (const tc of bounded) {
        console.error("DBG toolcall", tc.name);
        events.push(...(await this.executeToolCall(turn, tc.name, (tc.args ?? {}) as Record<string, unknown>, events, turnState)));;
      }
      if (this.opts.replayMode) {
        for (const e of events) {
          if (e.family !== 'capture') continue;
          const result = e.result as { ok?: boolean; data?: { actionId?: string; kind?: string } };
          if (result?.ok && result.data?.actionId) {
            events.push(
              streamEvent('pending.action.requested', {
                runId: this.runId,
                turn,
                actionId: result.data.actionId,
                kind: result.data.kind ?? 'question',
              }),
            );
          }
        }
      }
    } catch (e) {
      await this.endRun('crashed', { turn, error: (e as Error).message });
      return;
    }
    const stored = await this.appendEvents(events);
    for (const e of stored) this.opts.onEvent?.(e);
    if (!this.opts.replayMode) {
      const pending = await this.opts.stores.pendingActions.list(this.runId);
      const pendingNew = pending.filter((p) => p.status === 'pending' && !events.some((e) => (e as { payload?: { actionId?: string } }).payload?.actionId === p.id));
      if (pendingNew.length > 0) {
        const notify = pendingNew.map((p) => streamEvent('pending.action.requested', { runId: this.runId, turn, actionId: p.id, kind: p.kind }));
        const notif = await this.appendEvents(notify);
        for (const e of notif) this.opts.onEvent?.(e);
      }
    }
  }

  private async executeToolCall(
    turn: number,
    name: string,
    args: Record<string, unknown>,
    turnEvents: Event[],
    state: RunState,
  ): Promise<Event[]> {
    const events: Event[] = [];
    const toolCallId = this.clock.nextId('tc');
    events.push(streamEvent('tool.call', { turn, toolCallId, name, args }));

    const confidenceFeatures = this.buildFeatures(name, args, state);
    console.error("DBG gate call");
    const decision = await this.opts.gate.decide(toolCallId, confidenceFeatures);
    console.error("DBG gate verdict", decision.verdict);
    events.push(
      streamEvent('gate.decision', {
        turn,
        decisionId: decision.decisionId,
        toolCallId,
        name,
        verdict: decision.verdict,
        score: decision.score,
        explain: decision.explain,
      }),
    );
    await this.opts.stores.decisions.insert({
      decisionId: decision.decisionId,
      turnId: String(turn),
      action: `${name}:${toolCallId}`,
      confidenceFeatures,
      verdict: decision.verdict,
      outcome: null,
      confirmedAt: null,
    });

    if (decision.verdict === 'reject') {
      events.push(streamEvent('tool.rejected', { turn, toolCallId, name, reason: 'gate-reject' }));
      return events;
    }

    if (decision.verdict === 'escalate') {
      const escalation = await this.raiseEscalation(turn, decision.decisionId, toolCallId, name, args, decision.score, decision.explain);
      events.push(streamEvent('escalation.created', { turn, escalationId: escalation.id, decisionId: decision.decisionId, toolCallId, name }));
      const verdict = await this.awaitEscalation(escalation.id);
      events.push(streamEvent('escalation.resolved', { turn, escalationId: escalation.id, verdict }));
      if (verdict === 'rejected' || verdict === 'vetoed') {
        events.push(streamEvent('tool.rejected', { turn, toolCallId, name, reason: `escalation-${verdict}` }));
        return events;
      }
    }

    const dup = this.findDuplicate(turnEvents, name, args);
    if (dup) {
      events.push(streamEvent('tool.deduplicated', { turn, toolCallId, name, args, matches: dup.toolCallId }));
      return events;
    }

    const budgetGate = this.opts.budgetGate;
    if (budgetGate) {
      const stepIdx = await this.countPriorCaptures(toolCallId);
      const estimatedTokens = this.opts.budget?.tokensPerStep ?? 1000;
      const budget = this.opts.budget?.budgetPerDecision ?? 5000;
      let outcome: 'pass' | 'blow' = 'pass';
      let budgetError: string | null = null;
      try {
        outcome = await budgetGate.gate({
          decisionId: this.runId,
          stepIdx,
          estimatedTokens,
          budget,
        });
      } catch (err) {
        budgetError = (err as Error).message;
      }
      if (outcome === 'blow') {
        events.push(
          streamEvent('budget.blow', {
            turn,
            toolCallId,
            name,
            stepIdx,
            estimatedTokens,
            budget,
          }),
        );
        const escalation = await this.raiseEscalation(turn, decision.decisionId, toolCallId, name, args, 0.0, {
          reason: 'budget-blow',
          estimatedTokens,
          budget,
        });
        events.push(streamEvent('escalation.created', { turn, escalationId: escalation.id, decisionId: decision.decisionId, toolCallId, name, reason: 'budget-blow' }));
        const verdict = await this.awaitEscalation(escalation.id);
        events.push(streamEvent('escalation.resolved', { turn, escalationId: escalation.id, verdict }));
        if (verdict === 'rejected' || verdict === 'vetoed') {
          events.push(streamEvent('tool.rejected', { turn, toolCallId, name, reason: `budget-${verdict}` }));
          return events;
        }
      }
      void budgetError;
    }

    const result = this.opts.replayMode
      ? await this.replayResult(toolCallId)
      : await this.opts.tools.call(name, args);

    const attempt = await this.countPriorCaptures(toolCallId);
    await this.recordCostStep(toolCallId, name, attempt, result);
    events.push({
      family: 'capture',
      toolCallId,
      result,
      ts: this.clock.now(),
      attempt,
    } as Event);
    return events;
  }

  private findDuplicate(
    turnEvents: Event[],
    name: string,
    args: Record<string, unknown>,
  ): { toolCallId: string } | null {
    const prior = turnEvents.filter((e) => e.family === 'stream' && e.kind === 'tool.call');
    for (const e of prior) {
      const p = (e as { payload?: { toolCallId: string; name: string; args: Record<string, unknown> } }).payload;
      if (p && p.name === name && canonicalJson(p.args) === canonicalJson(args)) {
        return { toolCallId: p.toolCallId };
      }
    }
    return null;
  }

  private async replayResult(toolCallId: string): Promise<unknown> {
    if (this.opts.replayResults) return this.opts.replayResults(toolCallId);
    const state = await this.foldedState();
    const recorded = state.toolResults.get(toolCallId);
    if (recorded === undefined) {
      throw new Error(`replay miss: no recorded capture for ${toolCallId}`);
    }
    return recorded;
  }

  private async countPriorCaptures(toolCallId: string): Promise<number> {
    const events = await this.opts.stores.events.list(this.runId);
    return events.filter((e) => e.family === 'capture' && e.toolCallId === toolCallId).length;
  }

  private async recordCostStep(
    toolCallId: string,
    name: string,
    attempt: number,
    result: unknown,
  ): Promise<void> {
    const budgetGate = this.opts.budgetGate;
    if (!budgetGate) return;
    const inputTokens = this.opts.budget?.tokensPerStep ?? 1000;
    try {
      await budgetGate.recordStep({
        decisionId: this.runId,
        stepIdx: 0,
        model: name,
        provider: 'local',
        quantization: null,
        inputTokens,
        cachedInputTokens: 0,
        outputTokens: 0,
        cacheEvent: 'miss',
        latencyMs: 0,
        promptFingerprint: `${this.runId}:${toolCallId}`,
        qualitySignal: 0.5,
        ts: this.clock.now(),
      } as StepRecord);
    } catch {
      // Ledger write failures must never crash a run (joint 3 non-crash rule).
    }
  }

  private async raiseEscalation(
    turn: number,
    decisionId: string,
    toolCallId: string,
    name: string,
    args: Record<string, unknown>,
    confidence: number,
    explain: Record<string, unknown>,
  ): Promise<Escalation> {
    const escalation: Escalation = {
      id: this.clock.nextId('esc'),
      runId: this.runId,
      decisionId,
      proposal: {
        action: `${name}:${toolCallId}`,
        turnId: String(turn),
        confidenceFeatures: { name, args },
        context: `tool call gated at confidence ${confidence.toFixed(3)} (run ${this.runId})`,
      },
      confidence,
      explain,
      verdict: 'pending',
      createdAt: this.clock.now(),
      resolvedAt: null,
      decidedBy: null,
    };
    await this.opts.stores.escalations.insert(escalation);
    return escalation;
  }

  private awaitEscalation(escalationId: string): Promise<string> {
    if (this.opts.replayMode) {
      return Promise.resolve('approved');
    }
    return new Promise((resolve) => {
      const check = async () => {
        const e = await this.opts.stores.escalations.get(escalationId);
        if (e && e.verdict !== 'pending') {
          resolve(e.verdict);
          return;
        }
        setTimeout(check, 5);
      };
      void check();
    });
  }

  private buildFeatures(name: string, args: Record<string, unknown>, state: RunState): Record<string, unknown> {
    const risk = RISK_TABLE[name] ?? 0.3;
    return {
      toolName: name,
      toolOk: true,
      schemaValid: true,
      riskScore: risk,
      evidenceScore: 0.5,
      retrievalSupport: 0,
      doubleSideEffect: false,
      sandbox: this.opts.sandboxLabel ?? null,
      turn: state.turn,
      args: args,
    };
  }

  private buildPrompt(state: RunState): ChatMessage[] {
    const messages: ChatMessage[] = [
      { role: 'system', content: 'You are a deterministic agent. Use the tools. Never narrate tool results twice.' },
      { role: 'user', content: this.task },
    ];
    for (const n of state.narratives) {
      messages.push({ role: 'assistant', content: (n.payload as { content?: string }).content ?? '' });
    }
    for (const [id, result] of state.toolResults) {
      messages.push({ role: 'tool', content: `tool ${id}: ${canonicalJson(result)}` });
    }
    return messages;
  }

  private async appendEvents(events: Event[]): Promise<StoredEvent[]> {
    if (events.length === 0) return [];
    const prev = await this.opts.stores.events.tail(this.runId);
    return this.opts.stores.events.append(this.runId, events, prev);
  }

  async foldedState(): Promise<RunState> {
    const events = await this.opts.stores.events.list(this.runId);
    return fold(events);
  }

  async endRun(reason: string, payload: Record<string, unknown> = {}): Promise<RunOutcome> {
    const events = await this.appendEvents([streamEvent('run.end', { reason, ...payload })]);
    for (const e of events) this.opts.onEvent?.(e);
    const run = (await this.opts.stores.runs.get(this.runId))!;
    await this.opts.stores.runs.update(this.runId, { status: 'ended', reason, endedAt: this.clock.now(), seq: run.seq });
    return this.outcome(await this.foldedState(), reason);
  }

  private waitForPendingActions(): Promise<void> {
    return new Promise((resolve) => {
      const check = async () => {
        const pending = await this.opts.stores.pendingActions.list(this.runId);
        if (!pending.some((p) => p.status === 'pending')) {
          resolve();
          return;
        }
        setTimeout(check, 5);
      };
      void check();
    });
  }
}

export function streamEvent(kind: string, payload: unknown): Event {
  return { family: 'stream', kind, payload };
}

export function narrativeEvent(kind: string, payload: unknown): Event {
  return { family: 'narrative', kind, payload };
}