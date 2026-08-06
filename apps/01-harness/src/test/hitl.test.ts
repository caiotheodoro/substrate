import { describe, expect, it } from 'vitest';
import { createMemoryStores } from '../db/memory';
import { requestAction, requiredFields, allReady, atomicResolve, requestActionTool } from '../hitl/pending-action';
import { InProcessHitlBridge } from '../hitl/hitl-bridge';
import { createDockApp } from '../hitl/hitl-dock';

const NOW = () => '2026-01-01T00:00:00.000Z';

describe('pending actions', () => {
  it('requestAction inserts a pending action and resolve completes it', async () => {
    const stores = createMemoryStores({ now: NOW });
    const action = await requestAction(
      stores,
      {
        runId: 'r1',
        turnId: '1',
        kind: 'form',
        prompt: 'Name?',
        schema: { properties: { name: { type: 'string' } }, required: ['name'] },
      },
      'pa-1',
      NOW,
    );
    expect(action.status).toBe('pending');
    expect(requiredFields(action.schema)).toEqual(['name']);
    expect(allReady([action])).toBe(false);
    await stores.pendingActions.resolve('pa-1', { name: 'Ada' }, 'human');
    const resolved = await stores.pendingActions.get('pa-1');
    expect(resolved?.status).toBe('resolved');
    expect(allReady([resolved!])).toBe(true);
  });

  it('atomicResolve resolves multiple actions and reports allReady', async () => {
    const stores = createMemoryStores({ now: NOW });
    await requestAction(stores, { runId: 'r1', turnId: '1', kind: 'question', prompt: 'a?' }, 'pa-1', NOW);
    await requestAction(stores, { runId: 'r1', turnId: '1', kind: 'question', prompt: 'b?' }, 'pa-2', NOW);
    const resolved = await atomicResolve(stores, ['pa-1', 'pa-2'], { 'pa-1': { a: 1 }, 'pa-2': { b: 2 } }, 'human');
    expect(resolved).toHaveLength(2);
    expect(allReady(resolved)).toBe(true);
  });

  it('requestActionTool returns a ToolSpec with an idempotent id', async () => {
    const stores = createMemoryStores({ now: NOW });
    const tool = requestActionTool(stores, { idGen: () => 'pa-42', now: NOW });
    expect(tool.name).toBe('request_action');
    const result = await tool.run({ kind: 'question', prompt: 'ok?', runId: 'r1' });
    expect((result.data as { actionId: string }).actionId).toBe('pa-42');
    const action = await stores.pendingActions.get('pa-42');
    expect(action?.status).toBe('pending');
  });
});

describe('InProcessHitlBridge', () => {
  it('waits for a resolved action and returns the answer', async () => {
    const stores = createMemoryStores({ now: NOW });
    const bridge = new InProcessHitlBridge(stores);
    const action = await requestAction(stores, { runId: 'r1', turnId: '1', kind: 'question', prompt: 'x?' }, 'pa-9', NOW);
    const waitP = bridge.waitForResolved(action.id);
    setTimeout(async () => {
      await stores.pendingActions.resolve('pa-9', { answer: 'yes' }, 'human');
    }, 5);
    const resolved = await waitP;
    expect(resolved.answer).toEqual({ answer: 'yes' });
  });

  it('rejects when the action does not exist', async () => {
    const stores = createMemoryStores({ now: NOW });
    const bridge = new InProcessHitlBridge(stores);
    await expect(bridge.waitForResolved('missing')).rejects.toThrow();
  });
});

describe('dock', () => {
  it('dockApp serves action endpoints', async () => {
    const stores = createMemoryStores({ now: NOW });
    await requestAction(stores, { runId: 'r1', turnId: '1', kind: 'question', prompt: 'q?' }, 'pa-5', NOW);
    const app = createDockApp(stores);
    expect(app).toBeDefined();
  });
});
